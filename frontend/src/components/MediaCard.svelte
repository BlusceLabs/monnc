<script>
  export let item;
  export let kind = null; // 'movie' | 'tv' | 'person' | null (auto)

  const IMG = 'https://image.tmdb.org/t/p';
  function ph(label) {
    const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='500' height='750'><rect width='100%' height='100%' fill='#20221f'/><rect width='100%' height='6' fill='#e6b325'/><text x='50%' y='50%' fill='#8f9a84' font-family='sans-serif' font-size='26' text-anchor='middle' dominant-baseline='middle'>${label}</text></svg>`;
    return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
  }

  const abs = (p) => typeof p === 'string' && (p.startsWith('http://') || p.startsWith('https://'));
  $: type = kind || item.media_type || (item.first_air_date || item.name && !item.title ? 'tv' : 'movie');
  $: isPerson = type === 'person';
  $: title = item.title || item.name || 'Untitled';
  $: date = item.release_date || item.first_air_date || '';
  $: yr = date ? date.slice(0, 4) : '';
  $: img = isPerson
    ? (item.profile_path ? (abs(item.profile_path) ? item.profile_path : `${IMG}/original${item.profile_path}`) : ph('No photo'))
    : (item.poster_path ? (abs(item.poster_path) ? item.poster_path : `${IMG}/original${item.poster_path}`) : ph('No poster'));
  $: score = Math.round((item.vote_average || 0) * 10);
  $: href = isPerson ? `/person/${item.id}` : `/details/${type}/${item.id}`;
  $: subtitle = isPerson ? (item.known_for_department || 'Acting') : yr;
  $: ring = score >= 70 ? '#7fb069' : score >= 40 ? '#e6b325' : '#e07a5f';
</script>

<a class="card" href={href} aria-label={title}>
  <div class="poster">
    <img src={img} alt={title} loading="lazy" />
    {#if !isPerson && item.vote_average}
      <span class="score" style={`--ring:${ring}`}>{score}<small>%</small></span>
    {/if}
    <span class="badge">{isPerson ? 'Person' : type === 'tv' ? 'TV' : 'Film'}</span>
    <div class="sheen"></div>
  </div>
  <div class="meta">
    <span class="title truncate-2">{title}</span>
    <span class="sub">{subtitle}</span>
  </div>
</a>

<style>
  .card { display: block; }
  .poster {
    position: relative; aspect-ratio: 2 / 3; border-radius: var(--radius);
    overflow: hidden; background: var(--charcoal-800);
    border: 1px solid var(--border);
    transition: transform .2s ease, box-shadow .2s ease, border-color .2s;
  }
  .card:hover .poster { transform: translateY(-4px); box-shadow: var(--shadow-1); border-color: var(--mustard-deep); }
  .poster img { width: 100%; height: 100%; object-fit: cover; }
  .sheen { position: absolute; inset: 0; background: linear-gradient(180deg, transparent 55%, rgba(16,17,19,0.85)); opacity: 0; transition: opacity .2s; }
  .card:hover .sheen { opacity: 1; }
  .score {
    position: absolute; bottom: 8px; left: 8px;
    background: rgba(16,17,19,0.85); color: #fff; font-weight: 700; font-size: 0.78rem;
    padding: 4px 7px; border-radius: var(--radius-pill);
    border: 1.5px solid var(--ring);
  }
  .score small { font-size: 0.6rem; opacity: 0.8; }
  .badge {
    position: absolute; top: 8px; right: 8px; font-size: 0.62rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.08em;
    background: rgba(43,53,45,0.85); color: var(--cactus-soft);
    padding: 3px 8px; border-radius: var(--radius-pill); border: 1px solid var(--border);
  }
  .meta { padding: 10px 2px 0; }
  .title { font-size: 0.92rem; font-weight: 600; }
  .sub { display: block; color: var(--text-dim); font-size: 0.8rem; margin-top: 2px; }
</style>
