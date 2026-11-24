<script lang="ts">
  import { ChevronDown, Minus, Plus, SlidersHorizontal } from 'lucide-svelte';
  export let minutes = 25;
  export let total: number;
  export let set: (minutes: number) => void;
  export let add: (minutes: number) => void;
  let amount: number | undefined = minutes;
  let error = '';
  let editing = false;
  let trigger: HTMLButtonElement | undefined;
  let lastMinutes = minutes;
  $: if (minutes !== lastMinutes) { amount = minutes; lastMinutes = minutes; error = ''; }
  function apply(adding: boolean) {
    if (amount === undefined || !Number.isInteger(amount) || amount < 1 || amount > 240) { error = 'Введи от 1 до 240 минут'; return; }
    if (adding && total + amount * 60 > 4 * 3600) { error = 'Общая длительность — до 240 минут'; return; }
    error = '';
    if (adding) add(amount); else set(amount);
    editing = false;
    trigger?.focus();
  }
</script>

<div class="timer-duration" class:editing on:focusout={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) editing = false; }}>
  <button bind:this={trigger} class="duration-trigger" aria-label="Настроить время таймера" aria-expanded={editing} aria-controls="timer-duration-editor" on:click={() => editing = !editing}>
    <SlidersHorizontal size={12}/><span>Своё время</span><ChevronDown size={12} class="duration-chevron"/>
  </button>
  <div class="duration-reveal" inert={!editing} aria-hidden={!editing}>
    <div class="duration-clip">
      <form id="timer-duration-editor" aria-label="Своя длительность таймера" on:submit|preventDefault={() => apply(false)}>
        <div class="duration-counter">
          <button class="duration-step" type="button" aria-label="Уменьшить время на минуту" disabled={!amount || amount <= 1} on:click={() => { amount = Math.max(1, (amount ?? minutes) - 1); error = ''; }}><Minus size={14}/></button>
          <label><input aria-label="Время таймера, минуты" type="number" min="1" max="240" step="1" bind:value={amount} on:keydown={event => { if (event.key === 'Escape') { event.stopPropagation(); editing = false; trigger?.focus(); } }}/><span>мин</span></label>
          <button class="duration-step" type="button" aria-label="Увеличить время на минуту" disabled={amount !== undefined && amount >= 240} on:click={() => { amount = Math.min(240, (amount ?? minutes) + 1); error = ''; }}><Plus size={14}/></button>
        </div>
        <div class="duration-actions">
          <button class="duration-set" type="submit" title="Задать длительность и остановить таймер">Задать</button>
          <button type="button" title="Добавить минуты без остановки таймера" on:click={() => apply(true)}><Plus size={11}/>Добавить</button>
        </div>
        {#if error}<small class="timer-duration-error" role="alert">{error}</small>{/if}
      </form>
    </div>
  </div>
</div>

<style>
  .timer-duration { position:relative; flex:none; min-width:0; margin-top:8px; }
  button { box-sizing:border-box; border:0; font:inherit; cursor:pointer; }
  .duration-trigger { width:100%; display:flex; align-items:center; gap:7px; padding:8px 10px; border:1px solid #292929; border-radius:10px; color:#999; background:transparent; font-size:10px; text-align:left; transition:color 160ms,background 160ms,border-color 160ms; }
  .duration-trigger span { flex:1; }
  .duration-trigger:hover,.editing .duration-trigger { color:#ddd; background:#1b1b1b; border-color:#383838; }
  .duration-trigger :global(.duration-chevron) { transition:transform 180ms; color:#777; }
  .editing .duration-trigger :global(.duration-chevron) { transform:rotate(180deg); }
  .duration-reveal { position:absolute; z-index:3; top:calc(100% + 6px); left:0; right:0; padding:9px; border:1px solid #353535; border-radius:12px; background:#1b1b1b; box-shadow:0 8px 20px #0008; opacity:0; transform:translateY(-4px); pointer-events:none; transition:transform 160ms ease,opacity 140ms ease; }
  .editing .duration-reveal { opacity:1; transform:translateY(0); pointer-events:auto; }
  .duration-clip { min-height:0; overflow:hidden; }
  form { padding:0; }
  .duration-counter { display:flex; align-items:center; height:38px; padding:0 4px; border:1px solid #303030; border-radius:10px; background:#171717; }
  .duration-counter:focus-within { border-color:#8f7443; }
  .duration-step { display:grid; place-items:center; width:28px; height:28px; padding:0; border-radius:7px; background:transparent; color:#aaa; }
  .duration-step:hover:enabled { color:#eee; background:#2c2c2c; }
  .duration-step:disabled { color:#454545; cursor:default; }
  label { flex:1; min-width:0; display:flex; align-items:baseline; justify-content:center; gap:5px; color:#777; font-size:10px; }
  input { box-sizing:border-box; width:3ch; min-width:0; padding:0; border:0; outline:0; appearance:textfield; background:transparent; color:#eee; font:inherit; font-size:20px; font-weight:500; font-variant-numeric:tabular-nums; text-align:center; }
  input::-webkit-inner-spin-button,input::-webkit-outer-spin-button { appearance:none; margin:0; }
  .duration-counter input:focus,.duration-counter input:focus-visible { outline:0; box-shadow:none; border:0; }
  .duration-actions { display:grid; grid-template-columns:1fr 1fr; gap:6px; margin-top:6px; }
  .duration-actions button { display:flex; align-items:center; justify-content:center; gap:3px; height:29px; padding:0 6px; border-radius:9px; background:#242424; color:#b3b3b3; font-size:10px; transition:background 160ms,color 160ms; }
  .duration-actions button:hover { background:#303030; color:#eee; }
  .duration-actions .duration-set { background:#30291d; color:#e1c28e; }
  .duration-actions .duration-set:hover { background:#403522; color:#ffe0ab; }
  button:focus-visible { outline:1px solid var(--amber,#d6b476); outline-offset:2px; }
  .timer-duration-error { display:block; color:#debda1; font-size:10px; line-height:1.4; margin:6px 0 0; }
  @media(prefers-reduced-motion:reduce) { .duration-reveal,.duration-trigger,.duration-trigger :global(.duration-chevron),.duration-actions button { transition:none; } }
</style>
