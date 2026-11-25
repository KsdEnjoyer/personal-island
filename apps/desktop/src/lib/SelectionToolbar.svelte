<script lang="ts">
  import { onMount, tick } from 'svelte';
  import type { Editor } from '@tiptap/core';
  import { Bold, Italic, Underline, Strikethrough, Highlighter, RemoveFormatting } from 'lucide-svelte';
  import { editorSelection, selectedRichEditor } from './rich-editors';
  type Format = 'bold' | 'italic' | 'underline' | 'strike' | 'highlight' | 'clear';
  const tools = [
    {id:'bold',label:'Жирный',icon:Bold}, {id:'italic',label:'Курсив',icon:Italic},
    {id:'underline',label:'Подчёркнутый',icon:Underline}, {id:'strike',label:'Зачёркнутый',icon:Strikethrough},
    {id:'highlight',label:'Выделить цветом',icon:Highlighter}, {id:'clear',label:'Убрать форматирование',icon:RemoveFormatting},
  ] as const;
  let editor: Editor | undefined;
  let toolbar: HTMLDivElement | undefined;
  let visible = false;
  let x = 0;
  let y = 0;
  let active: Partial<Record<Format,boolean>> = {};
  let selectionKey = '';
  let dismissed = '';
  let frame = 0;
  function update() {
    frame = 0;
    const selection = window.getSelection();
    const target = selectedRichEditor(selection?.anchorNode ?? null);
    if (!target || target.isDestroyed || !target.isEditable || !selection?.rangeCount || selection.isCollapsed || target.state.selection.empty || !selection.toString().trim()) { visible = false; editor = undefined; return; }
    if (selectedRichEditor(selection.focusNode) !== target) { visible = false; return; }
    const root = target.view.dom;
    if (root.closest('[inert],[aria-hidden="true"]') || (!root.contains(document.activeElement) && !toolbar?.contains(document.activeElement))) { visible = false; return; }
    const bounds = (root.closest('.note-editor,.formatted-input') ?? root).getBoundingClientRect();
    const rects = [...selection.getRangeAt(0).getClientRects()].filter(r => r.width && r.bottom > Math.max(0,bounds.top) && r.top < Math.min(innerHeight,bounds.bottom));
    if (!rects.length) { visible = false; return; }
    const {from,to} = target.state.selection;
    const key = `${from}:${to}:${selection.toString()}`;
    if (editor !== target || selectionKey !== key) dismissed = '';
    editor = target; selectionKey = key;
    if (dismissed === key) { visible = false; return; }
    active = Object.fromEntries(tools.map(tool => [tool.id,tool.id !== 'clear' && target.isActive(tool.id)]));
    const first = rects[0];
    const anchor = rects.filter(r=>Math.abs(r.top-first.top)<2).reduce((a,b)=>b.width<a.width ? b : a,first);
    const width = Math.min(230,innerWidth-16);
    x = Math.max(8,Math.min(innerWidth-width-8,(anchor.left+anchor.right-width)/2));
    y = anchor.top >= 56 ? anchor.top-46 : Math.min(innerHeight-46,rects[rects.length-1].bottom+8);
    visible = true;
  }
  function schedule() { if (!frame) frame = requestAnimationFrame(update); }
  function command(name: Format) {
    if (!editor || editor.isDestroyed) return;
    const chain = editor.chain().focus();
    if (name === 'bold') chain.toggleBold().run();
    else if (name === 'italic') chain.toggleItalic().run();
    else if (name === 'underline') chain.toggleUnderline().run();
    else if (name === 'strike') chain.toggleStrike().run();
    else if (name === 'highlight') chain.toggleHighlight({color:'#6c5524'}).run();
    else chain.unsetAllMarks().run();
    schedule();
  }
  function keys(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      dismissed = selectionKey; visible = false; event.preventDefault(); event.stopPropagation();
      editor?.commands.focus();
    } else if (['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
      const buttons = [...(toolbar?.querySelectorAll<HTMLButtonElement>('button') ?? [])];
      const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length-1 : (at+(event.key === 'ArrowRight' ? 1 : -1)+buttons.length)%buttons.length;
      buttons[next]?.focus(); event.preventDefault();
    }
  }
  onMount(() => {
    const blur = () => { visible = false; };
    const keyboard = (event: KeyboardEvent) => {
      if (event.altKey && event.key === 'F10' && visible) { event.preventDefault(); void tick().then(()=>toolbar?.querySelector('button')?.focus()); }
    };
    document.addEventListener('selectionchange',schedule);
    document.addEventListener('pointerup',schedule);
    document.addEventListener('keyup',schedule);
    document.addEventListener('scroll',schedule,true);
    document.addEventListener('keydown',keyboard);
    window.addEventListener('resize',schedule);
    window.addEventListener('blur',blur);
    document.addEventListener('focusin',schedule);
    const visibility = new MutationObserver(schedule);
    visibility.observe(document.body,{subtree:true,attributes:true,attributeFilter:['inert','aria-hidden']});
    editorSelection.addEventListener('change',schedule);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('selectionchange',schedule);
      document.removeEventListener('pointerup',schedule);
      document.removeEventListener('keyup',schedule);
      document.removeEventListener('scroll',schedule,true);
      document.removeEventListener('keydown',keyboard);
      window.removeEventListener('resize',schedule);
      window.removeEventListener('blur',blur);
      document.removeEventListener('focusin',schedule);
      visibility.disconnect();
      editorSelection.removeEventListener('change',schedule);
    };
  });
</script>

{#if visible}
  <div bind:this={toolbar} class="selection-toolbar" role="toolbar" tabindex="-1" aria-label="Форматирование выделенного текста" style:left={`${x}px`} style:top={`${y}px`} on:mousedown|preventDefault on:keydown={keys}>
    {#each tools as tool}
      <button type="button" class:active={active[tool.id]} class:clear={tool.id === 'clear'} aria-label={tool.label} aria-pressed={!!active[tool.id]} title={tool.label} on:click={() => command(tool.id)}><svelte:component this={tool.icon} size={15} strokeWidth={1.7}/></button>
    {/each}
    <span class="selection-tip" aria-hidden="true"></span>
  </div>
{/if}

<style>
  .selection-toolbar { position:fixed; z-index:30; display:flex; align-items:center; gap:3px; box-sizing:border-box; width:230px; max-width:calc(100vw - 16px); height:38px; padding:4px 6px; border:1px solid #3b3b3b; border-radius:12px; background:#202020; box-shadow:0 5px 18px #0008; animation:selection-in 130ms ease-out; }
  button { display:grid; place-items:center; flex:1; min-width:0; height:28px; padding:0; border:0; border-radius:7px; background:transparent; color:#a7a7a7; cursor:pointer; }
  button:hover,button.active { color:#f1d39b; background:#3b3222; }
  button.clear { border-left:1px solid #3c3c3c; border-radius:0 7px 7px 0; margin-left:3px; }
  button:focus-visible { outline:1px solid #d6b476; outline-offset:-1px; }
  .selection-tip { position:absolute; bottom:-4px; left:calc(50% - 3px); width:6px; height:6px; transform:rotate(45deg); background:#202020; border-right:1px solid #3b3b3b; border-bottom:1px solid #3b3b3b; }
  @keyframes selection-in { from {opacity:0;transform:translateY(3px)} to {opacity:1;transform:translateY(0)} }
  @media(prefers-reduced-motion:reduce) { .selection-toolbar { animation:none; } }
</style>
