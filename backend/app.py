#!/usr/bin/env python3
"""
app.py — monnc backend API.

Wires the Python backend to the Astro frontend:

  Frontend (Astro, :4321)  ──►  Backend (FastAPI, :8028)
                                      │
                                      ├─ /api/tmdb/...        → TMDB forward proxy
                                      │                          (key stays server-side)
                                      ├─ /api/stream/movie/:id → real 111movies sources
                                      ├─ /api/stream/tv/:id/:s/:e
                                      ├─ /api/subtitles         → WebVTT (srt→vtt)
                                      ├─ /api/stream/play?url= → range-aware passthrough
                                      │                          (fixes CORS on bcdn hosts)
                                      └─ /px?target=<url>      → HEVC→H.264 transcoding
                                                                 proxy (proxy.py)

Run:  uvicorn app:app --host 0.0.0.0 --port 8028
"""
from __future__ import annotations

import json
import logging
import urllib.parse

import asyncio
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

import config
from stream import (
    StreamError,
    get_movie_sources,
    get_subtitle_manifest,
    get_subtitle_url,
    download_subtitle,
    srt_to_vtt,
    get_tv_sources,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("monnc")

app = FastAPI(title="monnc backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HTTP = httpx.AsyncClient(
    timeout=httpx.Timeout(20.0, read=None, write=30.0, pool=10.0),
    follow_redirects=True,
    headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    },
)


# ─────────────────────────────────────────────────────────────────────────────
# TMDB forward proxy  (key never leaves the backend)
# ─────────────────────────────────────────────────────────────────────────────

def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


async def _run(fn, *args):
    """Run a blocking tmdb.py call in a worker thread (keeps the loop free)."""
    return await asyncio.to_thread(fn, *args)


# tmdb.py pulls in scrapling, which may be partially installed (e.g. missing
# curl_cffi). Import it lazily so the rest of the backend (streams, the
# /px transcoding proxy, health) still boots if tmdb.py can't load.
_tmdb_mod = None


def _tmdb():
    global _tmdb_mod
    if _tmdb_mod is None:
        import tmdb

        _tmdb_mod = tmdb
    return _tmdb_mod


def _norm_card(it: dict) -> dict:
    # Handles both the raw TMDB API shape (poster_path/backdrop_path) and the
    # scrape-normalized shape (poster/backdrop full URLs).
    poster = it.get("poster_path") or it.get("poster")
    backdrop = it.get("backdrop_path") or it.get("backdrop")
    return {
        "id": _to_int(it.get("id")),
        "media_type": it.get("media_type") or it.get("kind"),
        "title": it.get("title") or it.get("name"),
        "name": it.get("title") or it.get("name"),
        "original_title": it.get("original_title") or it.get("title"),
        "original_name": it.get("title") or it.get("name"),
        "poster_path": poster,   # full URL (scrape) or path (API); frontend is tolerant
        "profile_path": poster,
        "backdrop_path": backdrop,
        "overview": it.get("overview"),
        "vote_average": it.get("vote_average") or it.get("rating") or 0,
    }


def _wrap_list(data) -> dict:
    # Already API-paged JSON (tmdb.py used its API fallback with a key).
    if isinstance(data, dict) and "results" in data:
        return data
    items = data or []
    return {
        "page": 1,
        "results": [_norm_card(i) for i in items],
        "total_pages": 1,
        "total_results": len(items),
    }


def _norm_detail(d: dict, kind: str) -> dict:
    if not d:
        return {}
    # Full API JSON — pass through, just reconcile the backdrop key.
    if "poster_path" in d or "backdrop_path" in d:
        d = dict(d)
        d["backdrop_path"] = d.get("backdrop_path") or d.get("backdrop")
        return d
    # Scrape-normalized shape — fill the appended sub-resources the
    # detail page reads via optional chaining.
    poster = d.get("poster")
    genres = [{"id": 0, "name": g} for g in (d.get("genres") or [])]
    return {
        "id": _to_int(d.get("id")),
        "title": d.get("title"), "name": d.get("title"),
        "original_title": d.get("original_title"), "original_name": d.get("title"),
        "overview": d.get("overview"),
        "release_date": (f"{d['year']}-01-01" if d.get("year") else ""),
        "first_air_date": str(d["year"]) if d.get("year") else None,
        "genres": genres,
        "poster_path": poster, "backdrop_path": None,
        "vote_average": d.get("rating") or 0, "vote_count": 0,
        "runtime": d.get("runtime"),
        "credits": {"cast": [], "crew": []},
        "images": {"posters": [], "backdrops": []},
        "videos": {"results": []},
        "recommendations": {"results": []}, "similar": {"results": []},
        "reviews": {"results": []}, "keywords": {"keywords": []},
        "external_ids": {}, "watch/providers": {"results": {}},
        "release_dates": {"results": []}, "belongs_to_collection": None,
        "tagline": None, "budget": 0, "revenue": 0,
        "status": None, "original_language": None,
    }


_MOVIE_BOARDS = ("popular", "top_rated", "upcoming", "now_playing")
_TV_BOARDS = ("popular", "top_rated", "on_the_air", "airing_today")


@app.api_route("/api/tmdb/{path:path}", methods=["GET", "POST"])
async def tmdb_proxy(path: str, request: Request):
    parts = [p for p in path.split("/") if p]
    try:
        if len(parts) >= 2 and parts[0] == "trending":
            media = parts[1]
            window = parts[2] if len(parts) > 2 else "week"
            data = await _run(_tmdb().trending, media, window)
            return JSONResponse(_wrap_list(data))
        if len(parts) == 2 and parts[0] == "search":
            # /api/tmdb/search/{multi|movie|tv|person|collection|company|keyword}?query=&page=
            q = request.query_params.get("query", "")
            try:
                page = int(request.query_params.get("page", "1"))
            except ValueError:
                page = 1
            kind = parts[1]
            data = await _run(_tmdb().search, kind, q, page)
            payload = _wrap_list(data)
            # TMDB's *typed* search endpoints (person/movie/tv/...) omit
            # `media_type` on each result, so the frontend mis-classifies
            # them (a person with `name` but no `title` looks like a tv show).
            # Stamp the search kind onto every result so routing is correct.
            if kind != "multi" and isinstance(payload, dict):
                for it in payload.get("results", []):
                    if isinstance(it, dict) and not it.get("media_type"):
                        it["media_type"] = kind
            return JSONResponse(payload)
        if len(parts) >= 2 and parts[0] == "person":
            # /api/tmdb/person/{id} or /api/tmdb/person/{id}/{sub}
            sub = parts[2] if len(parts) > 2 else ""
            try:
                data = await _run(_tmdb().get_person, parts[1], sub)
            except Exception:
                raise HTTPException(status_code=404, detail=f"person {parts[1]} not found")
            return JSONResponse(data)
        if len(parts) == 2 and parts[0] == "movie" and parts[1] in _MOVIE_BOARDS:
            return JSONResponse(_wrap_list(await _run(_tmdb().movie_boards, parts[1])))
        if len(parts) == 2 and parts[0] == "tv" and parts[1] in _TV_BOARDS:
            return JSONResponse(_wrap_list(await _run(_tmdb().tv_boards, parts[1])))
        if len(parts) == 4 and parts[0] == "tv" and parts[2] == "season":
            # /api/tmdb/tv/{id}/season/{n} -> raw season object (has `episodes`)
            try:
                data = await _run(_tmdb().tv_appendages, parts[1], f"season/{parts[3]}")
                if not data:
                    raise HTTPException(status_code=404, detail=f"tv {parts[1]} season {parts[3]} not found")
                return JSONResponse(data)
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"tmdb.py error: {exc}")
        if len(parts) == 3 and parts[0] == "tv" and parts[2] == "seasons":
            # /api/tmdb/tv/{id}/seasons -> list of {season_number, name, ...}
            try:
                data = await _run(_tmdb().get_tv_seasons, parts[1])
                return JSONResponse(data)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"tmdb.py error: {exc}")
        if len(parts) == 2 and parts[0] in ("movie", "tv"):
            fn = _tmdb().get_movie if parts[0] == "movie" else _tmdb().get_tv
            return JSONResponse(_norm_detail(await _run(fn, parts[1]), parts[0]))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"tmdb.py error: {exc}")
    raise HTTPException(status_code=404, detail=f"tmdb path not mapped: {path}")


async def _tmdb_imdb_id(tmdb_id: str, kind: str) -> str | None:
    """Resolve an IMDb id via tmdb.py's get_movie/get_tv (None without a key)."""
    fn = _tmdb().get_movie if kind == "movie" else _tmdb().get_tv
    try:
        data = await _run(fn, tmdb_id)
    except Exception:
        return None
    if not data:
        return None
    if "imdb_id" in data:
        return data.get("imdb_id")
    return (data.get("external_ids") or {}).get("imdb_id")


# ─────────────────────────────────────────────────────────────────────────────
# Streaming (111movies / MovieBox)
# ─────────────────────────────────────────────────────────────────────────────

def _pick_best_source(sources: list[dict]) -> dict | None:
    if not sources:
        return None
    def score(s: dict):
        q = str(s.get("quality", ""))
        num = 0
        for tok in ("1080", "720", "480", "360", "240"):
            if tok in q:
                num = int(tok)
                break
        mp4 = 1 if str(s.get("type", "")).lower() in ("mp4", "html5", "mkv") else 0
        return (mp4, num)
    return sorted(sources, key=score, reverse=True)[0]


def _build_tracks(imdb_id: str | None, manifest: list[dict] | None) -> list[dict]:
    tracks = []
    if not imdb_id or not manifest:
        return tracks
    for s in manifest:
        lang = s.get("language")
        if not lang:
            continue
        tracks.append({
            "src": f"/api/subtitles?imdb_id={urllib.parse.quote(imdb_id)}&lang={urllib.parse.quote(lang)}",
            "srclang": lang,
            "label": s.get("display") or lang,
            "kind": "subtitles",
        })
    return tracks


@app.get("/api/stream/movie/{tmdb_id}")
async def stream_movie(tmdb_id: str):
    try:
        data = get_movie_sources(tmdb_id)
    except StreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    sources = data.get("sources", []) or []
    best = _pick_best_source(sources)
    imdb_id = (data.get("imdb_id") or
               await _tmdb_imdb_id(tmdb_id, "movie"))
    subs = None
    if imdb_id:
        try:
            subs = get_subtitle_manifest(imdb_id)
        except StreamError:
            subs = None
    return {
        "type": "movie",
        "tmdb_id": tmdb_id,
        "imdb_id": imdb_id,
        "stream_url": best["url"] if best else None,
        "sources": sources,
        "tracks": _build_tracks(imdb_id, subs),
    }


@app.get("/api/stream/tv/{tmdb_id}/{season}/{episode}")
async def stream_tv(tmdb_id: str, season: int, episode: int):
    try:
        data = get_tv_sources(tmdb_id, season, episode)
    except StreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    sources = data.get("sources", []) or []
    best = _pick_best_source(sources)
    imdb_id = (data.get("imdb_id") or
               await _tmdb_imdb_id(tmdb_id, "tv"))
    subs = None
    if imdb_id:
        try:
            subs = get_subtitle_manifest(imdb_id, season=season, episode=episode)
        except StreamError:
            subs = None
    return {
        "type": "tv",
        "tmdb_id": tmdb_id,
        "season": season,
        "episode": episode,
        "imdb_id": imdb_id,
        "stream_url": best["url"] if best else None,
        "sources": sources,
        "tracks": _build_tracks(imdb_id, subs),
    }


@app.get("/api/subtitles")
async def subtitles(imdb_id: str, lang: str = "en", season: int | None = None,
                    episode: int | None = None):
    try:
        url = get_subtitle_url(imdb_id, language=lang, season=season, episode=episode)
        if not url:
            raise HTTPException(status_code=404, detail=f"No {lang} subtitle for {imdb_id}")
        srt_bytes = download_subtitle(url)
    except StreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    vtt = srt_to_vtt(srt_bytes.decode("utf-8", "ignore"))
    return Response(vtt, media_type="text/vtt; charset=utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Range-aware passthrough proxy (same-origin playback, no CORS on bcdn hosts)
# ─────────────────────────────────────────────────────────────────────────────

_HTTP_FORWARD = {
    "user-agent", "referer", "origin", "accept", "accept-encoding",
    "accept-language", "range", "cookie",
}


@app.api_route("/api/stream/play", methods=["GET", "HEAD"])
async def stream_play(request: Request):
    target = request.query_params.get("url")
    if not target or not urllib.parse.urlparse(target).scheme in ("http", "https"):
        raise HTTPException(status_code=400, detail="Missing or invalid ?url=")
    headers = {k: v for k, v in request.headers.items()
               if k.lower() in _HTTP_FORWARD}
    try:
        upstream = await HTTP.send(
            HTTP.build_request("GET" if request.method == "GET" else "HEAD",
                              target, headers=headers),
            stream=True,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream error: {exc}")

    resp_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in ("connection", "keep-alive", "transfer-encoding", "upgrade")
    }
    resp_headers.setdefault("Accept-Ranges", "bytes")
    resp_headers["Access-Control-Allow-Origin"] = "*"

    if request.method == "HEAD":
        await upstream.aclose()
        return Response(status_code=upstream.status_code, headers=resp_headers)

    async def gen():
        async for chunk in upstream.aiter_bytes():
            yield chunk

    return StreamingResponse(
        gen(), status_code=upstream.status_code,
        headers=resp_headers,
        background=None,
    )


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "tmdb_source": "tmdb.py (scrape-first; API fallback with TMDB_API_KEY)",
        "tmdb_api_key_set": bool(config.TMDB_API_KEY),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Mount the HEVC→H.264 transcoding proxy (proxy.py) at /px
#   e.g.  /px?target=<urlencoded bcdn url>
# ─────────────────────────────────────────────────────────────────────────────

from proxy import app as _proxy_app  # noqa: E402

app.mount("/px", _proxy_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host=config.BACKEND_HOST, port=config.BACKEND_PORT,
                log_level="info")
