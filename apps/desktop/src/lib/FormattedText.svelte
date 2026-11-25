<script lang="ts">
  import { onMount } from 'svelte';
  export let value: string;
  let render: typeof import('./rich-text')['richText'] | undefined;
  $: html = render?.(value).html;
  onMount(() => {
    let disposed = false;
    void import('./rich-text').then(module=>{ if (!disposed) render = module.richText; }).catch(()=>{});
    return () => { disposed = true; };
  });
</script>

<div class="formatted-text">{#if html}{@html html}{:else}{value}{/if}</div>

<style>
  .formatted-text { overflow-wrap:anywhere; }
  .formatted-text :global(p) { margin:0; }
  .formatted-text :global(mark) { background:#6c5524; color:inherit; border-radius:2px; }
  .formatted-text :global(ul),.formatted-text :global(ol) { margin:2px 0; padding-left:17px; }
  .formatted-text :global(ul[data-type="taskList"]) { list-style:none; }
  .formatted-text :global(input) { pointer-events:none; }
</style>
