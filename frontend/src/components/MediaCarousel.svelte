<script>
  import MediaCard from './MediaCard.svelte';
  export let items = [];
  export let kind = null;
  let track;
  function scroll(dir) {
    if (!track) return;
    track.scrollBy({ left: dir * track.clientWidth * 0.85, behavior: 'smooth' });
  }
</script>

{#if items.length}
  <div class="carousel">
    <button class="arrow left" on:click={() => scroll(-1)} aria-label="Scroll left">‹</button>
    <div class="track" bind:this={track}>
      {#each items as item (item.id + '-' + (item.media_type || ''))}
        <div class="slide"><MediaCard {item} {kind} /></div>
      {/each}
    </div>
    <button class="arrow right" on:click={() => scroll(1)} aria-label="Scroll right">›</button>
  </div>
{/if}

<style>
  .carousel { position: relative; }
  .track {
    display: grid; grid-auto-flow: column; grid-auto-columns: 160px;
    gap: 18px; overflow-x: auto; scroll-snap-type: x mandatory;
    padding: 4px 2px 12px; scrollbar-width: thin;
    scrollbar-color: var(--jungle-600) transparent;
  }
  .track::-webkit-scrollbar { height: 8px; }
  .track::-webkit-scrollbar-thumb { background: var(--jungle-600); border-radius: 999px; }
  .slide { scroll-snap-align: start; }
  .arrow {
    position: absolute; top: 40%; transform: translateY(-50%); z-index: 3;
    width: 42px; height: 42px; border-radius: 50%;
    background: rgba(16,17,19,0.9); color: var(--text); border: 1px solid var(--border);
    font-size: 1.4rem; cursor: pointer; display: grid; place-items: center;
    opacity: 0; transition: opacity .2s, background .2s;
  }
  .carousel:hover .arrow { opacity: 1; }
  .arrow:hover { background: var(--mustard); color: var(--charcoal-900); }
  .arrow.left { left: -18px; }
  .arrow.right { right: -18px; }
  @media (max-width: 720px) { .track { grid-auto-columns: 132px; } .arrow { display: none; } }
</style>
