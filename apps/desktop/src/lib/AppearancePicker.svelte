<script lang="ts">
  import { Check } from 'lucide-svelte';
  import capriMask from '../assets/capri-mask.svg';
  import type { IslandAppearance } from './appearance';
  export let value: IslandAppearance = 'island';
  export let portraitName = 'Капри';
  export let change: (value: IslandAppearance) => void;
</script>

<fieldset class="appearance-picker">
  <legend>Оформление</legend>
  <div class="appearance-options">
    <label class="appearance-choice" class:chosen={value === 'island'}>
      <input type="radio" name="island-appearance" value="island" checked={value === 'island'} on:change={() => change('island')}/>
      <span class="appearance-sample classic-sample" aria-hidden="true"><span class="sample-island"><b>16:41</b><i></i><span>3 дела</span></span></span>
      <span class="appearance-caption">Островок <span class="appearance-check">{#if value === 'island'}<Check size={11}/>{/if}</span></span>
    </label>
    <label class="appearance-choice" class:chosen={value === 'portrait'}>
      <input type="radio" name="island-appearance" value="portrait" checked={value === 'portrait'} on:change={() => change('portrait')}/>
      <span class="appearance-sample portrait-sample" aria-hidden="true">
        <img src={capriMask} width="102" height="39" alt=""/>
      </span>
      <span class="appearance-caption">{portraitName} <span class="appearance-check">{#if value === 'portrait'}<Check size={11}/>{/if}</span></span>
    </label>
  </div>
</fieldset>

<style>
  .appearance-picker { border:0; padding:0; margin:13px 0 3px; min-width:0; }
  legend { padding:0 3px; margin-bottom:9px; font-size:10px; color:#a5a19a; }
  .appearance-options { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
  .appearance-choice { position:relative; display:flex; flex-direction:column; align-items:stretch; justify-content:start; gap:4px; min-width:0; padding:5px 7px 9px; border:1px solid #343330; border-radius:12px; background:#151514; cursor:pointer; transition:border-color 160ms,background 160ms; }
  .appearance-choice:hover { background:#20201d; border-color:#575044; }
  .appearance-choice.chosen { background:#25221a; border-color:#a78a55; }
  .appearance-choice:focus-within { outline:2px solid #d7b77b; outline-offset:2px; }
  input { position:absolute; opacity:0; width:1px; height:1px; margin:0; pointer-events:none; }
  .appearance-sample { display:grid; place-items:center; width:100%; height:58px; overflow:hidden; }
  .sample-island { display:flex; align-items:center; justify-content:space-between; gap:5px; width:85px; height:24px; padding:0 7px; background:#050505; border-radius:0 0 9px 9px; box-shadow:0 5px 7px #0003; }
  .sample-island b { font-size:9px; font-weight:620; color:#e5e4df; }
  .sample-island i { width:3px; height:9px; border-radius:2px; background:#aa9975; }
  .sample-island > span { color:#9a9790; font-size:7px; white-space:nowrap; }
  .appearance-caption { display:flex; align-items:center; justify-content:space-between; gap:5px; width:100%; color:#c2bfb8; font-size:10px; line-height:14px; }
  .chosen .appearance-caption { color:#e9d5ae; }
  .appearance-check { width:13px; height:13px; display:grid; place-items:center; border-radius:50%; flex:none; color:#1a1711; }
  .chosen .appearance-check { background:#d3b47b; }
  @media (prefers-reduced-motion:reduce) { .appearance-choice {transition:none} }
</style>
