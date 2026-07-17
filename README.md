# monnc

A cinematic streaming **discovery** front-end (Astro + Svelte + Video.js) wired
to a Python **backend** that proxies TMDB and serves real, playable streams.

```
┌──────────────┐         ┌──────────────────────────────┐
│  Frontend    │         │  Backend (FastAPI :8028)     │
│  Astro SSR   │ ──────▶ │  app.py                      │
│  :4321       │  /api/* │  ├─ /api/tmdb/*  TMDB fwd  │
│  (node)      │         │  ├─ /api/stream 111movies  │
│              │         │  ├─ /api/subtitles  WebVTT  │
│              │         │  ├─ /api/stream/play (CORS) │
│              │         │  └─ /px  HEVC→H.264 proxy   │
└──────────────┘         └──────────────────────────────┘
        ▲                        │
        └──── Caddy (:PORT) ─────┘   reverse proxy / edge
```

## Architecture

* **Frontend** — Astro SSR (static shell + Svelte islands). Every TMDB request
  is made to our own backend (`/api/tmdb`), so the TMDB key never reaches the
  browser. Player uses Video.js with quality + subtitle tracks.
* **Backend** (`backend/app.py`) — FastAPI. Three jobs:
  1. **TMDB forward proxy** (`/api/tmdb/*`) — key stays server-side. Works
     scrape-first with an API-key fallback (see `tmdb.py`).
  2. **Streaming** (`/api/stream/*`) — resolves real 111movies / MovieBox
     sources + subtitles and decrypts the AES-GCM payload (see `stream.py`).
  3. **Transcoding proxy** (`/px`) — streams media through ffmpeg, transcoding
     HEVC→H.264 on the fly and passing H.264 straight through (see `proxy.py`).

## Run it locally

### 1. Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add your TMDB key (v4 token or v3 key)
uvicorn app:app --host 0.0.0.0 --port 8028
```

### 2. Frontend (new terminal)
```bash
cd frontend
npm install
cp .env.example .env       # PUBLIC_API_BASE defaults to http://localhost:8028
npm run dev                 # http://localhost:4321
```

Open <http://localhost:4321>. Every TMDB request goes through the backend
(`/api/tmdb`), and **Watch** pages pull a real source from the 111movies
pipeline and stream it back same-origin via `/px`. Add `?target=<url>` against
`/px` to route a source through the HEVC→H.264 transcoding proxy.

## Deploy to production (single container)

The repo ships a `Dockerfile` + `Caddyfile` + `deploy/start.sh` that build a
single image running the backend, the Astro SSR node server, and Caddy as the
public edge on `$PORT`.

```bash
# Build
docker build -t monnc \
  --build-arg PUBLIC_API_BASE=https://your-domain.example \
  .

# Run (TMDB key + PORT injected at runtime)
docker run -d --name monnc \
  -e PORT=8080 \
  -e TMDB_ACCESS_TOKEN=your_v4_token \
  -e PROXY_ALLOW_EXTERNAL_TARGETS=false \
  -p 8080:8080 \
  monnc
```

`deploy/start.sh` starts three processes and Caddy routes:

| Path       | Destination           |
| ---------- | --------------------- |
| `/api/*`   | backend FastAPI :8028 |
| `/px/*`    | backend FastAPI :8028 |
| everything | Astro SSR node :4321  |

### Required environment (backend)
| Variable                   | Purpose                                              |
| -------------------------- | ---------------------------------------------------- |
| `TMDB_ACCESS_TOKEN` / `TMDB_API_KEY` | TMDB auth (kept server-side)          |
| `PUBLIC_API_BASE` (build)  | Deployed origin the frontend calls for `/api`       |
| `PORT`                     | Public port Caddy listens on (default 8080)         |
| `PROXY_ALLOW_EXTERNAL_TARGETS` | `false` (default) restricts `/px` to known 111movies bcdn hosts; `true` allows any origin (SSRF risk) |

## Security notes (production)

* The `/px` transcoding gateway is an open proxy for media. By default it only
  forwards to the allowlisted 111movies/MovieBox bcdn hosts and rejects
  private/loopback/link-local targets (SSRF guard in `proxy.py`). To turn it
  into a general gateway set `PROXY_ALLOW_EXTERNAL_TARGETS=true` and lock it
  down with `API_KEY` + `ALLOWED_ORIGINS`.
* Bind the backend and node server to `127.0.0.1` (the `start.sh` entrypoint
  already does this); only Caddy should be publicly reachable.

## Backend endpoints
| Endpoint | Purpose |
| -------- | ------- |
| `GET /api/tmdb/{path}` | Forward to TMDB (key stays server-side) |
| `GET /api/stream/movie/:id` | Real sources + subtitle manifest |
| `GET /api/stream/tv/:id/:season/:episode` | TV episode sources |
| `GET /api/subtitles?imdb_id=&lang=` | WebVTT (SubRip→VTT) |
| `GET /api/stream/play?url=` | Range-aware passthrough (fixes CORS) |
| `GET /px?target=<url>` | HEVC→H.264 transcoding proxy (`proxy.py`) |

See `backend/README` notes in `proxy.py` / `stream.py` for the streaming
and transcoding internals.
