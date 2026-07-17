<script>
  export let cast = [];
  export let limit = 20;
  const IMG = 'https://image.tmdb.org/t/p';
  function ph() {
    const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='185' height='185'><rect width='100%' height='100%' fill='#20221f'/><text x='50%' y='50%' fill='#8f9a84' font-family='sans-serif' font-size='60' text-anchor='middle' dominant-baseline='middle'>👤</text></svg>`;
    return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
  }
  $: people = (cast || []).slice(0, limit);
  function role(p) {
    if (p.character) return p.character;
    if (p.roles && p.roles.length) return p.roles.map((r) => r.character).join(', ');
    return p.job || '';
  }
</script>

<div class="cast-row">
  {#each people as p (p.id + (p.credit_id || ''))}
    <a class="cast" href={`/person/${p.id}`}>
      <img src={p.profile_path ? `${IMG}/original${p.profile_path}` : ph()} alt={p.name} loading="lazy" />
      <strong class="truncate-2">{p.name}</strong>
      <span class="truncate-2 muted">{role(p)}</span>
    </a>
  {/each}
</div>

<style>
  .cast-row { display: grid; grid-auto-flow: column; grid-auto-columns: 128px; gap: 16px; overflow-x: auto; padding-bottom: 10px; scrollbar-width: thin; scrollbar-color: var(--jungle-600) transparent; }
  .cast-row::-webkit-scrollbar { height: 8px; }
  .cast-row::-webkit-scrollbar-thumb { background: var(--jungle-600); border-radius: 999px; }
  .cast img { width: 128px; height: 160px; object-fit: cover; border-radius: var(--radius); border: 1px solid var(--border); background: var(--charcoal-800); }
  .cast strong { display: block; font-size: 0.85rem; margin-top: 8px; }
  .cast span { font-size: 0.78rem; }
</style>
