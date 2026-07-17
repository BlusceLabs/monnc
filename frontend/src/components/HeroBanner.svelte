<script>
  export let items = [];
  const IMG = 'https://image.tmdb.org/t/p';
  const abs = (p) => typeof p === 'string' && (p.startsWith('http://') || p.startsWith('https://'));
  // tmdb.py scrape returns absolute poster URLs and no backdrops, so fall
  // back to the poster (or an absolute URL) when there's no backdrop.
  const bgUrl = (p) => !p ? '' : abs(p) ? p : `${IMG}/original${p}`;
  let i = 0;
  let timer;
  $: active = items[i] || {};
  $: type = active.media_type || (active.first_air_date ? 'tv' : 'movie');
  $: title = active.title || active.name || '';
  $: date = active.release_date || active.first_air_date || '';
  $: score = Math.round((active.vote_average || 0) * 10);
  $: bg = bgUrl(active.backdrop_path || active.poster_path);

  function go(n) { i = (n + items.length) % items.length; restart(); }
  function restart() {
    clearInterval(timer);
    timer = setInterval(() => (i = (i + 1) % items.length), 7000);
  }
  import { onMount, onDestroy } from 'svelte';
  onMount(restart);
  onDestroy(() => clearInterval(timer));
</script>

<section class="hero">
  {#each items as it, idx}
    <div class="bg" class:show={idx === i}
      style={`background-image:url(${bgUrl(it.backdrop_path || it.poster_path)})`}></div>
  {/each}
  <div class="scrim"></div>
  <div class="container hero-content">
    <span class="eyebrow">{type === 'tv' ? 'Featured series' : 'Featured film'}</span>
    <h1>{title}</h1>
    <div class="row hero-meta">
      {#if active.vote_average}<span class="gauge">★ {score}%</span>{/if}
      {#if date}<span class="muted">{date.slice(0,4)}</span>{/if}
    </div>
    <p class="truncate-3 lede">{active.overview}</p>
    <div class="row">
      <a class="btn btn-primary" href={`/watch/${type}/${active.id}`}>▶ Watch</a>
      <a class="btn btn-ghost" href={`/details/${type}/${active.id}`}>More info</a>
    </div>
  </div>
  <div class="dots">
    {#each items as _, idx}
      <button class:active={idx === i} on:click={() => go(idx)} aria-label={`Slide ${idx + 1}`}></button>
    {/each}
  </div>
</section>

<style>
  .hero { position: relative; min-height: 78vh; display: flex; align-items: flex-end; overflow: hidden; }
  .bg { position: absolute; inset: 0; background-size: cover; background-position: center 18%; opacity: 0; transform: scale(1.05); transition: opacity 1s ease, transform 7s ease; }
  .bg.show { opacity: 1; transform: scale(1); }
  .scrim { position: absolute; inset: 0; background: linear-gradient(90deg, rgba(16,17,19,0.95) 0%, rgba(16,17,19,0.6) 45%, rgba(16,17,19,0.2) 100%), linear-gradient(0deg, var(--charcoal) 2%, transparent 55%); }
  .hero-content { position: relative; z-index: 2; padding-bottom: 64px; max-width: 640px; }
  .hero-content h1 { font-size: clamp(2.2rem, 5vw, 3.6rem); margin: 10px 0 12px; }
  .hero-meta { margin-bottom: 14px; }
  .gauge { background: var(--mustard); color: var(--charcoal-900); font-weight: 700; padding: 3px 10px; border-radius: var(--radius-pill); font-size: 0.85rem; }
  .lede { color: var(--text); opacity: 0.9; font-size: 1.02rem; margin-bottom: 22px; }
  .dots { position: absolute; bottom: 26px; right: 24px; z-index: 3; display: flex; gap: 8px; }
  .dots button { width: 24px; height: 5px; border-radius: 4px; border: none; background: rgba(244,241,234,0.3); cursor: pointer; padding: 0; }
  .dots button.active { background: var(--mustard); width: 34px; }
  @media (max-width: 720px) { .hero { min-height: 68vh; } .scrim { background: linear-gradient(0deg, var(--charcoal) 8%, rgba(16,17,19,0.35) 60%, rgba(16,17,19,0.5)); } }
</style>
