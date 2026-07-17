<script>
  import { API_BASE } from '../lib/config';

  export let compact = false;
  export let initial = '';

  let q = initial;
  let open = false;
  let loading = false;
  let suggestions = [];
  let activeIndex = -1;
  let timer;

  const IMG = 'https://image.tmdb.org/t/p';
  const abs = (p) => typeof p === 'string' && (p.startsWith('http://') || p.startsWith('https://'));

  function thumb(item) {
    const p = item.poster_path || item.profile_path || item.backdrop_path;
    if (!p) return '';
    return abs(p) ? p : `${IMG}/w185${p}`;
  }
  function typeOf(item) {
    if (item.media_type === 'person') return 'person';
    if (item.media_type === 'tv') return 'tv';
    if (item.media_type === 'movie') return 'movie';
    if (item.first_air_date || (item.name && !item.title)) return 'tv';
    return 'movie';
  }
  function hrefFor(item) {
    const t = typeOf(item);
    return t === 'person' ? `/person/${item.id}` : `/details/${t}/${item.id}`;
  }
  function label(item) {
    return item.title || item.name || 'Untitled';
  }
  function meta(item) {
    const t = typeOf(item);
    if (t === 'person') return 'Person';
    const yr = (item.release_date || item.first_air_date || '').slice(0, 4);
    return yr || (t === 'tv' ? 'TV' : 'Film');
  }

  async function fetchSuggestions(term) {
    loading = true;
    try {
      const url = `${API_BASE}/api/tmdb/search/multi?query=${encodeURIComponent(term)}&page=1`;
      const res = await fetch(url);
      if (!res.ok) throw new Error('search failed');
      const data = await res.json();
      suggestions = (data.results || [])
        .filter((x) => x.poster_path || x.profile_path || x.backdrop_path)
        .slice(0, 8);
      open = suggestions.length > 0;
      activeIndex = -1;
    } catch (e) {
      suggestions = [];
      open = false;
    } finally {
      loading = false;
    }
  }

  function onInput() {
    clearTimeout(timer);
    const term = q.trim();
    if (term.length < 2) {
      suggestions = [];
      open = false;
      return;
    }
    timer = setTimeout(() => fetchSuggestions(term), 250);
  }

  function submit(e) {
    e.preventDefault();
    const term = q.trim();
    if (term) window.location.href = `/search?q=${encodeURIComponent(term)}`;
  }

  function onKey(e) {
    if (!open || !suggestions.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIndex = (activeIndex + 1) % suggestions.length;
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIndex = (activeIndex - 1 + suggestions.length) % suggestions.length;
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      window.location.href = hrefFor(suggestions[activeIndex]);
    } else if (e.key === 'Escape') {
      open = false;
      activeIndex = -1;
    }
  }

  function onBlur() {
    // Delay so a click on a suggestion still registers before close.
    setTimeout(() => {
      open = false;
      activeIndex = -1;
    }, 150);
  }
</script>

<form class={`search ${compact ? 'compact' : ''}`} on:submit={submit} role="search">
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
    <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2" />
    <line x1="16.5" y1="16.5" x2="21" y2="21" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
  </svg>
  <input
    type="search"
    bind:value={q}
    on:input={onInput}
    on:keydown={onKey}
    on:focus={() => { if (suggestions.length) open = true; }}
    on:blur={onBlur}
    placeholder={compact ? 'Search…' : 'Search movies, shows, people…'}
    aria-label="Search"
    aria-expanded={open}
    aria-autocomplete="list"
    autocomplete="off"
  />
  {#if !compact}<button class="btn btn-primary" type="submit">Search</button>{/if}

  {#if open}
    <div class="suggest" role="listbox">
      {#each suggestions as item, i}
        <a
          class="suggest-item"
          class:active={i === activeIndex}
          href={hrefFor(item)}
          role="option"
          aria-selected={i === activeIndex}
          on:mouseenter={() => (activeIndex = i)}
        >
          {#if thumb(item)}
            <img class="suggest-thumb" src={thumb(item)} alt="" loading="lazy" />
          {:else}
            <span class="suggest-thumb placeholder"></span>
          {/if}
          <span class="suggest-text">
            <span class="suggest-title">{label(item)}</span>
            <span class="suggest-meta">{meta(item)}</span>
          </span>
        </a>
      {/each}
    </div>
  {/if}
</form>

<style>
  .search { position: relative; display: flex; align-items: center; gap: 10px; width: 100%; }
  .search svg { color: var(--text-dim); flex: none; position: absolute; margin-left: 14px; pointer-events: none; }
  input {
    flex: 1; width: 100%; padding: 11px 16px 11px 42px; min-height: 44px;
    background: rgba(244,241,234,0.06);
    border: 1px solid rgba(255,255,255,0.14);
    border-radius: var(--radius-pill); color: var(--text); font-size: 0.95rem;
    backdrop-filter: blur(14px) saturate(150%);
    -webkit-backdrop-filter: blur(14px) saturate(150%);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
    transition: border-color .2s, background .2s;
  }
  input::placeholder { color: var(--text-faint); }
  input:focus { outline: none; border-color: var(--mustard); background: rgba(230,179,37,0.06); }
  .compact input { padding-block: 9px; min-height: 40px; }
  .btn { flex: none; }

  /* ---- Autocomplete dropdown ---- */
  .suggest {
    position: absolute;
    top: calc(100% + 8px);
    left: 0; right: 0;
    z-index: 100;
    /* Liquid glassmorphism */
    background: rgba(22, 24, 27, 0.55);
    backdrop-filter: blur(22px) saturate(160%);
    -webkit-backdrop-filter: blur(22px) saturate(160%);
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: var(--radius);
    box-shadow:
      0 12px 40px rgba(0, 0, 0, 0.45),
      inset 0 1px 0 rgba(255, 255, 255, 0.12),
      inset 0 -1px 0 rgba(0, 0, 0, 0.25);
    overflow-x: hidden;
    max-height: 40vh;
    overflow-y: auto;
    scrollbar-width: none;        /* Firefox */
    -ms-overflow-style: none;     /* legacy Edge */
  }
  .suggest::-webkit-scrollbar { display: none; }  /* Chrome/Safari */
  .suggest-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 12px;
    color: var(--text);
    text-decoration: none;
    border-bottom: 1px solid var(--border);
  }
  .suggest-item:last-child { border-bottom: none; }
  .suggest-item.active,
  .suggest-item:hover {
    background: rgba(244, 241, 234, 0.10);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.10);
  }
  .suggest-thumb {
    width: 36px; height: 52px; flex: none;
    border-radius: 6px; object-fit: cover; background: var(--charcoal-800);
  }
  .suggest-thumb.placeholder {
    display: inline-block;
    background: linear-gradient(135deg, var(--charcoal-800), var(--jungle-800));
  }
  .suggest-text { display: flex; flex-direction: column; min-width: 0; }
  .suggest-title {
    font-weight: 600; font-size: 0.92rem;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .suggest-meta { font-size: 0.78rem; color: var(--text-dim); }
</style>
