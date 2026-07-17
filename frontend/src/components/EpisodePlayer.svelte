<script>
  import VideoPlayer from './VideoPlayer.svelte';
  import { tmdb } from '../lib/tmdb';
  import { API_BASE } from '../lib/config';

  export let tvId;
  export let seasons = [];
  export let initialSeason = 1;

  let selectedSeason = initialSeason;
  let episodes = [];
  let loading = false;
  let selectedEp = null;
  let src = '';
  let tracks = [];
  let sources = [];
  let note = '';
  let resolving = false;

  const demoHls = 'https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8';

  async function loadSeason(n) {
    loading = true;
    selectedEp = null;
    src = ''; note = '';
    try {
      const data = await tmdb.tvSeason(tvId, n);
      episodes = (data?.episodes || [])
        .filter((e) => e.episode_number)
        .map((e) => ({
          season_number: e.season_number,
          episode_number: e.episode_number,
          name: e.name,
          overview: e.overview,
          still: e.still_path
            ? `https://image.tmdb.org/t/p/w300${e.still_path}`
            : '',
          air_date: e.air_date,
          vote_average: e.vote_average || 0,
        }));
    } catch (e) {
      episodes = [];
      note = 'Could not load episodes for this season.';
    } finally {
      loading = false;
    }
  }

  async function selectEp(ep) {
    selectedEp = ep;
    resolving = true;
    note = '';
    sources = [];
    try {
      const res = await fetch(
        `${API_BASE}/api/stream/tv/${tvId}/${ep.season_number}/${ep.episode_number}`
      );
      if (res.ok) {
        const s = await res.json();
        if (s.stream_url) {
          const proxied = (u) => `${API_BASE}/px?target=${encodeURIComponent(u)}`;
          src = proxied(s.stream_url);
          sources = (s.sources || []).map((x) => ({
            label: x.quality || (x.type ? x.type.toUpperCase() : 'Source'),
            url: proxied(x.url),
            type: x.type,
          }));
          tracks = (s.tracks || []).map((t) => ({
            ...t,
            src: t.src.startsWith('http') ? t.src : `${API_BASE}${t.src}`,
          }));
          note = 'Live pipeline · 111movies source routed through the /px transcoding proxy.';
          return;
        }
      }
      src = demoHls;
      note = 'No backend source found for this episode — showing an open sample stream.';
    } catch (e) {
      src = demoHls;
      note = 'Stream backend unreachable — showing an open sample stream.';
    } finally {
      resolving = false;
    }
  }

  function pickSeason(n) {
    if (n === selectedSeason) return;
    selectedSeason = n;
    loadSeason(n);
  }

  // Initial load (runs in the browser once hydrated).
  import { onMount } from 'svelte';
  onMount(() => loadSeason(selectedSeason));
</script>

<div class="ep-ui">
  <div class="season-bar">
    {#each seasons as s}
      <button
        class="s-btn"
        class:active={s.season_number === selectedSeason}
        on:click={() => pickSeason(s.season_number)}
      >
        {s.name || `Season ${s.season_number}`}
      </button>
    {/each}
  </div>

  {#if src}
    <div class="player">
      <VideoPlayer
        src={src}
        sources={sources}
        poster={selectedEp?.still || ''}
        title={selectedEp ? `S${selectedEp.season_number}·E${selectedEp.episode_number} — ${selectedEp.name}` : ''}
        subtitle={selectedEp?.air_date || ''}
        {tracks}
      />
      {#if note}<p class="note">{note}</p>{/if}
    </div>
  {/if}

  <div class="ep-grid" class:dim={resolving}>
    {#if loading}
      <p class="muted pad">Loading episodes…</p>
    {:else if episodes.length === 0}
      <p class="muted pad">No episodes listed for this season.</p>
    {:else}
      {#each episodes as ep (ep.season_number + '-' + ep.episode_number)}
        <button
          class="ep"
          class:active={selectedEp && selectedEp.episode_number === ep.episode_number}
          on:click={() => selectEp(ep)}
        >
          <div class="ep-still">
            {#if ep.still}
              <img src={ep.still} alt="" loading="lazy" />
            {:else}
              <span class="ep-ph">S{ep.season_number}E{ep.episode_number}</span>
            {/if}
            <span class="ep-num">E{ep.episode_number}</span>
          </div>
          <div class="ep-meta">
            <strong>{ep.name || `Episode ${ep.episode_number}`}</strong>
            {#if ep.air_date}<span class="muted">{ep.air_date}</span>{/if}
            {#if ep.overview}<p class="ep-ov">{ep.overview}</p>{/if}
          </div>
        </button>
      {/each}
    {/if}
  </div>
</div>

<style>
  .ep-ui { display: flex; flex-direction: column; gap: 22px; }
  .season-bar { display: flex; flex-wrap: wrap; gap: 10px; }
  .s-btn {
    padding: 9px 16px; border-radius: var(--radius-pill);
    border: 1px solid var(--border); background: var(--charcoal-800);
    color: var(--text-dim); font-weight: 600; font-size: 0.86rem; cursor: pointer;
    transition: all .18s ease;
  }
  .s-btn:hover { color: var(--text); border-color: var(--cactus); }
  .s-btn.active { background: var(--mustard); color: var(--charcoal-900); border-color: var(--mustard); }
  .player { max-width: 1000px; }
  .note { margin: 12px 2px 0; font-size: 0.85rem; color: var(--cactus-soft); }
  .ep-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px; transition: opacity .2s;
  }
  .ep-grid.dim { opacity: 0.45; pointer-events: none; }
  .ep {
    display: grid; grid-template-columns: 132px 1fr; gap: 14px; text-align: left;
    padding: 10px; border-radius: var(--radius); border: 1px solid var(--border);
    background: var(--charcoal-800); color: var(--text); cursor: pointer;
    transition: transform .18s, border-color .18s, background .18s;
  }
  .ep:hover { transform: translateY(-3px); border-color: var(--cactus); }
  .ep.active { border-color: var(--mustard); background: var(--jungle-800); }
  .ep-still { position: relative; aspect-ratio: 16 / 9; border-radius: 8px; overflow: hidden; background: var(--charcoal-900); }
  .ep-still img { width: 100%; height: 100%; object-fit: cover; }
  .ep-ph { position: absolute; inset: 0; display: grid; place-items: center; color: var(--cactus); font-weight: 700; font-size: 0.82rem; }
  .ep-num { position: absolute; left: 6px; bottom: 6px; background: rgba(16,17,19,0.85); color: var(--mustard); font-size: 0.74rem; font-weight: 700; padding: 2px 7px; border-radius: 999px; }
  .ep-meta { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .ep-meta strong { font-size: 0.92rem; line-height: 1.25; }
  .ep-ov { font-size: 0.8rem; color: var(--text-dim); margin: 4px 0 0; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  .muted { color: var(--text-dim); }
  .pad { padding: 18px 2px; }
</style>
