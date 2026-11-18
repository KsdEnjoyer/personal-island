"""Compact artwork and SPb weather UI, including paused/offline states."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from qa_weather import fixture
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/qa'
results=[]
def passed(name):
    results.append({'test':name,'status':'passed'});print(name,flush=True)
with sync_playwright() as p:
    paths=sorted((Path(os.environ['LOCALAPPDATA'])/'ms-playwright').glob('chromium_headless_shell-*/**/chrome-headless-shell.exe'))
    browser=p.chromium.launch(executable_path=str(paths[-1]))
    context=browser.new_context(viewport={'width':760,'height':520},timezone_id='America/New_York',reduced_motion='reduce')
    page=context.new_page();errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf-8'))
    page.goto('http://127.0.0.1:1420/')
    page.add_style_tag(content='html,body,#app{background:#383b48!important}')
    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
    page.evaluate('data=>{qaWeather=data;qaReveal()}',fixture())
    expect(page.locator('.pill-weather')).to_contain_text('-1°')
    page.evaluate("qaMedia={sessions:[{id:'qa',label:'QA player'}],session_id:'qa',source:'QA player',title:'Тихий город',artist:'Исполнитель',artwork:'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2264%22 height=%2264%22%3E%3Crect width=%2264%22 height=%2264%22 fill=%22%23964a35%22/%3E%3Ccircle cx=%2232%22 cy=%2232%22 r=%2218%22 fill=%22%23e6bc78%22/%3E%3C/svg%3E',playing:true,position:0,duration:100,can_toggle:true,can_previous:false,can_next:false};qaReveal()")
    expect(page.locator('.pill-artwork')).to_be_visible()
    assert page.locator('.pill-artwork').evaluate('el=>el.complete&&el.naturalWidth>0')
    expect(page.locator('.pill-center')).to_have_text('Тихий город')
    page.screenshot(path=str(OUT/'compact-artwork-weather.png'))
    page.evaluate('qaMedia.playing=false;qaReveal()')
    expect(page.locator('.pill-paused')).to_be_visible()
    expect(page.locator('.pill-artwork')).to_be_visible()
    expect(page.locator('.pill-center')).to_have_text('Тихий город')
    passed('Compact island keeps a real image, track title and weather while playing or paused')
    page.locator('.pill').click()
    page.get_by_role('button',name='Закрепить островок').click()
    page.get_by_role('button',name='Погода',exact=True).click()
    expect(page.locator('.weather-hours .weather-hour')).to_have_count(6)
    expect(page.locator('.weather-days .weather-day')).to_have_count(5)
    expect(page.locator('.weather-temperature')).to_contain_text('Ощущается как -5°')
    expect(page.locator('.weather-metrics')).to_contain_text('4,2 м/с')
    expected=page.evaluate("time=>new Date(time*1000).toLocaleString('ru-RU',{timeZone:'Europe/Moscow',hour:'2-digit',minute:'2-digit'})",fixture()['data']['hourly'][0]['time'])
    expect(page.locator('.weather-hour small').first).to_have_text(expected)
    for selector in ('.weather-attribution','.weather-day'):
        expect(page.locator(selector).last).to_be_in_viewport()
    assert page.locator('.weather-panel').evaluate('el=>el.scrollHeight<=el.clientHeight+1'), 'Weather panel should fit without hiding attribution'
    page.screenshot(path=str(OUT/'weather-spb.png'))
    passed('Weather shows local SPb hours, five days, feels-like, wind and attribution')
    page.evaluate("qaWeather.stale=true;qaWeather.error='Нет соединения с сервисом погоды'")
    page.get_by_label('Обновить погоду').click()
    expect(page.locator('.weather-message')).to_contain_text('Данные от')
    expect(page.locator('.weather-now')).to_have_class('weather-now stale')
    expect(page.locator('.pill-weather')).to_contain_text('—°')
    page.evaluate("qaWeather={data:null,stale:false,error:'Нет соединения с сервисом погоды'}")
    page.get_by_label('Обновить погоду').click()
    expect(page.locator('.weather-empty')).to_be_visible()
    expect(page.locator('.weather-temperature')).to_have_count(0)
    passed('Offline UI labels cached data and never substitutes invented current temperatures')
    page.get_by_role('button',name='Свернуть',exact=True).click()
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
    page.evaluate('qaMedia.artwork=null;qaReveal()')
    expect(page.locator('.pill-artwork')).to_have_count(0)
    expect(page.locator('.pill-symbol svg')).to_be_visible()
    passed('Players without artwork retain the music-icon fallback')
    assert not errors,errors
    context.close();browser.close()
(OUT/'weather-ui-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
