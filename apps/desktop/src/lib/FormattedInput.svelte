<script lang="ts">
  import { onMount } from 'svelte';
  import type { Editor } from '@tiptap/core';
  import { registerRichEditor } from './rich-editors';
  export let value = '';
  export let label: string;
  export let placeholder = '';
  export let disabled = false;
  export let maxLength = 10000;
  let host: HTMLDivElement;
  let editor: Editor | undefined;
  let emitted = value;
  let empty = !value.trim();
  let loadError = false;
  $: if (editor && value !== emitted) {
    emitted = value;
    editor.commands.setContent(value,{contentType:'markdown',emitUpdate:false});
    empty = editor.isEmpty;
  }
  $: if (editor) editor.setEditable(!disabled,false);
  onMount(() => {
    let disposed = false;
    let unregister: (()=>void) | undefined;
    void (async () => {
      try {
        const [{Editor,Extension},{Plugin},{markdownExtensions}] = await Promise.all([import('@tiptap/core'),import('@tiptap/pm/state'),import('./rich-text')]);
        if (disposed) return;
        const limit = Extension.create({name:'inputLength',addProseMirrorPlugins:()=>[new Plugin({filterTransaction:(transaction,state)=>!transaction.docChanged || transaction.doc.textContent.length <= maxLength || transaction.doc.textContent.length < state.doc.textContent.length})]});
        editor = new Editor({element:host,extensions:[...markdownExtensions(),limit],content:value,contentType:'markdown',editable:!disabled,
          editorProps:{attributes:{'role':'textbox','aria-label':label,'aria-multiline':'true','spellcheck':'true'},transformPastedText:text=>text.slice(0,maxLength)},
          onUpdate:({editor:current})=>{ emitted = current.isEmpty ? '' : current.getMarkdown(); value = emitted; empty = current.isEmpty; },
        });
        unregister = registerRichEditor(editor);
      } catch { if (!disposed) loadError = true; }
    })();
    return () => { disposed = true; unregister?.(); editor?.destroy(); };
  });
</script>

<div class="formatted-input" class:is-disabled={disabled} class:is-empty={empty && !loadError} data-placeholder={placeholder} aria-busy={!editor && !loadError} bind:this={host}>{#if loadError}<span role="alert">Не удалось открыть редактор. Открой вкладку заново.</span>{/if}</div>

<style>
  .formatted-input { position:relative; display:block; flex:none; min-width:0; min-height:65px; max-height:140px; overflow:auto; padding:9px 10px; border:1px solid #393939; border-radius:10px; background:#161616; color:#ddd; font-size:11px; line-height:1.6; scrollbar-width:thin; }
  .formatted-input:focus-within { border-color:#89734b; }
  .formatted-input.is-empty::before { position:absolute; left:10px; top:9px; color:#686868; content:attr(data-placeholder); pointer-events:none; }
  .formatted-input.is-disabled { opacity:.55; }
  .formatted-input :global(.tiptap) { outline:none; min-height:45px; overflow-wrap:anywhere; white-space:pre-wrap; }
  .formatted-input :global(p) { margin:0 0 4px; }
  .formatted-input :global(p:last-child) { margin-bottom:0; }
  .formatted-input :global(mark) { background:#6c5524; color:inherit; border-radius:2px; padding:0 1px; }
  .formatted-input :global(ul),.formatted-input :global(ol) { margin:4px 0; padding-left:19px; }
  .formatted-input :global(ul[data-type="taskList"]) { list-style:none; padding-left:0; }
  .formatted-input :global(li[data-type="taskItem"]) { display:flex; gap:6px; }
  .formatted-input :global(li[data-type="taskItem"] > div) { min-width:0; flex:1; }
</style>
