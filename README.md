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

## Deploy to production

The repo ships a **single-container** setup (`Dockerfile` + `Caddyfile` +
`deploy/start.sh`) that runs the backend, the Astro SSR node server, and Caddy
as the public edge — all on the platform-injected `$PORT`. This works unchanged
on every host below. Caddy also serves automatic HTTPS on a bare VPS when you
set `SITE_DOMAIN` (it obtains + renews a Let's Encrypt cert on :443 and
redirects HTTP→HTTPS, while the `$PORT` listener keeps answering plain HTTP for
platform health checks).

### One image, every platform

```bash
# Build (PUBLIC_API_BASE is inlined at build time — use your deployed URL)
docker build -t monnc \
  --build-arg PUBLIC_API_BASE=https://monnc.example.com \
  .

# Run locally / on any VPS
docker run -d --name monnc \
  -e PORT=8080 \
  -e TMDB_ACCESS_TOKEN=your_v4_token \
  -e PROXY_ALLOW_EXTERNAL_TARGETS=false \
  -p 8080:8080 \
  monnc
```

`deploy/start.sh` starts all three processes and Caddy routes:

| Path       | Destination           |
| ---------- | --------------------- |
| `/api/*`   | backend FastAPI :8028 |
| `/px/*`    | backend FastAPI :8028 |
| everything | Astro SSR node :4321  |

### Required environment
| Variable                   | When            | Purpose                                              |
| -------------------------- | --------------- | ---------------------------------------------------- |
| `TMDB_ACCESS_TOKEN` / `TMDB_API_KEY` | always | TMDB auth (kept server-side)            |
| `PUBLIC_API_BASE`          | build arg       | Deployed origin the frontend calls for `/api`       |
| `PORT`                     | runtime         | Public port Caddy listens on (default 8080)         |
| `SITE_DOMAIN`              | VPS w/ HTTPS    | e.g. `monnc.example.com` → Caddy auto-TLS on :443   |
| `PROXY_ALLOW_EXTERNAL_TARGETS` | runtime  | `false` (default) restricts `/px` to known 111movies bcdn hosts; `true` allows any origin (SSRF risk) |

---

### Heroku
Heroku builds Docker via the included `app.json` + `Procfile`. The `web`
process runs `deploy/start.sh` and Heroku injects `PORT`.

```bash
heroku create monnc
heroku stack:set container
# Set config vars (NOT in the image):
heroku config:set TMDB_ACCESS_TOKEN=your_v4_token
heroku config:set PUBLIC_API_BASE=https://monnc.herokuapp.com
heroku config:set PROXY_ALLOW_EXTERNAL_TARGETS=false
git push heroku master
```
> `PUBLIC_API_BASE` must match your `*.herokuapp.com` URL. Rebuild the image
> after changing it (it is baked in at build time). Alternatively use your own
> domain via Heroku Custom Domains and set `SITE_DOMAIN` + `PUBLIC_API_BASE`.

### Railway
Railway auto-detects `railway.json` (Docker builder). Set vars in the
Railway dashboard (or CLI) — `PORT` is injected automatically.

```bash
railway init
railway variables set TMDB_ACCESS_TOKEN=your_v4_token \
  PUBLIC_API_BASE=https://monnc.up.railway.app \
  PROXY_ALLOW_EXTERNAL_TARGETS=false
railway up
```

### Render
Click *New → Blueprint* and select the repo; `render.yaml` provisions the
service. Fill in `TMDB_ACCESS_TOKEN` and `PUBLIC_API_BASE` (your `.onrender.com`
URL) in the dashboard, then deploy. Health check hits `/api/health`.

### Fly.io
`fly.toml` is included. `PORT` (8080) is injected; the `internal_port` matches.

```bash
fly launch --no-deploy   # or just: fly deploy
fly secrets set TMDB_ACCESS_TOKEN=your_v4_token
fly secrets set PUBLIC_API_BASE=https://monnc.fly.dev
fly deploy
# Optional custom domain + auto HTTPS:
fly certs add monnc.example.com
fly secrets set SITE_DOMAIN=monnc.example.com PUBLIC_API_BASE=https://monnc.example.com
```

### DigitalOcean App Platform
Point it at the repo and choose **Docker** as the type; the included
`Dockerfile` is used. Add the env vars in the app's *Environment* tab:
`PORT` (auto), `TMDB_ACCESS_TOKEN`, `PUBLIC_API_BASE` (your
`https://<app>.ondigitalocean.app` URL), and `PROXY_ALLOW_EXTERNAL_TARGETS=false`.
The HTTP health check uses `/api/health`.

### DigitalOcean Droplet (VPS / 裸机)
SSH in, install Docker, then run the image. For HTTPS, point an A record at the
droplet and set `SITE_DOMAIN` so Caddy obtains a Let's Encrypt cert on :443.

```bash
# Install Docker (if needed):
#   curl -fsSL https://get.docker.com | sh

docker run -d --name monnc --restart unless-stopped \
  -p 80:8080 -p 443:443 \
  -e PORT=8080 \
  -e SITE_DOMAIN=monnc.example.com \
  -e TMDB_ACCESS_TOKEN=your_v4_token \
  -e PUBLIC_API_BASE=https://monnc.example.com \
  -e PROXY_ALLOW_EXTERNAL_TARGETS=false \
  monnc
```
> Caddy needs ports 80 & 443 open on the droplet's firewall for the cert
> handshake. The app itself stays on 127.0.0.1 inside the container; only
> Caddy is published.

### Any other VPS / generic Docker host
The same `docker run` as the Droplet works everywhere (Hetzner, Vultr, Linode,
EC2, bare metal). Set `SITE_DOMAIN` for HTTPS or omit it for plain HTTP behind
your own reverse proxy / Cloudflare.

---

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
