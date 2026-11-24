<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import { Music2, Pause, Play, SkipBack, SkipForward, ExternalLink } from 'lucide-svelte';
  import PlayerVolume from './PlayerVolume.svelte';
  import TrackSeek from './TrackSeek.svelte';
  import type { MediaState } from '../types';
  export let media: MediaState | null;
  export let mediaError = '';
  export let preferred: string | null;
  export let refresh: () => Promise<void>;
  let busy = false;
  let error = '';
  async function command(action: string) {
    if (!media?.session_id || busy) return;
    busy = true; error = '';
    try { await invoke('media_command', { sessionId: media.session_id, action }); await refresh(); }
    catch (err) { error = String(err); }
    finally { busy = false; }
  }
  async function open() { try { await invoke('open_yandex_music'); } catch (err) { error = String(err); } }
</script>

<section class="music-panel utility-panel" aria-label="Музыкальный плеер">
  <div class="utility-heading"><div><h1>Музыка</h1><p>{media?.session_id ? media.source : 'Плеер не подключён'}</p></div><button class="music-open" on:click={open}>Яндекс Музыка <ExternalLink size={12}/></button></div>
  {#if error || mediaError}<p class="utility-error" role="alert">{error || mediaError}</p>{/if}
  {#if media?.session_id}
    <div class="music-body"><div class="album-art">{#if media.artwork}<img src={media.artwork} alt="Обложка текущего трека"/>{:else}<Music2 size={72} strokeWidth={.7}/>{/if}<span class="album-badge" class:playing={media.playing}>{media.playing ? 'Сейчас играет' : 'На паузе'}</span></div>
      <div class="track-info"><div class="track-source-row"><label class="source-select">Источник<select aria-label="Источник музыки" bind:value={preferred} on:change={refresh}><option value={null}>Автоматически</option>{#each media.sessions as session}<option value={session.id}>{session.label}</option>{/each}</select></label><PlayerVolume sessionId={media.session_id}/></div><h2>{media.title || 'Без названия'}</h2><p class="track-artist">{media.artist || media.source}</p><TrackSeek {media} {refresh}/><div class="playback-controls"><button aria-label="Предыдущий трек" disabled={busy || !media.can_previous} on:click={() => command('previous')}><SkipBack size={22} fill="currentColor"/></button><button class="music-play" aria-label={media.playing ? 'Приостановить музыку' : 'Продолжить музыку'} disabled={busy || !media.can_toggle} on:click={() => command('toggle')}>{#if media.playing}<Pause size={24} fill="currentColor"/>{:else}<Play size={24} fill="currentColor"/>{/if}</button><button aria-label="Следующий трек" disabled={busy || !media.can_next} on:click={() => command('next')}><SkipForward size={22} fill="currentColor"/></button></div></div>
    </div>
  {:else}
    <div class="music-empty"><div class="empty-record"><Music2 size={32} strokeWidth={1}/></div><h2>Нет активного трека</h2><p>Включи трек в Яндекс Музыке — в приложении<br/>или браузере с системным управлением медиа.</p><button class="music-open" on:click={open}>Открыть Яндекс Музыку <ExternalLink size={12}/></button></div>
  {/if}
</section>
