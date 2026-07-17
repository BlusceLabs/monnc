// Central runtime configuration read from environment variables.
//
// All TMDB traffic is routed through the Python backend (PUBLIC_API_BASE),
// which keeps the API key server-side. The backend exposes TMDB at
// /api/tmdb and streaming/subtitles at /api/stream + /api/subtitles.
export const API_BASE = import.meta.env.PUBLIC_API_BASE ?? 'http://localhost:8028';
export const TMDB_BASE = `${API_BASE}/api/tmdb`;
export const IMG_BASE = 'https://image.tmdb.org/t/p';

// v4 bearer token / v3 key (only used as a fallback; backend holds the real key).
export const TMDB_ACCESS_TOKEN = import.meta.env.TMDB_ACCESS_TOKEN ?? '';
export const TMDB_API_KEY = import.meta.env.TMDB_API_KEY ?? '';

export const LANGUAGE = import.meta.env.PUBLIC_TMDB_LANGUAGE ?? 'en-US';
export const REGION = import.meta.env.PUBLIC_TMDB_REGION ?? 'US';

// The app is usable as long as the backend API is reachable.
export const hasCredentials = Boolean(API_BASE);

export const SITE = {
  name: 'monnc',
  tagline: 'A warmer way to discover film & television.',
};
