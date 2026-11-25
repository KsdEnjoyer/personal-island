<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { Editor } from '@tiptap/core';
  import StarterKit from '@tiptap/starter-kit';
  import Highlight from '@tiptap/extension-highlight';
  import TaskList from '@tiptap/extension-task-list';
  import TaskItem from '@tiptap/extension-task-item';
  import { registerRichEditor } from './rich-editors';
  import { Bold, Italic, Strikethrough, Highlighter, List, ListOrdered, ListChecks, Plus, Check, BellPlus, Copy, Trash2, X, LoaderCircle } from 'lucide-svelte';
  export let refresh: () => Promise<void>;
  type Category = 'notes' | 'ideas' | 'shopping';
  type Note = { id:number; category:Category; title:string; document:string; revision:number; updated_at:string };
  const sections: { id:Category; label:string }[] = [{id:'notes',label:'Заметки'},{id:'ideas',label:'Идеи'},{id:'shopping',label:'Покупки'}];
  const blank = JSON.stringify({type:'doc',content:[{type:'paragraph'}]});
  let category:Category = 'notes';
  let records:Note[] = [];
  let id:number | null = null;
  let revision = 0;
  let title = '';
  let document = blank;
  let host:HTMLDivElement;
  let editor:Editor | undefined;
  let unregisterEditor: (() => void) | undefined;
  let loading = true;
  let loadFailed = false;
  let switching = false;
  let dirty = false;
  let saving:Promise<boolean> | undefined;
  let saveTimer:ReturnType<typeof setTimeout>;
  let error = '';
  let message = '';
  let deleting = false;
  let reminderOpen = false;
  let reminderTitle = '';
  let reminderDate = '';
  let reminderBusy = false;
  let disposed = false;
  let format = { bold:false, italic:false, strike:false, highlight:false, bulletList:false, orderedList:false, taskList:false };
  $: currentNotes = records.filter(note=>note.category === category);
  const emptyFor = (section:Category) => section === 'shopping'
    ? JSON.stringify({type:'doc',content:[{type:'taskList',content:[{type:'taskItem',attrs:{checked:false},content:[{type:'paragraph'}]}]}]}) : blank;
  function updateFormat() {
    if (!editor) return;
    format = {bold:editor.isActive('bold'),italic:editor.isActive('italic'),strike:editor.isActive('strike'),highlight:editor.isActive('highlight'),bulletList:editor.isActive('bulletList'),orderedList:editor.isActive('orderedList'),taskList:editor.isActive('taskList')};
  }
  function changed() {
    dirty = true; error = ''; message = '';
    clearTimeout(saveTimer); saveTimer = setTimeout(() => void flush(), 400);
  }
  export async function flush():Promise<boolean> {
    clearTimeout(saveTimer);
    if (saving) return saving;
    if (!dirty) return true;
    saving = (async () => {
      while (dirty) {
        const snapshot = { category, title, document };
        dirty = false;
        try {
          const saved = await invoke<Note>('save_note', { id, revision, note:snapshot });
          error = '';
          id = saved.id; revision = saved.revision;
          records = [saved,...records.filter(note=>note.id !== saved.id)];
        } catch (err) { dirty = true; error = String(err); return false; }
      }
      return true;
    })();
    try { return await saving; } finally { saving = undefined; }
  }
  function load(note?:Note) {
    id = note?.id ?? null; revision = note?.revision ?? 0; title = note?.title ?? '';
    document = note?.document ?? emptyFor(category); dirty = false; message = ''; error = '';
    editor?.commands.setContent(JSON.parse(document), {emitUpdate:false});
    updateFormat();
  }
  async function readNotes() {
    loading = true; loadFailed = false;
    try {
      const saved = await invoke<Note[]>('list_notes');
      if (!disposed) { records = saved; load(records.find(note=>note.category === category)); }
    } catch (err) { if (!disposed) { error = String(err); loadFailed = true; } }
    finally { if (!disposed) { loading = false; editor?.setEditable(!loadFailed, false); } }
  }
  async function saveCopy() {
    if (loading || switching || saving) return;
    switching = true; editor?.setEditable(false, false);
    try {
      const saved = await invoke<Note>('save_note',{id:null,revision:0,note:{category,title,document}});
      id = saved.id; revision = saved.revision; records = [saved,...records];
      dirty = false; error = ''; message = 'Сохранена отдельная копия';
    } catch (err) { error = String(err); }
    finally { switching = false; editor?.setEditable(true, false); }
  }
  async function choose(section:Category, noteId?:number, create = false) {
    if (switching || loading || loadFailed) return;
    switching = true;
    editor?.setEditable(false, false);
    if (await flush()) {
      category = section;
      load(create ? undefined : records.find(note=>note.category === section && (noteId === undefined || note.id === noteId)));
      deleting = false; reminderOpen = false;
      if (create) { dirty = true; await flush(); }
    }
    editor?.setEditable(true, false); switching = false;
  }
  function command(name:keyof typeof format) {
    if (!editor || switching || loading) return;
    const chain = editor.chain().focus();
    if (name === 'bold') chain.toggleBold().run();
    else if (name === 'italic') chain.toggleItalic().run();
    else if (name === 'strike') chain.toggleStrike().run();
    else if (name === 'highlight') chain.toggleHighlight({color:'#6c5524'}).run();
    else if (name === 'bulletList') chain.toggleBulletList().run();
    else if (name === 'orderedList') chain.toggleOrderedList().run();
    else chain.toggleTaskList().run();
  }
  async function copy() {
    if (!editor) return;
    try {
      const text = `${title}${title ? '\n' : ''}${editor.getText()}`;
      const heading = window.document.createElement('h3'); heading.textContent = title;
      if (typeof ClipboardItem !== 'undefined' && navigator.clipboard.write) {
        await navigator.clipboard.write([new ClipboardItem({'text/plain':new Blob([text],{type:'text/plain'}),'text/html':new Blob([heading.outerHTML+editor.getHTML()],{type:'text/html'})})]);
      } else await navigator.clipboard.writeText(text);
      message = 'Заметка скопирована';
    } catch (err) { error = `Не удалось скопировать: ${String(err)}`; }
  }
  async function remove() {
    if (switching || !await flush()) return;
    switching = true;
    try {
      if (id !== null) await invoke('delete_note',{id,revision});
      records = records.filter(note=>note.id !== id); deleting = false;
      load(records.find(note=>note.category === category));
    } catch (err) { error = String(err); }
    finally { switching = false; }
  }
  function openReminder() {
    if (!editor) return;
    const {from,to} = editor.state.selection;
    reminderTitle = (editor.state.doc.textBetween(from,to,' ') || title || editor.getText().split('\n').find(line=>line.trim()) || '').slice(0,200);
    const soon = new Date(Date.now()+30*60000);
    reminderDate = new Date(soon.getTime()-soon.getTimezoneOffset()*60000).toISOString().slice(0,16);
    reminderOpen = true; error = '';
  }
  async function remind() {
    if (reminderBusy || !reminderTitle.trim()) return;
    const date = new Date(reminderDate);
    if (!Number.isFinite(date.getTime()) || date <= new Date()) { error = 'Выбери время в будущем'; return; }
    if (!await flush()) return;
    reminderBusy = true;
    try {
      await invoke('create_task',{task:{title:reminderTitle.trim(),notes:`Из заметки: ${title || 'Без названия'}`,due_at:date.toISOString(),reminder_at:date.toISOString(),priority:0}});
      reminderOpen = false; message = 'Напоминание добавлено'; await refresh();
    } catch (err) { error = String(err); }
    finally { reminderBusy = false; }
  }
  onMount(() => {
    editor = new Editor({element:host,extensions:[StarterKit.configure({link:false,trailingNode:false}),Highlight.configure({multicolor:true}),TaskList,TaskItem.configure({nested:true})],content:JSON.parse(blank),editable:false,
      editorProps:{attributes:{'aria-label':'Текст заметки','role':'textbox','aria-multiline':'true','spellcheck':'true'}},
      onUpdate:({editor:current}) => { document = JSON.stringify(current.getJSON()); changed(); },onTransaction:updateFormat});
    unregisterEditor = registerRichEditor(editor);
    void readNotes();
  });
  onDestroy(() => { disposed = true; clearTimeout(saveTimer); void flush(); unregisterEditor?.(); editor?.destroy(); });
</script>
<svelte:window on:keydown={event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); void flush(); } }}/>

<section class="notes-panel" aria-label="Заметки, идеи и покупки" aria-busy={loading || switching}>
  <div class="note-sections" role="tablist" aria-label="Разделы записей">
    {#each sections as section}<button role="tab" aria-selected={category === section.id} class:active={category === section.id} disabled={loading || switching || loadFailed} on:click={() => choose(section.id)}>{section.label}</button>{/each}
    <button class="new-note" aria-label="Новая запись" title="Новая запись в этом разделе" disabled={loading || switching || loadFailed} on:click={() => choose(category,undefined,true)}><Plus size={14}/></button>
    <select aria-label="Открыть запись" value={id ?? ''} disabled={loading || switching || !currentNotes.length} on:change={event => choose(category,Number(event.currentTarget.value))}>
      {#if id === null}<option value="">Новая запись</option>{/if}
      {#each currentNotes as note}<option value={note.id}>{note.title || 'Без названия'}</option>{/each}
    </select>
  </div>
  <div class="note-paper">
    <input class="note-title" aria-label="Название записи" maxlength="200" placeholder={category === 'shopping' ? 'Список покупок' : category === 'ideas' ? 'Новая идея' : 'Название заметки'} bind:value={title} on:input={changed} disabled={loading || switching || loadFailed}/>
    <div class="note-editor" bind:this={host}></div>
    {#if loading}<span class="note-loading">Открываю записи…</span>{/if}
    {#if !title && document === blank && !loading}<span class="note-placeholder">Текст заметки…</span>{/if}
    {#if deleting}<div class="note-dialog" role="dialog" aria-label="Удаление записи"><b>Удалить эту запись?</b><span>Задачи и напоминания сохранятся.</span><div><button on:click={() => deleting = false}>Отмена</button><button class="danger" on:click={remove}>Удалить запись</button></div></div>{/if}
    {#if reminderOpen}<form class="note-dialog reminder-dialog" aria-label="Напоминание из заметки" on:submit|preventDefault={remind}><b>Напомнить о записи<button type="button" aria-label="Закрыть напоминание" on:click={() => reminderOpen = false}><X size={14}/></button></b><input aria-label="Текст напоминания из заметки" maxlength="200" bind:value={reminderTitle}/><input type="datetime-local" aria-label="Время напоминания из заметки" bind:value={reminderDate}/><button class="remind-submit" disabled={reminderBusy || !reminderTitle.trim()}>Создать напоминание</button></form>{/if}
  </div>
  {#if error}<div class="note-error" role="alert">{error}<button on:click={() => loadFailed ? readNotes() : flush()}>{loadFailed ? 'Открыть повторно' : 'Повторить сохранение'}</button>{#if !loadFailed}<button disabled={switching || !!saving} on:click={saveCopy}>Сохранить копию</button>{/if}</div>{:else if message}<div class="note-message" role="status">{message}</div>{/if}
  <div class="note-toolbar" role="toolbar" tabindex="-1" aria-label="Форматирование заметки" on:mousedown|preventDefault>
    {#each [{id:'bold',label:'Жирный',icon:Bold},{id:'italic',label:'Курсив',icon:Italic},{id:'strike',label:'Зачёркнутый',icon:Strikethrough},{id:'highlight',label:'Выделить цветом',icon:Highlighter},{id:'bulletList',label:'Маркированный список',icon:List},{id:'orderedList',label:'Нумерованный список',icon:ListOrdered},{id:'taskList',label:'Чек-лист',icon:ListChecks}] as tool}
      <button class:active={format[tool.id as keyof typeof format]} aria-label={tool.label} title={tool.label} aria-pressed={format[tool.id as keyof typeof format]} disabled={loading || switching || loadFailed} on:click={() => command(tool.id as keyof typeof format)}><svelte:component this={tool.icon} size={14}/></button>
    {/each}
    <button class="blue-highlight" aria-label="Выделить синим" title="Синее выделение" disabled={loading || switching || loadFailed} on:click={() => editor?.chain().focus().toggleHighlight({color:'#3d5772'}).run()}><i></i></button>
    <span class="toolbar-space"></span>
    <button class="save-state" class:saved={!dirty && !saving} aria-label={dirty || saving ? 'Сохранить запись' : 'Запись сохранена'} title={dirty || saving ? 'Сохранить запись' : 'Сохранено на компьютере'} disabled={loading || switching || loadFailed} on:click={() => flush()}>{#if saving}<LoaderCircle size={14}/>{:else}<Check size={14}/>{/if}</button>
    <button class="note-remind" aria-label="Напомнить о заметке" title="Напомнить о выделенном тексте или записи" disabled={loading || switching || loadFailed} on:click={openReminder}><BellPlus size={14}/><span>Напомнить</span></button>
    <button aria-label="Копировать заметку" title="Копировать с форматированием" disabled={loading || switching || loadFailed} on:click={copy}><Copy size={14}/></button>
    <button aria-label="Удалить заметку" title="Удалить запись" disabled={loading || switching || loadFailed} on:click={() => deleting = true}><Trash2 size={14}/></button>
  </div>
</section>

<style>
  .notes-panel { min-width:0; min-height:0; display:flex; flex-direction:column; gap:6px; }
  .note-sections { display:flex; align-items:center; gap:4px; flex:none; height:25px; }
  .note-sections button { background:#191919; border:0; color:#909090; font-size:10px; font-weight:600; border-radius:14px; padding:5px 9px; white-space:nowrap; }
  .note-sections button.active { background:#34312c; color:#f3eadd; }
  .note-sections .new-note { display:grid; place-items:center; padding:4px; }
  .note-sections select { min-width:0; width:112px; margin-left:auto; border:0; color:#96928b; background:#141414; border-radius:7px; padding:4px; font-size:10px; color-scheme:dark; }
  .note-paper { position:relative; flex:1; min-height:0; background:#101010; border-radius:17px; padding:15px 14px; display:flex; flex-direction:column; overflow:hidden; }
  .note-title { width:100%; flex:none; padding:0 0 7px; font-size:13px; font-weight:650; border:0; background:none; outline:none; color:#e6e4df; }
  .note-title::placeholder { color:#66615b; }
  .note-editor { min-height:0; flex:1; overflow:auto; scrollbar-width:thin; scrollbar-color:#333 transparent; }
  .note-editor :global(.tiptap) { display:flow-root; outline:none; min-height:100%; font-size:12px; line-height:1.65; color:#d5d3ce; overflow-wrap:anywhere; caret-color:#ffb224; }
  .note-editor :global(.tiptap p) { margin:0 0 3px; }
  .note-editor :global(.tiptap h1),.note-editor :global(.tiptap h2),.note-editor :global(.tiptap h3) { font-size:15px; margin:7px 0 4px; }
  .note-editor :global(.tiptap em) { font-style:italic; font-synthesis:style; }
  .note-editor :global(.tiptap strong) { font-weight:700; }
  .note-editor :global(.tiptap mark) { color:#fff0c4; padding:0 2px; border-radius:2px; }
  .note-editor :global(.tiptap ul),.note-editor :global(.tiptap ol) { padding-left:20px; margin:3px 0 7px; }
  .note-editor :global(.tiptap ul[data-type="taskList"]) { list-style:none; padding-left:0; }
  .note-editor :global(.tiptap li[data-checked]) { display:flex; gap:7px; align-items:flex-start; }
  .note-editor :global(.tiptap li[data-checked] > div) { flex:1; min-width:0; }
  .note-editor :global(.tiptap li[data-checked] > label) { display:flex; padding-top:3px; user-select:none; }
  .note-editor :global(.tiptap input[type="checkbox"]) { appearance:none; margin:0; width:14px; height:14px; border:1px solid #666055; border-radius:50%; cursor:pointer; background:transparent; }
  .note-editor :global(.tiptap input[type="checkbox"]:checked) { background:#ffb224; border-color:#ffb224; }
  .note-editor :global(.tiptap input[type="checkbox"]:checked::after) { content:'✓'; color:#382500; font-size:11px; line-height:12px; display:block; text-align:center; font-weight:800; }
  .note-editor :global(.tiptap li[data-checked="true"] > div > p) { color:#68645e; text-decoration:line-through; }
  .note-editor :global(.tiptap blockquote) { border-left:2px solid #8c7652; padding-left:10px; margin:8px 0; color:#aaa; }
  .note-editor :global(.tiptap pre) { white-space:pre-wrap; background:#222; padding:8px; border-radius:5px; }
  .note-loading,.note-placeholder { position:absolute; top:44px; left:15px; font-size:11px; color:#5f5b54; pointer-events:none; }
  .note-toolbar { display:flex; align-items:center; gap:2px; flex:none; height:26px; }
  .note-toolbar button { width:26px; height:25px; display:grid; place-items:center; background:none; color:#85827b; border:0; border-radius:6px; padding:0; }
  .note-toolbar button:hover,.note-toolbar button.active { color:#eee6d7; background:#2e2c28; }
  .note-toolbar .saved { color:#61bf93; }
  .note-toolbar .note-remind { width:auto; display:flex; gap:4px; font-size:9px; padding:0 4px; }
  .toolbar-space { flex:1; min-width:0; }
  .blue-highlight i { width:8px; height:8px; border-radius:2px; background:#6684a3; }
  .note-dialog { position:absolute; inset:auto 10px 12px; display:flex; flex-direction:column; gap:10px; padding:14px; border:1px solid #3e392f; border-radius:12px; background:#23211e; box-shadow:0 6px 24px #0008; font-size:12px; z-index:2; }
  .note-dialog span { color:#a39c90; font-size:11px; }
  .note-dialog > div,.note-dialog b { display:flex; align-items:center; justify-content:space-between; gap:8px; }
  .note-dialog button { border:0; background:#35312a; color:#d8cbb4; border-radius:7px; padding:7px; font-size:11px; }
  .note-dialog .danger { color:#ffb3a6; }
  .note-dialog input { width:100%; min-width:0; background:#161616; color:#ddd; border:1px solid #423e36; border-radius:6px; padding:7px; font-size:11px; color-scheme:dark; }
  .note-error,.note-message { font-size:10px; line-height:1.4; padding:3px 6px; flex:none; max-height:52px; overflow:auto; }
  .note-error { color:#f0b3a0; } .note-message { color:#9bc3ab; }
  .note-error button { color:#efcf94; background:none; border:0; font-size:10px; text-decoration:underline; }
</style>
