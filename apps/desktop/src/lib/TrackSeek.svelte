<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import type { MediaState } from '../types';
  export let media: MediaState;
  export let compact = false;
  export let refresh: () => Promise<void>;
  let draft = 0;
  let gesture: string | null = null;
  let pending: { identity: string; sessionId: string; title: string; position: number } | null = null;
  let seeking = false;
  let error = '';
  let status = 'idle';
  const trackKey = () => `${media.session_id}|${media.title}|${media.artist}|${media.duration}`;
  $: available = !!media.session_id && media.can_seek && media.duration > 0;
  $: if (gesture === null && pending === null && !seeking) draft = Math.max(0, Math.min(media.position, media.duration));
  $: position = draft;
  const time = (value: number) => `${Math.floor(value / 60)}:${Math.floor(value % 60).toString().padStart(2, '0')}`;
  function preview(event: Event) {
    if (gesture === null) gesture = trackKey();
    draft = Number((event.currentTarget as HTMLInputElement).value);
    if (media.session_id) pending = { identity: gesture, sessionId: media.session_id, title: media.title, position: draft };
    status = 'editing';
  }
  async function commit() {
    const request = pending;
    pending = null;
    gesture = null;
    if (!request) return;
    if (!available || seeking || request.identity !== trackKey()) { status = 'cancelled'; return; }
    draft = request.position; seeking = true; error = ''; status = 'seeking';
    try { await invoke('seek_media', { sessionId: request.sessionId, position: request.position, title: request.title }); await refresh(); status = 'done'; }
    catch (err) { error = String(err); status = 'error'; }
    finally { seeking = false; }
  }
</script>

<div class="track-seek" class:compact data-seek-status={status}>
  <input class="seek-input" type="range" aria-label="Перемотать трек" min="0" max={Math.max(1, media.duration)} step="0.1" bind:value={draft}
    aria-valuetext={`${time(position)} из ${time(media.duration)}`} disabled={!available || seeking}
    title={available ? 'Перемотать трек' : 'Плеер не предоставил перемотку через Windows'}
    style={`--seek:${media.duration > 0 ? position / media.duration * 100 : 0}%`}
    on:pointerdown={() => { gesture = trackKey(); error = ''; }} on:input={preview} on:change={commit}
    on:blur={() => { if (pending) void commit(); }}/>
  {#if !compact}<div class="seek-times"><span>{time(position)}</span><span>{time(media.duration)}</span></div>{/if}
  {#if error}<small class="seek-error" role="alert">{error}</small>{/if}
  {#if !available && !compact}<small class="seek-unavailable">Перемотка недоступна в этом плеере</small>{/if}
</div>

<style>
  .track-seek { min-width:0; width:100%; }
  .seek-input { display:block; width:100%; height:14px; padding:0; margin:0; appearance:none; background:transparent; cursor:pointer; border:0; accent-color:var(--amber,#b6d8c2); }
  .seek-input::-webkit-slider-runnable-track { height:3px; border-radius:4px; background:linear-gradient(to right,var(--amber,#b6d8c2) var(--seek),#343a36 var(--seek)); }
  .seek-input::-webkit-slider-thumb { appearance:none; width:9px; height:9px; margin-top:-3px; border-radius:50%; background:var(--amber,#b6d8c2); transition:transform 120ms; }
  .seek-input:hover::-webkit-slider-thumb,.seek-input:focus-visible::-webkit-slider-thumb { transform:scale(1.3); }
  .seek-input:disabled { opacity:.4; cursor:default; }
  .seek-times { display:flex; justify-content:space-between; color:#898f8b; font-size:10px; font-variant-numeric:tabular-nums; }
  .compact .seek-input { height:9px; }
  .compact .seek-input::-webkit-slider-runnable-track { height:2px; }
  .compact .seek-input::-webkit-slider-thumb { height:7px; width:7px; margin-top:-2.5px; }
  .seek-error,.seek-unavailable { display:block; font-size:10px; line-height:1.4; margin-top:4px; color:#cbb091; }
  .compact .seek-error { position:absolute; top:100%; left:0; right:0; padding:5px; border-radius:6px; background:#211c17; }
  @media(prefers-reduced-motion:reduce) { .seek-input::-webkit-slider-thumb { transition:none; } }
</style>
