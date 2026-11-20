<script lang="ts">
  import { Pause, Play, RotateCcw } from 'lucide-svelte';
  export let seconds: number;
  export let total: number;
  export let running: boolean;
  export let minutes = 25;
  export let compact = false;
  export let toggle: () => void;
  export let set: (minutes: number) => void;
  export let add: (minutes: number) => void;
  export let reset: () => void;
  let amount: number | undefined = minutes;
  let error = '';
  const countdown = (value: number) => `${Math.floor(value / 60).toString().padStart(2,'0')}:${(value % 60).toString().padStart(2,'0')}`;
  function apply(adding: boolean) {
    if (amount === undefined || !Number.isInteger(amount) || amount < 1 || amount > 240) { error = 'Введи от 1 до 240 минут'; return; }
    if (adding && total + amount * 60 > 4 * 3600) { error = 'Общая длительность — до 240 минут'; return; }
    error = '';
    if (adding) add(amount); else set(amount);
  }
</script>

<section class="focus-timer" class:compact aria-label="Таймер фокуса">
  <div class="timer-main"><strong aria-live="off">{countdown(seconds)}</strong><button class="timer-start" aria-label={running ? 'Приостановить таймер' : 'Запустить таймер'} on:click={toggle}>{#if running}<Pause size={12} fill="currentColor"/>Пауза{:else}<Play size={12} fill="currentColor"/>Старт{/if}</button><button class="timer-clear" aria-label="Сбросить таймер" title="Сбросить" on:click={reset}><RotateCcw size={13}/></button></div>
  <div class="timer-meta"><span>{running ? 'Идёт фокус' : 'На паузе'}</span><span>Всего {Math.round(total / 60)} мин</span></div>
  <div class="timer-meter" aria-hidden="true"><i style:width={`${Math.max(0,Math.min(100,100*(1-seconds/Math.max(1,total))))}%`}></i></div>
  <form class="timer-editor" on:submit|preventDefault={() => apply(false)}>
    <label><span class="sr-only">Время таймера, минуты</span><input aria-label="Время таймера, минуты" type="number" min="1" max="240" step="1" bind:value={amount}/><span>мин</span></label>
    <button type="submit" title="Задать длительность и остановить таймер">Задать</button><button type="button" title="Добавить минуты без остановки таймера" on:click={() => apply(true)}>Добавить</button>
  </form>
  {#if error}<small class="timer-error" role="alert">{error}</small>{/if}
</section>

<style>
  .focus-timer { width:100%; min-width:0; color:#eee; }
  .timer-main { display:flex; align-items:center; gap:6px; }
  strong { flex:1; font-size:31px; font-weight:600; letter-spacing:-1.5px; font-variant-numeric:tabular-nums; }
  button { border:0; cursor:pointer; font:inherit; }
  .timer-start { display:flex; align-items:center; justify-content:center; gap:5px; background:#e9eae9; color:#171a18; border-radius:18px; height:29px; padding:0 11px; font-size:10px; }
  .timer-clear { padding:3px; color:#868f89; background:transparent; border-radius:8px; }
  .timer-meta { display:flex; justify-content:space-between; color:#818a84; font-size:9px; margin:5px 0 8px; }
  .timer-meter { height:2px; background:#282e2a; border-radius:2px; overflow:hidden; margin-bottom:10px; }
  .timer-meter i { display:block; height:100%; background:var(--amber,#b6d8c2); }
  .timer-editor { display:flex; align-items:center; gap:4px; }
  label { display:flex; gap:3px; align-items:center; flex:1; min-width:0; color:#8e9891; font-size:10px; }
  input { width:38px; min-width:0; border:1px solid #343d36; border-radius:7px; padding:5px 2px 5px 5px; background:#191e1b; color:#e4eae6; font-size:11px; }
  .timer-editor button { font-size:9px; border-radius:8px; padding:7px 6px; color:#c8d5cc; background:#222b25; }
  .timer-editor button:hover { background:#334038; color:white; }
  .timer-error { display:block; color:#debda1; font-size:10px; margin-top:5px; }
  .sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); }
  .compact strong { font-size:29px; }
  :global(.capri-theme) .focus-timer { color:#dfedcd; }
</style>
