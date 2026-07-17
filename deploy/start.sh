#!/usr/bin/env bash
# Single entrypoint for every host (VPS / Heroku / Railway / Render / Fly).
# Starts the Python backend (+ /px ffmpeg proxy) and the Astro SSR frontend,
# then runs Caddy as the public reverse proxy on $PORT.
set -e
export PORT="${PORT:-8080}"

# Caddy is baked into the Docker image; install it on bare platforms if missing.
if ! command -v caddy >/dev/null 2>&1; then
  echo "[deploy] caddy not found — downloading..."
  curl -fsSL "https://caddyserver.com/api/v2/linux/amd64?software=http" -o /tmp/caddy
  install -m 0755 /tmp/caddy /usr/local/bin/caddy
fi

# 1) Backend: FastAPI (TMDB proxy) + /px HEVC→H.264 transcode proxy.
( cd backend && exec uvicorn app:app --host 127.0.0.1 --port 8028 ) &

# 2) Frontend: Astro node standalone SSR.
( cd frontend && HOST=127.0.0.1 PORT=4321 exec node ./dist/server/entry.mjs ) &

# 3) Public edge: /api + /px -> backend, everything else -> frontend SSR.
exec caddy run --config Caddyfile --adapter caddyfile
