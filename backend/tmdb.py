"""
tmdb.py — COMPLETE TMDB v3 client (scrape-by-default + API fallback).

Covers the full public v3 surface:
movies, tv (series/season/episode), person, search (multi/movie/tv/person/
collection/company/keyword), discover, trending, genres, watch/providers,
reviews, keywords, networks, companies, collections, credits, certifications,
find, changes, lists, account, authentication, guest sessions, images,
translations, ratings.

ARCHITECTURE
- PRIMARY: scrape themoviedb.org with Scrapling static Fetcher (no API key,
  no 50/sec key quota). TMDB is server-rendered with schema.org JSON-LD, so
  the fast static path works for the read endpoints.
- FALLBACK: TMDB v3 REST API (your registered key). Used when scraping fails
  (markup change / block / timeout) or for endpoints that have no anonymous
  web page (account, auth, guest sessions, user ratings/watchlist).
- THROTTLE: one shared token bucket caps BOTH sources at 50/sec.

All public functions return normalized dicts/lists so callers don't care
which source answered. Unknown/optional fields are omitted, not error.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from functools import lru_cache
from urllib.parse import quote_plus

# DynamicFetcher pulls in playwright (heavy, needs browser binaries). Make
# it optional so static scraping works in a light venv; dynamic-only
# pages simply fall back when it's unavailable.
try:
    from scrapling.fetchers import Fetcher, DynamicFetcher
except ImportError:
    from scrapling.fetchers import Fetcher
    DynamicFetcher = None

try:
    import httpx
except ImportError:
    httpx = None

from config import TMDB_API_KEY, TMDB_BASE

log = logging.getLogger(__name__)

SITE = "https://www.themoviedb.org"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

STATIC_TIMEOUT = 20_000   # ms, Scrapling static fetch
DYNAMIC_TIMEOUT = 30_000  # ms, Scrapling headless fetch
API_TIMEOUT = 20          # s, httpx

# ---------------------------------------------------------------------------
# TOKEN BUCKET (shared across both sources)
# ---------------------------------------------------------------------------
_RATE = 50.0
_CAP = 50
_lock = threading.Lock()
_tokens = float(_CAP)
_last = time.monotonic()


def _throttle() -> None:
    """Block until a token is available, capping BOTH sources at _RATE/sec.

    The wait is computed while holding the lock but slept OUTSIDE it, so a
    thread hitting backpressure never blocks the others. Tokens may go
    negative, which fairly reserves future capacity across concurrent callers.
    """
    global _tokens, _last
    with _lock:
        now = time.monotonic()
        _tokens = min(_CAP, _tokens + (now - _last) * _RATE)
        _last = now
        _tokens -= 1
        wait = 0.0 if _tokens >= 0 else -_tokens / _RATE
    if wait:
        time.sleep(wait)


# ---------------------------------------------------------------------------
# HTTP CLIENT (shared, pooled) + unified request helper
# ---------------------------------------------------------------------------
_client = (
    httpx.Client(
        base_url=TMDB_BASE,
        timeout=API_TIMEOUT,
        headers={"User-Agent": UA},
    )
    if httpx is not None
    else None
)


def _api_request(
    method: str,
    path: str,
    params: dict | None = None,
    body: dict | None = None,
) -> dict | None:
    """Single entry point for all v3 REST calls. Returns parsed JSON or None."""
    if not TMDB_API_KEY or _client is None:
        return None
    _throttle()
    params = dict(params or {})
    params["api_key"] = TMDB_API_KEY
    try:
        resp = _client.request(
            method,
            path,
            params=params,
            json=body if body is not None else None,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        log.warning("API %s %s -> HTTP %s", method, path, resp.status_code)
    except Exception:
        log.warning("API %s %s failed", method, path, exc_info=True)
    return None


def _api_get(path: str, params: dict | None = None) -> dict | None:
    return _api_request("GET", path, params=params)


def _api_post(
    path: str, params: dict | None = None, body: dict | None = None
) -> dict | None:
    return _api_request("POST", path, params=params, body=body or {})


def _api_delete(path: str, params: dict | None = None) -> dict | None:
    return _api_request("DELETE", path, params=params)


# ---------------------------------------------------------------------------
# SHARED HELPERS
# ---------------------------------------------------------------------------
_LD_JSON_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.S
)
_CDATA_RE = re.compile(r"//\s*<!\[CDATA\[|//\s*\]\]>|/\*.*?\*/", re.S)
_TITLE_RE = re.compile(r"<title>(.*?)(?: \u2014| -| \|)", re.S)


def _extract_ld_json(html: str, want_type: str | None = None) -> dict | None:
    """Parse a schema.org JSON-LD block (TMDB wraps it in CDATA).

    Scans every ld+json block and, when `want_type` is given, returns the
    first whose \"@type\" matches -- so a leading non-matching block (e.g. a
    BreadcrumbList) doesn't cause a spurious API fallback.
    """
    for raw in _LD_JSON_RE.findall(html):
        clean = _CDATA_RE.sub("", raw).strip()
        # Trim to the first balanced {...} object.
        depth = 0
        started = False
        end = 0
        for i, ch in enumerate(clean):
            if ch == "{":
                started = True
                depth += 1
            elif ch == "}":
                depth -= 1
                if started and depth == 0:
                    end = i + 1
                    break
        try:
            obj = json.loads(clean[:end]) if end else json.loads(clean)
        except Exception:
            continue
        if want_type is None or obj.get("@type") == want_type:
            return obj
    return None


@lru_cache(maxsize=256)
def _get_page(url: str, dynamic: bool = False) -> str | None:
    """Scrapling fetch; returns decoded HTML or None (cached by url+mode).

    dynamic=True uses the headless renderer for JS-heavy pages (reviews,
    images, translations, videos) that don't appear in the static HTML.
    """
    _throttle()
    try:
        if dynamic:
            if DynamicFetcher is None:
                return None  # headless renderer unavailable -> let callers fall back
            resp = DynamicFetcher.fetch(
                url, stealthy_headers=True, timeout=DYNAMIC_TIMEOUT
            )
        else:
            resp = Fetcher.get(
                url, stealthy_headers=True, timeout=STATIC_TIMEOUT
            )
    except Exception:
        log.warning("fetch failed: %s (dynamic=%s)", url, dynamic, exc_info=True)
        return None
    if getattr(resp, "status", 200) != 200:
        return None
    body = getattr(resp, "body", None)
    return body.decode("utf-8", "ignore") if body else None


def _img(path: str | None, size: str = "w500") -> str | None:
    return f"https://image.tmdb.org/t/p/{size}{path}" if path else None


def _year_from_ld(ld: dict) -> str:
    """Extract a 4-char year from releasedEvent/datePublished, null-safe."""
    raw = ""
    rel = ld.get("releasedEvent")
    if isinstance(rel, list) and rel:
        raw = rel[0].get("startDate") or ""
    elif isinstance(rel, dict):
        raw = rel.get("startDate") or ""
    raw = raw or ld.get("datePublished") or ""
    return raw[:4]


# ---------------------------------------------------------------------------
# SCRAPE PARSERS (anonymous web pages)
# ---------------------------------------------------------------------------
_CARD_RE = re.compile(
    r'href="/(movie|tv|person|collection|company|network|keyword)/(\d+)-([^"?]+)"'
)
_SEARCH_CARD_RE = re.compile(
    r'href="/(movie|tv|person|collection|company|keyword)/(\d+)-([^"?]+)"'
)
_BROWSE_CARD_RE = re.compile(r'href="/(movie|tv)/(\d+)-([^"?]+)"')
_REVIEW_AUTHOR_RE = re.compile(r'href="/u/([^"]+)"')
_REVIEW_TEASER_RE = re.compile(r'class="teaser[^"]*"><p>(.*?)</p>', re.S)
_REVIEW_P_RE = re.compile(r"<p>(.*?)</p>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WATCH_PROV_RE = re.compile(
    r'title="([^"]+)"[^>]*>\s*<img[^>]+src="https://[^"]*logo[^"]*"'
)
_WATCH_NET_RE = re.compile(
    r'href="https://www\.themoviedb\.org/network/(\d+)-([^"?]+)"'
)
_IMAGE_URL_RE = re.compile(r'(?:data-src|src|href)="(https://image\.tmdb\.org/t/p/[^"]+)"')
_YT_RE = re.compile(r'href="https://www\.youtube\.com/watch\?v=([^"&]+)"')
_TRANSLATION_RE = re.compile(
    r'href="#([a-zA-Z]{2}-[a-zA-Z]{2})"[^>]*>\s*([^<]+?)\s*'
    r'<span[^>]*>([a-zA-Z]{2}-[a-zA-Z]{2})</span>'
)
_TRANSLATION_CODE_RE = re.compile(r'href="#([a-zA-Z]{2}-[a-zA-Z]{2})"')
_POSTER_RE = re.compile(
    r'(?:data-src|src|srcset)="([^"]*?https://(?:image|media)\.themoviedb\.org/t/p/[^" ,]+)'
)


def _poster_near(html: str, pos: int, window: int = 5000) -> str | None:
    """Grab the first TMDB poster image within `window` chars after `pos`
    (cards render their poster img just after the title anchor)."""
    m = _POSTER_RE.search(html, pos, pos + window)
    return m.group(1) if m else None


def _norm_movie_from_ld(ld: dict, tmdb_id: str) -> dict:
    image = ld.get("image")
    return {
        "id": tmdb_id,
        "title": ld.get("name"),
        "original_title": ld.get("alternateName"),
        "year": _year_from_ld(ld),
        "overview": ld.get("description"),
        "genres": ld.get("genre") or [],
        "poster": image if isinstance(image, str) else None,
        "rating": (ld.get("aggregateRating") or {}).get("ratingValue"),
        "runtime": None,
        "source": "scrape",
    }


def _scrape_movie(tmdb_id: str, slug: str = "") -> dict | None:
    html = _get_page(f"{SITE}/movie/{tmdb_id}{('-' + slug) if slug else ''}")
    if not html:
        return None
    ld = _extract_ld_json(html, want_type="Movie")
    if not ld:
        return None
    return _norm_movie_from_ld(ld, tmdb_id)


def _scrape_tv(tmdb_id: str, slug: str = "") -> dict | None:
    html = _get_page(f"{SITE}/tv/{tmdb_id}{('-' + slug) if slug else ''}")
    if not html:
        return None
    ld = _extract_ld_json(html)
    if not ld:
        return None
    image = ld.get("image")
    return {
        "id": tmdb_id,
        "name": ld.get("name"),
        "original_name": ld.get("alternateName"),
        "year": (ld.get("datePublished") or "")[:4],
        "overview": ld.get("description"),
        "genres": ld.get("genre") or [],
        "poster": image if isinstance(image, str) else None,
        "rating": (ld.get("aggregateRating") or {}).get("ratingValue"),
        "source": "scrape",
    }


def _scrape_tv_seasons(tmdb_id: str) -> list[dict] | None:
    """Scrape the seasons list from the TMDB TV page (each season links
    to /tv/{id}/season/{n}). Works without an API key."""
    html = _get_page(f"{SITE}/tv/{tmdb_id}")
    if not html:
        return None
    out, seen = [], set()
    for m in re.finditer(rf'href="/tv/{tmdb_id}[^"/]*/season/(\d+)"', html):
        n = int(m.group(1))
        if n in seen or n == 0:
            continue
        seen.add(n)
        out.append({"season_number": n})
    out.sort(key=lambda s: s["season_number"])
    return out or None


def _scrape_search(kind: str, query: str) -> list[dict] | None:
    # Every search kind needs the ?query= param; only "multi" lives at /search.
    if kind == "multi":
        url = f"{SITE}/search?query={quote_plus(query)}"
    else:
        url = f"{SITE}/search/{kind}?query={quote_plus(query)}"
    html = _get_page(url)
    if not html:
        return None
    out = []
    for m in _SEARCH_CARD_RE.finditer(html):
        k, mid, slug = m.group(1), m.group(2), m.group(3)
        out.append(
            {"id": mid, "kind": k, "slug": slug,
             "title": slug.replace("-", " ").title(),
             "poster": _poster_near(html, m.end())}
        )
        if len(out) >= 20:
            break
    return out or None


def _scrape_browse(kind: str, sub: str) -> list[dict] | None:
    """popular/top_rated/now_playing/upcoming (movie) or airing_today/on_the_air (tv).
    Only the default popular board has a scrapeable page (/movie, /tv); the other
    boards 404 on the static path, so callers fall back to the API for those."""
    url = f"{SITE}/{kind}" if sub == "popular" else f"{SITE}/{kind}/{sub}"
    html = _get_page(url)
    if not html:
        return None
    out, seen = [], set()
    for m in _BROWSE_CARD_RE.finditer(html):
        k, mid, slug = m.group(1), m.group(2), m.group(3)
        if mid in seen:
            continue
        seen.add(mid)
        out.append(
            {"id": mid, "kind": k, "slug": slug,
             "title": slug.replace("-", " ").title(),
             "poster": _poster_near(html, m.end())}
        )
        if len(out) >= 20:
            break
    return out or None


def _scrape_cards(html: str, limit: int = 20) -> list[dict] | None:
    """Generic card extractor (movie/tv/person/company/network/collection)."""
    out, seen = [], set()
    for m in _CARD_RE.finditer(html):
        mid = m.group(2)
        if mid in seen:
            continue
        seen.add(mid)
        out.append(
            {"id": mid, "kind": m.group(1), "slug": m.group(3),
             "title": m.group(3).replace("-", " ").title(),
             "poster": _poster_near(html, m.end())}
        )
        if len(out) >= limit:
            break
    return out or None


# Static TMDB genre tables -- the /genre list page 404s on static fetch, but
# these IDs/names are stable and rarely change, so we use them as the
# scrape-equivalent source for genres().
_GENRES = {
    "movie": [
        {"id": 28, "name": "Action"}, {"id": 12, "name": "Adventure"},
        {"id": 16, "name": "Animation"}, {"id": 35, "name": "Comedy"},
        {"id": 80, "name": "Crime"}, {"id": 99, "name": "Documentary"},
        {"id": 18, "name": "Drama"}, {"id": 10751, "name": "Family"},
        {"id": 14, "name": "Fantasy"}, {"id": 36, "name": "History"},
        {"id": 27, "name": "Horror"}, {"id": 10402, "name": "Music"},
        {"id": 9648, "name": "Mystery"}, {"id": 10749, "name": "Romance"},
        {"id": 878, "name": "Science Fiction"}, {"id": 10770, "name": "TV Movie"},
        {"id": 53, "name": "Thriller"}, {"id": 10752, "name": "War"},
        {"id": 37, "name": "Western"},
    ],
    "tv": [
        {"id": 10759, "name": "Action & Adventure"}, {"id": 16, "name": "Animation"},
        {"id": 35, "name": "Comedy"}, {"id": 80, "name": "Crime"},
        {"id": 99, "name": "Documentary"}, {"id": 18, "name": "Drama"},
        {"id": 10751, "name": "Family"}, {"id": 10762, "name": "Kids"},
        {"id": 9648, "name": "Mystery"}, {"id": 10763, "name": "News"},
        {"id": 10764, "name": "Reality"}, {"id": 10765, "name": "Sci-Fi & Fantasy"},
        {"id": 10766, "name": "Soap"}, {"id": 10767, "name": "Talk"},
        {"id": 10768, "name": "War & Politics"}, {"id": 37, "name": "Western"},
    ],
}


def _scrape_reviews(html: str) -> list[dict] | None:
    """Parse the JS-rendered /reviews page. Each review lives in a
    <div class=\"review_container\"> block with the author in /u/... and the
    body in a <p> inside the 'teaser' div."""
    out = []
    for part in html.split('class="review_container">'):
        if not part.strip():
            continue
        author = _REVIEW_AUTHOR_RE.search(part)
        p = _REVIEW_TEASER_RE.search(part) or _REVIEW_P_RE.search(part)
        if not p:
            continue
        txt = _TAG_RE.sub("", p.group(1)).strip()
        if txt:
            out.append(
                {"author": author.group(1) if author else None,
                 "content": txt[:600]}
            )
    return out or None


def _scrape_watch(html: str) -> dict | None:
    """Best-effort: collect provider names from the /watch page."""
    provs = [{"name": m.group(1)} for m in _WATCH_PROV_RE.finditer(html)]
    if not provs:  # fallback: network links
        provs = [
            {"id": m.group(1), "name": m.group(2).replace("-", " ").title()}
            for m in _WATCH_NET_RE.finditer(html)
        ]
    return {"results": provs} if provs else None


def _scrape_episodes(html: str, tmdb_id: str) -> list[dict] | None:
    out, seen = [], set()
    for m in re.finditer(
        rf'href="/tv/{tmdb_id}[^"/]*/season/\d+/episode/(\d+)"', html
    ):
        n = int(m.group(1))
        if n not in seen:
            seen.add(n)
            out.append({"episode_number": n})
    return out or None


def _scrape_image_urls(html: str) -> list[str] | None:
    urls = _IMAGE_URL_RE.findall(html)
    return [u.split("?")[0] for u in dict.fromkeys(urls)] or None


def _scrape_detail(html: str, tmdb_id: str, kind: str) -> dict:
    """Generic detail-page parse: title from <title> + JSON-LD if present."""
    ld = _extract_ld_json(html) or {}
    title = _TITLE_RE.search(html)
    name = ld.get("name") or (title.group(1).strip() if title else None)
    return {"id": tmdb_id, "name": name, "source": "scrape"}


def _scrape_appendage(kind: str, tmdb_id: str, sub: str) -> dict | list | None:
    """Scrape the sub-pages that have anonymous web pages."""
    if sub == "reviews":
        html = _get_page(f"{SITE}/{kind}/{tmdb_id}/reviews", dynamic=True)
        return _scrape_reviews(html) if html else None
    if sub == "images":
        posters = _scrape_image_urls(
            _get_page(f"{SITE}/{kind}/{tmdb_id}/images/posters", dynamic=True) or ""
        )
        backdrops = _scrape_image_urls(
            _get_page(f"{SITE}/{kind}/{tmdb_id}/images/backdrops", dynamic=True) or ""
        )
        if posters or backdrops:
            return {"posters": posters or [], "backdrops": backdrops or [],
                    "source": "scrape"}
    if sub == "videos":
        html = _get_page(f"{SITE}/{kind}/{tmdb_id}/videos", dynamic=True)
        if html:
            vids = _YT_RE.findall(html)
            if vids:
                return {"results": [{"key": v, "site": "YouTube"}
                                    for v in dict.fromkeys(vids)],
                        "source": "scrape"}
    # 'changes' has no anonymous page (404) -- callers fall back to the API.
    return None


# ===========================================================================
# PUBLIC FACADE -- scrape first, API on failure
# ===========================================================================
# ---- MOVIES ----
def get_movie(
    tmdb_id: str,
    slug: str = "",
    append: str = "credits,external_ids,watch/providers,videos,recommendations,"
    "similar,reviews,images,keywords,translations,alternative_titles,release_dates",
) -> dict:
    # Prefer the full raw API record when a key is configured: it carries
    # videos, credits, watch/providers, recommendations, etc. that the
    # detail page renders. The scrape path only yields a slim record
    # (name + overview + genre names) and is used as the no-key fallback.
    if TMDB_API_KEY:
        d = _api_get(f"/movie/{tmdb_id}", {"append_to_response": append})
        if d:
            return d
    d = _scrape_movie(tmdb_id, slug)
    if d:
        return d
    d = _api_get(f"/movie/{tmdb_id}", {"append_to_response": append})
    if not d:
        raise RuntimeError(f"movie {tmdb_id} unavailable from both sources")
    return d


def movie_appendages(tmdb_id: str, sub: str) -> dict | list:
    """sub in: credits, external_ids, watch/providers, videos, recommendations,
    similar, reviews, images, keywords, translations, alternative_titles,
    release_dates, lists, changes, account_states, rating."""
    scraped = _scrape_appendage("movie", tmdb_id, sub)
    if scraped:
        return scraped
    d = _api_get(f"/movie/{tmdb_id}/{sub}")
    if d is None:
        raise RuntimeError(f"movie/{tmdb_id}/{sub} unavailable")
    return d


def movie_boards(sub: str) -> list:
    """sub in: popular, top_rated, now_playing, upcoming, latest, changes."""
    if sub == "changes":
        d = _api_get("/movie/changes")
        return d.get("results", []) if d else []
    # 'popular' has a scrapeable page, but the scrape omits vote_average and
    # release_date -- so its cards render without the score ring / year and
    # look inconsistent with the API-backed rows. Use the API for it.
    if sub == "popular":
        d = _api_get(f"/movie/{sub}")
        return d.get("results", []) if d else []
    scraped = _scrape_browse("movie", sub)
    if scraped:
        return scraped
    d = _api_get(f"/movie/{sub}")
    return d.get("results", []) if d else []


# ---- TV ----
def get_tv(
    tmdb_id: str,
    slug: str = "",
    append: str = "credits,external_ids,watch/providers,videos,recommendations,"
    "similar,reviews,images,keywords,translations,alternative_titles,"
    "content_ratings,aggregate_credits,season,episode_groups",
) -> dict:
    # Prefer the full raw API record when a key is configured (see
    # get_movie for the rationale). The scrape path is the no-key fallback.
    if TMDB_API_KEY:
        d = _api_get(f"/tv/{tmdb_id}", {"append_to_response": append})
        if d:
            return d
    d = _scrape_tv(tmdb_id, slug)
    if d:
        return d
    d = _api_get(f"/tv/{tmdb_id}", {"append_to_response": append})
    if not d:
        raise RuntimeError(f"tv {tmdb_id} unavailable from both sources")
    return d


def get_tv_seasons(tmdb_id: str) -> list[dict]:
    """List of {season_number, name?, episode_count?, poster?, air_date?} for a
    TV show.

    We fetch the full /tv/{id} record ONCE (the `seasons` array is already
    embedded), which is cheaper than one API call per season. The scraped
    season numbers are used only as a no-key fallback.
    """
    d = _api_get(f"/tv/{tmdb_id}")
    if d and d.get("seasons"):
        return [
            {"season_number": s.get("season_number"), "name": s.get("name"),
             "episode_count": s.get("episode_count"),
             "poster": _img(s.get("poster_path"), "w300"),
             "air_date": s.get("air_date")}
            for s in d["seasons"] if s.get("season_number")
        ]
    # No API key / no data -- fall back to scraped season numbers only.
    scraped = _scrape_tv_seasons(tmdb_id)
    if scraped:
        return [
            {"season_number": s["season_number"],
             "name": f"Season {s['season_number']}",
             "episode_count": None, "poster": None, "air_date": None}
            for s in scraped
        ]
    return []


def tv_appendages(tmdb_id: str, sub: str) -> dict | list:
    """sub in: credits, external_ids, watch/providers, videos, recommendations,
    similar, reviews, images, keywords, translations, alternative_titles,
    content_ratings, aggregate_credits, episode_groups, lists, changes,
    account_states, screened_theatrically, rating."""
    scraped = _scrape_appendage("tv", tmdb_id, sub)
    if scraped:
        return scraped
    d = _api_get(f"/tv/{tmdb_id}/{sub}")
    if d is None:
        raise RuntimeError(f"tv/{tmdb_id}/{sub} unavailable")
    return d


def get_season(tmdb_id: str, season_number: int, sub: str = "") -> dict:
    """sub in: '', changes, account_states, aggregate_credits, credits,
    external_ids, images, videos, translations."""
    if not sub:
        html = _get_page(f"{SITE}/tv/{tmdb_id}/season/{season_number}")
        if html:
            eps = _scrape_episodes(html, tmdb_id)
            if eps:
                return {"season_number": season_number, "episodes": eps,
                        "source": "scrape"}
    path = f"/tv/{tmdb_id}/season/{season_number}" + (f"/{sub}" if sub else "")
    d = _api_get(path)
    if d is None:
        raise RuntimeError(
            f"tv/{tmdb_id}/season/{season_number}/{sub} unavailable"
        )
    return d


def get_episode(
    tmdb_id: str, season_number: int, episode_number: int, sub: str = ""
) -> dict:
    """sub in: '', changes, account_states, credits, external_ids, images,
    videos, translations."""
    if not sub:
        html = _get_page(
            f"{SITE}/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}"
        )
        if html:
            ld = _extract_ld_json(html) or {}
            title = _TITLE_RE.search(html)
            return {
                "season_number": season_number,
                "episode_number": episode_number,
                "name": ld.get("name") or (title.group(1).strip() if title else None),
                "source": "scrape",
            }
    path = (
        f"/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}"
        + (f"/{sub}" if sub else "")
    )
    d = _api_get(path)
    if d is None:
        raise RuntimeError("episode unavailable")
    return d


def tv_boards(sub: str) -> list:
    """sub in: popular, top_rated, airing_today, on_the_air, latest, changes."""
    if sub == "changes":
        d = _api_get("/tv/changes")
        return d.get("results", []) if d else []
    if sub == "popular":
        d = _api_get(f"/tv/{sub}")
        return d.get("results", []) if d else []
    scraped = _scrape_browse("tv", sub)
    if scraped:
        return scraped
    d = _api_get(f"/tv/{sub}")
    return d.get("results", []) if d else []


# ---- PERSON ----
def get_person(
    person_id: str,
    sub: str = "",
    append: str = "combined_credits,external_ids,images,tagged_images,"
    "translations,changes",
) -> dict:
    if sub:
        d = _api_get(f"/person/{person_id}/{sub}")
        if d is None:
            raise RuntimeError(f"person/{person_id}/{sub} unavailable")
        return d

    def _api_record():
        d = _api_get(f"/person/{person_id}", {"append_to_response": append})
        if not d:
            return None
        # Pass the full API record through (combined_credits etc. included)
        # so a person detail page has the filmography and external ids.
        credits = d.get("combined_credits") or {"cast": [], "crew": []}
        return {"id": str(d.get("id")), "name": d.get("name"),
                "biography": d.get("biography"),
                "birthday": d.get("birthday"), "deathday": d.get("deathday"),
                "place_of_birth": d.get("place_of_birth"),
                "known_for_department": d.get("known_for_department"),
                "profile": _img(d.get("profile_path")),
                "combined_credits": credits,
                "external_ids": d.get("external_ids") or {},
                "images": (d.get("images") or {}).get("profiles", []),
                "source": "api"}

    # Prefer the API when a key is configured: scraping only yields name +
    # bio and no filmography/external ids, which the person page needs.
    if TMDB_API_KEY:
        rec = _api_record()
        if rec:
            return rec
    html = _get_page(f"{SITE}/person/{person_id}")
    if html:
        ld = _extract_ld_json(html)
        if ld and ld.get("@type") in ("Person", None):
            return {"id": person_id, "name": ld.get("name"),
                    "biography": ld.get("description"),
                    "image": ld.get("image"), "source": "scrape"}
    rec = _api_record()
    if not rec:
        raise RuntimeError(f"person {person_id} unavailable")
    return rec
    return {"id": str(d.get("id")), "name": d.get("name"),
            "biography": d.get("biography"),
            "birthday": d.get("birthday"), "deathday": d.get("deathday"),
            "place_of_birth": d.get("place_of_birth"),
            "known_for_department": d.get("known_for_department"),
            "profile": _img(d.get("profile_path")),
            "combined_credits": credits,
            "external_ids": d.get("external_ids") or {},
            "images": (d.get("images") or {}).get("profiles", []),
            "source": "api"}


def person_boards(sub: str) -> list:
    """sub in: popular, latest, changes."""
    if sub == "popular":
        html = _get_page(f"{SITE}/person")
        if html:
            cards = _scrape_cards(html)
            if cards:
                return cards
    d = _api_get(f"/person/{sub}")
    return d.get("results", []) if d else []


# ---- SEARCH ----
def search(kind: str, query: str, page: int = 1, year: int | None = None) -> list | dict:
    """kind in: multi, movie, tv, person, collection, company, keyword.

    Prefers the TMDB API so results carry consistent fields (poster_path,
    vote_average, release dates, correct titles) and the real total_results /
    total_pages. Falls back to the anonymous scrape only when no key is set.
    Returns the full API dict (results + totals) or a list for the scrape path.
    """
    valid = ("multi", "movie", "tv", "person", "collection", "company", "keyword")
    if kind not in valid:
        return []
    params: dict = {"query": query, "page": page, "include_adult": False}
    if year:
        params["year"] = year
    d = _api_get(f"/search/{kind}", params)
    if d is not None:
        return d
    # No API key (or API error) -> scrape fallback (lower fidelity).
    scraped = _scrape_search(kind, query)
    return scraped or []


# ---- DISCOVER ----
def discover(kind: str, **filters) -> list:
    """kind in: movie, tv. Scrape the /discover/{kind} board (ignores filters
    unless they map to query params); API fallback carries the full filter set."""
    params = "?" + "&".join(f"{k}={v}" for k, v in filters.items()) if filters else ""
    html = _get_page(f"{SITE}/discover/{kind}{params}")
    if html:
        cards = _scrape_cards(html)
        if cards:
            return cards
    d = _api_get(f"/discover/{kind}", filters)
    return d.get("results", []) if d else []


# ---- TRENDING ----
def trending(media_type: str = "all", time_window: str = "week", page: int = 1) -> list:
    """media_type in: all, movie, tv, person. time_window in: day, week.
    Scrape-equivalent: the /movie and /tv popular boards are TMDB's trending
    surfaces. 'all'/'person' fall back to the API (no anonymous page)."""
    if media_type in ("movie", "tv"):
        html = _get_page(f"{SITE}/{media_type}")
        if html:
            cards = _scrape_cards(html)
            if cards:
                return cards
    d = _api_get(f"/trending/{media_type}/{time_window}", {"page": page})
    return d.get("results", []) if d else []


# ---- GENRES ----
def genres(kind: str = "movie") -> list:
    """kind in: movie, tv. The /genre list page 404s on static fetch, so we use
    the stable static genre tables (scrape-equivalent, no API key needed)."""
    return _GENRES.get(kind, [])


# ---- WATCH PROVIDERS ----
def watch_providers(kind: str, tmdb_id: str) -> dict:
    """kind in: movie, tv. The /watch page renders providers via a JustWatch
    XHR (not in the DOM), so this is API-only. Returns the region->provider
    map when a key is present, else an empty dict."""
    d = _api_get(f"/{kind}/{tmdb_id}/watch/providers")
    return d.get("results", {}) if d else {}


def watch_providers_available_regions(kind: str = "movie") -> list:
    d = _api_get(f"/watch/providers/{kind}/regions")
    return d.get("results", []) if d else []


# ---- REVIEWS ----
def reviews(kind: str, tmdb_id: str, page: int = 1) -> list:
    html = _get_page(f"{SITE}/{kind}/{tmdb_id}/reviews", dynamic=True)
    scraped = _scrape_reviews(html) if html else None
    if scraped:
        return scraped
    d = _api_get(f"/{kind}/{tmdb_id}/reviews", {"page": page})
    return d.get("results", []) if d else []


# ---- KEYWORDS ----
def keyword(id_or_name: str, tmdb_id: str = "") -> dict:
    target = tmdb_id or id_or_name
    d = _api_get(f"/keyword/{target}")
    return d or {}


def keyword_movies(keyword_id: str, page: int = 1) -> list:
    """Scrape the keyword's movie list. The /keyword/{id}/movie path 404s, so
    we scrape the main /keyword/{id} page (which lists its movies); API
    fallback for paging."""
    html = _get_page(f"{SITE}/keyword/{keyword_id}")
    if html:
        cards = _scrape_cards(html)
        if cards:
            return cards
    d = _api_get(f"/keyword/{keyword_id}/movies", {"page": page})
    return d.get("results", []) if d else []


# ---- NETWORKS ----
def network(network_id: str, sub: str = "") -> dict:
    """sub in: '', alternative_names, images."""
    if not sub:
        html = _get_page(f"{SITE}/network/{network_id}")
        if html:
            return _scrape_detail(html, network_id, "network")
    d = _api_get(f"/network/{network_id}" + (f"/{sub}" if sub else ""))
    return d or {}


# ---- COMPANIES ----
def company(company_id: str, sub: str = "") -> dict:
    """sub in: '', alternative_names, images."""
    if not sub:
        html = _get_page(f"{SITE}/company/{company_id}")
        if html:
            return _scrape_detail(html, company_id, "company")
    d = _api_get(f"/company/{company_id}" + (f"/{sub}" if sub else ""))
    return d or {}


# ---- COLLECTIONS ----
def collection(collection_id: str, sub: str = "") -> dict:
    """sub in: '', images, translations."""
    if not sub:
        html = _get_page(f"{SITE}/collection/{collection_id}")
        if html:
            return _scrape_detail(html, collection_id, "collection")
    d = _api_get(f"/collection/{collection_id}" + (f"/{sub}" if sub else ""))
    return d or {}


# ---- CREDITS ----
def credit(credit_id: str) -> dict:
    d = _api_get(f"/credit/{credit_id}")
    return d or {}


# ---- CERTIFICATIONS ----
def certifications(kind: str = "movie") -> dict:
    d = _api_get(f"/certification/{kind}/list")
    return d or {}


# ---- FIND (by external id: imdb, tvdb, fb, etc.) ----
def find(external_id: str, source: str = "imdb_id") -> dict:
    """source in: imdb_id, freebase_mid, freebase_id, tvdb_id, tvrage_id,
    facebook_id, twitter_id, instagram_id."""
    d = _api_get(f"/find/{external_id}", {"external_source": source})
    return d or {}


# ---- CHANGES (lists of changed ids) ----
def changes(kind: str, page: int = 1, **filters) -> dict:
    """kind in: movie, tv, person. The changed-id feed has no anonymous web
    page (the per-item /changes board 404s), so this is API-only."""
    d = _api_get(f"/{kind}/changes", {"page": page, **filters})
    return d or {}


# ---- LISTS ----
def tmdb_list(
    list_id: str, sub: str = "", item_id: str = "", body: dict | None = None
) -> dict:
    """Read: '', item_status. Write (API-only, need session): add_item,
    clear, remove_item."""
    if sub in ("add_item", "clear", "remove_item"):
        return _api_post(f"/list/{list_id}/{sub}", body=body) or {}
    d = _api_get(f"/list/{list_id}" + (f"/{sub}" if sub else ""))
    return d or {}


# ---- IMAGES / TRANSLATIONS (generic) ----
def images(kind: str, tmdb_id: str) -> dict:
    posters = _scrape_image_urls(
        _get_page(f"{SITE}/{kind}/{tmdb_id}/images/posters", dynamic=True) or ""
    )
    backdrops = _scrape_image_urls(
        _get_page(f"{SITE}/{kind}/{tmdb_id}/images/backdrops", dynamic=True) or ""
    )
    if posters or backdrops:
        return {"posters": posters or [], "backdrops": backdrops or [],
                "source": "scrape"}
    d = _api_get(f"/{kind}/{tmdb_id}/images")
    return d or {}


def translations(kind: str, tmdb_id: str) -> dict:
    html = _get_page(f"{SITE}/{kind}/{tmdb_id}/translations", dynamic=True)
    if html:
        rows = _TRANSLATION_RE.findall(html)
        if not rows:
            rows = [(c, c, c) for c in _TRANSLATION_CODE_RE.findall(html)]
        if rows:
            seen, out = set(), []
            for code, name, _ in rows:
                if code in seen:
                    continue
                seen.add(code)
                out.append(
                    {"iso_639_1": code.split("-")[0],
                     "iso_3166_1": code.split("-")[-1],
                     "name": name.strip(), "english_name": name.strip()}
                )
            return {"translations": out, "source": "scrape"}
    d = _api_get(f"/{kind}/{tmdb_id}/translations")
    return d or {}


# ---- ACCOUNT (API-only; needs session_id) ----
def account(account_id: str, session_id: str, sub: str = "", **filters) -> dict:
    """sub in: '', favorite/movies, favorite/tv, rated/movies, rated/tv,
    rated/tv/episodes, watchlist, watchlist/movies, watchlist/tv.
    Needs a v3 session_id (from authentication flow)."""
    d = _api_get(f"/account/{account_id}/{sub}",
                 {"session_id": session_id, **filters})
    return d or {}


def account_mark(account_id: str, session_id: str, action: str, body: dict) -> dict:
    """action in: favorite, watchlist, rating (POST). body has media_id/type."""
    return _api_post(f"/account/{account_id}/{action}",
                     {"session_id": session_id}, body) or {}


# ---- AUTHENTICATION (API-only) ----
def auth_request_token() -> dict:
    return _api_get("/authentication/token/new") or {}


def auth_session_new(request_token: str) -> dict:
    return _api_post("/authentication/session/new",
                     body={"request_token": request_token}) or {}


def auth_guest_session() -> dict:
    return _api_get("/authentication/guest_session/new") or {}


def auth_session_validate(request_token: str, username: str, password: str) -> dict:
    return _api_post(
        "/authentication/token/validate_with_login",
        body={"request_token": request_token, "username": username,
              "password": password},
    ) or {}


def auth_session_convert(access_token: str) -> dict:
    return _api_post("/authentication/session/convert/4",
                     body={"access_token": access_token}) or {}


# ---- RATINGS / WATCHLIST (write; API-only) ----
def rate(kind: str, tmdb_id: str, session_id: str, value: float) -> dict:
    """kind in: movie, tv, tv/episode/{s}/{e}. rating POST/DELETE."""
    return _api_post(f"/{kind}/{tmdb_id}/rating", {"session_id": session_id},
                     body={"value": value}) or {}


def delete_rating(kind: str, tmdb_id: str, session_id: str) -> dict:
    return _api_delete(f"/{kind}/{tmdb_id}/rating",
                       {"session_id": session_id}) or {}


# ---- CONFIGURATION ----
def configuration() -> dict:
    d = _api_get("/configuration")
    return d or {}


def primary_translations() -> list:
    d = _api_get("/configuration/primary_translations")
    return d or []


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    # quick self-test of a few read endpoints (scrape default)
    print("movie:", get_movie("533535", "deadpool-and-wolverine").get("title"))
    print("tv:", get_tv("1399", "game-of-thrones").get("name"))
    print("trending(all/week) count:", len(trending("all", "week")))
    print("search(movie,batman) count:", len(search("movie", "batman")))
    print("genres(movie):", [g["name"] for g in genres("movie")][:5])
