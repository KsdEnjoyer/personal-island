<script lang="ts">
  import { Clock3, Music2, Pause, Play, SkipBack, SkipForward } from 'lucide-svelte';
  import mask from '../assets/capri-mask.svg';
  import WeatherIcon from './WeatherIcon.svelte';
  import PlayerVolume from './PlayerVolume.svelte';
  import { degrees } from './weather';
  import type { MediaState, WeatherState } from '../types';
  export let now: Date;
  export let focusSeconds: number;
  export let timerRunning = false;
  export let tasksLabel: string;
  export let weather: WeatherState;
  export let media: MediaState | null;
  export let playback = false;
  export let mediaBusy = false;
  export let announcement = '';
  export let open: () => void;
  export let mediaCommand: (action: string) => Promise<boolean>;
  export let volumeOpen = false;
  export let reducedMotion = false;
  $: clock = now.toLocaleTimeString('ru-RU', {hour:'2-digit', minute:'2-digit'});
  $: countdown = `${Math.floor(focusSeconds / 60).toString().padStart(2,'0')}:${(focusSeconds % 60).toString().padStart(2,'0')}`;
</script>

<section class="capri-face" class:playing={playback} aria-label="Островок Капри">
  <button class="capri-open" aria-label="Открыть панель Капри" on:click={open}></button>
  <img class="capri-mask" src={mask} width="272" height="104" alt="" draggable="false"/>
  <button class="capri-eye capri-clock" aria-label="Развернуть список задач" on:click={open}>
    <strong>{clock}</strong><span class:running={timerRunning}><Clock3 size={9}/>{countdown}</span>
  </button>
  <button class="capri-eye capri-summary" aria-label="Открыть задачи и погоду" on:click={open}>
    <strong>{tasksLabel}</strong>
    <span class:stale={weather.stale} title={weather.stale ? 'Погода из сохранённых данных' : 'Санкт-Петербург'}><WeatherIcon code={weather.data?.current.weather_code ?? -1} isDay={!!weather.data?.current.is_day} size={11}/>{weather.data && !weather.stale ? degrees(weather.data.current.temperature_2m) : '—°'}<small>СПб</small></span>
  </button>
  {#if playback && media}
    <div class="capri-player" role="group" aria-label="Управление музыкой Капри">
      <button class="capri-skip" aria-label="Предыдущий трек" disabled={mediaBusy || !media.can_previous} on:click={() => mediaCommand('previous')}><SkipBack size={13} fill="currentColor"/></button>
      <PlayerVolume sessionId={media.session_id || ''} wheelOnly bind:open={volumeOpen} detached detachedOffset={14} {reducedMotion}>
      <button class="capri-cover" class:paused={!media.playing} aria-label={media.playing ? 'Приостановить музыку' : 'Продолжить музыку'} title={`${media.title || 'Без названия'} — ${media.artist || media.source} · Колёсико — громкость`} disabled={mediaBusy || !media.can_toggle} on:click={() => mediaCommand('toggle')}>
        {#if media.artwork}<img src={media.artwork} alt="Обложка текущего трека"/>{:else}<Music2 size={17}/>{/if}
        <span class="cover-action" aria-hidden="true">{#if media.playing}<Pause size={12} fill="currentColor"/>{:else}<Play size={12} fill="currentColor"/>{/if}</span>
      </button>
      </PlayerVolume>
      <button class="capri-skip" aria-label="Следующий трек" disabled={mediaBusy || !media.can_next} on:click={() => mediaCommand('next')}><SkipForward size={13} fill="currentColor"/></button>
    </div>
  {/if}
  {#if announcement}<button class="capri-announcement" on:click={open}>{announcement}</button>{/if}
</section>

<style>
  .capri-face { position:relative; width:272px; height:104px; isolation:isolate; }
  .capri-open { position:absolute; inset:0; padding:0; border:0; background:transparent; border-radius:28px; }
  .capri-eye,.capri-player,.capri-announcement {z-index:2}
  .capri-mask { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; user-select:none; filter:drop-shadow(0 6px 5px #0005); }
  .capri-eye { position:absolute; display:flex; flex-direction:column; justify-content:center; align-items:center; gap:1px; height:31px; padding:1px 2px; border:0; color:#deffed; background:transparent; min-width:0; }
  .capri-eye:hover { color:#fff; }
  .capri-eye:focus-visible { outline-color:#27f18b; outline-offset:-3px; border-radius:8px; }
  .capri-clock { top:44px; left:53px; width:77px; }
  .capri-clock strong { font-size:18px; line-height:19px; letter-spacing:-.5px; font-weight:650; font-variant-numeric:tabular-nums; }
  .capri-eye > span { display:flex; align-items:center; justify-content:center; gap:3px; font-size:8px; line-height:9px; color:#8ac6a4; font-variant-numeric:tabular-nums; }
  .capri-clock > .running { color:#b0facc; }
  .capri-summary { top:43px; left:145px; width:73px; }
  .capri-summary strong { max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11px; line-height:15px; font-weight:620; color:#deffed; }
  .capri-summary small { margin-left:2px; font-size:7px; color:#759083; }
  .capri-summary .stale { color:#777; }
  .capri-player { position:absolute; left:98px; top:78px; width:80px; height:24px; display:flex; align-items:center; justify-content:center; gap:5px; background:#08070c; border-radius:7px; }
  .capri-cover { position:relative; display:grid; place-items:center; width:22px; height:22px; flex:none; padding:0; border:0; border-radius:5px; background:#1b2424; color:#bce8ff; overflow:hidden; }
  .capri-cover > img { width:22px; height:22px; object-fit:cover; }
  .capri-cover .cover-action { position:absolute; inset:0; display:grid; place-items:center; background:#0006; opacity:0; transition:opacity 140ms; }
  .capri-cover:hover .cover-action,.capri-cover:focus-visible .cover-action,.capri-cover.paused .cover-action {opacity:1}
  .capri-skip { display:grid; place-items:center; width:19px; height:24px; padding:0; border:0; background:transparent; color:#adcebd; border-radius:5px; }
  .capri-skip:hover { color:#fff; background:#22ef8018; }
  .capri-announcement { position:absolute; left:30px; right:24px; bottom:-22px; max-height:22px; overflow:hidden; border:1px solid #48db8c40; border-radius:6px; background:#0c1914; color:#c6f3d7; padding:3px 6px; font-size:9px; text-overflow:ellipsis; white-space:nowrap; }
</style>
