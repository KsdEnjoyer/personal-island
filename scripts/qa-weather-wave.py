"""Reference weather layout, actual canvas contour motion, and task-count spacing."""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from qa_weather import fixture
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/qa';results=[]
def passed(name,**details):results.append({'test':name,'status':'passed',**details});print(name,details,flush=True)
with sync_playwright() as p:
    exe=sorted((Path(os.environ['LOCALAPPDATA'])/'ms-playwright').glob('chromium_headless_shell-*/**/chrome-headless-shell.exe'))[-1]
    browser=p.chromium.launch(executable_path=str(exe));context=browser.new_context(viewport={'width':760,'height':520},timezone_id='Europe/Moscow')
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf-8'))
    page.goto('http://127.0.0.1:1420/');page.add_style_tag(content='html,body,#app{background:#333b49!important}')
    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
    page.mouse.move(750,510)
    page.evaluate('data=>{qaWeather=data;qaTasks=[];qaReveal()}',fixture());page.wait_for_timeout(700)
    assert page.locator('.pill-summary>b').inner_text()=='0\u00a0задач',repr(page.locator('.pill-summary>b').inner_text())
    passed('Task count has a real nonbreaking space, including zero tasks')
    def contour():
        return page.locator('canvas').evaluate('''canvas=>{
          const ctx=canvas.getContext('2d'),dpr=canvas.width/canvas.clientWidth;
          const w=parseFloat(document.querySelector('.island-shell').style.getPropertyValue('--shape-width'));
          const h=parseFloat(document.querySelector('.island-shell').style.getPropertyValue('--shape-height'));
          const ys=[];
          for(let x=(canvas.clientWidth-w)/2+35;x<(canvas.clientWidth+w)/2-35;x+=2){
            let bottom=0;
            for(let y=h-16;y<h+16;y++){if(ctx.getImageData(Math.round(x*dpr),Math.round(y*dpr),1,1).data[3]>220)bottom=y;}
            ys.push(bottom);
          }
          return {spread:Math.max(...ys)-Math.min(...ys),ys};
        }''')
    idle=contour()
    page.evaluate("qaMedia={sessions:[{id:'qa.exe',label:'QA'}],session_id:'qa.exe',source:'QA',title:'Ночной Петербург',artist:'Исполнитель',artwork:null,playing:true,position:10,duration:200,can_toggle:true,can_previous:true,can_next:true};qaEmit('media-changed',qaMedia)")
    page.wait_for_timeout(1000);playing=contour();page.screenshot(path=str(OUT/'wave-compact-playing.png'))
    expect(page.locator('.equalizer')).to_have_count(0)
    assert playing['spread']>=idle['spread']+3,(idle['spread'],playing['spread'])
    page.wait_for_timeout(200);assert contour()['ys']!=playing['ys']
    passed('Playback animates the actual bottom contour; no separate equalizer bars',idle_spread=idle['spread'],playing_spread=playing['spread'])
    page.evaluate("qaMedia.playing=false;qaEmit('media-changed',qaMedia)");page.wait_for_timeout(1200)
    assert contour()['spread']<=idle['spread']+2
    page.emulate_media(reduced_motion='reduce')
    page.evaluate("qaMedia.playing=true;qaEmit('media-changed',qaMedia)");page.wait_for_timeout(100)
    frozen=contour();page.wait_for_timeout(250);assert contour()['ys']==frozen['ys']
    passed('Pausing calms the contour; reduced motion keeps it still')
    page.evaluate('qaReveal()');page.locator('.pill').click();page.get_by_label('Закрепить островок').click();page.get_by_role('button',name='Погода',exact=True).click()
    expect(page.locator('.weather-hour')).to_have_count(8);expect(page.locator('.weather-day')).to_have_count(7)
    expect(page.locator('.weather-metrics')).to_contain_text('4,2 м/с');expect(page.locator('.weather-metrics')).to_contain_text('СЗ');expect(page.locator('.weather-metrics')).to_contain_text('0,3 мм')
    expect(page.locator('.weather-daylight')).to_contain_text('09:00');expect(page.locator('.weather-daylight')).to_contain_text('16:00')
    board=page.locator('.weather-board-grid').bounding_box();city=page.locator('.weather-city').bounding_box();hours=page.locator('.weather-hours').bounding_box();days=page.locator('.weather-daily-card').bounding_box()
    assert city['x']<hours['x'] and hours['y']<days['y']
    for selector in ['.weather-board','.weather-city','.weather-outlook','.weather-daily-card']:
        assert page.locator(selector).evaluate('el=>el.scrollHeight<=el.clientHeight+1 && el.scrollWidth<=el.clientWidth+1'),selector
    for row in page.locator('.temperature-rail i').all():
        assert row.evaluate('el=>{let r=el.getBoundingClientRect(),p=el.parentElement.getBoundingClientRect();return r.width>0&&r.left>=p.left-.5&&r.right<=p.right+.5}')
    page.screenshot(path=str(OUT/'weather-reference-night.png'))
    passed('Weather uses a tall city card, hourly strip, seven temperature ranges, rain and daylight')
    page.evaluate('qaWeather.data.current.is_day=1;qaWeather.data.current.weather_code=2');page.get_by_label('Обновить погоду').click();page.wait_for_timeout(150);page.screenshot(path=str(OUT/'weather-reference-day.png'))
    page.evaluate("qaWeather.stale=true;qaWeather.error='Нет сети'");page.get_by_label('Обновить погоду').click();expect(page.locator('.weather-message')).to_contain_text('Данные от')
    expect(page.locator('.weather-city-updated')).to_contain_text('Сохранено')
    page.evaluate('delete qaWeather.data.current.precipitation;qaWeather.data.daily.forEach(d=>{delete d.sunrise;delete d.sunset;delete d.precipitation})');page.get_by_label('Обновить погоду').click()
    expect(page.locator('.weather-metrics')).to_contain_text('—');expect(page.locator('.weather-daylight')).to_contain_text('—:—')
    page.evaluate("qaWeather={data:null,stale:false,error:'Нет сети'}");page.get_by_label('Обновить погоду').click();expect(page.locator('.weather-empty')).to_be_visible();expect(page.get_by_label('Обновить погоду')).to_be_visible()
    passed('Offline and legacy caches stay labelled; missing rain/daylight are never invented')
    assert not errors,errors
    browser.close()
(OUT/'weather-wave-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
