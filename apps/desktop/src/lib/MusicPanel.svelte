<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import { Music2, Pause, Play, SkipBack, SkipForward, ExternalLink } from 'lucide-svelte';
  import PlayerVolume from './PlayerVolume.svelte';
  import TrackSeek from './TrackSeek.svelte';
  import { MUSIC_APP_NAMES, musicAppId, openMusicApp, type MusicApp } from './media-preference';
  import type { MediaState } from '../types';
  export let media: MediaState | null;
  export let mediaError = '';
  export let preferred: string | null;
  export let musicAppBinding = false;
  export let selectSource: (source: string | null) => Promise<void>;
  export let refresh: () => Promise<void>;
  let busy = false;
  let error = '';
  let bindingBusy = false;
  $: linked = musicAppId(preferred);
  $: availableApps = media?.available_apps ?? [];
  $: activeApp = media?.sessions.find(session => session.id === media?.session_id)?.app;
  $: selectedApp = [linked, activeApp].find(app => app && availableApps.includes(app)) ?? availableApps[0];
  async function command(action: string) {
    if (!media?.session_id || busy) return;
    busy = true; error = '';
    try { await invoke('media_command', { sessionId: media.session_id, action }); await refresh(); }
    catch (err) { error = String(err); }
    finally { busy = false; }
  }
  async function open(app: MusicApp) { try { await openMusicApp(app); } catch (err) { error = String(err); } }
  async function changeSource(source: string | null) {
    if (bindingBusy) return;
    bindingBusy = true;
    error = '';
    try { await selectSource(source); }
    finally { bindingBusy = false; }
  }
</script>

{#snippet sourcePicker()}
  <label class="source-select">Источник
    <select aria-label="Источник музыки" value={preferred ?? ''} disabled={bindingBusy} on:change={event => changeSource(event.currentTarget.value || null)}>
      <option value="">Автоматически</option>
      {#if linked}
        <option value={linked}>{MUSIC_APP_NAMES[linked]} (привязка)</option>
      {/if}
      {#each media?.sessions ?? [] as session}
        {#if !musicAppId(session.id) && (!session.app || session.id === preferred)}
          <option value={session.id}>{session.label}</option>
        {/if}
      {/each}
    </select>
  </label>
{/snippet}

<section class="music-panel utility-panel" aria-label="Музыкальный плеер">
  <div class="utility-heading">
    <div><h1>Музыка</h1><p>{linked ? `Привязка: ${MUSIC_APP_NAMES[linked]}` : media?.session_id ? media.source : 'Плеер не подключён'}</p></div>
    {#if !musicAppBinding}
      <button class="music-open" on:click={() => open('yandex-music')}>Яндекс Музыка <ExternalLink size={12}/></button>
    {/if}
  </div>
  {#if musicAppBinding && (availableApps.length || linked)}
    <div class="music-service-actions">
      <label class="source-select service-select">
        <select aria-label="Музыкальное приложение" value={linked ?? ''} disabled={bindingBusy}
          on:change={event => changeSource(musicAppId(event.currentTarget.value))}>
          <option value="">Автоматически</option>
          {#if linked && !availableApps.includes(linked)}
            <option value={linked}>{MUSIC_APP_NAMES[linked]}</option>
          {/if}
          {#each availableApps as app}
            <option value={app}>{MUSIC_APP_NAMES[app]}</option>
          {/each}
        </select>
      </label>
      {#if selectedApp}
        {@const app = selectedApp}
        <button class="music-open" aria-label={`Открыть ${MUSIC_APP_NAMES[app]}`} on:click={() => open(app)}>
          {availableApps.length > 1 ? 'Открыть' : MUSIC_APP_NAMES[app]} <ExternalLink size={15}/>
        </button>
      {/if}
    </div>
  {/if}
  {#if musicAppBinding && !availableApps.length && !linked}
    <p class="music-binding-hint">Открой настольную Яндекс Музыку или Spotify и включи трек. Для обнаружения плеера нужен playerctl.</p>
  {/if}
  {#if error || mediaError}<p class="utility-error" role="alert">{error || mediaError}</p>{/if}
  {#if media?.session_id}
    <div class="music-body"><div class="album-art">{#if media.artwork}<img src={media.artwork} alt="Обложка текущего трека"/>{:else}<Music2 size={72} strokeWidth={.7}/>{/if}<span class="album-badge" class:playing={media.playing}>{media.playing ? 'Сейчас играет' : 'На паузе'}</span></div>
      <div class="track-info"><div class="track-source-row">{@render sourcePicker()}<PlayerVolume sessionId={media.session_id}/></div><h2>{media.title || 'Без названия'}</h2><p class="track-artist">{media.artist || media.source}</p><TrackSeek {media} {refresh}/><div class="playback-controls"><button aria-label="Предыдущий трек" disabled={busy || !media.can_previous} on:click={() => command('previous')}><SkipBack size={22} fill="currentColor"/></button><button class="music-play" aria-label={media.playing ? 'Приостановить музыку' : 'Продолжить музыку'} disabled={busy || !media.can_toggle} on:click={() => command('toggle')}>{#if media.playing}<Pause size={24} fill="currentColor"/>{:else}<Play size={24} fill="currentColor"/>{/if}</button><button aria-label="Следующий трек" disabled={busy || !media.can_next} on:click={() => command('next')}><SkipForward size={22} fill="currentColor"/></button></div></div>
    </div>
  {:else}
    <div class="music-empty">
      <div class="empty-record"><Music2 size={32} strokeWidth={1}/></div>
      <h2>{linked ? `Ожидание: ${MUSIC_APP_NAMES[linked]}` : 'Нет активного трека'}</h2>
      <p>{linked ? 'Плеер подключится, когда приложение запустится.' : 'Включи трек в настольном приложении.'}</p>
      {#if linked || media?.sessions.length}
        {@render sourcePicker()}
      {:else if !musicAppBinding}
        <button class="music-open" on:click={() => open('yandex-music')}>Открыть Яндекс Музыку <ExternalLink size={12}/></button>
      {/if}
    </div>
  {/if}
</section>

<style>
  .music-service-actions {
    flex: none;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 10px;
    margin-top: 12px;
  }
  .service-select { flex: 0 1 220px; min-width: 0; }
  .service-select select, .music-service-actions .music-open {
    min-height: 42px;
    border-radius: 10px;
    font-size: 13px;
    color: #e9e9e9;
  }
  .service-select select { width: 100%; padding: 0 12px; border: 1px solid #383838; }
  .music-service-actions .music-open { padding: 0 14px; }
  .music-binding-hint { margin: 9px 0 0; color: #9a9a9a; font-size: 11px; line-height: 1.4; }
</style>
