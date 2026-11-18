<script lang="ts">
  import { Bell, ArrowUpRight, X } from 'lucide-svelte';
  import type { Task } from '../types';
  export let task: Task;
  export let phase: 'bell' | 'opening' | 'message' = 'bell';
  export let remaining = 0;
  export let inline = false;
  export let leaving = false;
  export let open: () => void;
  export let dismiss: () => void;
  export let hover: (value: boolean) => void;
  $: at = task.due_at || task.reminder_at;
  $: date = at ? new Date(at) : null;
  $: time = date?.toLocaleTimeString('ru-RU', {hour:'2-digit', minute:'2-digit'}) || '';
  $: day = date && date.toDateString() !== new Date().toDateString()
    ? date.toLocaleDateString('ru-RU', {day:'numeric', month:'short'}) : 'Сегодня';
</script>

<section class="reminder-notice" class:inline class:leaving class:ringing={phase === 'bell'} data-phase={phase}
  aria-label={phase === 'message' ? 'Напоминание о задаче' : 'Новое напоминание'} role="status" aria-live="polite"
  on:mouseenter={() => hover(true)} on:mouseleave={() => hover(false)}
  on:focusin={() => hover(true)} on:focusout={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) hover(false); }}>
  <span class="reminder-emblem" aria-hidden="true">
    <span class="bell-swing"><Bell size={21} strokeWidth={1.7}/></span>
    <svg class="bell-impact" width="42" height="36" viewBox="0 0 42 36" fill="none">
      <path d="M30 7L34 4M32 12H37M10 7L7 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
    </svg>
    <span class="bell-halo"></span>
  </span>
  {#if phase === 'message'}
    <button class="reminder-open" on:click={open} title={`${task.title} — открыть задачу`}>
      <span class="reminder-eyebrow">Напоминание <time datetime={at || undefined} title={`${day}, ${time}`}>{time}</time>{#if remaining}<small title={`В очереди ещё ${remaining}`}>+{remaining}</small>{/if}<ArrowUpRight size={10}/></span>
      <strong>{task.title}</strong>
    </button>
    <button class="reminder-dismiss" aria-label="Закрыть напоминание" title="Закрыть напоминание" on:click={dismiss}><X size={13}/></button>
  {/if}
</section>

<style>
  .reminder-notice { position:relative; width:100%; height:100%; color:#e9e7e2; transition:opacity 180ms ease-in,transform 180ms ease-in; }
  .leaving { opacity:0; transform:translateY(-4px); }
  .reminder-emblem { position:absolute; left:50%; top:50%; transform:translate(calc(-50% - 107px),-50%); width:28px; height:28px; display:grid; place-items:center; color:#efc77e; transition:transform 420ms var(--ease); }
  .ringing .reminder-emblem { transform:translate(-50%,-50%); }
  .bell-swing { display:grid; place-items:center; transform-origin:50% 12%; }
  .ringing .bell-swing { animation:bell-strike 820ms 160ms cubic-bezier(.36,.04,.24,1) both; }
  .bell-impact { position:absolute; left:-7px; top:-4px; opacity:0; pointer-events:none; }
  .ringing .bell-impact { animation:impact 600ms 240ms ease-out both; }
  .bell-halo { position:absolute; inset:-4px; border:1px solid #e9ba671f; border-radius:50%; opacity:0; }
  .ringing .bell-halo { animation:halo 650ms 280ms ease-out both; }
  .reminder-open { position:absolute; left:54px; right:29px; top:8px; bottom:8px; display:flex; flex-direction:column; justify-content:center; gap:3px; text-align:left; border:0; padding:0; min-width:0; background:transparent; color:inherit; animation:message-in 260ms var(--ease) both; }
  .reminder-open:hover strong { color:#fff4df; }
  .reminder-eyebrow { display:flex; align-items:center; gap:6px; color:#b69b68; font-size:8.5px; line-height:9px; letter-spacing:.12px; white-space:nowrap; }
  time { color:#848079; font-variant-numeric:tabular-nums; }
  .reminder-eyebrow small { font-size:8px; color:#77736c; margin-left:auto; }
  .reminder-eyebrow :global(svg) { margin-left:auto; }
  strong { display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; line-clamp:2; overflow:hidden; overflow-wrap:anywhere; font-size:12px; font-weight:570; letter-spacing:-.12px; line-height:14px; }
  .reminder-dismiss { position:absolute; top:7px; right:7px; width:18px; height:18px; display:grid; place-items:center; border:0; border-radius:50%; color:#77736c; background:transparent; padding:0; animation:message-in 260ms var(--ease) both; }
  .reminder-dismiss:hover { color:#f1ddba; background:#ffffff0b; }
  .inline { position:absolute; top:58px; right:17px; z-index:6; width:272px; height:56px; border-radius:18px; background:#171612; box-shadow:0 12px 32px #0009,inset 0 0 0 1px #ead2a21a; transition:width 420ms var(--ease),height 420ms var(--ease),opacity 180ms ease-in,transform 180ms ease-in; }
  .inline.ringing { width:96px; height:40px; }
  @keyframes bell-strike { 0% {transform:rotate(0)} 12% {transform:rotate(-10deg)} 26% {transform:rotate(24deg)} 42% {transform:rotate(-19deg)} 58% {transform:rotate(12deg)} 73% {transform:rotate(-7deg)} 86% {transform:rotate(3deg)} 100% {transform:rotate(0)} }
  @keyframes impact { 0% {opacity:0;transform:scale(.85)} 20% {opacity:.9;transform:scale(1)} 100% {opacity:0;transform:scale(1.12)} }
  @keyframes halo { 0% {opacity:0;transform:scale(.7)} 20% {opacity:.8} 100% {opacity:0;transform:scale(1.4)} }
  @keyframes message-in { from {opacity:0;transform:translateY(3px)} to {opacity:1;transform:translateY(0)} }
  @media (prefers-reduced-motion:reduce) {
    .reminder-notice,.reminder-emblem {transition:none}
    .bell-swing,.bell-impact,.bell-halo,.reminder-open,.reminder-dismiss {animation:none!important}
  }
</style>
