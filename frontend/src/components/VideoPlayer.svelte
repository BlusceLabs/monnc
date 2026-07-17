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

  let el;
  let player;

  function guessType(url) {
    if (type) return type;
    if (url.endsWith('.m3u8')) return 'application/x-mpegURL';
    if (url.endsWith('.webm')) return 'video/webm';
    return 'video/mp4';
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
</style>
