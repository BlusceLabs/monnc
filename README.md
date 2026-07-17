# monnc

A cinematic streaming **discovery** front-end (Astro + Svelte + Video.js) wired
to a Python **backend** that proxies TMDB and serves real, playable streams.

```
┌──────────────┐         ┌──────────────────────────────┐
│  Frontend    │         │  Backend (FastAPI :8028)     │
│  Astro SSR   │ ──────▶ │  app.py                      │
│  :4321       │  /api/* │  ├─ /api/tmdb/*  TMDB fwd  │
└──────────────┘         │  ├─ /api/stream 111movies  │
                          │  ├─ /api/subtitles  WebVTT  │
                          │  ├─ /api/stream/play (CORS) │
                          │  └─ /px  HEVC→H.264 proxy   │
                          └──────────────────────────────┘
```

## Run it

### 1. Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add your TMDB key (v3 or v4)
uvicorn app:app --host 0.0.0.0 --port 8028
```

### 2. Frontend (new terminal)
```bash
cd frontend
npm install
cp .env.example .env       # PUBLIC_API_BASE defaults to http://localhost:8028
npm run dev                 # http://localhost:4321
```

Open <http://localhost:4321>. Every TMDB request now goes through the
backend (`/api/tmdb`), and **Watch** pages pull a real source from the
111movies pipeline and stream it back same-origin via `/api/stream/play`.
Add `?target=<url>` against `/px` to route a source through the HEVC→H.264
transcoding proxy.

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
