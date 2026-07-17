# ---- Frontend (Node) build stage ----
FROM node:20-bookworm AS fe
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# PUBLIC_API_BASE must be the deployed origin (e.g. https://app.railway.app).
# Astro inlines it at build time, so it must be set before `npm run build`.
ARG PUBLIC_API_BASE=""
ENV PUBLIC_API_BASE=$PUBLIC_API_BASE
RUN npm run build

# ---- Runtime stage ----
FROM python:3.12-slim AS run
WORKDIR /app

# ffmpeg (transcode) + curl + caddy (reverse proxy, from GitHub releases).
ARG CADDY_VERSION=2.9.1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_amd64.tar.gz" -o /tmp/caddy.tar.gz \
    && tar -xzf /tmp/caddy.tar.gz -C /usr/local/bin caddy \
    && chmod +x /usr/local/bin/caddy \
    && rm -f /tmp/caddy.tar.gz

COPY backend/ ./backend/
COPY frontend/dist/ ./frontend/dist/
COPY Caddyfile ./Caddyfile
COPY deploy/start.sh ./start.sh
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && chmod +x /app/start.sh

ENV PORT=8080
EXPOSE 8080
CMD ["/app/start.sh"]
