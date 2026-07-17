"""
config.py — Central backend configuration (read from environment variables).

Consumed by both the FastAPI app (app.py) and the standalone library modules
(tmdb.py, stream.py) so a single .env drives the whole backend.
"""
import os

# Load backend/.env when present (no-op if python-dotenv is unavailable).
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ── TMDB (used by the /api/tmdb forward proxy + tmdb.py scrape fallback) ──────
TMDB_BASE = os.environ.get("TMDB_BASE", "https://api.themoviedb.org/3")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_ACCESS_TOKEN = os.environ.get("TMDB_ACCESS_TOKEN", "")

# ── 111movies / MovieBox streaming pipeline (stream.py) ───────────────────────
FETCH_TIMEOUT_MS = _env_int("FETCH_TIMEOUT_MS", 20000)

# ── API server (app.py) ───────────────────────────────────────────────────────
BACKEND_HOST = os.environ.get("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = _env_int("BACKEND_PORT", 8028)

# Origins allowed to call the API (the Astro dev/preview server).
CORS_ORIGINS = [
    o.strip() for o in os.environ.get(
        "CORS_ORIGINS", "http://localhost:4321,http://127.0.0.1:4321"
    ).split(",") if o.strip()
]

# ── Transcoding reverse proxy (proxy.py), mounted at /px ──────────────────────
# Leave MEDIA_SERVER empty when only used as a target-based gateway (?target=...).
PROXY_MEDIA_SERVER = os.environ.get("MEDIA_SERVER", "")
PROXY_HOST = os.environ.get("PROXY_HOST", "0.0.0.0")
PROXY_PORT = _env_int("PROXY_PORT", 8080)

# Allow the proxy to fetch arbitrary external origins (the 111movies bcdn URLs).
PROXY_ALLOW_EXTERNAL_TARGETS = _env_bool("PROXY_ALLOW_EXTERNAL_TARGETS", True)
