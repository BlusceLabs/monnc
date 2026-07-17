<script>
  import { onMount, onDestroy } from 'svelte';
  import videojs from 'video.js';
  import 'video.js/dist/video-js.css';

  /** Source can be an HLS (.m3u8) or MP4 URL. */
  export let src = '';
  export let type = ''; // e.g. 'application/x-mpegURL' | 'video/mp4'
  export let poster = '';
  export let title = '';
  export let subtitle = '';
  export let tracks = []; // [{ src, srclang, label, kind:'captions', default }]
  /** Quality options: [{ label, url, type }] where `url` is an already
   *  proxy-routed (/px) playable URL. When >1, a gear menu appears. */
  export let sources = [];

  let el;
  let player;
  let menuOpen = false;

  // React to src changes (e.g. switching episodes / quality) without re-mounting.
  $: if (player && src) {
    player.src([{ src, type: guessType(src) }]);
  }

  function guessType(url) {
    if (type) return type;
    if (url.endsWith('.m3u8')) return 'application/x-mpegURL';
    if (url.endsWith('.webm')) return 'video/webm';
    return 'video/mp4';
  }

  function isActive(s) {
    return s.url === src;
  }

  function pick(s) {
    src = s.url;
    menuOpen = false;
  }

  function toggleMenu(e) {
    e.stopPropagation();
    menuOpen = !menuOpen;
  }

  onMount(() => {
    player = videojs(el, {
      controls: true,
      preload: 'auto',
      fluid: true,
      responsive: true,
      playbackRates: [0.5, 1, 1.25, 1.5, 2],
      poster,
      html5: { vhs: { overrideNative: true } },
      userActions: { hotkeys: true },
      controlBar: {
        skipButtons: { forward: 10, backward: 10 },
        volumePanel: { inline: false },
      },
      sources: src ? [{ src, type: guessType(src) }] : [],
    });

    // Attach caption/subtitle tracks.
    for (const t of tracks) {
      player.addRemoteTextTrack(
        { kind: t.kind || 'captions', src: t.src, srclang: t.srclang, label: t.label, default: t.default },
        false
      );
    }

    // Inject a branded title bar into the player chrome.
    if (title) {
      const bar = document.createElement('div');
      bar.className = 'vjs-title-bar';
      bar.innerHTML = `<strong>${title}</strong>${subtitle ? `<span>${subtitle}</span>` : ''}`;
      player.el().appendChild(bar);
    }
  });

  onDestroy(() => { if (player) player.dispose(); });
</script>

<div class="player-wrap">
  <!-- svelte-ignore a11y-media-has-caption -->
  <video bind:this={el} class="video-js vjs-theme-mustard vjs-big-play-centered" playsinline></video>

  {#if sources.length > 1}
    <div class="v-settings" class:open={menuOpen}>
        <button class="v-gear" on:click={toggleMenu} aria-label="Quality settings" aria-haspopup="true" aria-expanded={menuOpen}>
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <path fill="currentColor" d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.61-.22l-2.39.96a7.03 7.03 0 0 0-1.62-.94l-.36-2.54a.5.5 0 0 0-.5-.42h-3.84a.5.5 0 0 0-.5.42l-.36 2.54c-.58.24-1.12.56-1.62.94l-2.39-.96a.5.5 0 0 0-.61.22L2.68 8.84a.5.5 0 0 0 .12.64l2.03 1.58c-.05.3-.08.62-.08.94 0 .32.03.64.08.94l-2.03 1.58a.5.5 0 0 0-.12.64l1.92 3.32c.14.24.43.34.69.22l2.39-.96c.5.38 1.04.7 1.62.94l.36 2.54c.05.24.25.42.5.42h3.84c.25 0 .45-.18.5-.42l.36-2.54c.58-.24 1.12-.56 1.62-.94l2.39.96c.26.12.55.02.69-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58ZM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7Z"/>
        </svg>
      </button>
      {#if menuOpen}
        <ul class="v-menu" role="menu">
          <li class="v-menu-h">Quality</li>
          {#each sources as s (s.url)}
            <li role="none">
              <button role="menuitem" class="v-menu-i" class:active={isActive(s)} on:click={() => pick(s)}>
                {s.label}
                {#if isActive(s)}<span class="v-check">✓</span>{/if}
              </button>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}
</div>

<style>
  .player-wrap { border-radius: var(--radius-lg); overflow: hidden; border: 1px solid var(--border); box-shadow: var(--shadow-1); background: #000; }

  /* ---- Custom Video.js "mustard" skin ---- */
  :global(.vjs-theme-mustard) { --vjs-theme-mustard--primary: #e6b325; font-family: var(--font); }
  :global(.vjs-theme-mustard .vjs-control-bar) {
    background: linear-gradient(0deg, rgba(16,17,19,0.94), rgba(16,17,19,0.35));
    height: 3.4em; align-items: center;
  }
  :global(.vjs-theme-mustard .vjs-button > .vjs-icon-placeholder:before) { line-height: 1.9; }
  :global(.vjs-theme-mustard .vjs-play-progress) { background: #e6b325; }
  :global(.vjs-theme-mustard .vjs-play-progress:before) { color: #f2c94c; }
  :global(.vjs-theme-mustard .vjs-load-progress) { background: rgba(143,154,132,0.4); }
  :global(.vjs-theme-mustard .vjs-slider) { background: rgba(244,241,234,0.2); }
  :global(.vjs-theme-mustard .vjs-volume-level) { background: #e6b325; }
  :global(.vjs-theme-mustard .vjs-progress-holder) { height: 0.4em; border-radius: 4px; }
  :global(.vjs-theme-mustard .vjs-slider-bar) { border-radius: 4px; }
  :global(.vjs-theme-mustard.vjs-big-play-centered .vjs-big-play-button) {
    width: 84px; height: 84px; line-height: 84px; border-radius: 50%;
    background: rgba(230,179,37,0.92); border: none; color: #17181a;
    box-shadow: 0 8px 30px rgba(230,179,37,0.4); transition: transform .2s, background .2s;
  }
  :global(.vjs-theme-mustard.vjs-big-play-centered .vjs-big-play-button:hover) { background: #f2c94c; transform: scale(1.06); }
  :global(.vjs-theme-mustard .vjs-control:focus-visible) { text-shadow: none; box-shadow: inset 0 0 0 2px #f2c94c; }
  :global(.vjs-theme-mustard .vjs-menu li.vjs-selected) { background: #e6b325; color: #17181a; }
  :global(.vjs-theme-mustard .vjs-menu li:hover) { background: rgba(230,179,37,0.25); }
  :global(.vjs-theme-mustard .vjs-title-bar) {
    position: absolute; top: 0; left: 0; right: 0; padding: 16px 20px;
    background: linear-gradient(180deg, rgba(16,17,19,0.85), transparent);
    color: #f4f1ea; display: flex; flex-direction: column; gap: 2px;
    opacity: 1; transition: opacity .3s; pointer-events: none;
  }
  :global(.vjs-theme-mustard.vjs-user-inactive.vjs-playing .vjs-title-bar) { opacity: 0; }
  :global(.vjs-theme-mustard .vjs-title-bar strong) { font-family: var(--font-display); font-size: 1.1rem; }
  :global(.vjs-theme-mustard .vjs-title-bar span) { font-size: 0.85rem; color: var(--cactus-soft); }

  /* ---- Quality / settings gear ---- */
  .v-settings { position: absolute; top: 10px; right: 12px; z-index: 30; font-family: var(--font); }
  .v-gear {
    width: 38px; height: 38px; border-radius: 50%; display: grid; place-items: center;
    background: rgba(16,17,19,0.62); color: #f4f1ea; border: 1px solid rgba(255,255,255,0.16);
    cursor: pointer; backdrop-filter: blur(8px); transition: background .18s, transform .18s, color .18s;
  }
  .v-gear:hover { background: rgba(230,179,37,0.92); color: #17181a; transform: scale(1.06); }
  .v-settings.open .v-gear { background: var(--mustard); color: #17181a; }
  .v-menu {
    position: absolute; top: 46px; right: 0; min-width: 168px; list-style: none; margin: 0; padding: 6px;
    background: rgba(22,24,27,0.96); border: 1px solid rgba(255,255,255,0.16); border-radius: var(--radius);
    box-shadow: 0 12px 34px rgba(0,0,0,0.5); backdrop-filter: blur(16px);
    animation: vpop .14s ease;
  }
  @keyframes vpop { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: none; } }
  .v-menu-h { padding: 4px 10px 8px; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-faint); }
  .v-menu-i {
    width: 100%; text-align: left; display: flex; align-items: center; justify-content: space-between; gap: 10px;
    padding: 8px 10px; border: none; background: transparent; color: var(--text);
    font-size: 0.9rem; border-radius: 8px; cursor: pointer;
  }
  .v-menu-i:hover { background: rgba(244,241,234,0.1); }
  .v-menu-i.active { color: var(--mustard); font-weight: 600; }
  .v-check { color: var(--mustard); font-size: 0.8rem; }
</style>
