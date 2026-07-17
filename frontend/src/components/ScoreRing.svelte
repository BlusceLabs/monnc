<script>
  export let value = 0; // 0..10
  export let size = 56;
  $: pct = Math.round((value || 0) * 10);
  $: color = pct >= 70 ? '#7fb069' : pct >= 40 ? '#e6b325' : '#e07a5f';
  $: dash = 2 * Math.PI * 20;
</script>
<div class="ring" style={`width:${size}px;height:${size}px`}>
  <svg viewBox="0 0 48 48">
    <circle cx="24" cy="24" r="20" fill="#101113" stroke="#26292b" stroke-width="4" />
    <circle cx="24" cy="24" r="20" fill="none" stroke={color} stroke-width="4"
      stroke-linecap="round" stroke-dasharray={dash}
      stroke-dashoffset={dash - (dash * pct) / 100}
      transform="rotate(-90 24 24)" />
  </svg>
  <span style={`color:${color}`}>{pct}<small>%</small></span>
</div>
<style>
  .ring { position: relative; }
  svg { width: 100%; height: 100%; }
  span { position: absolute; inset: 0; display: grid; place-items: center; font-weight: 700; font-size: 0.85rem; }
  small { font-size: 0.55rem; opacity: 0.8; }
</style>
