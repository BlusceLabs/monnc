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

# ffmpeg (transcode) + curl (caddy fallback) + caddy (reverse proxy).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "https://caddyserver.com/api/v2/linux/amd64?software=http" -o /usr/local/bin/caddy \
    && chmod +x /usr/local/bin/caddy

COPY backend/ ./backend/
COPY frontend/dist/ ./frontend/dist/
COPY Caddyfile ./Caddyfile
COPY deploy/start.sh ./start.sh
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && chmod +x /app/start.sh

ENV PORT=8080
EXPOSE 8080
CMD ["/app/start.sh"]
