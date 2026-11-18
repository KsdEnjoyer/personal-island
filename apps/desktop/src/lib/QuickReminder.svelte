<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import { BellPlus, Check, X } from 'lucide-svelte';
  import { parseReminder } from './reminder';
  export let refresh: () => Promise<void>;
  let text = '';
  let date = '';
  let expanded = false;
  let busy = false;
  let error = '';
  let status = '';
  async function add() {
    if (busy || !text.trim()) return;
    const parsed = date ? { title:text.trim(), at:new Date(date) } : parseReminder(text);
    if (!parsed || !Number.isFinite(parsed.at.getTime()) || parsed.at <= new Date()) {
      expanded = true; error = 'Укажи будущее время или напиши «через 30 мин».'; return;
    }
    busy = true; error = ''; status = '';
    try {
      await invoke('create_task', { task:{ title:parsed.title, due_at:parsed.at.toISOString(), reminder_at:parsed.at.toISOString(), priority:0 } });
      text = ''; date = ''; expanded = false; status = 'Напоминание добавлено'; await refresh();
    } catch (err) { error = String(err); }
    finally { busy = false; }
  }
</script>
<form class="quick-reminder" on:submit|preventDefault={add}>
  {#if status}<span class="quick-status" role="status"><Check size={11}/>{status}</span>{/if}
  <div class="quick-entry"><input aria-label="Быстрое напоминание" maxlength="200" placeholder="Позвонить маме завтра в 9" bind:value={text}/><button aria-label="Добавить быстрое напоминание" title="Добавить напоминание" disabled={busy || !text.trim()}><BellPlus size={14}/></button></div>
  {#if expanded}<div class="quick-date"><input aria-label="Время быстрого напоминания" type="datetime-local" bind:value={date}/><button type="button" aria-label="Закрыть выбор времени" on:click={() => { expanded = false; error = ''; }}><X size={12}/></button></div>{/if}
  {#if error}<span class="quick-error" role="alert">{error}</span>{/if}
</form>
<style>
  .quick-reminder { margin-top:auto; padding-top:9px; flex:none; }
  .quick-entry { display:flex; align-items:center; background:#242424; border-radius:9px; padding:2px 5px 2px 8px; }
  input { width:100%; min-width:0; background:none; border:0; color:#ddd; font-size:10px; padding:8px 0; }
  input::placeholder { color:#777; }
  button { border:0; background:none; color:#c5aa73; display:grid; place-items:center; padding:5px; }
  .quick-date { display:flex; gap:3px; }
  .quick-date input { color-scheme:dark; font-size:10px; }
  .quick-error,.quick-status { display:flex; align-items:center; gap:4px; font-size:9px; line-height:1.4; padding:4px 1px; }
  .quick-error { color:#edb49c; } .quick-status { color:#9ec6ab; }
</style>
