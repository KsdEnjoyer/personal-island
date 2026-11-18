<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import { RefreshCw, Wind, Droplets, MapPin, ExternalLink, CloudOff, Umbrella, Sunrise, Sunset } from 'lucide-svelte';
  import WeatherIcon from './WeatherIcon.svelte';
  import { degrees, spbTime, weatherLabel } from './weather';
  import type { WeatherState } from '../types';
  export let weather: WeatherState;
  export let loading = false;
  export let now: Date;
  export let refresh: () => Promise<void>;
  let sourceError = '';
  const dateKey = (time: number) => spbTime(time, { day:'numeric',month:'numeric',year:'numeric' });
  const number = (value: number) => value.toLocaleString('ru-RU', { maximumFractionDigits:1 });
  const direction = (value?: number | null) => value == null ? '' : ['С','СВ','В','ЮВ','Ю','ЮЗ','З','СЗ'][Math.round(value / 45) % 8];
  $: data = weather.data;
  $: tone = !data?.current.is_day ? 'night' : [71,73,75,77,85,86].includes(data.current.weather_code) ? 'snow' : data.current.weather_code >= 51 ? 'rain' : data.current.weather_code <= 1 ? 'sunny' : 'cloudy';
  $: hours = data?.hourly.filter(hour => hour.time >= Math.floor(now.getTime() / 3_600_000) * 3600).slice(0, 8) || [];
  $: minimum = Math.min(...(data?.daily.map(day => day.low) || [0]));
  $: maximum = Math.max(...(data?.daily.map(day => day.high) || [1]));
  $: range = Math.max(1, maximum - minimum);
  $: today = data?.daily.find(day => dateKey(day.time) === dateKey(now.getTime() / 1000));
  async function openSource() { try { await invoke('open_weather_source'); } catch (err) { sourceError = String(err); } }
</script>

<section class="weather-panel weather-board" data-sky={tone} aria-label="Погода в Санкт-Петербурге">
  {#if data}
    <div class="weather-board-grid">
      <section class="weather-city weather-now" class:stale={weather.stale} aria-label="Сейчас в Петербурге">
        <header class="weather-city-heading"><h1><MapPin size={13}/>Санкт-Петербург</h1><button aria-label="Обновить погоду" disabled={loading} on:click={refresh}><RefreshCw size={14} class={loading ? 'spinning' : ''}/></button></header>
        <div class="weather-temperature"><WeatherIcon code={data.current.weather_code} isDay={!!data.current.is_day} size={52} colored/><span>{degrees(data.current.temperature_2m)}</span></div>
        <b class="weather-description">{weatherLabel(data.current.weather_code, !!data.current.is_day)}</b>
        <p class="weather-feels">Ощущается как {degrees(data.current.apparent_temperature)}{#if today} · {degrees(today.low)}…{degrees(today.high)}{/if}</p>
        {#if weather.error || sourceError}<p class="weather-message" role="status">{sourceError || weather.error}. Данные от {spbTime(data.fetched_at, { day:'numeric',month:'short',hour:'2-digit',minute:'2-digit' })}.</p>{/if}
        <div class="weather-metrics">
          <div title="Скорость и направление ветра"><Wind size={14}/><b>{number(data.current.wind_speed_10m)} м/с</b><small>{direction(data.current.wind_direction_10m) || 'Ветер'}</small></div>
          <div title="Относительная влажность"><Droplets size={14}/><b>{data.current.relative_humidity_2m}%</b><small>Влажность</small></div>
          <div title="Текущие осадки"><Umbrella size={14}/><b>{data.current.precipitation == null ? '—' : `${number(data.current.precipitation)} мм`}</b><small>Осадки</small></div>
        </div>
        <div class="weather-daylight"><span title="Восход"><Sunrise size={12}/>{today?.sunrise ? spbTime(today.sunrise, { hour:'2-digit',minute:'2-digit' }) : '—:—'}</span><span title="Закат"><Sunset size={12}/>{today?.sunset ? spbTime(today.sunset, { hour:'2-digit',minute:'2-digit' }) : '—:—'}</span></div>
        <small class="weather-city-updated">{weather.stale ? 'Сохранено' : 'Обновлено'} {spbTime(data.fetched_at, { hour:'2-digit',minute:'2-digit' })}</small>
      </section>
      <div class="weather-outlook">
        <section class="weather-hours" aria-label="Почасовой прогноз">{#each hours as hour, i}<div class="weather-hour" title={`${weatherLabel(hour.code, hour.is_day)} · вероятность осадков ${hour.precipitation}%`}><small>{i === 0 && hour.time === Math.floor(now.getTime()/3_600_000)*3600 ? 'Сейчас' : spbTime(hour.time, { hour:'2-digit',minute:'2-digit' })}</small><WeatherIcon code={hour.code} isDay={hour.is_day} size={22} colored/><b>{degrees(hour.temperature)}</b></div>{:else}<p class="weather-hours-empty">Прогноз устарел. Подключись к интернету для обновления.</p>{/each}</section>
        <section class="weather-daily-card" aria-label="Прогноз на неделю">
          <div class="weather-days">{#each data.daily as day}<div class="weather-day" title={`${spbTime(day.time, { day:'numeric',month:'long' })} · ${weatherLabel(day.code)}`}>
            <span class="weather-day-name" class:is-today={dateKey(day.time) === dateKey(now.getTime()/1000)}>{dateKey(day.time) === dateKey(now.getTime()/1000) ? 'Сегодня' : spbTime(day.time, { weekday:'short' })}</span><WeatherIcon code={day.code} size={19} colored/><small class="weather-day-low">{degrees(day.low)}</small><span class="temperature-rail" aria-hidden="true"><i style:left={`${(day.low-minimum)/range*100}%`} style:width={`${Math.max(3,(day.high-day.low)/range*100)}%`}></i></span><b class="weather-day-high">{degrees(day.high)}</b><span class="weather-day-rain">{day.precipitation == null || day.precipitation === 0 ? '' : `${number(day.precipitation)} мм`}</span>
          </div>{/each}</div>
          <div class="weather-attribution"><span>Время Петербурга · °C</span><button on:click={openSource}>Данные Open-Meteo <ExternalLink size={9}/></button></div>
        </section>
      </div>
    </div>
  {:else}
    <div class="weather-empty"><CloudOff size={36} strokeWidth={1}/><b>{loading ? 'Загружаю погоду для Петербурга…' : 'Погода пока недоступна'}</b><span>{loading ? 'Это займёт несколько секунд' : 'Нужно соединение с интернетом'}</span><button class="weather-refresh" disabled={loading} aria-label="Обновить погоду" on:click={refresh}><RefreshCw size={13}/>{loading ? 'Загружаю' : 'Попробовать снова'}</button>{#if weather.error}<p class="weather-message" role="status">{weather.error}</p>{/if}</div>
  {/if}
</section>

<style>
  .weather-board { flex:1; min-height:0; width:100%; padding:0; overflow:hidden; }
  .weather-board-grid { display:grid; grid-template-columns:205px minmax(0,1fr); gap:12px; height:100%; }
  .weather-city { --city-top:#3d7fc1; --city-bottom:#8394a2; position:relative; display:flex; flex-direction:column; align-items:stretch; gap:0; margin:0; padding:18px 15px 12px; border-radius:20px; overflow:hidden; background:linear-gradient(160deg,var(--city-top),var(--city-bottom)); min-width:0; height:100%; }
  [data-sky='night'] .weather-city { --city-top:#334f83; --city-bottom:#6b7b98; }
  [data-sky='sunny'] .weather-city { --city-top:#3d85c8; --city-bottom:#91a9b4; }
  [data-sky='rain'] .weather-city { --city-top:#416d9c; --city-bottom:#7c909e; }
  [data-sky='snow'] .weather-city { --city-top:#527ead; --city-bottom:#9baab4; }
  .weather-city.stale { opacity:.7; }
  .weather-city-heading { display:flex; align-items:center; justify-content:space-between; gap:5px; }
  .weather-city-heading h1 { display:flex; align-items:center; gap:4px; font-size:12px; font-weight:600; margin:0; white-space:nowrap; color:#fff; }
  .weather-city-heading button { border:0; background:none; color:#e2edfa; padding:3px; display:grid; place-items:center; border-radius:6px; }
  .weather-city-heading button:hover { background:#ffffff20; }
  .weather-temperature { flex:none; display:flex; align-items:center; gap:6px; margin:18px 0 9px; min-width:0; }
  .weather-temperature > span { font-size:52px; line-height:1; font-weight:500; letter-spacing:-2.5px; color:#fff; }
  .weather-description { font-size:13px; font-weight:600; line-height:1.4; color:#fff; }
  .weather-feels { margin:5px 0 0; font-size:10px; line-height:1.5; color:#e0e9f3; }
  .weather-message { font-size:9px; line-height:1.5; color:#fff0ca; background:#18354b40; padding:6px; border-radius:7px; margin:9px 0 0; overflow:auto; max-height:65px; flex:none; }
  .weather-metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:5px; min-width:0; margin-top:auto; padding:14px 0 0; color:#e9f2fc; }
  .weather-metrics > div { display:flex; flex-direction:column; align-items:flex-start; gap:5px; background:#17324838; padding:8px 6px 7px; border-radius:11px; min-width:0; }
  .weather-metrics b { font-size:10px; font-weight:600; white-space:nowrap; }
  .weather-city :global(.weather-metrics svg) { color:#d6e6f3; }
  .weather-metrics small { font-size:8px; color:#d0dfe9; }
  .weather-daylight { display:flex; gap:15px; margin-top:10px; color:#e4edf5; }
  .weather-daylight span { display:flex; align-items:center; gap:4px; font-size:10px; font-variant-numeric:tabular-nums; }
  .weather-city-updated { font-size:8px; color:#d4dfe9; margin-top:8px; }
  .weather-outlook { display:flex; flex-direction:column; gap:10px; min-height:0; }
  .weather-hours { display:grid; grid-auto-flow:column; grid-auto-columns:minmax(0,1fr); grid-template-columns:none; padding:14px 10px 13px; border:0; border-radius:20px; background:#111; flex:none; }
  .weather-hour { display:flex; flex-direction:column; gap:7px; align-items:center; line-height:1; }
  .weather-hour:first-child { background:none; }
  .weather-hour > small { font-size:9px; color:#919191; white-space:nowrap; }
  .weather-hour > b { font-size:12px; color:#f3f3f3; font-weight:600; }
  .weather-hours-empty { padding:8px; margin:0; font-size:11px; color:#999; grid-column:1/-1; }
  .weather-daily-card { background:#111; border-radius:20px; padding:12px 14px 10px; flex:1; display:flex; flex-direction:column; min-height:0; }
  .weather-days { display:flex; flex-direction:column; justify-content:space-between; gap:2px; padding:0; flex:1; min-height:0; }
  .weather-day { display:grid; grid-template-columns:49px 21px 27px minmax(0,1fr) 28px 39px; gap:6px; align-items:center; padding:0; background:none; border-radius:0; min-height:26px; }
  .weather-day-name { font-size:11px; color:#b5b5b5; text-transform:capitalize; }
  .weather-day-name.is-today { font-weight:600; color:#f5f5f5; }
  .weather-day-low { color:#858585; font-size:11px; text-align:right; font-variant-numeric:tabular-nums; }
  .weather-day-high { color:#f5f5f5; font-size:11px; justify-self:end; font-weight:550; font-variant-numeric:tabular-nums; }
  .temperature-rail { display:block; position:relative; height:4px; border-radius:5px; background:#2b2b2b; overflow:hidden; }
  .temperature-rail i { position:absolute; top:0; height:100%; border-radius:5px; background:linear-gradient(90deg,#aaceaf,#efcf82,#f49c6c); }
  .weather-day .weather-day-rain { color:#91c7ee; font-size:9px; white-space:nowrap; justify-self:end; }
  .weather-attribution { display:flex; justify-content:space-between; gap:8px; padding-top:12px; margin:0; color:#777; font-size:8px; flex:none; }
  .weather-attribution button { display:flex; gap:3px; align-items:center; border:0; padding:0; background:none; color:#969696; font-size:8px; }
  .weather-attribution button:hover { color:#eee; }
  .weather-empty { background:#111; border-radius:20px; height:100%; }
</style>
