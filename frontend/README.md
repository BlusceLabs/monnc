# monnc

A server-rendered **Astro + Svelte** streaming discovery front-end powered by The Movie Database (TMDB). Covers **88 TMDB endpoints**, ships 19 fully-featured pages, and includes a **watch page with a customised Video.js player**.

The palette is built around four brand colours:

| Token | Colour | Use |
| ----- | ------ | --- |
| Mustard yellow | `#e6b325` | Primary accent, buttons, active states, player |
| Charcoal black | `#17181a` | Canvas / background |
| Cactus grey | `#8f9a84` | Secondary text, chips |
| Jungle grey | `#2b352d` | Raised surfaces, cards, borders |

## Quick start

```bash
npm install
cp .env.example .env      # then paste your TMDB credentials
npm run dev               # http://localhost:4321
```

Get a free key at <https://www.themoviedb.org/settings/api>. Use either a
**v4 Read Access Token** (`TMDB_ACCESS_TOKEN`, recommended) or a classic **v3 API
key** (`TMDB_API_KEY`).

```bash
npm run build && npm run preview   # production build (Node standalone server)
```

## Pages / routes

| Route | Purpose |
| ----- | ------- |
| `/` | Hero carousel + trending / popular / top-rated rails |
| `/movies` | Movie hub |
| `/movies/browse/[category]` | Paginated grids: popular · top_rated · upcoming · now_playing |
| `/movies/[id]` | Movie detail: cast, crew, providers, collection, recommendations |
| `/tv` | TV hub |
| `/tv/browse/[category]` | popular · top_rated · on_the_air · airing_today |
| `/tv/[id]` | Series detail + season list |
| `/tv/[id]/season/[season]` | Episode guide |
| `/people` | Popular people (paginated) |
| `/person/[id]` | Person bio + known-for credits |
| `/trending` | Everything / Movies / TV / People × Today / Week |
| `/discover` | Filter by type, sort, genre, year |
| `/search` | Multi-search with All / Movies / TV / People tabs |
| `/genres` | Genre index (movie + TV) |
| `/genre/[type]/[id]` | Titles in a genre |
| `/collection/[id]` | Franchise / collection view |
| `/providers` | Streaming provider directory |
| `/watch/[type]/[id]` | **Watch page with customised Video.js player** |
| `/404` | Not-found |

## TMDB coverage (`src/lib/tmdb.ts`)

Configuration & reference (6) · Trending (4) · Movie lists (5) · Movie detail +
appended sub-resources (credits, images, videos, recommendations, similar,
reviews, keywords, release_dates, external_ids, watch/providers) · TV lists (5) ·
TV detail + seasons + episodes · People · Search (multi/movie/tv/person/
collection/company/keyword) · Discover (movie + TV) · Genres · Collections /
companies / keywords / networks / reviews · Watch-provider directory.
**88 numbered endpoints in total.**

## The Video.js player (`src/components/VideoPlayer.svelte`)

- Custom **`vjs-theme-mustard`** skin — mustard progress bar, volume, glowing play button, branded menu states.
- Auto-fading title bar overlay (title + subtitle) during playback.
- Playback-rate menu, 10s skip buttons, captions support, HLS via `videojs-http-streaming`.
- Keyboard shortcuts: `Space`/`K` play/pause · `←` `→` skip 10s · `↑` `↓` volume · `F` fullscreen · `M` mute.
- The demo route streams an open sample HLS — swap `source` for your licensed/DRM manifest in production.

## Tech stack

- **Astro SSR** (`output: 'server'`, `@astrojs/node`) — TMDB calls happen server-side, no API keys reach the browser.
- **Svelte** islands for interactive components (hero, carousels, player, search).
- Fully responsive (390px → desktop), reduced-motion aware, keyboard focus styles.
- Google Fonts: Inter (400, 500, 600) + Poppins (500, 600, 700).

> This product uses the TMDB API but is not endorsed or certified by TMDB.
