"""Compact transport and real pointer interaction with the vertical volume popup."""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/qa';results=[]
def passed(name):results.append({'test':name,'status':'passed'});print(name,flush=True)
with sync_playwright() as p:
    exe=sorted((Path(os.environ['LOCALAPPDATA'])/'ms-playwright').glob('chromium_headless_shell-*/**/chrome-headless-shell.exe'))[-1]
    browser=p.chromium.launch(executable_path=str(exe))
    context=browser.new_context(viewport={'width':760,'height':520},reduced_motion='reduce',timezone_id='Europe/Moscow')
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf8'));page.goto('http://127.0.0.1:1420/')
    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
    page.add_style_tag(content='html,body,#app{background:#30333b!important}')
    page.evaluate("""()=>{qaMedia={sessions:[{id:'qa.exe',label:'QA Player'}],session_id:'qa.exe',source:'QA Player',title:'LEGACY',artist:'PIXY, North West',artwork:'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2264%22 height=%2264%22%3E%3Crect width=%2264%22 height=%2264%22 fill=%22%232b5d58%22/%3E%3Ccircle cx=%2232%22 cy=%2232%22 r=%2218%22 fill=%22%23e6bc78%22/%3E%3C/svg%3E',playing:true,position:12,duration:200,can_toggle:true,can_previous:true,can_next:true};qaReveal()}""")
    expect(page.locator('.compact-cover')).to_be_visible()
    pill=page.locator('.music-pill').bounding_box();cover=page.locator('.compact-cover').bounding_box()
    assert abs((cover['x']+cover['width']/2)-(pill['x']+pill['width']/2))<1
    page.locator('.compact-stage').get_by_label('Предыдущий трек',exact=True).click();page.locator('.compact-stage').get_by_label('Следующий трек',exact=True).click()
    page.locator('.compact-stage').get_by_label('Приостановить музыку',exact=True).click()
    expect(page.locator('.compact-stage').get_by_label('Продолжить музыку',exact=True)).to_be_visible()
    assert not page.evaluate('qaMedia.playing')
    page.locator('.compact-stage').get_by_label('Продолжить музыку',exact=True).click()
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
    actions=page.evaluate("qaCalls.filter(c=>c.cmd==='media_command').map(c=>c.args.action)")
    assert actions==['previous','next','toggle','toggle'],actions
    page.screenshot(path=str(OUT/'music-compact-controls.png'))
    passed('Manual reveal centres artwork with previous/next; cover pauses and resumes without opening the dashboard')
    page.evaluate("qaReveal('track')")
    expect(page.locator('.track-peek')).to_be_visible()
    assert page.locator('.compact-stage').evaluate('e=>e.clientHeight')==76
    assert page.locator('.compact-stage').evaluate('e=>e.clientWidth')==360
    body=page.locator('.track-peek').bounding_box()
    for control in page.locator('.track-peek button').all():
        box=control.bounding_box()
        assert box['x']>=body['x'] and box['x']+box['width']<=body['x']+body['width']+1
        assert box['y']+box['height']<=body['y']+body['height']-3
    page.screenshot(path=str(OUT/'music-notification-tight.png'))
    page.get_by_label('Показать громкость плеера').click()
    slider=page.get_by_label('Громкость плеера',exact=True);expect(slider).to_be_enabled()
    assert page.locator('.compact-stage').evaluate('e=>e.clientHeight')==76
    assert page.evaluate('qaOverlayOpen') is True
    expect(slider).to_have_attribute('aria-orientation','vertical')
    box=slider.bounding_box();trigger=page.locator('.volume-trigger').bounding_box()
    assert box['height']>box['width']*2 and box['y']>trigger['y']+trigger['height']
    body=page.locator('.track-peek').bounding_box();popup=page.locator('.track-peek .volume-popover').bounding_box()
    assert popup['y']>=body['y']+body['height']+2,(body,popup)
    page.mouse.click(box['x']+box['width']/2,box['y']+12)
    page.wait_for_function('qaVolume>.8');high=page.evaluate('qaVolume')
    page.mouse.move(box['x']+box['width']/2,box['y']+12);page.mouse.down()
    page.mouse.move(box['x']+box['width']/2,box['y']+box['height']-12,steps=10);page.mouse.up()
    page.wait_for_function('qaVolume<.2');assert page.evaluate('qaVolume')<high
    page.evaluate('qaVolumeDelay=80')
    for value in ['15','45','76']:slider.fill(value)
    page.wait_for_function('qaVolume===.76')
    expect(page.locator('.volume-popover output')).to_have_text('76%')
    page.screenshot(path=str(OUT/'music-volume-vertical.png'))
    slider.press('ArrowUp');page.wait_for_function('qaVolume===.77')
    slider.press('Escape');expect(slider).to_have_count(0)
    expect(page.locator('.track-peek')).to_be_visible()
    assert page.locator('.compact-stage').evaluate('e=>e.clientHeight')==76
    passed('Volume floats below an unchanged 76px island; transparent overlay, dragging, queued input and Escape work')
    page.evaluate('qaVolumeAvailable=false')
    page.get_by_label('Показать громкость плеера').click();expect(page.get_by_role('button',name='Повторить')).to_be_visible()
    expect(page.get_by_label('Громкость плеера',exact=True)).to_have_count(0)
    page.evaluate('qaVolumeAvailable=true')
    expect(page.get_by_label('Громкость плеера',exact=True)).to_be_enabled(timeout=4000)
    page.evaluate("qaFail='player_volume'");page.get_by_label('Громкость плеера',exact=True).fill('30')
    expect(page.get_by_role('alert')).to_contain_text('QA simulated failure')
    page.evaluate("qaFail=null");page.get_by_label('Громкость плеера',exact=True).fill('42')
    page.wait_for_function('qaVolume===.42');expect(page.get_by_role('alert')).to_have_count(0)
    page.locator('.peek-title').click();page.get_by_label('Закрепить островок').click()
    expect(page.locator('.music-panel')).to_be_visible()
    page.locator('.music-panel').get_by_label('Показать громкость плеера').click()
    full=page.locator('.music-panel').get_by_label('Громкость плеера',exact=True);expect(full).to_be_enabled()
    expect(full).to_be_in_viewport()
    panel=page.locator('.music-panel').bounding_box();pop=page.locator('.music-panel .volume-popover').bounding_box()
    assert pop['y']+pop['height']<=panel['y']+panel['height'],(panel,pop)
    page.screenshot(path=str(OUT/'music-player-vertical-volume.png'))
    passed('Missing audio session reconnects; errors recover; the full player uses the same visible dropdown')
    assert not errors,errors
    browser.close()
(OUT/'music-layout-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
