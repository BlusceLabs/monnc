<script>
  export let key = '';        // YouTube video id
  export let poster = '';     // backdrop image to show before play
  export let title = '';
  let playing = false;
  $: src = playing && key
    ? `https://www.youtube.com/embed/${key}?autoplay=1&rel=0`
    : '';
</script>

{#if key}
  <div class="trailer">
    {#if !playing}
      <button class="t-launch" on:click={() => (playing = true)} aria-label="Play trailer">
        <img class="t-bg" src={poster} alt="" loading="lazy" />
        <span class="t-grad"></span>
        <span class="t-play">▶</span>
        <span class="t-label">Play trailer</span>
      </button>
    {:else}
      <div class="t-frame">
        <!-- svelte-ignore a11y-media-has-caption -->
        <iframe
          src={src}
          title={`${title} — trailer`}
          frameborder="0"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
          allowfullscreen
        ></iframe>
      </div>
    {/if}
  </div>
{/if}

<style>
  .trailer { border-radius: var(--radius-lg); overflow: hidden; border: 1px solid var(--border); box-shadow: var(--shadow-1); background: #000; }
  .t-launch { position: relative; display: block; width: 100%; padding: 0; border: none; cursor: pointer; background: #000; aspect-ratio: 16 / 9; }
  .t-bg { width: 100%; height: 100%; object-fit: cover; opacity: 0.62; transition: opacity .3s, transform .4s; }
  .t-launch:hover .t-bg { opacity: 0.5; transform: scale(1.03); }
  .t-grad { position: absolute; inset: 0; background: radial-gradient(120% 120% at 50% 50%, transparent 40%, rgba(16,17,19,0.7)); }
  .t-play { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 74px; height: 74px; border-radius: 50%; background: rgba(230,179,37,0.92); color: var(--charcoal-900); display: grid; place-items: center; font-size: 1.6rem; padding-left: 6px; box-shadow: 0 8px 30px rgba(230,179,37,0.4); transition: transform .2s, background .2s; }
  .t-launch:hover .t-play { background: var(--mustard-soft); transform: translate(-50%, -50%) scale(1.06); }
  .t-label { position: absolute; bottom: 16px; left: 18px; color: var(--text); font-weight: 600; letter-spacing: 0.02em; }
  .t-frame { position: relative; width: 100%; aspect-ratio: 16 / 9; }
  .t-frame iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }
</style>
