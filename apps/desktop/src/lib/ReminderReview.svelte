<script lang="ts">
  import { Bell, ChevronRight } from 'lucide-svelte';
  import WeatherIcon from './WeatherIcon.svelte';
  import { degrees } from './weather';
  import type { Task, WeatherState } from '../types';
  export let task: Task;
  export let now: Date;
  export let count: number;
  export let index: number;
  export let taskCount: number;
  export let weather: WeatherState;
  export let open: () => void;
  export let next: () => void;
  $: at = new Date(task.due_at || task.reminder_at!);
  $: missed = at.getTime() < now.getTime();
  $: when = `${at.toDateString() === now.toDateString() ? '' : at.toLocaleDateString('ru-RU', {day:'numeric',month:'short'}) + ' · '}${at.toLocaleTimeString('ru-RU', {hour:'2-digit',minute:'2-digit'})}`;
</script>

<section class="reminder-review" aria-label="Обзор напоминаний" data-task-id={task.id}>
  <button class="review-clock" on:click={open} aria-label="Открыть задачи из обзора">
    <strong>{now.toLocaleTimeString('ru-RU', {hour:'2-digit',minute:'2-digit'})}</strong>
    <small>{taskCount} в работе</small>
  </button>
  <button class="review-task" on:click={open} title={`${task.title} — ${when}`}>
    <span class="review-when" class:missed><Bell size={9}/><time datetime={at.toISOString()}>{when}</time><small>{missed ? 'пропущено' : 'скоро'}</small></span>
    <strong>{task.title}</strong>
  </button>
  <aside>
    <span class="review-weather" title="Погода в Санкт-Петербурге"><WeatherIcon code={weather.data?.current.weather_code ?? -1} isDay={!!weather.data?.current.is_day} size={11}/>{weather.data && !weather.stale ? degrees(weather.data.current.temperature_2m) : '—°'}</span>
    {#if count > 1}<button class="review-next" on:click={next} aria-label="Следующее напоминание" title="Следующее напоминание">{index + 1}/{count}<ChevronRight size={10}/></button>{:else}<span class="review-marker">дело</span>{/if}
  </aside>
</section>

<style>
  .reminder-review { width:100%; height:100%; display:flex; align-items:center; gap:10px; padding:7px 15px; color:#eceeea; }
  button { border:0; padding:0; background:transparent; color:inherit; text-align:left; }
  .review-clock { flex:none; display:flex; flex-direction:column; gap:4px; width:43px; }
  .review-clock > strong { font-size:17px; line-height:19px; font-weight:650; letter-spacing:-.6px; font-variant-numeric:tabular-nums; }
  .review-clock > small { color:#7e877f; font-size:8px; white-space:nowrap; }
  .review-task { min-width:0; flex:1; display:flex; flex-direction:column; gap:4px; }
  .review-when { display:flex; align-items:center; gap:4px; color:#a4bda9; font-size:8px; line-height:9px; white-space:nowrap; }
  .review-when.missed { color:#e1b778; }
  .review-when small { color:#86847b; font-size:7px; overflow:hidden; text-overflow:ellipsis; }
  .review-task > strong { display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; line-clamp:2; overflow:hidden; overflow-wrap:anywhere; font-size:11.5px; line-height:12.5px; font-weight:560; letter-spacing:-.1px; }
  .review-task:hover > strong { color:#fff3d7; }
  aside { flex:none; width:27px; display:flex; flex-direction:column; align-items:flex-end; gap:8px; }
  .review-weather { display:flex; align-items:center; gap:2px; font-size:9px; color:#d9c99f; white-space:nowrap; }
  .review-next { display:flex; align-items:center; font-size:8px; color:#98aa9d; font-variant-numeric:tabular-nums; white-space:nowrap; }
  .review-next:hover { color:#e5f5e9; }
  .review-marker { color:#6c766e; font-size:8px; }
  @media (prefers-reduced-motion:no-preference) { .review-task > strong { animation:review-in 180ms ease-out; } }
  @keyframes review-in { from {opacity:0;transform:translateY(2px)} to {opacity:1;transform:translateY(0)} }
</style>
