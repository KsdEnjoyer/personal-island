<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { Volume2, VolumeX, RotateCw } from 'lucide-svelte';
  import { fly } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  export let sessionId: string;
  export let open = false;
  export let detached = false;
  export let detachedOffset = 60;
  export let reducedMotion = false;
  let level = 0;
  let available = false;
  let muted = false;
  let loading = true;
  let error = '';
  let requested: { id:string; level:number } | null = null;
  let sending = false;
  let version = 0;
  let disposed = false;
  let loadedId = '';
  let root:HTMLDivElement;
  let trigger:HTMLButtonElement;
  let slider:HTMLInputElement;
  const popoverId = `volume-${crypto.randomUUID()}`;
  $: scope = /browser|chrome|msedge|firefox|^yandex\./i.test(sessionId) ? 'Звук браузера, включая другие вкладки' : 'Только звук этого плеера';
  type Volume = { available: boolean; level: number; muted: boolean };
  $: if (sessionId !== loadedId) { loadedId = sessionId; requested = null; void load(sessionId); }
  async function load(id: string) {
    const request = ++version;
    loading = true; available = false; error = '';
    try {
      const state = await invoke<Volume>('player_volume', { sessionId: id, level: null });
      if (request !== version || disposed) return;
      level = Math.round(state.level * 100); available = state.available; muted = state.muted;
    } catch (err) { if (request === version && !disposed) error = String(err); }
    finally { if (request === version && !disposed) loading = false; }
  }
  async function drain() {
    if (sending) return;
    sending = true;
    try {
      while (requested && !disposed) {
        const next = requested; requested = null;
        try {
          const result = await invoke<Volume>('player_volume', { sessionId: next.id, level: next.level / 100 });
          if (next.id === sessionId && !disposed) {
            muted = result.muted; error = ''; available = result.available;
            if (!requested) level = Math.round(result.level * 100);
          }
        } catch (err) { if (next.id === sessionId && !disposed) { error = String(err); requested = null; } }
      }
    } finally { sending = false; }
  }
  function set(value: number) {
    if (!available || loading) return;
    level = value; requested = { id:sessionId, level:value }; void drain();
  }
  async function toggle(event:MouseEvent) {
    open = !open;
    if (open) {
      await load(sessionId);
      await tick();
      if (!event.detail && open && available) slider?.focus();
    }
  }
  function outside(event:PointerEvent) { if (open && root && !root.contains(event.target as Node)) open = false; }
  function escape(event:KeyboardEvent) {
    if (event.key === 'Escape' && open) { event.stopPropagation(); open = false; trigger?.focus(); }
  }
  onMount(() => {
    // Browsers can publish media metadata before their audio session exists.
    const retry = setInterval(() => { if (open && !available && !loading && !error) void load(sessionId); }, 1500);
    return () => { clearInterval(retry); disposed = true; requested = null; ++version; };
  });
</script>
<svelte:window on:pointerdown={outside}/>
<div class="player-volume" class:detached style={`--detached-offset:${detachedOffset}px`} bind:this={root} role="group" aria-label="Управление громкостью плеера">
  <button class="volume-trigger" class:active={open} aria-label="Показать громкость плеера" aria-expanded={open} aria-controls={popoverId} title={`Громкость плеера · ${scope}`} bind:this={trigger} on:click={toggle} on:keydown={escape}>
    {#if muted || (available && level === 0)}<VolumeX size={17}/>{:else}<Volume2 size={17}/>{/if}
  </button>
  {#if open}
    <div id={popoverId} class="volume-popover" class:unavailable={!available} in:fly={{y:-8,duration:reducedMotion ? 0 : 240,easing:cubicOut}} out:fly={{y:-5,duration:reducedMotion ? 0 : 180,easing:cubicOut}}>
      {#if available}
        <span id={`${popoverId}-scope`} hidden>{scope}</span><output aria-live="off">{level}%</output>
        <input bind:this={slider} type="range" min="0" max="100" step="1" value={level} disabled={loading} aria-label="Громкость плеера" aria-describedby={`${popoverId}-scope`} aria-orientation="vertical" aria-valuetext={`${level}%${muted ? ', без звука' : ''}`} title={scope} on:input={event => set(Number(event.currentTarget.value))} on:keydown={escape}/>
        {#if error}<small class="volume-error" role="alert">{error}</small>{/if}
      {:else}
        <small role={error ? 'alert' : 'status'}>{loading ? 'Подключаю звук…' : error || 'Включи воспроизведение, чтобы подключить громкость.'}</small>
        {#if !loading}<button class="volume-retry" on:click={() => load(sessionId)} on:keydown={escape}><RotateCw size={12}/>Повторить</button>{/if}
      {/if}
    </div>
  {/if}
</div>
<style>
  .player-volume { color:#cae2d1; position:relative; flex:none; width:28px; z-index:4; }
  .volume-trigger { display:grid; place-items:center; width:28px; height:28px; border:0; padding:0; border-radius:50%; background:#18201b; color:inherit; }
  .volume-trigger:hover,.volume-trigger.active { background:#2a3b30; color:#fff; }
  .volume-popover { position:absolute; top:calc(100% + 6px); right:0; width:44px; height:116px; padding:9px 7px; background:#202823; border:1px solid #ffffff18; border-radius:15px; display:flex; flex-direction:column; align-items:center; gap:7px; box-shadow:0 10px 22px #0006; transform-origin:top center; }
  .detached .volume-popover { top:calc(100% + var(--detached-offset)); }
  .detached::after { content:''; position:absolute; right:0; top:100%; width:44px; height:calc(var(--detached-offset) + 2px); pointer-events:none; }
  .detached:has(.volume-popover)::after { pointer-events:auto; }
  output { font-size:10px; font-variant-numeric:tabular-nums; color:#dbefe2; line-height:13px; }
  input { writing-mode:vertical-lr; direction:rtl; width:24px; height:74px; flex:none; accent-color:#afd0bb; margin:0; padding:0; cursor:ns-resize; touch-action:none; }
  .unavailable { width:200px; height:auto; min-height:72px; align-items:stretch; padding:12px; gap:9px; }
  small { display:block; color:#aebcb3; font-size:10px; line-height:1.45; }
  .volume-error { position:absolute; top:0; right:50px; width:210px; padding:10px; border-radius:10px; background:#2c201b; color:#f0bda7; }
  .volume-retry { display:flex; gap:6px; align-items:center; align-self:flex-start; border:0; border-radius:8px; padding:5px 8px; font-size:10px; background:#344339; color:#e4eee7; }
</style>
