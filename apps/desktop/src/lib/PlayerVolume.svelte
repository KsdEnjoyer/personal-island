<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { Volume2, VolumeX, RotateCw } from 'lucide-svelte';
  import { fly } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import { createVolumeWheelSteps } from './volume-wheel';
  export let sessionId: string;
  export let open = false;
  export let detached = false;
  export let detachedOffset = 60;
  export let reducedMotion = false;
  export let wheelOnly = false;
  export let onOpen: () => void = () => {};
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
  let hovered = false;
  let dragging = false;
  let keyboardOpen = false;
  let focusSlider = false;
  let closeTimer:ReturnType<typeof setTimeout> | undefined;
  const wheelSteps = createVolumeWheelSteps();
  let wheelPending = 0;
  let root:HTMLDivElement;
  let trigger:HTMLButtonElement;
  let slider:HTMLInputElement;
  const popoverId = `volume-${crypto.randomUUID()}`;
  $: scope = /browser|chrome|msedge|firefox|^yandex\./i.test(sessionId) ? 'Звук браузера, включая другие вкладки' : 'Только звук этого плеера';
  type Volume = { available: boolean; level: number; muted: boolean };
  $: if (sessionId !== loadedId) { loadedId = sessionId; requested = null; wheelPending = 0; wheelSteps.reset(); void load(sessionId); }
  async function load(id: string) {
    const request = ++version;
    loading = true; available = false; error = '';
    try {
      const state = await invoke<Volume>('player_volume', { sessionId: id, level: null });
      if (request !== version || disposed) return;
      level = Math.round(state.level * 100); available = state.available; muted = state.muted;
    } catch (err) { if (request === version && !disposed) error = String(err); }
    finally {
      if (request === version && !disposed) {
        loading = false;
        applyWheel();
        void focusWhenReady();
      }
    }
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
    level = Math.max(0, Math.min(100, Math.round(value)));
    requested = { id:sessionId, level }; void drain();
  }
  async function focusWhenReady() {
    if (!focusSlider || !open || loading || !available) return;
    await tick();
    if (focusSlider && open && !disposed) { focusSlider = false; slider?.focus(); }
  }
  function show(focus = false) {
    clearTimeout(closeTimer);
    focusSlider ||= focus;
    keyboardOpen ||= focus;
    if (!open) {
      open = true;
      onOpen();
      if (!loading && !sending) { void load(sessionId); return; }
    }
    void focusWhenReady();
  }
  function close() {
    clearTimeout(closeTimer);
    open = false; keyboardOpen = false; focusSlider = false; wheelPending = 0; wheelSteps.reset();
  }
  function scheduleClose() {
    clearTimeout(closeTimer);
    if (hovered || dragging || keyboardOpen) return;
    closeTimer = setTimeout(() => { if (!hovered && !dragging && !keyboardOpen) close(); }, 260);
  }
  function enter(event:PointerEvent) {
    if (event.pointerType === 'touch') return;
    hovered = true; keyboardOpen = false;
    if (!wheelOnly) show(); else clearTimeout(closeTimer);
  }
  function leave() { hovered = false; keyboardOpen = false; wheelSteps.reset(); scheduleClose(); }
  function toggle(event:MouseEvent) {
    // A mouse click after hover should not immediately undo the hover opening.
    if (event.detail && hovered) { show(); return; }
    if (open) close(); else show(!event.detail);
  }
  function applyWheel() {
    if (!available || loading || !wheelPending) return;
    const change = wheelPending; wheelPending = 0;
    set(level + change);
  }
  function wheel(event:WheelEvent) {
    if (event.ctrlKey || !event.deltaY) return;
    event.preventDefault();
    show();
    if (error && !loading && !sending) void load(sessionId);
    wheelPending += wheelSteps.take(event);
    applyWheel();
  }
  function startDrag() { dragging = true; keyboardOpen = false; clearTimeout(closeTimer); }
  function endDrag() {
    if (!dragging) return;
    dragging = false; hovered = !!root?.matches(':hover'); scheduleClose();
  }
  function focusOut(event:FocusEvent) {
    if (event.relatedTarget instanceof Node && root.contains(event.relatedTarget)) return;
    keyboardOpen = false; focusSlider = false; scheduleClose();
  }
  function outside(event:PointerEvent) { if (open && root && !root.contains(event.target as Node)) close(); }
  function blur() { dragging = false; hovered = false; close(); }
  function keyboard(event:KeyboardEvent) {
    if (event.key === 'Escape' && open) { event.stopPropagation(); close(); (trigger || root?.querySelector('button'))?.focus(); }
    else if (['ArrowUp','ArrowDown','Home','End','PageUp','PageDown','Tab'].includes(event.key)) keyboardOpen = true;
  }
  onMount(() => {
    // Browsers can publish media metadata before their audio session exists.
    const retry = setInterval(() => { if (open && !available && !loading && !error) void load(sessionId); }, 1500);
    return () => { clearInterval(retry); clearTimeout(closeTimer); disposed = true; requested = null; ++version; };
  });
</script>
<svelte:window on:pointerdown={outside} on:pointerup={endDrag} on:pointercancel={endDrag} on:blur={blur}/>
<div class="player-volume" class:detached class:cover-volume={wheelOnly} style={`--detached-offset:${detachedOffset}px`} bind:this={root} role="group" aria-label="Управление громкостью плеера" on:pointerenter={enter} on:pointerleave={leave} on:focusout={focusOut} on:wheel|nonpassive={wheel}>
  {#if wheelOnly}<slot/>{:else}
  <button class="volume-trigger" class:active={open} aria-label="Показать громкость плеера" aria-expanded={open} aria-controls={popoverId} title={`Громкость плеера · Колёсико меняет звук · ${scope}`} bind:this={trigger} on:click={toggle} on:keydown={keyboard}>
    {#if muted || (available && level === 0)}<VolumeX size={17}/>{:else}<Volume2 size={17}/>{/if}
  </button>
  {/if}
  {#if open}
    <div id={popoverId} class="volume-popover" class:unavailable={!available} in:fly={{y:-8,duration:reducedMotion ? 0 : 240,easing:cubicOut}} out:fly={{y:-5,duration:reducedMotion ? 0 : 180,easing:cubicOut}}>
      {#if available}
        <span id={`${popoverId}-scope`} hidden>{scope}</span><output aria-live="off">{level}<span class="volume-unit">%</span></output>
        <div class="volume-rail" class:dragging style={`--volume-level:${level / 100}`}>
          <span class="rail-track" aria-hidden="true"><span class="rail-fill"></span></span>
          <span class="rail-thumb" aria-hidden="true"></span>
          <input bind:this={slider} type="range" min="0" max="100" step="1" value={level} disabled={loading} aria-label="Громкость плеера" aria-describedby={`${popoverId}-scope`} aria-orientation="vertical" aria-valuetext={`${level}%${muted ? ', без звука' : ''}`} title={scope} on:input={event => set(Number(event.currentTarget.value))} on:pointerdown={startDrag} on:keydown={keyboard}/>
        </div>
        <span class="volume-foot" aria-hidden="true">{#if muted || level === 0}<VolumeX size={9} strokeWidth={1.6}/>{:else}<Volume2 size={9} strokeWidth={1.6}/>{/if}</span>
        {#if error}<small class="volume-error" role="alert">{error}</small>{/if}
      {:else}
        <small role={error ? 'alert' : 'status'}>{loading ? 'Подключаю звук…' : error || 'Включи воспроизведение, чтобы подключить громкость.'}</small>
        {#if !loading}<button class="volume-retry" on:click={() => load(sessionId)} on:keydown={keyboard}><RotateCw size={12}/>Повторить</button>{/if}
      {/if}
    </div>
  {/if}
</div>
<style>
  .player-volume { color:#cae2d1; position:relative; flex:none; width:28px; z-index:4; }
  .cover-volume { width:auto; display:flex; align-items:center; }
  .cover-volume .volume-popover { left:50%; right:auto; margin-left:-13px; }
  .volume-trigger { display:grid; place-items:center; width:28px; height:28px; border:0; padding:0; border-radius:50%; background:#18201b; color:inherit; }
  .volume-trigger:hover,.volume-trigger.active { background:#2a3b30; color:#fff; }
  .volume-popover { position:absolute; top:calc(100% + 6px); right:0; width:26px; height:122px; padding:8px 0; background:linear-gradient(165deg,#202622fa,#111714fa); border:1px solid #c7e0cd12; border-radius:13px; display:flex; flex-direction:column; align-items:center; gap:5px; box-shadow:0 8px 22px #080d0a50,inset 0 1px 0 #ffffff05; transform-origin:top center; }
  .detached .volume-popover { top:calc(100% + var(--detached-offset)); }
  .player-volume::after { content:''; position:absolute; right:0; top:100%; width:44px; height:8px; pointer-events:none; }
  .detached::after { height:calc(var(--detached-offset) + 2px); }
  .player-volume:has(.volume-popover)::after { pointer-events:auto; }
  .player-volume.cover-volume::after { right:calc(50% - 22px); }
  output { display:flex; align-items:baseline; justify-content:center; gap:1px; font-size:9px; font-weight:500; font-variant-numeric:tabular-nums; color:#cedad2; line-height:11px; letter-spacing:-.15px; }
  .volume-unit { font-size:7px; color:#89998e; }
  .volume-rail { position:relative; flex:none; width:28px; height:74px; border-radius:10px; }
  .rail-track { position:absolute; top:4px; bottom:4px; left:calc(50% - 1px); width:2px; overflow:hidden; border-radius:2px; background:#c3d3c71c; pointer-events:none; }
  .rail-fill { position:absolute; bottom:0; left:0; width:100%; height:calc(var(--volume-level) * 100%); border-radius:2px; background:linear-gradient(to top,#789a83,#c4d8ca); }
  .rail-thumb { position:absolute; left:50%; bottom:calc(4px + (100% - 8px) * var(--volume-level)); width:7px; height:7px; border-radius:50%; background:#d2e2d7; box-shadow:0 0 0 2px #a6c3af0a,0 1px 3px #0004; transform:translate(-50%,50%); pointer-events:none; transition:box-shadow 140ms,background-color 140ms; }
  .volume-rail:hover .rail-thumb,.volume-rail:has(input:focus-visible) .rail-thumb,.volume-rail.dragging .rail-thumb { background:#e3eee7; box-shadow:0 0 0 3px #b0d0bb14,0 1px 4px #0004; }
  .volume-rail:has(input:focus-visible) { outline:1px solid #a9c6b369; outline-offset:1px; }
  .volume-rail input { position:absolute; inset:0; appearance:none; -webkit-appearance:none; writing-mode:vertical-lr; direction:rtl; width:28px; height:74px; border:0; border-radius:0; background:transparent; opacity:0; margin:0; padding:0; cursor:ns-resize; touch-action:none; }
  input::-webkit-slider-runnable-track { background:transparent; border:0; }
  input::-webkit-slider-thumb { appearance:none; -webkit-appearance:none; width:8px; height:8px; border:0; background:transparent; }
  input::-moz-range-track { background:transparent; border:0; }
  input::-moz-range-thumb { width:8px; height:8px; border:0; background:transparent; }
  .volume-foot { display:grid; place-items:center; width:12px; height:9px; flex:none; color:#85998c; }
  @media (forced-colors:active) {
    .volume-rail input { opacity:1; appearance:auto; accent-color:Highlight; }
    input::-webkit-slider-runnable-track { background:GrayText; }
    input::-webkit-slider-thumb { appearance:auto; -webkit-appearance:auto; background:Highlight; border:1px solid ButtonText; }
    .rail-track,.rail-thumb { display:none; }
  }
  @media (prefers-reduced-motion:reduce) { .rail-thumb { transition:none; } }
  .unavailable { width:200px; height:auto; min-height:72px; align-items:stretch; padding:12px; gap:9px; }
  small { display:block; color:#aebcb3; font-size:10px; line-height:1.45; }
  .volume-error { position:absolute; top:0; right:50px; width:210px; padding:10px; border-radius:10px; background:#2c201b; color:#f0bda7; }
  .volume-retry { display:flex; gap:6px; align-items:center; align-self:flex-start; border:0; border-radius:8px; padding:5px 8px; font-size:10px; background:#344339; color:#e4eee7; }
</style>
