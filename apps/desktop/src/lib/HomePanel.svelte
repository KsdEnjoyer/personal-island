<script lang="ts">
  import { onMount } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { listen } from '@tauri-apps/api/event';
  import { ArrowUpRight, ExternalLink, ListTodo, Timer, Music2, CloudSun, NotebookPen, Clipboard, Pause, Play, Plus, RotateCcw, SkipBack, SkipForward, SlidersHorizontal } from 'lucide-svelte';
  import WeatherIcon from './WeatherIcon.svelte';
  import { reviewLabel } from './widget-settings';
  import { degrees, weatherLabel } from './weather';
  import { MUSIC_APP_NAMES, openMusicApp, type MusicApp } from './media-preference';
  import type { Task, MediaState, WeatherState, WidgetSettings } from '../types';
  export let active = false;
  export let tasks:Task[];
  export let now:Date;
  export let media:MediaState | null;
  export let mediaError = '';
  export let weather:WeatherState;
  export let focusSeconds:number;
  export let focusTotalSeconds:number;
  export let timerRunning:boolean;
  export let widgetSettings:WidgetSettings;
  export let shortcutLabel: string | null;
  export let pinned:boolean;
  export let reducedMotion:boolean;
  export let mediaBusy:boolean;
  export let musicApp:MusicApp | null;
  $: playLabel = musicApp === 'yandex-music' ? 'Включить Яндекс Музыку' : musicApp ? 'Включить Spotify' : 'Выбрать плеер';
  export let navigate:(tab:'today'|'tasks'|'calendar'|'notes'|'music'|'weather'|'clipboard')=>void;
  export let createTask:()=>void;
  export let toggleFocus:()=>void;
  export let addMinute:()=>void;
  export let resetFocus:()=>void;
  export let mediaCommand:(action:string)=>void;
  export let playMusic:()=>void;
  export let openSettings:()=>void;
  type Summary = {notes:number;ideas:number;shopping:number;clipboard:number;pinned:number;capturing:boolean};
  let summary:Summary | null = null;
  let summaryError = '';
  let loading = false;
  let disposed = false;
  let openingMusic = false;
  let launchError = '';
  async function openPlayer() {
    if (!musicApp || openingMusic) return;
    openingMusic = true;
    launchError = '';
    try { await openMusicApp(musicApp); }
    catch (err) { launchError = String(err); }
    finally { openingMusic = false; }
  }
  $: openTasks = tasks.filter(t=>t.status==='open');
  $: overdue = openTasks.filter(t=>t.due_at && Date.parse(t.due_at)<now.getTime());
  $: todayTasks = openTasks.filter(t=>t.due_at && new Date(t.due_at).toDateString()===now.toDateString());
  $: nearest = openTasks.filter(t=>t.due_at).sort((a,b)=>Date.parse(a.due_at!)-Date.parse(b.due_at!))[0];
  $: if (active) void refreshSummary();
  const countdown = (seconds:number)=>`${Math.floor(seconds/60).toString().padStart(2,'0')}:${(seconds%60).toString().padStart(2,'0')}`;
  const plural = new Intl.PluralRules('ru');
  const recordCount = (count:number | undefined) => count===undefined ? '— записей' : `${count} ${plural.select(count)==='one' ? 'запись' : plural.select(count)==='few' ? 'записи' : 'записей'}`;
  function due(date:string) {
    const value = new Date(date);
    return `${value.toDateString()===now.toDateString() ? 'Сегодня' : value.toLocaleDateString('ru-RU',{day:'numeric',month:'short'})} · ${value.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}`;
  }
  async function refreshSummary() {
    if (loading || disposed) return;
    loading = true;
    try {
      const result = await invoke<Summary>('get_widget_summary');
      if (!disposed) { summary = result; summaryError = ''; }
    } catch(err) { if (!disposed) summaryError = String(err); }
    finally { loading = false; }
  }
  onMount(()=>{
    const unsubscribe = listen('clipboard-changed',()=>{if(active) void refreshSummary();}).catch(()=>()=>{});
    const timer = setInterval(()=>{if(active) void refreshSummary();},15000);
    return ()=>{ disposed = true; clearInterval(timer); void unsubscribe.then(stop=>stop()); };
  });
</script>

<section class="home-panel" aria-label="Краткий обзор островка">
  <div class="home-heading"><div><h1>Главная</h1><p>{now.toLocaleDateString('ru-RU',{weekday:'long',day:'numeric',month:'long'})}</p></div><span class="home-live"><i></i>{pinned ? 'Закреплён' : 'Островок работает'}</span></div>
  <div class="overview-grid">
    <section class="overview-card tasks-overview" aria-label="Сводка задач">
      <div class="card-heading"><h2><ListTodo size={13}/>Задачи</h2><div><button class="small-action" aria-label="Новая задача" title="Новая задача" on:click={createTask}><Plus size={14}/></button><button class="small-action" aria-label="Открыть все задачи" on:click={()=>navigate('tasks')}><ArrowUpRight size={14}/></button></div></div>
      <div class="task-stats"><button on:click={()=>navigate('tasks')}><b>{openTasks.length}</b><span>Всего</span></button><button on:click={()=>navigate('today')}><b>{todayTasks.length}</b><span>Сегодня</span></button><button class:late={overdue.length>0} on:click={()=>navigate('today')}><b>{overdue.length}</b><span>Просрочено</span></button></div>
      <button class="nearest-task" title={nearest?.title} on:click={()=>navigate('calendar')}>{#if nearest}<span>{nearest.title}</span><small>{due(nearest.due_at!)}</small>{:else}<span>Ближайших сроков нет</span><ArrowUpRight size={11}/>{/if}</button>
    </section>
    <section class="overview-card focus-overview" aria-label="Таймер работы">
      <div class="card-heading"><h2><Timer size={13}/>Таймер</h2><span class:running={timerRunning}>{timerRunning ? 'Идёт фокус' : focusSeconds === 0 ? 'Завершён' : 'На паузе'}</span></div>
      <div class="focus-line"><strong>{countdown(focusSeconds)}</strong><button class="start-focus" aria-label={timerRunning ? 'Приостановить таймер' : 'Запустить таймер'} on:click={toggleFocus}>{#if timerRunning}<Pause size={13} fill="currentColor"/>Пауза{:else}<Play size={13} fill="currentColor"/>Старт{/if}</button></div>
      <div class="focus-bottom"><span>{Math.round(focusTotalSeconds/60)} мин</span><button aria-label="Добавить минуту" on:click={addMinute}>+1 мин</button><button aria-label="Сбросить таймер" on:click={resetFocus}><RotateCcw size={11}/></button></div>
      <div class="focus-progress" aria-hidden="true"><i style:width={`${Math.max(0,Math.min(100,100*(1-focusSeconds/focusTotalSeconds)))}%`} style:transition={reducedMotion ? 'none' : undefined}></i></div>
    </section>
    <section class="overview-card music-overview" aria-label="Музыка в обзоре">
      {#if launchError || mediaError}<p class="launch-error" role="alert">{launchError || mediaError}</p>{/if}
      <div class="card-heading"><h2><Music2 size={13}/>Музыка</h2><div class="music-actions">{#if musicApp}<button class="launch-music" aria-label={musicApp === 'yandex-music' ? 'Открыть Яндекс Музыку' : 'Открыть Spotify'} disabled={openingMusic} aria-busy={openingMusic} on:click={openPlayer}>{MUSIC_APP_NAMES[musicApp]}<ExternalLink size={10}/></button>{/if}<button class="small-action" aria-label="Открыть музыкальный плеер" on:click={()=>navigate('music')}><ArrowUpRight size={14}/></button></div></div>
      <div class="home-track">
        <button class="home-cover" aria-label={media?.playing ? 'Приостановить музыку' : media?.session_id ? 'Продолжить музыку' : playLabel} aria-busy={mediaBusy} disabled={mediaBusy} on:click={()=>{launchError='';playMusic();}}>{#if media?.artwork}<img src={media.artwork} alt="Обложка трека"/>{:else if !media?.session_id}<Play size={19} fill="currentColor"/>{:else}<Music2 size={21}/>{/if}{#if media?.session_id}<span>{#if media.playing}<Pause size={14} fill="currentColor"/>{:else}<Play size={14} fill="currentColor"/>{/if}</span>{/if}</button>
        <button class="home-track-title" title={mediaError || media?.title} on:click={()=>navigate('music')}><b>{mediaBusy ? 'Подключаем плеер…' : media?.title || 'Включить музыку'}</b><small>{mediaError ? 'Попробуй ещё раз' : mediaBusy ? 'Дождись начала воспроизведения' : media?.session_id ? `${media.playing ? 'Играет' : 'Пауза'} · ${media.artist || media.source}` : musicApp ? `Play откроет «${MUSIC_APP_NAMES[musicApp]}»` : 'Выбери приложение во вкладке «Музыка»'}</small></button>
        <div class="home-transport">
          <button aria-label="Предыдущий трек" disabled={!media?.can_previous || mediaBusy} on:click={()=>mediaCommand('previous')}><SkipBack size={13} fill="currentColor"/></button>
          <button class="home-play" aria-label={media?.playing ? 'Приостановить музыку' : media?.session_id ? 'Продолжить музыку' : playLabel} title={media?.playing ? 'Пауза' : 'Воспроизвести'} aria-busy={mediaBusy} disabled={mediaBusy} on:click={()=>{launchError='';playMusic();}}>{#if media?.playing}<Pause size={14} fill="currentColor"/>{:else}<Play size={14} fill="currentColor"/>{/if}</button>
          <button aria-label="Следующий трек" disabled={!media?.can_next || mediaBusy} on:click={()=>mediaCommand('next')}><SkipForward size={13} fill="currentColor"/></button>
        </div>
      </div>
    </section>
    <button class="overview-card weather-overview" aria-label="Открыть погоду" on:click={()=>navigate('weather')}>
      <span class="card-heading"><span class="card-title"><CloudSun size={13}/>Санкт-Петербург</span><ArrowUpRight size={13}/></span>
      <span class="home-weather"><strong>{weather.data && !weather.stale ? degrees(weather.data.current.temperature_2m) : '—°'}</strong>{#if weather.data}<WeatherIcon code={weather.data.current.weather_code} isDay={!!weather.data.current.is_day} size={31}/>{:else}<CloudSun size={31}/>{/if}<span>{weather.stale ? 'Сохранённый прогноз' : weather.data ? weatherLabel(weather.data.current.weather_code) : 'Погода недоступна'}<small>{weather.data && !weather.stale ? `Ощущается ${degrees(weather.data.current.apparent_temperature)}` : 'Открыть прогноз'}</small></span></span>
    </button>
    <button class="overview-card notes-overview" aria-label="Открыть заметки" on:click={()=>navigate('notes')}>
      <span class="card-heading"><span class="card-title"><NotebookPen size={13}/>Записи</span><ArrowUpRight size={13}/></span><span class="notes-stats"><span>Заметки <b>{summaryError ? '—' : summary?.notes ?? '—'}</b></span><span>Идеи <b>{summaryError ? '—' : summary?.ideas ?? '—'}</b></span><span>Покупки <b>{summaryError ? '—' : summary?.shopping ?? '—'}</b></span></span>
    </button>
    <button class="overview-card clipboard-overview" aria-label="Открыть буфер обмена" on:click={()=>navigate('clipboard')}>
      <span class="card-heading"><span class="card-title"><Clipboard size={13}/>Буфер обмена</span><span class="capture-status" class:paused={summary?.capturing===false}><i></i>{summaryError ? 'Нет данных' : summary ? summary.capturing ? 'Запись' : 'Пауза' : '…'}</span></span><span class="clipboard-stats"><span>{recordCount(summaryError ? undefined : summary?.clipboard)}</span><span>{summaryError ? '—' : summary?.pinned ?? '—'} закреплено</span></span>
    </button>
  </div>
  <div class="widget-status">
    {#if shortcutLabel}<span><kbd>{shortcutLabel}</kbd>Показать</span>{/if}
    <span>{reviewLabel(widgetSettings.review_interval_minutes)}</span><button aria-label="Открыть настройки виджета" on:click={openSettings}><SlidersHorizontal size={11}/>Настройки</button>
  </div>
</section>

<style>
  .home-panel { flex:1; min-height:0; display:flex; flex-direction:column; gap:10px; }
  .home-heading { display:flex; justify-content:space-between; align-items:center; padding:0 3px; flex:none; }
  h1 { margin:0; font-size:18px; letter-spacing:-.5px; font-weight:600; }
  .home-heading p { margin:3px 0 0; font-size:10px; color:#777; text-transform:capitalize; }
  .home-live { display:flex; gap:6px; align-items:center; color:#8d9f91; font-size:9px; }
  .home-live i,.capture-status i { width:4px; height:4px; background:#91b69e; border-radius:50%; }
  .overview-grid { flex:1; min-height:0; display:grid; grid-template-columns:minmax(0,1.12fr) minmax(0,1fr); grid-template-rows:1.3fr 1fr .77fr; gap:8px; }
  .overview-card { min-width:0; min-height:0; padding:11px 13px; border:0; border-radius:17px; background:#101010; color:#e5e5e5; text-align:left; display:flex; flex-direction:column; }
  button.overview-card:hover { background:#191919; }
  .card-heading { display:flex; align-items:center; justify-content:space-between; gap:8px; min-height:18px; flex:none; }
  .card-heading h2,.card-title { margin:0; display:flex; gap:6px; align-items:center; font-size:11px; font-weight:500; color:#b8b8b8; }
  .card-heading > div { display:flex; }
  .card-heading > span:not(.card-title) { font-size:9px; color:#757575; }
  .card-heading > span.running { color:#d6b476; }
  .small-action { display:grid; place-items:center; width:21px; height:20px; border:0; border-radius:6px; background:none; color:#797979; padding:0; }
  .small-action:hover { color:#eee; background:#292929; }
  .music-overview { position:relative; }
  .music-actions { align-items:center; gap:5px; }
  .launch-music { display:flex; align-items:center; gap:5px; min-height:23px; padding:0 8px; border:1px solid #344238; border-radius:8px; background:#1b2820; color:#b6cdbf; font:inherit; font-size:9px; white-space:nowrap; }
  .launch-music:hover { background:#293b2e; color:#e1efe5; }
  .launch-music:focus-visible { outline:2px solid #b6cdbf; outline-offset:2px; }
  .launch-music:disabled { opacity:.55; cursor:wait; }
  .launch-error { position:absolute; z-index:1; inset:auto 7px 5px; margin:0; padding:5px 7px; border:1px solid #634538; border-radius:7px; background:#2c211b; color:#edc4ab; font-size:9px; line-height:1.35; }
  .task-stats { display:flex; gap:22px; margin:4px 0; }
  .task-stats button { border:0; padding:0; display:flex; flex-direction:column; gap:0; background:none; text-align:left; }
  .task-stats b { font-size:24px; line-height:1.05; font-weight:550; letter-spacing:-.8px; font-variant-numeric:tabular-nums; }
  .task-stats span { font-size:8px; color:#777; }
  .task-stats .late b { color:#d9a77e; }
  .nearest-task { display:flex; align-items:center; justify-content:space-between; gap:9px; margin-top:auto; padding:5px 0 0; background:none; border:0; border-top:1px solid #242424; min-width:0; color:#a0a0a0; }
  .nearest-task span { font-size:9px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .nearest-task small { font-size:8px; white-space:nowrap; color:#8d7f6d; }
  .focus-line { display:flex; align-items:center; justify-content:space-between; gap:15px; margin:4px 0; }
  .focus-line strong { font-size:28px; letter-spacing:-1px; font-weight:500; font-variant-numeric:tabular-nums; line-height:1.1; }
  .start-focus { display:flex; gap:5px; align-items:center; justify-content:center; min-width:73px; height:28px; padding:0 11px; border:0; border-radius:15px; font-size:10px; background:#e5e5e5; color:#171717; }
  .start-focus:hover { background:#fff; }
  .focus-bottom { display:flex; align-items:center; gap:10px; color:#777; font-size:8px; margin-top:auto; }
  .focus-bottom button { display:flex; align-items:center; border:0; padding:2px 4px; background:none; color:#9f9f9f; border-radius:5px; font-size:9px; }
  .focus-bottom > span { margin-right:auto; }
  .focus-progress { height:2px; background:#2a251c; border-radius:2px; margin-top:5px; }
  .focus-progress i { display:block; height:100%; background:#d6b476; transition:width 1s linear; }
  .home-track { display:flex; gap:9px; align-items:center; min-width:0; flex:1; margin-top:4px; }
  .home-cover { width:38px; height:38px; flex:none; position:relative; display:grid; place-items:center; border:0; border-radius:9px; overflow:hidden; padding:0; background:#1c2821; color:#b6cdbf; }
  .home-cover img { width:100%; height:100%; object-fit:cover; }
  .home-cover > span { position:absolute; inset:0; display:grid; place-items:center; opacity:0; background:#0006; transition:opacity 180ms; }
  .home-cover:hover > span,.home-cover:focus-visible > span { opacity:1; }
  .home-cover:disabled { opacity:.5; cursor:wait; }
  .home-track-title { min-width:0; flex:1; border:0; padding:0; text-align:left; background:none; display:flex; flex-direction:column; gap:5px; }
  .home-track-title b { font-size:12px; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .home-track-title small { font-size:9px; color:#828e86; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .home-transport { display:flex; align-items:center; gap:3px; flex:none; }
  .home-transport button { display:grid; place-items:center; width:21px; height:27px; border:0; border-radius:7px; background:none; color:#a4b6aa; padding:0; }
  .home-transport button:hover { background:#263329; }
  .home-transport .home-play {width:28px;height:28px;border-radius:50%;background:#dce9df;color:#14251a;}
  .home-transport .home-play:hover {background:#fff;color:#14251a;}
  .weather-overview { background:#11171b; }
  .weather-overview:hover { background:#172027!important; }
  .weather-overview .card-title { color:#9eacb5; }
  .home-weather { display:flex; align-items:center; gap:11px; flex:1; margin-top:4px; min-width:0; }
  .home-weather strong { font-size:30px; font-weight:500; letter-spacing:-1px; color:#e1d4b6; white-space:nowrap; }
  .home-weather > span { min-width:0; font-size:9px; line-height:1.45; color:#adbdc5; }
  .home-weather small { display:block; color:#6e8390; font-size:8px; margin-top:3px; }
  .notes-stats { display:flex; justify-content:space-between; gap:8px; margin-top:auto; font-size:9px; color:#787878; }
  .notes-stats b { color:#cacaca; margin-left:4px; font-weight:500; }
  .capture-status { display:flex; align-items:center; gap:5px; }
  .capture-status.paused i { background:#b79864; }
  .clipboard-stats { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-top:auto; font-size:9px; color:#777; }
  .widget-status { display:flex; align-items:center; justify-content:space-between; gap:10px; flex:none; min-height:18px; font-size:8px; color:#686868; padding:0 3px; }
  .widget-status > span,.widget-status button { display:flex; align-items:center; gap:5px; }
  .widget-status button { border:0; padding:3px 0; background:none; color:#888; font-size:9px; }
</style>
