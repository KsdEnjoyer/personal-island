<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { Plus, ChevronLeft, ChevronRight, Search, SlidersHorizontal, CalendarDays, CalendarRange, Bell, Check, NotebookPen, ArrowUpRight, X, Trash2, Clock3, Flag, ListTodo } from 'lucide-svelte';
  import type { Task, WeatherState } from '../types';
  import MonthCalendar from './MonthCalendar.svelte';
  import WeatherIcon from './WeatherIcon.svelte';
  import { degrees } from './weather';
  import { dayKey, startOfWeek, addDays, localInput, minutesOfDay, timeLabel, taskColor, layoutDeadlines } from './calendar';
  export let tasks:Task[];
  export let now:Date;
  export let weather:WeatherState;
  export let selected:Date;
  export let interacting = false;
  export let refresh:() => Promise<void>;
  export let openNotes:() => Promise<void>;
  export let planner = false;
  export let changeLayout:(wide:boolean) => Promise<void>;
  type View = 'week' | 'month' | 'day';
  let view:View = 'week';
  let search = '';
  let priorities = [true,true,true];
  let showCompleted = false;
  let remindersOnly = false;
  let filtersOpen = false;
  let timeline:HTMLDivElement;
  let modal:'new' | 'detail' | null = null;
  let current:Task | null = null;
  let title = '';
  let notes = '';
  let when = '';
  let priority = 0;
  let busy = false;
  let error = '';
  let deleteConfirm = false;
  let quickOpen = false;
  let quickText = '';
  let noteBusy = false;
  let savedNotes:{id:number;title:string;document:string;category:string}[] = [];
  let noteError = '';
  let disposed = false;
  const HOUR = 56;
  const hours = Array.from({length:24},(_,i)=>i);
  const shortDate = (date:Date) => date.toLocaleDateString('ru-RU',{day:'numeric',month:'short'});
  $: week = Array.from({length:view === 'day' ? 1 : 7},(_,i)=>view === 'day' ? new Date(selected.getFullYear(),selected.getMonth(),selected.getDate()) : addDays(startOfWeek(selected),i));
  $: month = new Date(selected.getFullYear(),selected.getMonth(),1);
  $: monthDays = Array.from({length:42},(_,i)=>addDays(startOfWeek(month),i));
  $: dated = tasks.filter(task=>task.due_at);
  $: filtered = dated.filter(task=>priorities[task.priority] && (showCompleted || task.status === 'open') && (!remindersOnly || task.reminder_at));
  $: matches = filtered.filter(task=>`${task.title} ${task.notes || ''}`.toLocaleLowerCase('ru-RU').includes(search.trim().toLocaleLowerCase('ru-RU'))).sort((a,b)=>Date.parse(a.due_at!)-Date.parse(b.due_at!));
  $: dayTasks = dated.filter(task=>dayKey(new Date(task.due_at!))===dayKey(selected)).sort((a,b)=>Date.parse(a.due_at!)-Date.parse(b.due_at!));
  $: finished = dayTasks.filter(task=>task.status === 'done').length;
  $: dayReminders = dayTasks.filter(task=>task.status === 'open' && task.reminder_at);
  $: isToday = dayKey(selected)===dayKey(now);
  $: nowInWeek = week.some(day=>dayKey(day)===dayKey(now));
  $: selectedLabel = isToday ? 'Сегодня' : selected.toLocaleDateString('ru-RU',{weekday:'long'});
  $: interacting = !!modal || quickOpen || busy || noteBusy || filtersOpen;
  $: if(!planner) { quickOpen = false; filtersOpen = false; }
  async function requestWeek(day:Date) {
    selected = new Date(day); view = 'week'; search = '';
    if(!planner) await changeLayout(true);
    await tick(); if(timeline) timeline.scrollTop=8*HOUR;
  }
  function move(delta:number) {
    if (view === 'month') selected = new Date(selected.getFullYear(),selected.getMonth()+delta,1);
    else selected = addDays(selected,delta*(view === 'week' ? 7 : 1));
  }
  async function goToday() {
    selected = new Date(now); search = '';
    await tick();
    if(timeline) timeline.scrollTop=Math.max(0,(now.getHours()-2)*HOUR);
  }
  function create(date?:Date) {
    const at = date || new Date(selected.getFullYear(),selected.getMonth(),selected.getDate(),Math.min(23,now.getHours()+1));
    when = localInput(at); title = ''; notes = ''; priority = 0; current = null;
    modal = 'new'; deleteConfirm = false; error = '';
    void tick().then(()=>window.document.querySelector<HTMLInputElement>('.calendar-dialog input[name="title"]')?.focus());
  }
  function slot(event:MouseEvent,day:Date) {
    const box = event.currentTarget as HTMLButtonElement;
    const minutes = event.detail === 0 ? 9*60 : Math.min(23*60+30,Math.floor((event.clientY-box.getBoundingClientRect().top)/HOUR*2)*30);
    create(new Date(day.getFullYear(),day.getMonth(),day.getDate(),Math.floor(Math.max(0,minutes)/60),Math.max(0,minutes)%60));
  }
  function inspect(task:Task) { current = task; when = localInput(new Date(task.due_at!)); modal = 'detail'; error = ''; deleteConfirm = false; void tick().then(()=>window.document.querySelector<HTMLElement>('.calendar-dialog')?.focus()); }
  function dialogKeys(event:KeyboardEvent) {
    if(event.key !== 'Tab') return;
    const items = [...(event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled)')];
    const first = items[0], last = items[items.length-1];
    if(event.shiftKey && (window.document.activeElement === first || window.document.activeElement === event.currentTarget)) { event.preventDefault();last?.focus(); }
    else if(!event.shiftKey && window.document.activeElement === last) { event.preventDefault();first?.focus(); }
  }
  async function save() {
    if (busy || !title.trim()) return;
    const date = new Date(when);
    if(!Number.isFinite(date.getTime())) { error = 'Выбери дату и время'; return; }
    busy = true; error = '';
    try {
      await invoke('create_task',{task:{title:title.trim(),notes:notes.trim() || null,due_at:date.toISOString(),priority:Number(priority)}});
      await refresh(); selected = date; modal = null;
    } catch(err) { error = String(err); }
    finally { busy = false; }
  }
  async function complete(task:Task) {
    if(busy) return; busy = true; error = '';
    try { await invoke('complete_task',{id:task.id,completed:task.status !== 'done'}); await refresh(); if(current?.id === task.id) current = {...task,status:task.status === 'done' ? 'open' : 'done'}; }
    catch(err) { error = String(err); }
    finally { busy = false; }
  }
  async function reschedule() {
    if(!current || busy) return;
    const date = new Date(when);
    if(!Number.isFinite(date.getTime())) { error = 'Выбери дату и время'; return; }
    busy = true; error = '';
    try {
      const offset = current.reminder_at ? Date.parse(current.due_at!)-Date.parse(current.reminder_at) : 30*60000;
      await invoke('reschedule_task',{id:current.id,dueAt:date.toISOString(),reminderAt:new Date(date.getTime()-offset).toISOString()});
      await refresh(); selected = date; modal = null;
    } catch(err) { error = String(err); }
    finally { busy = false; }
  }
  async function remove() {
    if(!current || busy) return; busy = true; error = '';
    try { await invoke('delete_task',{id:current.id}); await refresh(); modal = null; }
    catch(err) { error = String(err); }
    finally { busy = false; }
  }
  async function readNotes() {
    try { const result = await invoke<typeof savedNotes>('list_notes'); if(!disposed) { savedNotes = result.filter(note=>note.category === 'notes').slice(0,3); noteError = ''; } }
    catch(err) { if(!disposed) noteError = String(err); }
  }
  async function addNote() {
    if(noteBusy || !quickText.trim()) return; noteBusy = true; noteError = '';
    const lines = quickText.trim().split('\n');
    const heading = lines[0].slice(0,100);
    const body = [lines[0].slice(100),...lines.slice(1)].filter(Boolean).join('\n');
    const document = JSON.stringify({type:'doc',content:body ? body.split('\n').map(text=>({type:'paragraph',content:text ? [{type:'text',text}] : []})) : [{type:'paragraph'}]});
    try { await invoke('save_note',{id:null,revision:0,note:{category:'notes',title:heading,document}}); quickText = ''; quickOpen = false; await readNotes(); }
    catch(err) { noteError = String(err); }
    finally { noteBusy = false; }
  }
  onMount(()=>{ void readNotes(); void tick().then(()=>{if(timeline)timeline.scrollTop=8*HOUR;}); return ()=>{disposed = true;interacting = false;}; });
</script>

<svelte:window on:keydown={event=>{if(event.key === 'Escape' && (modal || quickOpen || filtersOpen)) { event.stopImmediatePropagation(); if(!busy && !noteBusy) { modal = null; quickOpen = false; filtersOpen = false; } }}}/>

<section class="calendar-board" class:compact-calendar={!planner} aria-label="Календарь задач">
  {#if !planner}
  <section class="compact-month calendar-surface" aria-label="Месяц">
    <MonthCalendar bind:selected today={now} {tasks} openWeek={requestWeek}/>
  </section>
  <section class="compact-agenda calendar-surface" aria-label="Задачи выбранного дня">
    <header class="compact-agenda-heading"><div><h2>{selected.toLocaleDateString('ru-RU',{day:'numeric',month:'long'})}</h2><span>{selected.toLocaleDateString('ru-RU',{weekday:'long'})} · {dayTasks.length}</span></div><button class="icon-button" aria-label="Новое событие" title="Добавить задачу" on:click={()=>create()}><Plus size={17}/></button></header>
    <div class="compact-day-list">{#each dayTasks as task}<article class="compact-task"><button class="task-checkbox" class:checked={task.status === 'done'} disabled={busy} aria-label={`${task.status === 'done' ? 'Вернуть' : 'Завершить'}: ${task.title}`} on:click={()=>complete(task)}><Check size={11}/></button><button class="compact-task-detail" class:completed={task.status === 'done'} aria-label={`Открыть задачу: ${task.title}`} on:click={()=>inspect(task)}><b>{task.title}</b><small>{timeLabel(new Date(task.due_at!))}</small></button></article>{:else}<span class="compact-no-tasks">Нет задач на этот день</span>{/each}</div>
    <button class="open-week-planner" on:click={()=>requestWeek(selected)}><CalendarRange size={15}/>Планировщик недели<ChevronRight size={14}/></button>
  </section>
  {:else}
  <aside class="calendar-left calendar-surface">
    <button class="planner-back" on:click={()=>changeLayout(false)}><ChevronLeft size={15}/>К месяцу</button>
    <button class="new-event" on:click={()=>create()}><Plus size={20}/>Новое событие</button>
    <MonthCalendar bind:selected today={now} tasks={filtered} openWeek={requestWeek}/>
    <div class="source-heading">Мои задачи<SlidersHorizontal size={13}/></div>
    <div class="calendar-sources">
      {#each [{label:'Обычные',color:'purple'},{label:'Важные',color:'blue'},{label:'Срочные',color:'coral'}] as source,index}
        <label class="source" style={`--source:${source.color === 'purple' ? '#a6baad' : source.color === 'blue' ? '#c8b37e' : '#d38f7e'}`}><input type="checkbox" aria-label={`Показывать: ${source.label}`} bind:checked={priorities[index]}/><span class="source-check"><Check size={12}/></span><span>{source.label}</span><small>{dated.filter(task=>task.priority === index && task.status === 'open').length}</small></label>
      {/each}
    </div>
    <label class="source secondary-source"><input type="checkbox" aria-label="Только с напоминанием" bind:checked={remindersOnly}/><span class="source-check"><Bell size={12}/></span><span>С напоминанием</span></label>
    <label class="completed-filter"><input type="checkbox" bind:checked={showCompleted}/>Показывать завершённые</label>
  </aside>

  <section class="calendar-center calendar-surface" aria-label="Расписание">
    <header class="calendar-topbar">
      <div class="period-navigation"><button aria-label="Предыдущий период" on:click={()=>move(-1)}><ChevronLeft size={17}/></button><button aria-label="Следующий период" on:click={()=>move(1)}><ChevronRight size={17}/></button><h1>{selected.toLocaleDateString('ru-RU',{month:'long',year:'numeric'})}</h1></div>
      <label class="event-search"><Search size={14}/><input aria-label="Поиск по событиям" placeholder="Поиск по событиям" bind:value={search}/>{#if search}<button aria-label="Очистить поиск событий" on:click={()=>search = ''}><X size={12}/></button>{/if}</label>
      <select aria-label="Вид календаря" bind:value={view}><option value="week">Неделя</option><option value="month">Месяц</option><option value="day">День</option></select>
      <button class:active={filtersOpen} class="calendar-filter-button" aria-label="Фильтры календаря" aria-expanded={filtersOpen} on:click={()=>filtersOpen = !filtersOpen}><SlidersHorizontal size={16}/></button>
    </header>
    <div class="calendar-period-meta"><span>{view === 'month' ? `${filtered.filter(task=>new Date(task.due_at!).getMonth()===selected.getMonth() && new Date(task.due_at!).getFullYear()===selected.getFullYear()).length} дел в месяце` : `${shortDate(week[0])} — ${shortDate(week[week.length-1])}`}</span><button on:click={goToday}>Сегодня</button><span class="deadline-legend"><i></i>Карточка — срок задачи</span></div>
    {#if filtersOpen}<div class="calendar-filter-popover"><label><input type="checkbox" bind:checked={showCompleted}/>Завершённые задачи</label><label><input type="checkbox" bind:checked={remindersOnly}/>Только с напоминанием</label></div>{/if}
    {#if error && !modal}<p class="calendar-error" role="alert">{error}<button aria-label="Убрать ошибку календаря" on:click={()=>error = ''}><X size={12}/></button></p>{/if}
    {#if search.trim()}
      <div class="calendar-results" aria-label="Результаты поиска событий"><div class="search-count">Найдено: {matches.length}</div>{#each matches as task}<button class="search-result" on:click={()=>inspect(task)}><i class={taskColor(task)}></i><span><b>{task.title}</b><small>{new Date(task.due_at!).toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'})} · {timeLabel(new Date(task.due_at!))}</small></span><ArrowUpRight size={14}/></button>{:else}<div class="calendar-empty"><Search size={25}/><b>Совпадений нет</b><span>Проверь текст или включённые фильтры.</span></div>{/each}</div>
    {:else if view === 'month'}
      <div class="board-month-weekdays" aria-hidden="true">{#each ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'] as label}<span>{label}</span>{/each}</div>
      <div class="board-month" aria-label="Расписание на месяц">
        {#each monthDays as day}
          {@const entries = filtered.filter(task=>dayKey(new Date(task.due_at!))===dayKey(day)).sort((a,b)=>Date.parse(a.due_at!)-Date.parse(b.due_at!))}
          <div class="board-month-cell" class:outside={day.getMonth() !== month.getMonth()} class:selected-cell={dayKey(day)===dayKey(selected)}>
            <div class="month-cell-top"><button class:current-date={dayKey(day)===dayKey(now)} aria-label={`Выбрать ${shortDate(day)}`} on:click={()=>selected = day}>{day.getDate()}</button><button class="cell-add" aria-label={`Добавить на ${shortDate(day)}`} on:click={()=>create(new Date(day.getFullYear(),day.getMonth(),day.getDate(),9))}><Plus size={11}/></button></div>
            {#each entries.slice(0,2) as task}<button class={`month-event ${taskColor(task)}`} title={task.title} on:click={()=>inspect(task)}><small>{timeLabel(new Date(task.due_at!))}</small>{task.title}</button>{/each}
            {#if entries.length>2}<button class="more-events" on:click={()=>{selected = day;view = 'day';}}>Ещё {entries.length-2}</button>{/if}
          </div>
        {/each}
      </div>
    {:else}
      <div class="week-heading" style={`--days:${week.length}`}><span></span>{#each week as day}<button class:chosen={dayKey(day)===dayKey(selected)} class:actual-today={dayKey(day)===dayKey(now)} aria-label={`Выбрать день ${shortDate(day)}`} aria-pressed={dayKey(day)===dayKey(selected)} on:click={()=>selected = day}><small>{day.toLocaleDateString('ru-RU',{weekday:'short'})}</small><b>{day.getDate()}</b></button>{/each}</div>
      <div class="time-scroll" bind:this={timeline} aria-label={view === 'week' ? 'Расписание на неделю' : 'Расписание на день'}>
        <div class="time-grid" style={`height:${24*HOUR+54}px;--days:${week.length};--hour:${HOUR}px`}>
          <div class="time-ruler" aria-hidden="true">{#each hours as hour}<span style={`top:${hour*HOUR}px`}>{String(hour).padStart(2,'0')}:00</span>{/each}</div>
          <div class="day-columns">{#each week as day}<div class="day-column" class:chosen-column={dayKey(day)===dayKey(selected)}>
            <button class="slot-layer" aria-label={`Добавить событие ${shortDate(day)}`} on:click={event=>slot(event,day)}></button>
            {#each layoutDeadlines(filtered,day,HOUR) as card (card.task.id)}<button class={`deadline-card ${taskColor(card.task)}`} class:collision={card.lanes > 1} class:done-card={card.task.status === 'done'} style={`top:${card.top}px;left:calc(${card.lane/card.lanes*100}% + 2px);width:calc(${100/card.lanes}% - 4px)`} aria-label={`${card.task.title}, ${timeLabel(new Date(card.task.due_at!))}`} title={`${card.task.title} · срок ${timeLabel(new Date(card.task.due_at!))}`} on:click={()=>inspect(card.task)}><span>{#if card.task.reminder_at}<Bell size={11}/>{:else}<ListTodo size={11}/>{/if}<b>{card.task.title}</b></span><small>{timeLabel(new Date(card.task.due_at!))}</small></button>{/each}
          </div>{/each}</div>
          {#if nowInWeek}<div class="now-line" style={`top:${minutesOfDay(now)*HOUR/60}px`} aria-label={`Сейчас ${timeLabel(now)}`}><span>{timeLabel(now)}</span><i style={`left:calc(42px + (100% - 42px) * ${week.findIndex(day=>dayKey(day)===dayKey(now))/week.length})`}></i></div>{/if}
        </div>
      </div>
    {/if}
  </section>

  <aside class="calendar-right">
    <section class="day-summary calendar-surface"><div class="day-summary-top"><div><h2>{selectedLabel}</h2><p>{selected.toLocaleDateString('ru-RU',{weekday:'short',day:'numeric',month:'long'})}</p></div>{#if isToday}<span class="day-weather" title={weather.stale ? 'Погода из сохранённых данных' : 'Санкт-Петербург'}><WeatherIcon code={weather.data?.current.weather_code ?? -1} isDay={!!weather.data?.current.is_day} size={23}/><b>{weather.data && !weather.stale ? degrees(weather.data.current.temperature_2m) : '—'}</b></span>{/if}</div>
      <div class="day-agenda">{#each dayTasks.filter(task=>task.status === 'open').slice(0,3) as task}<button on:click={()=>inspect(task)}><i class={taskColor(task)}></i><time>{timeLabel(new Date(task.due_at!))}</time><b>{task.title}</b></button>{:else}<span class="small-empty">Нет задач на этот день</span>{/each}</div>
    </section>
    <section class="day-checklist calendar-surface"><div class="right-heading"><h2>Задачи на день</h2><span>{finished} из {dayTasks.length}</span><svg viewBox="0 0 30 30" class="day-progress" aria-label={`Выполнено ${finished} из ${dayTasks.length}`}><circle cx="15" cy="15" r="11"/><circle cx="15" cy="15" r="11" pathLength="1" stroke-dasharray="1" stroke-dashoffset={1-(dayTasks.length ? finished/dayTasks.length : 0)}/></svg></div><div class="day-tasks">{#each dayTasks as task}<button class:completed={task.status === 'done'} aria-label={`${task.status === 'done' ? 'Вернуть' : 'Завершить'}: ${task.title}`} disabled={busy} on:click={()=>complete(task)}><span class="day-check">{#if task.status === 'done'}<Check size={12}/>{/if}</span><b>{task.title}</b></button>{:else}<span class="small-empty">Здесь будут дела выбранного дня.</span>{/each}</div></section>
    <section class="day-notifications calendar-surface"><div class="right-heading"><h2><Bell size={17}/>Напоминания</h2><button aria-label="Новое напоминание в календаре" on:click={()=>create()}><Plus size={17}/></button></div><div class="day-reminder-list">{#each dayReminders as task}<button on:click={()=>inspect(task)}><Bell size={15}/><b>{task.title}</b><time>{timeLabel(new Date(task.reminder_at!))}</time></button>{:else}<span class="small-empty">Напоминаний на этот день нет.</span>{/each}</div></section>
    <section class="calendar-quick-notes calendar-surface"><div class="right-heading"><h2><NotebookPen size={17}/>Быстрые заметки</h2><button aria-label="Открыть все заметки" on:click={openNotes}><ArrowUpRight size={17}/></button></div>{#if noteError}<p class="calendar-error" role="alert">{noteError}<button on:click={readNotes}>Повторить</button></p>{/if}{#if !quickOpen}<div class="quick-note-list">{#each savedNotes as note}<button on:click={openNotes}><i></i>{note.title || 'Без названия'}</button>{:else}{#if !quickOpen}<span class="small-empty">Нет заметок</span>{/if}{/each}</div>{/if}{#if quickOpen}<form class="calendar-note-form" on:submit|preventDefault={addNote}><textarea aria-label="Быстрая заметка календаря" placeholder="Что запомнить?" rows="2" maxlength="2000" bind:value={quickText}></textarea><div><button type="button" on:click={()=>quickOpen = false}>Отмена</button><button disabled={noteBusy || !quickText.trim()}>Сохранить</button></div></form>{:else}<button class="quick-note-add" on:click={()=>quickOpen = true}><Plus size={12}/>Записать мысль</button>{/if}</section>
  </aside>

  {/if}
  {#if modal}<div class="calendar-modal" role="presentation"><div class="calendar-dialog" on:keydown={dialogKeys} role="dialog" aria-modal="true" aria-label={modal === 'new' ? 'Новое событие календаря' : 'Событие календаря'} tabindex="-1"><div class="dialog-title"><span><CalendarDays size={17}/>{modal === 'new' ? 'Новое событие' : 'Детали события'}</span><button aria-label="Закрыть событие" disabled={busy} on:click={()=>modal = null}><X size={17}/></button></div>{#if error}<p class="calendar-error" role="alert">{error}</p>{/if}
    {#if modal === 'new'}<form class="calendar-event-form" on:submit|preventDefault={save}><input name="title" aria-label="Название события" placeholder="Что запланировать?" maxlength="200" bind:value={title}/><label><Clock3 size={15}/><span>Дата и время</span><input aria-label="Время события" type="datetime-local" required bind:value={when}/></label><textarea aria-label="Описание события" placeholder="Детали, которые пригодятся" rows="3" maxlength="10000" bind:value={notes}></textarea><label><Flag size={15}/><span>Приоритет</span><select aria-label="Приоритет события" bind:value={priority}><option value={0}>Обычный</option><option value={1}>Важный</option><option value={2}>Срочный</option></select></label><p class="event-help"><Bell size={12}/>Срок задачи · напомним за 30 минут</p><button class="event-submit" disabled={busy || !title.trim()}>{busy ? 'Сохраняю…' : 'Добавить событие'}</button></form>
    {:else if current}<div class="calendar-event-detail"><h3>{current.title}</h3>{#if current.notes}<p class="detail-notes">{current.notes}</p>{/if}<span class={`detail-priority ${taskColor(current)}`}>{current.priority === 2 ? 'Срочная задача' : current.priority === 1 ? 'Важная задача' : 'Обычная задача'}</span><label>Срок задачи<input aria-label="Новый срок события" type="datetime-local" bind:value={when}/></label><button class="event-submit" disabled={busy} on:click={reschedule}>Сохранить срок</button><div class="detail-actions"><button disabled={busy} on:click={()=>current && complete(current)}><Check size={14}/>{current.status === 'done' ? 'Вернуть в работу' : 'Завершить'}</button><button disabled={busy} on:click={()=>deleteConfirm = true}><Trash2 size={14}/>Удалить</button></div>{#if deleteConfirm}<div class="event-delete-confirm"><b>Удалить задачу навсегда?</b><button on:click={()=>deleteConfirm = false}>Отмена</button><button disabled={busy} on:click={remove}>Да, удалить</button></div>{/if}</div>{/if}
  </div></div>{/if}
</section>

<style>
  .planner-back { display:flex; align-items:center; gap:5px; background:none; color:#999; border:0; font-size:10px; padding:0 0 12px; }
  .calendar-board.compact-calendar { grid-template-columns:1.1fr 1fr; gap:10px; }
  .compact-month { padding:17px 13px; overflow:auto; scrollbar-width:thin; }
  .compact-month :global(.month-heading) { margin-bottom:16px; }
  .compact-month :global(.month-heading strong) { font-size:14px; }
  .compact-month :global(.month-weekdays) { margin-bottom:10px; font-size:10px; }
  .compact-month :global(.calendar-day) { height:32px; font-size:12px; }
  .compact-agenda { padding:16px 14px 12px; display:flex; flex-direction:column; overflow:hidden; }
  .compact-agenda-heading { display:flex; align-items:center; justify-content:space-between; gap:6px; margin-bottom:14px; flex:none; }
  .compact-agenda-heading h2 { font-size:15px; font-weight:600; margin:0 0 4px; }
  .compact-agenda-heading span { color:#777; font-size:10px; }
  .compact-day-list { flex:1; min-height:0; overflow:auto; scrollbar-width:thin; scrollbar-color:#333 transparent; }
  .compact-task { display:flex; align-items:flex-start; gap:8px; padding:9px 0; border-bottom:1px solid #ffffff08; }
  .compact-task .task-checkbox { margin-top:1px; }
  .compact-task-detail { display:flex; flex-direction:column; min-width:0; flex:1; gap:4px; background:none; border:0; padding:0; text-align:left; }
  .compact-task-detail b { font-size:11px; font-weight:450; overflow-wrap:anywhere; color:#d5d5d5; line-height:1.4; }
  .compact-task-detail small { color:#777; font-size:9px; }
  .compact-task-detail.completed b { text-decoration:line-through; color:#666; }
  .compact-no-tasks { display:block; margin:9px 0; font-size:11px; color:#666; }
  .open-week-planner { display:flex; align-items:center; gap:6px; margin-top:12px; padding:9px 8px; width:100%; background:#202020; color:#bcbcbc; border:0; border-radius:9px; font-size:10px; text-align:left; flex:none; }
  .open-week-planner > :global(svg:last-child) { margin-left:auto; }
  .calendar-board { display:grid;grid-template-columns:188px minmax(0,1fr) 228px;gap:10px;flex:1;min-height:0;position:relative; }
  .calendar-surface { border-radius:20px; background:var(--surface,#101010); min-width:0; min-height:0; }
  button,input,select,textarea { font-family:inherit; }
  .calendar-left { padding:15px 12px; display:flex; flex-direction:column; overflow:auto; scrollbar-width:thin; }
  .new-event { display:flex;align-items:center;justify-content:center;gap:6px;background:#e9e9e9;border:0;border-radius:13px;padding:11px 6px;font-size:11px;font-weight:600;color:#111;flex:none;margin-bottom:22px; }
  .new-event:hover { filter:brightness(1.12); }
  .calendar-left :global(.month-calendar) { flex:none; }
  .calendar-left :global(.month-heading) { gap:3px; margin-bottom:12px; }
  .calendar-left :global(.month-heading strong) { font-size:12px; color:#e4e4e4; letter-spacing:0; }
  .calendar-left :global(.month-controls) { gap:0; }
  .calendar-left :global(.month-controls button) { width:18px; height:23px; }
  .calendar-left :global(.calendar-today) { display:none; }
  .calendar-left :global(.month-weekdays) { font-size:9px; color:#969696; }
  .calendar-left :global(.calendar-day) { font-size:10px; height:26px; border-radius:50%; color:#dbdbdb; gap:0; }
  .calendar-left :global(.calendar-day.selected) { background:#332b1e;color:#f0c985;box-shadow:none; }
  .calendar-left :global(.calendar-day.today) { box-shadow:inset 0 0 0 1px #888888; }
  .calendar-left :global(.calendar-day:hover:not(.selected)) { background:#2e2e2e; }
  .calendar-left :global(.calendar-day i.has-tasks) { background:#a1a1a1; width:3px; height:3px; }
  .calendar-left :global(.calendar-day.urgent i.has-tasks) { background:#a9a9a9; }
  .calendar-left :global(.calendar-day.outside) { opacity:.36; }
  .calendar-left :global(.month-legend) { display:none; }
  .source-heading { display:flex; align-items:center; justify-content:space-between; border-top:1px solid #ffffff13; margin-top:18px; padding:17px 1px 12px; font-size:12px; font-weight:600; color:#e1e1e1; }
  .source-heading :global(svg) { color:#9f9f9f; }
  .calendar-sources { display:flex; flex-direction:column; gap:13px; }
  .source { display:flex; align-items:center; gap:8px; font-size:11px; color:#dddddd; cursor:pointer; position:relative; --source:#939393; }
  .source input { position:absolute; opacity:0; width:18px; height:18px; margin:0; }
  .source input:focus-visible + .source-check { outline:2px solid #ffffff; outline-offset:3px; }
  .source-check { width:18px; height:18px; border-radius:5px; background:#282828; color:transparent; display:grid; place-items:center; border:1px solid #595959; flex:none; }
  .source input:checked + .source-check { color:#ffffff; background:var(--source); border-color:#ffffff30; }
  .source small { margin-left:auto; color:#7a7a7a; font-size:10px; }
  .secondary-source { border-top:1px solid #ffffff13; padding-top:17px; margin-top:20px; font-size:10px; }
  .completed-filter { display:flex; align-items:center; gap:5px; color:#929292; font-size:9px; margin-top:16px; cursor:pointer; }
  .completed-filter input,.calendar-filter-popover input { accent-color:#8f8f8f; }
  .calendar-center { display:flex; flex-direction:column; padding:14px 12px 10px; overflow:hidden; position:relative; }
  .calendar-topbar { display:flex; align-items:center; gap:9px; flex:none; min-height:30px; }
  .period-navigation { display:flex; align-items:center; gap:1px; flex:none; }
  .calendar-topbar button,.calendar-period-meta button { display:grid; place-items:center; border:0; color:#b3b3b3; background:none; padding:4px; border-radius:7px; }
  .calendar-topbar button:hover { background:#323232; color:#ffffff; }
  .period-navigation h1 { margin:0 7px 0 4px; color:#eaeaea; font-size:13px; font-weight:650; text-transform:capitalize; white-space:nowrap; }
  .event-search { display:flex; align-items:center; gap:6px; min-width:60px; flex:1; padding:7px 8px; border-radius:10px; background:#ffffff04; border:1px solid #ffffff10; color:#888888; }
  .event-search input { width:100%; min-width:0; border:0; outline:none; background:none; color:#dbdbdb; font-size:10px; }
  .event-search input::placeholder { color:#9a9a9a; }
  .event-search button { padding:0; }
  .calendar-topbar select { background:#ffffff08; color:#dedede; border:1px solid #ffffff0b; border-radius:10px; padding:7px 5px; color-scheme:dark; font-size:10px; max-width:79px; }
  .calendar-topbar .calendar-filter-button { background:#ffffff07; padding:8px; }
  .calendar-topbar .active { background:#3c3c3c; color:#d7d7d7; }
  .calendar-period-meta { display:flex; align-items:center; gap:10px; font-size:9px; color:#878787; border-bottom:1px solid #ffffff10; padding:7px 0 10px; flex:none; }
  .calendar-period-meta button { display:inline; padding:2px 6px; color:#c4c4c4; background:#37373755; font-size:9px; }
  .deadline-legend { display:flex; align-items:center; gap:4px; margin-left:auto; font-size:8px; }
  .deadline-legend i { width:4px; height:4px; border-radius:50%; background:#9e9e9e; }
  .calendar-filter-popover { position:absolute; top:50px; right:12px; z-index:8; background:#2a2a2a; border:1px solid #454545; border-radius:12px; box-shadow:0 8px 20px #00000088; padding:13px; display:flex; flex-direction:column; gap:10px; font-size:11px; }
  .calendar-filter-popover label { display:flex; gap:7px; align-items:center; }
  .week-heading { display:grid; grid-template-columns:42px repeat(var(--days),minmax(0,1fr)); flex:none; height:58px; padding-right:6px; }
  .week-heading button { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px; margin:5px 5px; border-radius:13px; color:#bebebe; background:none; border:1px solid transparent; }
  .week-heading button.chosen { background:#2c261c;border-color:#8c6c3e33;color:#efcd95; }
  .week-heading button.actual-today:not(.chosen) { border-color:#6b6b6b; }
  .week-heading small { font-size:10px; text-transform:capitalize; }
  .week-heading b { font-weight:500; font-size:17px; }
  .time-scroll { min-height:0; flex:1; overflow-y:auto; scrollbar-width:thin; scrollbar-color:#3f3f3f transparent; overscroll-behavior:contain; }
  .time-grid { position:relative; }
  .time-ruler { position:absolute; top:0; bottom:0; left:0; width:42px; }
  .time-ruler > span { position:absolute; font-size:9px; color:#979797; padding-top:4px; }
  .day-columns { position:absolute; left:42px; right:0; top:0; bottom:0; display:grid; grid-template-columns:repeat(var(--days),minmax(0,1fr)); background:repeating-linear-gradient(to bottom,#ffffff0e 0,#ffffff0e 1px,transparent 1px,transparent var(--hour)); }
  .day-column { position:relative; min-width:0; border-left:1px solid #ffffff0b; }
  .day-column:last-child { border-right:1px solid #ffffff0b; }
  .chosen-column { background:#b59b6410;box-shadow:inset 1px 0 #927c4820,inset -1px 0 #927c4820; }
  .slot-layer { position:absolute; inset:0; width:100%; height:100%; border:0; background:none; padding:0; border-radius:0; }
  .slot-layer:hover { background:#ffffff02; }
  .purple { --event:#a6baad;--event-bg:#24352a; }
  .blue { --event:#c8b37e;--event-bg:#393223; }
  .coral { --event:#d38f7e;--event-bg:#442a25; }
  .green { --event:#8eb99f;--event-bg:#27392d; }
  .deadline-card { position:absolute; z-index:2; height:50px; padding:5px 5px; background:var(--event-bg); color:#f1f1f1; border:1px solid color-mix(in srgb,var(--event) 82%,transparent); border-radius:8px; text-align:left; overflow:hidden; box-shadow:inset 0 0 0 1px #ffffff09,0 3px 8px #00000022; }
  .deadline-card:hover { filter:brightness(1.2); z-index:3; }
  .deadline-card > span { display:flex; gap:4px; align-items:flex-start; }
  .deadline-card :global(svg) { flex:none; margin-top:2px; }
  .deadline-card b { font-size:11px; line-height:1.2; font-weight:600; display:-webkit-box; -webkit-line-clamp:2; line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; overflow-wrap:normal; }
  .deadline-card.collision :global(svg) { display:none; }
  .deadline-card.collision b { display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-size:10px; }
  .deadline-card > small { display:block; font-size:9px; line-height:1.3; color:#e1e1e1; margin-top:1px; }
  .done-card { opacity:.65; }
  .done-card b { text-decoration:line-through; }
  .now-line { position:absolute;left:0;right:0;height:1px;background:#d9b775;z-index:4;pointer-events:none; }
  .now-line > span { position:absolute;top:-9px;left:0;background:#d9b775;color:#231e14;border-radius:8px;padding:2px 5px;font-size:9px;font-weight:650; }
  .now-line > i { position:absolute;top:-3px;width:7px;height:7px;background:#e9c98a;border-radius:50%; }
  .board-month-weekdays { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); padding:12px 0 7px; font-size:10px; color:#9c9c9c; text-align:center; flex:none; }
  .board-month { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); grid-template-rows:repeat(6,minmax(0,1fr)); min-height:0; flex:1; border-top:1px solid #ffffff12; border-left:1px solid #ffffff12; }
  .board-month-cell { min-width:0; min-height:0; overflow:hidden; padding:3px; border-right:1px solid #ffffff0c; border-bottom:1px solid #ffffff0c; }
  .board-month-cell.outside { opacity:.4; }
  .selected-cell { background:#5757572a; }
  .month-cell-top { display:flex; justify-content:space-between; align-items:center; margin-bottom:3px; }
  .month-cell-top button { border:0; background:none; color:#dcdcdc; border-radius:50%; font-size:10px; width:21px; height:21px; display:grid; place-items:center; padding:0; }
  .month-cell-top .current-date { background:#6c6c6c; color:#ffffff; }
  .cell-add { opacity:0; }
  .board-month-cell:hover .cell-add,.cell-add:focus-visible { opacity:1; }
  .month-event { width:100%; display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; text-align:left; border:0; border-left:2px solid var(--event); background:color-mix(in srgb,var(--event-bg) 70%,transparent); color:#e5e5e5; border-radius:3px; padding:3px; margin:2px 0; font-size:8px; }
  .month-event small { font-size:7px; margin-right:3px; color:#c0c0c0; }
  .more-events { font-size:8px; color:#ababab; background:none; border:0; padding:2px; }
  .calendar-results { flex:1; min-height:0; overflow:auto; padding:10px 2px; scrollbar-width:thin; }
  .search-count { font-size:10px; color:#929292; margin:0 0 8px; }
  .search-result { width:100%; display:flex; align-items:center; gap:10px; text-align:left; color:#dcdcdc; background:#ffffff04; border:0; border-radius:10px; padding:12px 9px; margin-bottom:6px; }
  .search-result i { width:4px; height:30px; border-radius:3px; background:var(--event); }
  .search-result > span { flex:1; min-width:0; }
  .search-result b { display:block; font-size:12px; overflow-wrap:anywhere; }
  .search-result small { font-size:10px; color:#9a9a9a; }
  .calendar-empty { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:10px; min-height:250px; color:#878787; font-size:11px; }
  .calendar-empty b { color:#bfbfbf; font-weight:500; }
  .calendar-right { display:grid; grid-template-rows:auto minmax(140px,1fr) auto minmax(140px,1fr); gap:10px; min-height:0; overflow-y:auto; scrollbar-width:thin; scrollbar-color:#373737 transparent; }
  .calendar-right > section { flex-shrink:0; padding:15px 13px; }
  .calendar-right h2 { margin:0; font-size:12px; font-weight:600; color:#e5e5e5; }
  .day-summary-top { display:flex; justify-content:space-between; gap:5px; align-items:center; }
  .day-summary h2 { text-transform:capitalize; font-size:15px; }
  .day-summary p { font-size:10px; color:#9e9e9e; margin:5px 0 0; }
  .day-weather { display:flex; align-items:center; gap:4px; color:#bebebe; font-size:11px; }
  .day-weather b { font-weight:500; }
  .day-agenda { display:flex; flex-direction:column; gap:9px; margin-top:16px; }
  .day-agenda button { display:flex; gap:7px; align-items:center; padding:0; background:none; border:0; font-size:10px; text-align:left; }
  .day-agenda i { width:3px; height:19px; border-radius:4px; background:var(--event); flex:none; }
  .day-agenda time { color:#a8a8a8; font-size:9px; flex:none; }
  .day-agenda b { color:#dedede; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .right-heading { display:flex; align-items:center; justify-content:space-between; gap:5px; margin-bottom:12px; }
  .right-heading h2 { display:flex; align-items:center; gap:5px; }
  .right-heading > span { margin-left:auto; font-size:9px; color:#929292; white-space:nowrap; }
  .right-heading button { display:grid; place-items:center; padding:0; border:0; background:none; color:#aeaeae; }
  .day-progress { width:24px; height:24px; flex:none; transform:rotate(-90deg); }
  .day-progress circle { fill:none; stroke:#3e3e3e; stroke-width:4; }
  .day-progress circle + circle { stroke:#929292; stroke-linecap:round; transition:stroke-dashoffset 200ms; }
  .day-checklist { display:flex; flex-direction:column; }
  .day-tasks { display:flex; flex-direction:column; gap:8px; flex:1; min-height:0; overflow:auto; scrollbar-width:thin; }
  .day-tasks button { display:flex; align-items:flex-start; gap:9px; padding:0; text-align:left; background:none; border:0; color:#d9d9d9; }
  .day-check { width:16px; height:16px; display:grid; place-items:center; border:1px solid #6e6e6e; border-radius:4px; flex:none; }
  .completed .day-check { background:#688371;border-color:#92ad9b; }
  .day-tasks b { font-size:10px; font-weight:400; line-height:1.5; overflow-wrap:anywhere; }
  .completed b { color:#818181; text-decoration:line-through; }
  .day-reminder-list { display:flex; flex-direction:column; gap:5px; max-height:100px; overflow:auto; scrollbar-width:thin; scrollbar-color:#434343 transparent; }
  .day-reminder-list button { display:flex; gap:7px; align-items:center; border:0; border-radius:8px; background:#ffffff07; padding:9px 7px; text-align:left; color:#aaaaaa; }
  .day-reminder-list b { flex:1; min-width:0; font-size:9px; color:#cdcdcd; font-weight:400; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .day-reminder-list time { color:#a0a0a0; font-size:9px; }
  .calendar-right .calendar-quick-notes { display:flex; flex-direction:column; min-height:140px; }
  .quick-note-list { display:flex; flex-direction:column; gap:7px; flex:1; min-height:0; overflow:auto; scrollbar-width:thin; }
  .quick-note-list button { display:flex; gap:7px; align-items:baseline; border:0; background:#8d8d8d0b; color:#c4c4c4; padding:5px 7px; border-radius:5px; text-align:left; font-size:10px; line-height:1.5; overflow-wrap:anywhere; }
  .quick-note-list i { width:3px; height:3px; border-radius:50%; background:#b3b3b3; flex:none; }
  .small-empty { display:block; color:#7f7f7f; font-size:10px; line-height:1.7; }
  .quick-note-add { display:flex; align-items:center; gap:5px; color:#8c8c8c; background:none; border:0; padding:12px 0 0; font-size:9px; }
  .calendar-note-form textarea { width:100%; margin-top:8px; min-width:0; background:#272727; border:1px solid #4d4d4d; color:#d5d5d5; border-radius:8px; padding:7px; font-size:10px; resize:vertical; max-height:110px; }
  .calendar-note-form > div { display:flex; justify-content:space-between; gap:6px; }
  .calendar-note-form button { background:#333333; color:#d0d0d0; border:0; border-radius:6px; padding:5px; font-size:9px; }
  .calendar-error { display:flex; align-items:center; gap:5px; background:#33333366; color:#c0c0c0; border-radius:7px; padding:8px; font-size:10px; line-height:1.4; overflow-wrap:anywhere; }
  .calendar-error button { color:inherit; background:none; border:0; margin-left:auto; font-size:10px; }
  .calendar-modal { position:absolute; inset:0; z-index:20; display:grid; place-items:center; background:#04040499; backdrop-filter:blur(7px); border-radius:20px; overflow:auto; padding:12px; }
  .calendar-dialog { width:370px;max-width:100%;max-height:100%;overflow:auto;scrollbar-width:thin;padding:20px;background:#191919;border:1px solid #333;border-radius:20px;box-shadow:0 20px 60px #0008; }
  .dialog-title,.dialog-title span { display:flex; align-items:center; justify-content:space-between; gap:8px; color:#dadada; font-size:13px; font-weight:600; }
  .dialog-title button { display:grid; place-items:center; background:none; border:0; padding:0; color:#949494; }
  .calendar-event-form,.calendar-event-detail { display:flex; flex-direction:column; gap:12px; margin-top:19px; }
  .calendar-dialog input,.calendar-dialog select,.calendar-dialog textarea { width:100%; background:#0e0e0e; border:1px solid #484848; border-radius:9px; padding:9px; color:#d9d9d9; font-size:11px; color-scheme:dark; min-width:0; }
  .calendar-dialog textarea { resize:vertical; max-height:140px; }
  .calendar-dialog input[name="title"] { font-size:14px; font-weight:550; padding:10px; }
  .calendar-event-form label { display:flex; align-items:center; gap:6px; color:#a8a8a8; font-size:10px; }
  .calendar-event-form label > span { flex:none; }
  .calendar-event-form label input,.calendar-event-form label select { flex:1; }
  .event-help { display:flex; align-items:center; gap:6px; margin:0; color:#979797; font-size:10px; }
  .event-submit { border:0;border-radius:10px;background:#e9e9e9;color:#111;padding:10px;font-size:12px;font-weight:600; }
  .calendar-event-detail h3 { margin:0; font-size:18px; line-height:1.4; overflow-wrap:anywhere; color:#dedede; }
  .detail-notes { margin:0; white-space:pre-wrap; overflow-wrap:anywhere; max-height:100px; overflow:auto; color:#aaaaaa; font-size:11px; line-height:1.6; }
  .detail-priority { width:fit-content; color:var(--event); background:color-mix(in srgb,var(--event-bg) 45%,transparent); border-radius:6px; font-size:10px; padding:4px 7px; }
  .calendar-event-detail label { display:flex; flex-direction:column; gap:6px; color:#929292; font-size:10px; }
  .detail-actions { display:flex; justify-content:space-between; gap:8px; }
  .detail-actions button { display:flex; align-items:center; gap:6px; border:0; color:#bdbdbd; background:#272727; border-radius:8px; padding:7px; font-size:10px; }
  .event-delete-confirm { display:flex; flex-wrap:wrap; gap:8px; padding:11px; background:#34343466; border-radius:10px; font-size:11px; }
  .event-delete-confirm b { width:100%; color:#bfbfbf; font-weight:500; }
  .event-delete-confirm button { background:#424242; color:#cdcdcd; border:0; border-radius:6px; padding:5px; font-size:10px; }
  @media (min-width:1100px) { .new-event{font-size:12px}.source{font-size:12px}.calendar-left :global(.month-heading strong){font-size:13px}.calendar-left :global(.calendar-day){font-size:11px;height:28px}.calendar-left :global(.month-weekdays){font-size:10px}.period-navigation h1{font-size:15px}.event-search input,.calendar-topbar select{font-size:11px}.calendar-right h2{font-size:14px}.day-summary h2{font-size:17px}.day-summary p{font-size:11px}.day-agenda b,.day-tasks b,.quick-note-list button{font-size:11px}.day-agenda time,.day-reminder-list time,.day-reminder-list b{font-size:10px}.small-empty{font-size:11px}.day-agenda{gap:11px} }
  @media (max-width:1000px) { .calendar-board { grid-template-columns:155px minmax(0,1fr) 185px;gap:8px; }.calendar-left {padding:13px 9px}.calendar-topbar{flex-wrap:wrap;gap:5px}.period-navigation{flex:1}.event-search{order:5;flex-basis:100%;padding:6px}.calendar-right > section{padding:12px 10px}.right-heading h2{font-size:11px}.deadline-card b{font-size:8px}.deadline-card :global(svg){display:none}.deadline-legend{display:none} }
  @media (max-width:810px) { .calendar-board {grid-template-columns:130px minmax(0,1fr)}.calendar-right {display:none}.calendar-left{padding:10px 7px}.new-event{font-size:10px;padding:9px 3px}.calendar-left :global(.month-heading strong){font-size:10px}.calendar-left :global(.calendar-day){height:23px;font-size:9px}.source{font-size:10px;gap:6px}.secondary-source{font-size:9px}.completed-filter{font-size:8px}.calendar-center{padding:10px 8px} }
  @media (max-height:640px) {.calendar-left{padding-top:10px}.new-event{margin-bottom:12px}.source-heading{margin-top:10px;padding-top:12px}.calendar-sources{gap:8px}.secondary-source{margin-top:12px;padding-top:12px}.calendar-right > section{padding-top:12px;padding-bottom:12px}.day-agenda{margin-top:11px}.day-checklist .day-tasks{max-height:100px} }
</style>
