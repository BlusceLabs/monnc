<script>
  import { tmdb } from '../lib/tmdb';

  export let tvId;
  export let seasons = [];      // [{ season_number, name, episode_count }]
  export let initialSeason = 1;
  export let currentEpisode = 1;

  let season = initialSeason;
  let episodes = [];
  let loading = false;

  async function loadSeason(n) {
    loading = true;
    try {
      const data = await tmdb.tvSeason(tvId, n);
      episodes = (data?.episodes || [])
        .filter((e) => e.episode_number)
        .map((e) => ({
          episode_number: e.episode_number,
          name: e.name,
          air_date: e.air_date,
          still: e.still_path
            ? `https://image.tmdb.org/t/p/w300${e.still_path}`
            : '',
        }));
    } catch (e) {
      episodes = [];
    } finally {
      loading = false;
    }
  }

  function onSeason(e) {
    season = parseInt(e.target.value, 10) || season;
    loadSeason(season);
  }

  import { onMount } from 'svelte';
  onMount(() => loadSeason(season));
</script>

<div class="we">
  <div class="we-head">
    <h2>Up next</h2>
    {#if seasons.length > 1}
      <label class="we-pick">
        <span class="muted">Season</span>
        <select value={season} on:change={onSeason}>
          {#each seasons as s}
            <option value={s.season_number} selected={s.season_number === season}>
              {s.name || `Season ${s.season_number}`}
            </option>
          {/each}
        </select>
      </label>
    {/if}
  </div>

  <div class="ep-list" class:dim={loading}>
    {#if loading}
      <p class="muted pad">Loading episodes…</p>
    {:else if episodes.length === 0}
      <p class="muted pad">No episodes listed for this season.</p>
    {:else}
      {#each episodes as e (e.episode_number)}
        <a
          class="up-ep"
          class:active={e.episode_number === currentEpisode}
          href={`/watch/tv/${tvId}?season=${season}&episode=${e.episode_number}`}
        >
          <div class="up-still">
            {#if e.still}
              <img src={e.still} alt="" loading="lazy" />
            {:else}
              <span class="up-ph">E{e.episode_number}</span>
            {/if}
          </div>
          <div class="up-meta">
            <strong>Ep {e.episode_number}: {e.name || 'Untitled'}</strong>
            {#if e.air_date}<span class="muted">{e.air_date}</span>{/if}
          </div>
        </a>
      {/each}
    {/if}
  </div>
</div>

<style>
  .we { margin-top: 40px; }
  .we-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
  .we-head h2 { font-size: 1.3rem; margin: 0; }
  .we-pick { display: inline-flex; align-items: center; gap: 8px; font-size: 0.88rem; }
  .we-pick select {
    appearance: none; padding: 8px 30px 8px 14px; border-radius: var(--radius-pill);
    border: 1px solid var(--border); background: var(--charcoal-800); color: var(--text);
    font: inherit; cursor: pointer;
    background-image: linear-gradient(45deg, transparent 50%, var(--cactus) 50%), linear-gradient(135deg, var(--cactus) 50%, transparent 50%);
    background-position: calc(100% - 16px) 52%, calc(100% - 11px) 52%;
    background-size: 5px 5px, 5px 5px; background-repeat: no-repeat;
  }
  .ep-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; transition: opacity .2s; }
  .ep-list.dim { opacity: 0.45; pointer-events: none; }
  .up-ep {
    display: grid; grid-template-columns: 120px 1fr; gap: 12px; align-items: center;
    padding: 8px; border-radius: var(--radius); border: 1px solid var(--border);
    background: var(--charcoal-800); color: var(--text); text-decoration: none;
    transition: transform .18s, border-color .18s;
  }
  .up-ep:hover { transform: translateY(-3px); border-color: var(--cactus); }
  .up-ep.active { border-color: var(--mustard); background: var(--jungle-800); }
  .up-still { position: relative; aspect-ratio: 16 / 9; border-radius: 8px; overflow: hidden; background: var(--charcoal-900); }
  .up-still img { width: 100%; height: 100%; object-fit: cover; }
  .up-ph { position: absolute; inset: 0; display: grid; place-items: center; color: var(--cactus); font-weight: 700; }
  .up-meta { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .up-meta strong { font-size: 0.9rem; line-height: 1.25; }
  .up-meta .muted { font-size: 0.8rem; }
  .muted { color: var(--text-dim); }
  .pad { padding: 16px 2px; }
</style>
