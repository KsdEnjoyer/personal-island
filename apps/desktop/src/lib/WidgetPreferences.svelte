<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import { onDestroy } from 'svelte';
  import { capturedShortcut, defaultShortcut, linuxDefaultShortcut, shortcutLabel, type ShortcutMode } from './widget-settings';
  import type { WidgetSettings } from '../types';
  export let settings: WidgetSettings;
  export let save: (value: WidgetSettings) => Promise<boolean>;
  export let busy = false;
  export let error = '';
  export let shortcutMode: ShortcutMode = 'windows';
  export let systemShortcut: string | null = null;
  let capturing = false;
  let captureError = '';
  let customMinutes: number | undefined = settings.review_interval_minutes || 30;
  let selectingCustom = ![0,15,30,60,120].includes(settings.review_interval_minutes);
  $: defaultKey = settings.shortcut.key === 192 && !settings.shortcut.ctrl && !settings.shortcut.alt && !settings.shortcut.shift;
  async function suppression(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    if (!await save({...settings, suppress_shortcut_character:input.checked})) input.checked = settings.suppress_shortcut_character;
  }
  async function capture(active: boolean) {
    capturing = active;
    try { await invoke('set_shortcut_capture', { capturing: active }); }
    catch (err) { capturing = false; captureError = String(err); }
  }
  async function configurePortal() {
    captureError = '';
    try { await invoke('configure_portal_shortcuts'); }
    catch (err) { captureError = String(err); }
  }
  async function keydown(event: KeyboardEvent) {
    event.preventDefault(); event.stopPropagation();
    if (event.key === 'Escape') { const input = event.currentTarget as HTMLInputElement; await capture(false); input.blur(); return; }
    if (event.repeat || ['Control','Alt','Shift','Meta'].includes(event.key)) return;
    const shortcut = capturedShortcut(event, shortcutMode === 'windows');
    if (!shortcut) {
      captureError = shortcutMode === 'windows' ? 'Ctrl/Alt + буква, цифра, пробел или F1–F11 / F13–F24' : 'Ctrl/Alt + буква, цифра, пробел или F1–F24';
      return;
    }
    captureError = '';
    if (await save({ ...settings, shortcut })) await capture(false);
  }
  async function interval(value: number) {
    selectingCustom = value === -1;
    if (selectingCustom) { customMinutes = settings.review_interval_minutes || 30; return; }
    await save({ ...settings, review_interval_minutes: value });
  }
  async function applyCustom() {
    if (!Number.isInteger(customMinutes) || !customMinutes || customMinutes < 5 || customMinutes > 1440) { captureError = 'Интервал — целое число от 5 до 1440 минут'; return; }
    captureError = '';
    await save({ ...settings, review_interval_minutes: customMinutes });
  }
  onDestroy(() => { void invoke('set_shortcut_capture', { capturing: false }).catch(() => {}); });
</script>

<section class="widget-preferences" aria-label="Клавиши и автопоказ">
  {#if shortcutMode === 'portal'}
    <div class="preference-heading"><span>Показать / скрыть{systemShortcut ? ` · ${systemShortcut}` : ''}</span><button disabled={busy} on:click={configurePortal}>Настроить в системе</button></div>
  {:else}
  <div class="preference-heading"><span>Показать / скрыть</span><button disabled={busy} on:click={() => save({...settings, shortcut: {...(shortcutMode === 'windows' ? defaultShortcut : linuxDefaultShortcut)}})}>Сбросить</button></div>
  <input class="shortcut-recorder" readonly aria-label="Сочетание для показа островка" aria-busy={busy} value={capturing ? 'Нажми новое сочетание…' : shortcutLabel(settings.shortcut)} disabled={busy}
    on:focus={() => capture(true)} on:click={() => { captureError = ''; void capture(true); }} on:blur={() => capture(false)} on:keydown={keydown}/>
  <p class="preference-note">Нажми на поле и задай сочетание. Escape — отмена.</p>
  {/if}
  {#if shortcutMode === 'windows'}
  <label class="character-row"><span>Не печатать Ё / ` при вызове</span><input type="checkbox" checked={settings.suppress_shortcut_character} disabled={busy || !defaultKey} on:change={suppression}/></label>
  <p class="preference-note">{#if !defaultKey}Для клавиши Ё / `. Выбранное сочетание уже не печатает символ.{:else if settings.suppress_shortcut_character}Клавиша только показывает и скрывает островок. В его текстовых полях Ё вводится как обычно.{:else}Одиночное Ё печатает символ. Двойное за 1,5 с убирает его из ввода.{/if}</p>
  {/if}
  <label class="interval-row"><span>Автопоказ дел</span><select aria-label="Интервал автопоказа" disabled={busy} value={selectingCustom ? -1 : settings.review_interval_minutes} on:change={event => interval(Number(event.currentTarget.value))}><option value={0}>Выключен</option><option value={15}>15 минут</option><option value={30}>30 минут</option><option value={60}>1 час</option><option value={120}>2 часа</option><option value={-1}>Свой интервал…</option></select></label>
  {#if selectingCustom}<form class="custom-interval" on:submit|preventDefault={applyCustom}><input type="number" aria-label="Свой интервал автопоказа, минуты" min="5" max="1440" step="1" bind:value={customMinutes} disabled={busy}/><span>мин</span><button type="submit" disabled={busy}>Применить</button></form>{/if}
  <p class="preference-note">По часам: 30 минут — в :00 и :30. Свой интервал отсчитывается от полуночи. Обычные напоминания о задачах работают отдельно.</p>
  {#if captureError || error || settings.shortcut_error}<p class="preference-error" role="alert">{captureError || error || settings.shortcut_error}</p>{/if}
</section>

<style>
  .widget-preferences { border-top:1px solid #313731; margin-top:8px; padding-top:10px; }
  .preference-heading { display:flex; align-items:center; justify-content:space-between; font-size:11px; color:#cbd3cd; margin-bottom:6px; }
  .preference-heading button { border:0; background:none; font-size:9px; color:#8fa997; padding:2px; cursor:pointer; }
  .widget-preferences .shortcut-recorder { box-sizing:border-box; width:100%; height:32px; border:1px solid #3d4940; border-radius:9px; background:#111713; color:#e2ede5; padding:6px 9px; text-align:center; font-size:11px; cursor:pointer; }
  .shortcut-recorder:focus { outline:1px solid #86a990; border-color:#86a990; }
  .preference-note { font-size:9px; line-height:1.5; color:#8b978f; margin:6px 1px 9px; }
  .character-row { display:flex; align-items:center; justify-content:space-between; gap:10px; font-size:11px; color:#cbd3cd; padding:5px 0; cursor:pointer; }
  .character-row input { width:15px; height:15px; margin:0; flex:none; accent-color:#9abb9f; }
  .character-row:has(input:disabled) { opacity:.55; cursor:default; }
  .widget-preferences .interval-row { padding:5px 0; font-size:11px; display:flex; align-items:center; justify-content:space-between; }
  select { max-width:145px; background:#252f28; color:#d5e1d8; padding:6px; border:1px solid #3b463e; border-radius:7px; font-size:10px; }
  .custom-interval { display:flex; align-items:center; gap:6px; color:#92a096; font-size:10px; margin:5px 0; }
  .widget-preferences .custom-interval input { width:64px; height:28px; border:1px solid #3b463e; border-radius:7px; padding:3px 5px; background:#172019; color:#d5e1d8; font-size:11px; }
  .custom-interval button { margin-left:auto; border:0; border-radius:7px; padding:7px 9px; background:#334638; color:#dfebe2; font-size:10px; }
  .preference-error { color:#dfb499; font-size:10px; line-height:1.5; margin:6px 0; }
</style>
