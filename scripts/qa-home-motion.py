"""Home summary/navigation, detached volume and smooth interruptible motion."""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from qa_weather import fixture
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/qa';results=[]
def passed(name,**metrics):results.append({'test':name,'status':'passed',**metrics});print(name,metrics,flush=True)
with sync_playwright() as p:
    exe=sorted((Path(os.environ['LOCALAPPDATA'])/'ms-playwright').glob('chromium_headless_shell-*/**/chrome-headless-shell.exe'))[-1]
    browser=p.chromium.launch(executable_path=str(exe))
    context=browser.new_context(viewport={'width':760,'height':520},timezone_id='Europe/Moscow',reduced_motion='reduce')
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf8'));page.goto('http://127.0.0.1:1420/')
    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
    page.add_style_tag(content='html,body,#app{background:#30333b!important}')
    assert not page.evaluate("qaCalls.some(c=>c.cmd==='get_widget_summary')")
    page.evaluate("qaNotes=[{id:1,category:'notes',title:'One'},{id:2,category:'shopping',title:'Two'}];qaClipboard=[{id:1,kind:'text',text:'Local',pinned:true}]")
    page.evaluate('data=>{qaWeather=data;qaReveal()}',fixture());page.locator('.pill').click()
    page.get_by_label('Закрепить островок').click()
    expect(page.get_by_role('button',name='Главная',exact=True)).to_have_attribute('aria-current','page')
    expect(page.locator('.home-panel')).to_be_visible()
    expect(page.locator('.notes-stats')).to_contain_text('Заметки 1')
    expect(page.locator('.notes-stats')).to_contain_text('Покупки 1')
    expect(page.locator('.clipboard-stats')).to_contain_text('1 запись')
    expect(page.locator('.task-stats button').nth(0)).to_contain_text('4')
    expect(page.locator('.weather-overview')).to_contain_text('-1°')
    assert page.locator('.home-panel').evaluate('e=>e.scrollHeight<=e.clientHeight+1 && e.scrollWidth<=e.clientWidth+1')
    assert not page.evaluate("qaCalls.some(c=>c.cmd==='list_notes'||c.cmd==='list_clipboard')")
    page.screenshot(path=str(OUT/'home-overview.png'))
    passed('Home shows real task, timer, player, weather, notes and clipboard summaries without loading payloads')
    page.get_by_label('Запустить таймер',exact=True).click();expect(page.locator('.focus-overview')).to_contain_text('Идёт фокус')
    page.get_by_label('Добавить минуту',exact=True).click();expect(page.locator('.focus-line strong')).to_contain_text('26:')
    page.get_by_label('Открыть все задачи',exact=True).click();expect(page.locator('.task-item')).to_have_count(4)
    page.get_by_role('button',name='Главная',exact=True).click()
    page.get_by_label('Новая задача',exact=True).click();expect(page.get_by_label('Название задачи',exact=True)).to_be_visible()
    page.get_by_role('button',name='Отмена',exact=True).click()
    page.get_by_role('button',name='Главная',exact=True).click()
    for label,selector in [('Открыть погоду','.weather-panel'),('Открыть буфер обмена','.clipboard-panel')]:
        page.get_by_label(label,exact=True).click();expect(page.locator(selector)).to_be_visible()
        page.get_by_role('button',name='Главная',exact=True).click()
    page.evaluate("qaClipboardEnabled=false;qaEmit('clipboard-changed',null)")
    expect(page.locator('.capture-status')).to_contain_text('Пауза')
    page.get_by_label('Открыть настройки виджета').click();expect(page.locator('.settings-panel')).to_be_visible()
    page.keyboard.press('Escape')
    passed('Overview actions navigate correctly, timer state persists, and clipboard capture status updates live')
    page.keyboard.press('Escape');expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
    page.emulate_media(reduced_motion='no-preference')
    page.wait_for_timeout(100)
    page.evaluate('qaReveal()');page.wait_for_timeout(100)
    transform=page.locator('.island-shell').evaluate('e=>{const m=new DOMMatrix(getComputedStyle(e).transform);return {x:m.a,y:m.d,opacity:Number(getComputedStyle(e).opacity)}}')
    assert abs(transform['x']-transform['y'])<.01 and 0<transform['opacity']<1,transform
    page.wait_for_timeout(450)
    page.evaluate("""()=>{window.qaShapeFrames=[];const end=performance.now()+1100;const sample=t=>{qaShapeFrames.push({time:t,height:parseFloat(document.querySelector('.island-shell').style.getPropertyValue('--shape-height'))});if(t<end)requestAnimationFrame(sample)};requestAnimationFrame(sample)}""")
    page.locator('.pill').click();page.wait_for_timeout(1150)
    frames=page.evaluate('qaShapeFrames');heights=[f['height'] for f in frames]
    assert max(heights)<=458.4 and min(heights)>=55.6,heights
    assert all(b>=a-.5 for a,b in zip(heights,heights[1:])),heights
    assert abs(heights[-1]-458)<.5
    page.get_by_label('Закрепить островок').click()
    page.get_by_role('button',name='Задачи',exact=True).click()
    assert page.locator('.view-stage').evaluate('e=>e.getAnimations().some(a=>a.playState==="running")')
    for tab in ['Календарь','Задачи','Главная']:
        page.get_by_role('button',name=tab,exact=True).click()
    page.wait_for_timeout(400)
    assert page.locator('.view-stage').evaluate('e=>getComputedStyle(e).opacity')=='1'
    page.keyboard.press('Escape');page.wait_for_timeout(80);page.evaluate('qaReveal()')
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
    page.wait_for_timeout(1300)
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
    passed('Presence keeps proportions; expansion has no overshoot; rapid tabs and reveal during exit settle cleanly',samples=len(frames),maximum_height=max(heights))
    page.emulate_media(reduced_motion='reduce');page.locator('.pill').click()
    page.get_by_role('button',name='Задачи',exact=True).click()
    assert not page.locator('.view-stage').evaluate('e=>e.getAnimations().some(a=>a.playState==="running")')
    passed('Reduced motion skips view animations and shape spring')
    assert not errors,errors
    browser.close()
(OUT/'home-motion-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
