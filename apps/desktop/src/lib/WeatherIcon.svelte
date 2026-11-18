<script lang="ts">
  import { Sun, Moon, CloudSun, CloudMoon, Cloud, CloudFog, CloudDrizzle, CloudRain, CloudSnow, CloudLightning } from 'lucide-svelte';
  export let code: number;
  export let isDay = true;
  export let size = 18;
  export let colored = false;
  $: snow = [71,73,75,77,85,86].includes(code);
  $: wet = [51,53,55,56,57,61,63,65,66,67,80,81,82].includes(code);
  $: icon = code === 0 ? (isDay ? Sun : Moon)
    : [1, 2].includes(code) ? (isDay ? CloudSun : CloudMoon)
    : [45, 48].includes(code) ? CloudFog
    : [51, 53, 55].includes(code) ? CloudDrizzle
    : [71, 73, 75, 77, 85, 86].includes(code) ? CloudSnow
    : [56, 57, 61, 63, 65, 66, 67, 80, 81, 82].includes(code) ? CloudRain
    : [95, 96, 97, 99].includes(code) ? CloudLightning : Cloud;
</script>
{#if colored}
  <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
    {#if code <= 2}
      {#if isDay}<g stroke="#ffcf65" stroke-width="3" stroke-linecap="round"><path d="M24 3v5m0 32v5M3 24h5m32 0h5M9 9l4 4m22 22 4 4M9 39l4-4m22-22 4-4"/><circle cx="24" cy="24" r="11" fill="#ffcf65" stroke="none"/></g>{:else}<path d="M33 5a17 17 0 1 0 12 25A17 17 0 0 1 33 5" fill="#dce4ff"/>{/if}
    {/if}
    {#if code > 0}<path d="M17 45C4 45 4 28 16 27c1-17 25-19 29-3 17-2 23 21 5 21Z" fill="#d6dfed"/>{/if}
    {#if wet}<g stroke="#8fc9f0" stroke-width="3.5" stroke-linecap="round"><path d="m20 50-3 7m15-7-3 7m15-7-3 7"/></g>{/if}
    {#if snow}<g fill="#cdeeff"><circle cx="18" cy="54" r="2.3"/><circle cx="31" cy="57" r="2.3"/><circle cx="44" cy="53" r="2.3"/></g>{/if}
    {#if code >= 95}<path d="m32 40-9 14h9l-4 9 15-17h-10l5-6Z" fill="#ffd46c"/>{/if}
    {#if [45,48].includes(code)}<path d="M12 51h40M16 58h32" stroke="#aebed0" stroke-width="3" stroke-linecap="round"/>{/if}
  </svg>
{:else}<svelte:component this={icon} {size} strokeWidth={1.6} aria-hidden="true"/>{/if}
