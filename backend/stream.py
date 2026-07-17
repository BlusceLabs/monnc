"""
111movies stream pipeline — fully reverse-engineered & working.

End-to-end flow (every step verified live):

  AUTH
    POST https://momlover.notyourtype.dad/auth/generate-token
        body: {"clientData":{}}
        headers: Origin: https://player.vidlove.cc
        -> {"success":true,"token":"<jwt-ish>","expiresMs":30000}
    (token is valid ~30s; refresh per request)

  DATA (movie)
    GET https://momlover.notyourtype.dad/moviebox/movie/{tmdb_id}
        headers:
          x-request-token: <token from AUTH>
          x-response-encryption: aes-gcm
          Origin: https://player.vidlove.cc
        -> {"v":"gcm","payload":"<base64>"}

  DATA (tv episode)
    GET https://momlover.notyourtype.dad/moviebox/tv/{tmdb_id}/{season}/{episode}
        same headers -> same envelope shape. type:"tv", season/episode set.

  SUBTITLES (separate service, no crypto)
    111movies proxies OpenSubtitles via its own /wyzie endpoint:
      GET https://111movies.net/wyzie?id={imdb_id}[&season={s}&episode={e}]
        -> [{display, language, url:"https://111movies.net/wyzie/{token}", encoding}]
      GET https://111movies.net/wyzie/{token}  -> raw SubRip (.srt)
    See get_subtitle_manifest() / get_subtitle_url() below.

  DECODE (moviebox payload)
    1. base64 decode  -> raw bytes (NOT zstd; the sec-* 'zstd' label is misdirection)
    2. split:  salt=bytes[0:16]  iv=bytes[16:28]  ct=bytes[28:-16]  tag=bytes[-16:]
    3. key = SHA256("Sn00pD0g#RESP_B4SE_K3y_2026!" + salt)   # hardcoded const
    4. AESGCM(key).decrypt(iv, ct+tag)  -> JSON
        {success,type,tmdbId,sources:[{url,quality,type,size,provider}],subtitles:[...]}

  sources[].url  ->  real MP4 on bcdn.hakunaymatata.com (verified 200/206, video/mp4).
"""
import base64
import hashlib
import json
import re
import urllib.request
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class StreamError(RuntimeError):
    """Raised when the 111movies/MovieBox backend is unreachable or returns
    data we cannot decode. Surfaced by the API as a 502."""


# Honor the shared fetch-timeout config when available; fall back to 20s.
try:
    from config import FETCH_TIMEOUT_MS as _FETCH_TIMEOUT_MS
except Exception:  # config not importable in isolation
    _FETCH_TIMEOUT_MS = 20000
_TIMEOUT = max(1, int(_FETCH_TIMEOUT_MS) / 1000)

HOST = "https://momlover.notyourtype.dad"
RESP_BASE_KEY = b"Sn00pD0g#RESP_B4SE_K3y_2026!"
ORIGIN = "https://player.vidlove.cc"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _post(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Origin": ORIGIN, "User-Agent": UA}, method="POST")
    try:
        return urllib.request.urlopen(req, timeout=_TIMEOUT).read()
    except Exception as exc:  # timeout / 5xx / DNS / TLS
        raise StreamError(f"POST {url} failed: {type(exc).__name__}: {exc}") from exc


def _get(url, token):
    req = urllib.request.Request(url, headers={"Origin": ORIGIN, "User-Agent": UA,
                                                "x-request-token": token,
                                                "x-response-encryption": "aes-gcm"}, method="GET")
    try:
        return urllib.request.urlopen(req, timeout=_TIMEOUT).read()
    except Exception as exc:
        raise StreamError(f"GET {url} failed: {type(exc).__name__}: {exc}") from exc


def get_token(host=HOST):
    raw = _post(f"{host}/auth/generate-token", {"clientData": {}})
    try:
        return json.loads(raw)["token"]
    except (ValueError, KeyError) as exc:
        raise StreamError("auth/generate-token returned an unexpected payload") from exc


def decrypt_payload(payload_b64: str) -> dict:
    blob = base64.b64decode(payload_b64)
    salt, iv, tag = blob[0:16], blob[16:28], blob[-16:]
    ct = blob[28:-16]
    key = hashlib.sha256(RESP_BASE_KEY + salt).digest()
    plaintext = AESGCM(key).decrypt(iv, ct + tag, None)
    return json.loads(plaintext.decode("utf-8"))


def get_movie_sources(tmdb_id, host=HOST, token=None):
    """Return the decoded moviebox JSON (sources + subtitles) for a TMDB id."""
    token = token or get_token(host)
    body = _get(f"{host}/moviebox/movie/{tmdb_id}", token)
    try:
        env = json.loads(body)
        payload = env["payload"]
    except (ValueError, KeyError) as exc:
        raise StreamError("moviebox/movie envelope was not the expected JSON") from exc
    return decrypt_payload(payload)


def get_stream_urls(tmdb_id, host=HOST):
    """Convenience: list of {url, quality, type, size} for a TMDB id."""
    data = get_movie_sources(tmdb_id, host)
    return [
        {"url": s["url"], "quality": s.get("quality"), "type": s.get("type"),
         "size": s.get("size"), "provider": s.get("provider")}
        for s in data.get("sources", [])
    ]


def get_tv_sources(tmdb_id, season, episode, host=HOST, token=None):
    """TV-episode variant. Endpoint: /moviebox/tv/{tmdb_id}/{season}/{episode}.
    Same token + AES-GCM envelope as movies. Returns decoded JSON."""
    token = token or get_token(host)
    body = _get(f"{host}/moviebox/tv/{tmdb_id}/{season}/{episode}", token)
    env = json.loads(body)
    return decrypt_payload(env["payload"])


def get_tv_stream_urls(tmdb_id, season, episode, host=HOST):
    """Convenience: list of {url, quality, type, size} for a TV episode."""
    data = get_tv_sources(tmdb_id, season, episode, host)
    return [
        {"url": s["url"], "quality": s.get("quality"), "type": s.get("type"),
         "size": s.get("size"), "provider": s.get("provider")}
        for s in data.get("sources", [])
    ]


# ----------------------------------------------------------------------------
# SUBTITLES  (separate from the moviebox crypto; served by 111movies' /wyzie)
#
#   111movies proxies OpenSubtitles via its own /wyzie endpoint:
#     GET https://111movies.net/wyzie?id={imdb_id}[&season={s}&episode={e}]
#       -> [{display, language, url:"https://111movies.net/wyzie/{token}",
#            encoding:"UTF-8"}, ...]
#     GET https://111movies.net/wyzie/{token}
#       -> raw SubRip (.srt) file (content-type application/force-download)
#   No auth/token/encryption needed. TV episodes add season/episode params.
# ----------------------------------------------------------------------------
WYZIE_BASE = "https://111movies.net"


def get_subtitle_manifest(imdb_id, season=None, episode=None, base=WYZIE_BASE):
    """Return the list of available subtitles for a title (or TV episode)."""
    params = f"id={imdb_id}"
    if season is not None:
        params += f"&season={season}&episode={episode}"
    req = urllib.request.Request(f"{base}/wyzie?{params}",
                                 headers={"User-Agent": UA, "Origin": base}, method="GET")
    raw = urllib.request.urlopen(req, timeout=_TIMEOUT).read()
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise StreamError("wyzie manifest was not valid JSON") from exc


def get_subtitle_url(imdb_id, language="en", season=None, episode=None, base=WYZIE_BASE):
    """Convenience: direct .srt download URL for a given language (default en)."""
    for s in get_subtitle_manifest(imdb_id, season, episode, base):
        if s.get("language") == language:
            return s["url"]
    return None


def download_subtitle(url, base=WYZIE_BASE):
    """Fetch a .srt file from a /wyzie/{token} URL.

    Cloudflare fronts this endpoint: it requires a browser User-Agent AND a
    Referer/Origin of 111movies.net, and the token is single-use/short-lived,
    so always re-fetch the manifest (get_subtitle_url) immediately before this.
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": f"{base}/",
        "Origin": base,
    }, method="GET")
    return urllib.request.urlopen(req, timeout=_TIMEOUT).read()


def srt_to_vtt(srt: str) -> str:
    """Best-effort SubRip (.srt) -> WebVTT (.vtt) for <track src>.

    Browsers only render WebVTT text tracks, and the wyzie endpoint serves
    raw SubRip, so the proxy converts it before returning text/vtt.
    """
    srt = srt.replace("\ufeff", "").replace("\r", "")
    cues: list[str] = []
    for raw_block in re.split(r"\n\s*\n", srt):
        lines = [ln for ln in raw_block.split("\n") if ln.strip() != ""]
        if not lines:
            continue
        if lines[0].strip().isdigit():  # drop the numeric cue index
            lines = lines[1:]
        if not lines:
            continue
        cues.append("\n".join(
            ln.replace(",", ".") if "-->" in ln else ln for ln in lines
        ))
    return "WEBVTT\n\n" + "\n\n".join(cues) + ("\n" if cues else "")


if __name__ == "__main__":
    import sys
    # usage: python3 stream111.py MOVIE_TMDB_ID
    #        python3 stream111.py TV_TMDB_ID SEASON EPISODE
    #   (streams)  -- add flag "subs" to also print subtitle languages
    args = sys.argv[1:]
    show_subs = "subs" in args
    args = [a for a in args if a != "subs"]
    if len(args) == 3:
        tid, s, e = args
        print(f"=== TV {tid} s{s}e{e} ===")
        for src in get_tv_stream_urls(tid, s, e):
            print(f"[{src['quality']}] {src['type']}  {src['size']}B  {src['provider']}")
            print("   ", src["url"])
        if show_subs:
            print("--- subtitles ---")
            for sub in get_subtitle_manifest("tt0944947", s, e):
                print(f"  [{sub['language']}] {sub['display']}  {sub['url']}")
    else:
        tid = args[0] if args else "533535"
        print(f"=== MOVIE {tid} ===")
        for src in get_stream_urls(tid):
            print(f"[{src['quality']}] {src['type']}  {src['size']}B  {src['provider']}")
            print("   ", src["url"])
        if show_subs:
            print("--- subtitles ---")
            for sub in get_subtitle_manifest("tt6263850"):
                print(f"  [{sub['language']}] {sub['display']}  {sub['url']}")