<script lang="ts">
  import { ChevronLeft, ChevronRight } from 'lucide-svelte';
  import type { Task } from '../types';

  export let selected: Date;
  export let today: Date;
  export let tasks: Task[];
  export let openWeek: ((day:Date) => void) | undefined = undefined;
  let firstClick:Date | undefined;
  let touchWeek = '';
  let touchTime = 0;
  const key = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  $: month = new Date(selected.getFullYear(), selected.getMonth(), 1);
  $: offset = (month.getDay() + 6) % 7;
  $: days = Array.from({ length: 42 }, (_, i) => new Date(month.getFullYear(), month.getMonth(), i - offset + 1));
  $: weeks = Array.from({length:6},(_,i)=>days.slice(i*7,i*7+7));
  $: counts = tasks.reduce((map, task) => {
    if (task.due_at && task.status === 'open') {
      const day = key(new Date(task.due_at));
      map.set(day, (map.get(day) || 0) + 1);
    }
    return map;
  }, new Map<string, number>());
  $: monthTasks = tasks.filter(task => task.due_at && new Date(task.due_at).getMonth() === month.getMonth() && new Date(task.due_at).getFullYear() === month.getFullYear());
  $: completed = monthTasks.filter(task => task.status === 'done').length;
  const urgent = (day: Date) => tasks.some(task => task.status === 'open' && task.priority === 2 && task.due_at && key(new Date(task.due_at)) === key(day));
  function moveMonth(delta: number) {
    selected = new Date(month.getFullYear(), month.getMonth() + delta, 1);
  }
  function touch(day:Date,event:PointerEvent) {
    if(event.pointerType !== 'touch' || !openWeek) return;
    const monday = new Date(day.getFullYear(),day.getMonth(),day.getDate()-(day.getDay()+6)%7);
    const weekKey = key(monday);
    if(touchWeek === weekKey && event.timeStamp-touchTime<400) { openWeek(day); touchWeek = ''; }
    else { touchWeek = weekKey; touchTime = event.timeStamp; }
  }
</script>

<section class="month-calendar" aria-label="Календарь на месяц">
  <div class="month-heading">
    <strong aria-live="polite">{month.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' })}</strong>
    <div class="month-controls">
      <button class="calendar-today" on:click={() => selected = new Date(today)}>Сегодня</button>
      <button class="icon-button" aria-label="Предыдущий месяц" on:click={() => moveMonth(-1)}><ChevronLeft size={15}/></button>
      <button class="icon-button" aria-label="Следующий месяц" on:click={() => moveMonth(1)}><ChevronRight size={15}/></button>
    </div>
  </div>
  <div class="month-weekdays" aria-hidden="true">{#each ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'] as day}<span>{day}</span>{/each}</div>
  <div class="month-grid">
    {#each weeks as week}
    <div class="calendar-week" data-week={key(week[0])} role="group" aria-label={`Неделя с ${week[0].toLocaleDateString('ru-RU',{day:'numeric',month:'long'})}`}>
    {#each week as day}
      <button class="calendar-day" class:outside={day.getMonth() !== month.getMonth()} class:today={key(day) === key(today)}
        class:selected={key(day) === key(selected)} class:weekend={day.getDay() === 0 || day.getDay() === 6} class:urgent={urgent(day)} aria-pressed={key(day) === key(selected)}
        aria-current={key(day) === key(today) ? 'date' : undefined} data-date={key(day)}
        aria-label={`${day.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })}${counts.get(key(day)) ? `, задач: ${counts.get(key(day))}` : ''}`}
        title={openWeek ? 'Двойной клик — планировщик недели' : undefined} aria-keyshortcuts={openWeek ? 'Control+Enter' : undefined}
        on:click={event => { if(event.detail < 2) firstClick = day; selected = day; }} on:dblclick={() => openWeek?.(firstClick || day)}
        on:pointerup={event => touch(day,event)} on:keydown={event => { if(event.key === 'Enter' && event.ctrlKey && openWeek) { event.preventDefault(); openWeek(day); } }}>
        <span>{day.getDate()}</span><span class="day-markers" aria-hidden="true">{#each Array(Math.min(3, counts.get(key(day)) || 0)) as _}<i class="has-tasks"></i>{/each}</span>
      </button>
    {/each}
    </div>
    {/each}
  </div>
  <div class="month-legend"><span><i></i>Планы <b>{monthTasks.filter(task => task.status === 'open').length}</b></span><span><i class="urgent"></i>Срочно</span><span class="month-completed">Готово {completed} / {monthTasks.length}</span></div>
</section>
<style>
  .month-heading strong { color:#e4e4e4; }
  .calendar-day.today { box-shadow:inset 0 0 0 1px #675638; }
  .calendar-day.selected { background:#332b1e; color:#f0c985; box-shadow:none; }
  .calendar-day.outside { opacity:.4; }
  .calendar-day.weekend:not(.selected) { color:#aaa; }
  .calendar-day.selected i.has-tasks { background:#e0b779; }
  .day-markers { display:flex; gap:2px; height:5px; align-items:center; }
  .month-legend { display:flex; gap:10px; color:#777; font-size:9px; margin-top:10px; }
  .month-legend > span { display:flex; gap:4px; align-items:center; }
  .month-legend i { width:4px; height:4px; background:#b5b5b5; border-radius:50%; }
  .month-legend i.urgent { background:#d98f78; }
  .month-completed { margin-left:auto; }
  .month-grid { display:flex; flex-direction:column; gap:3px; }
  .calendar-week { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:3px; border-radius:8px; }
  .calendar-week:has(.calendar-day:hover) { background:#ffffff03; }
</style>
