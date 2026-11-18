<script lang="ts">
  import { onMount } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { listen, type UnlistenFn } from '@tauri-apps/api/event';
  import { Clipboard, Search, Pin, Trash2, Pause, Play, ArrowUpLeft, Type, Image as ImageIcon, File, Files } from 'lucide-svelte';
  import type { ClipboardEntry, ClipboardHistory } from '../types';
  export let paste: (id: number) => Promise<void>;
  let entries: ClipboardEntry[] = [];
  let search = '';
  let pinnedOnly = false;
  let enabled = false;
  let loading = true;
  let error = '';
  let busy = false;
  let deleted: number | null = null;
  let request = 0;
  let disposed = false;
  let searchTimer: ReturnType<typeof setTimeout>;
  async function refresh() {
    const version = ++request;
    try {
      const result = await invoke<ClipboardHistory>('list_clipboard', { search, pinnedOnly });
      if (disposed || version !== request) return;
      entries = result.entries; enabled = result.enabled; error = '';
    } catch (err) { if (!disposed && version === request) error = String(err); }
    finally { if (!disposed && version === request) loading = false; }
  }
  function searchChanged() { clearTimeout(searchTimer); searchTimer = setTimeout(refresh, 140); }
  function scope(pinned: boolean) {
    if (pinnedOnly === pinned) return;
    clearTimeout(searchTimer); pinnedOnly = pinned; search = ''; deleted = null;
    entries = []; loading = true; void refresh();
  }
  async function action(run: () => Promise<unknown>) {
    if (busy) return;
    busy = true; error = '';
    try { await run(); await refresh(); }
    catch (err) { error = String(err); }
    finally { busy = false; }
  }
  onMount(() => {
    let stop: UnlistenFn | undefined;
    void refresh();
    void listen('clipboard-changed', () => { void refresh(); }).then(unlisten => { if (disposed) unlisten(); else stop = unlisten; });
    const polling = setInterval(refresh, 3000);
    return () => { disposed = true; request++; stop?.(); clearInterval(polling); clearTimeout(searchTimer); };
  });
</script>

<section class="clipboard-panel utility-panel" aria-label="История буфера обмена">
  <div class="utility-heading"><div><h1>Буфер обмена <span>{entries.length}</span></h1></div><button class="capture-toggle" aria-label={enabled ? 'Приостановить запись буфера' : 'Возобновить запись буфера'} aria-pressed={!enabled} disabled={busy} on:click={() => action(() => invoke('set_clipboard_enabled', { enabled: !enabled }))}>{#if enabled}<Pause size={13}/><span>Запись идёт</span>{:else}<Play size={13}/><span>На паузе</span>{/if}</button></div>
  <div class="clipboard-scopes" role="group" aria-label="Раздел истории буфера"><button class:active={!pinnedOnly} aria-pressed={!pinnedOnly} on:click={() => scope(false)}>Последние 9</button><button class:active={pinnedOnly} aria-pressed={pinnedOnly} on:click={() => scope(true)}><Pin size={11}/>Закреплённые</button></div>
  <label class="clipboard-search"><Search size={16}/><input aria-label="Поиск в буфере обмена" placeholder={pinnedOnly ? 'Поиск в закреплённых…' : 'Поиск среди последних 9…'} bind:value={search} on:input={searchChanged}/><span>Только на этом компьютере</span></label>
  {#if !enabled && !loading}<p class="clipboard-privacy">Запись выключена. При включении текст, картинки и пути файлов сохраняются на этом компьютере. Не копируй секреты, пока запись включена.</p>{/if}
  {#if error}<p class="utility-error" role="alert">{error}</p>{/if}
  <div class="clipboard-grid" class:recent={!pinnedOnly} aria-busy={loading || busy}>
    {#each entries as entry (entry.id)}
      <article class="clipboard-card" class:pinned={entry.pinned}>
        <div class="clip-meta"><span>{#if entry.kind === 'image'}<ImageIcon size={12}/> Картинка{:else if entry.kind === 'files'}<Files size={12}/> {entry.files?.length === 1 ? 'Файл' : `Файлы · ${entry.files?.length || 0}`}{:else}<Type size={12}/> Текст{/if}</span><div><button class="clip-pin" aria-label={entry.pinned ? 'Открепить запись' : 'Закрепить запись'} aria-pressed={entry.pinned} disabled={busy} on:click={() => action(() => invoke('pin_clipboard', { id: entry.id, pinned: !entry.pinned }))}><Pin size={13}/></button><button aria-label="Удалить запись" disabled={busy} on:click={() => deleted = entry.id}><Trash2 size={13}/></button></div></div>
        <button class="clip-content" class:clip-files={entry.kind === 'files'} aria-label={entry.kind === 'image' ? `Вставить картинку ${entry.width} на ${entry.height}` : entry.kind === 'files' ? `Вставить файлы: ${entry.files?.map(file=>file.name).join(', ')}` : `Вставить текст: ${entry.text?.slice(0, 80)}`} disabled={busy} on:click={() => action(() => paste(entry.id))}>
          {#if entry.kind === 'files'}
            {#if entry.thumbnail}<img src={entry.thumbnail} alt="Превью скопированного фото"/>{:else}<span class="file-symbol"><File size={26}/><small>{entry.files?.[0]?.name.split('.').pop()?.toUpperCase()}</small></span>{/if}
            <span class="file-names" title={`Для вставки исходные файлы должны оставаться на месте.\n${entry.files?.map(file=>file.path).join('\n')}`}>{entry.files?.map(file=>file.name).join(', ')}</span>
          {:else if entry.kind === 'image' && entry.thumbnail}<img src={entry.thumbnail} alt={`Скопированная картинка, ${entry.width} × ${entry.height}`}/>{:else}<span class="clip-text">{entry.text}</span>{/if}
          <span class="clip-bottom"><small>{entry.kind === 'image' ? `${entry.width} × ${entry.height}` : entry.kind === 'files' ? 'Файлы на диске' : new Date(entry.captured_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</small><span>Вставить <ArrowUpLeft size={12}/></span></span>
        </button>
        {#if deleted === entry.id}<div class="clip-delete"><span>Удалить запись?</span><button on:click={() => deleted = null}>Отмена</button><button disabled={busy} on:click={() => action(async () => { await invoke('delete_clipboard', { id: entry.id }); deleted = null; })}>Удалить</button></div>{/if}
      </article>
    {:else}
      <div class="clipboard-empty"><Clipboard size={27} strokeWidth={1.2}/><b>{search ? 'Ничего не нашлось' : loading ? 'Загружаю историю…' : pinnedOnly ? 'Нет закреплённых записей' : enabled ? 'Скопируй что-нибудь' : 'История на паузе'}</b><span>{search ? 'Попробуй другое слово' : pinnedOnly ? 'Нажми на булавку у нужной записи' : 'Текст, картинки и файлы появятся после копирования'}</span></div>
    {/each}
  </div>
  <div class="clipboard-foot"><span><ArrowUpLeft size={12}/> Клик — вставить в предыдущее окно</span><span><Pin size={11}/> Закреплённое остаётся в истории</span></div>
</section>
<style>
  .clipboard-panel {padding:14px}
  .clipboard-privacy {margin:0 0 6px;color:#909b93;font-size:9px;line-height:1.4;flex:none}
  .capture-toggle {padding:6px 9px}
  .clipboard-scopes {display:flex;gap:5px;margin-top:8px;flex:none}
  .clipboard-scopes button {display:flex;align-items:center;gap:5px;border:0;border-radius:7px;padding:4px 7px;font-size:10px;background:#1c1c1c;color:#929292}
  .clipboard-scopes button.active {background:#303030;color:#e5e5e5}
  .clipboard-search {margin:6px 0;padding-bottom:6px}
  .clipboard-foot {padding-top:8px;font-size:8px}
  .clipboard-grid.recent {grid-template-rows:repeat(3,minmax(0,1fr));gap:7px}
  .recent .clip-meta {height:18px;padding:0 6px 0 8px}
  .recent .clip-meta button {width:20px;height:18px}
  .recent .clip-content {height:calc(100% - 18px);min-height:0;padding:3px 7px 4px;gap:2px}
  .recent .clip-text {font-size:10px;line-height:12px;-webkit-line-clamp:2;line-clamp:2;flex:1;min-height:0}
  .recent .clip-content > img {height:calc(100% - 15px);min-height:0;flex:1}
  .recent .clip-files > img,.recent .file-symbol {height:22px;min-height:0;flex:1}
  .recent .file-symbol :global(svg) {width:14px;height:14px}
  .recent .file-names {font-size:9px;line-height:10px;flex:none}
  .recent .clip-bottom {flex:none;margin-top:auto}
  .recent .clip-bottom :is(small,span) {font-size:8px;line-height:10px}
  .recent .clipboard-empty {grid-row:1/-1;min-height:0}
  .clip-files { gap:6px; }
  .clip-files > img { height:68px; }
  .file-symbol { height:68px; display:flex; align-items:center; justify-content:center; gap:9px; color:#a6bfcf; width:100%; background:#202b33; border-radius:7px; }
  .file-symbol small { font-size:11px; letter-spacing:.6px; }
  .file-names { width:100%; font-size:10px; line-height:1.4; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:#d4dbe0; }
</style>
