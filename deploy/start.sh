#!/usr/bin/env bash
# Single entrypoint for every host:
#   PaaS  — Heroku, Railway, Render, Fly.io, DigitalOcean App Platform
#   VPS   — DigitalOcean Droplet, any VM/裸机
#
# Starts the Python backend (+ /px ffmpeg transcode proxy) and the Astro SSR
# frontend, then runs Caddy as the public edge on $PORT.
#
# Behaviour:
#   * Always binds $PORT (default 8080). PaaS platforms inject this.
#   * If SITE_DOMAIN is set (e.g. "monnc.example.com"), Caddy also serves
#     automatic HTTPS on :443 and redirects HTTP→HTTPS.
#   * If DISABLE_CADDY=1 the platforms' own proxy is used and the app must
#     listen on $PORT directly — in that mode we expose the Astro SSR frontend
#     on $PORT and the backend on 127.0.0.1:8028 (still reachable same-origin
#     via /api and /px only if a sidecar routes them; prefer leaving Caddy on).
set -e
export PORT="${PORT:-8080}"

# ── Caddy config: HTTPS only when a domain is set ──
if [ -n "${SITE_DOMAIN:-}" ]; then
  # Domain present: Caddy obtains + renews a cert for :443 and redirects
  # HTTP→HTTPS (its default behaviour). Leave the global block empty so the
  # default applies. The $PORT site still answers plain HTTP for health checks.
  export CADDY_GLOBAL=""
  export SITE_ADDR=" ${SITE_DOMAIN}"
else
  # PaaS mode: TLS is terminated upstream; bind $PORT in plain HTTP only.
  export CADDY_GLOBAL=$'auto_https off\n'
  export SITE_ADDR=""
fi

# Caddy is baked into the Docker image; install it on bare platforms if missing.
if ! command -v caddy >/dev/null 2>&1; then
  echo "[deploy] caddy not found — downloading from GitHub releases..."
  CADDY_VERSION="${CADDY_VERSION:-2.9.1}"
  curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_amd64.tar.gz" -o /tmp/caddy.tar.gz
  tar -xzf /tmp/caddy.tar.gz -C /tmp caddy
  install -m 0755 /tmp/caddy /usr/local/bin/caddy
  rm -f /tmp/caddy.tar.gz
fi

# 1) Backend: FastAPI (TMDB proxy) + /px HEVC→H.264 transcode proxy.
( cd backend && exec uvicorn app:app --host 127.0.0.1 --port 8028 ) &

# 2) Frontend: Astro node standalone SSR.
( cd frontend && HOST=127.0.0.1 PORT=4321 exec node ./dist/server/entry.mjs ) &

# Give the two upstreams a moment to bind before Caddy starts proxying.
sleep 2

# 3) Public edge: /api + /px -> backend, everything else -> frontend SSR.
exec caddy run --config Caddyfile --adapter caddyfile
