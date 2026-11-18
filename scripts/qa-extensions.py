"""Clipboard, media and whole-island motion checks with isolated IPC data."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/qa'
results=[]
def passed(name):
    results.append({'test':name,'status':'passed'}); print(name,flush=True)

with sync_playwright() as p:
    paths=sorted((Path(os.environ['LOCALAPPDATA'])/'ms-playwright').glob('chromium_headless_shell-*/**/chrome-headless-shell.exe'))
    browser=p.chromium.launch(executable_path=str(paths[-1]))
    context=browser.new_context(viewport={'width':760,'height':520},record_video_dir=str(OUT/'extensions-motion'))
    page=context.new_page(); errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf-8'))
    page.goto('http://127.0.0.1:1420/')
    page.add_style_tag(content='html,body,#app{background:#383b48!important}')
    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
    page.mouse.move(750,510)
    page.evaluate('qaReveal()'); page.wait_for_timeout(80)
    opacity=float(page.locator('.island-shell').evaluate('el=>getComputedStyle(el).opacity'))
    assert 0<opacity<1,opacity
    page.wait_for_timeout(500)
    assert page.locator('.island-shell').evaluate('el=>getComputedStyle(el).transform')=='none'
    page.keyboard.press('Escape'); page.wait_for_timeout(60)
    assert float(page.locator('.island-shell').evaluate('el=>getComputedStyle(el).opacity'))<1
    assert not page.evaluate("qaCalls.some(c=>c.cmd==='hide_island')")
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
    passed('Whole island animates in/out; native hide waits for the exit')
    page.emulate_media(reduced_motion='reduce')
    page.evaluate('''() => {
      qaClipboard = [
        {id:1,kind:'text',text:'Привет, островок',thumbnail:null,pinned:false,captured_at:100,width:null,height:null},
        {id:2,kind:'text',text:'Local clipboard',thumbnail:null,pinned:false,captured_at:200,width:null,height:null},
        {id:3,kind:'image',text:null,thumbnail:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jOqkAAAAASUVORK5CYII=',pinned:false,captured_at:300,width:80,height:60}
      ]; qaReveal();
    }''')
    page.locator('.pill').click()
    page.get_by_role('button',name='Закрепить островок').click()
    page.get_by_role('button',name='Буфер обмена',exact=True).click()
    expect(page.locator('.clipboard-card')).to_have_count(3)
    expect(page.locator('.clip-content img')).to_be_visible()
    page.get_by_label('Поиск в буфере обмена').fill('ПРИВЕТ')
    expect(page.locator('.clipboard-card')).to_have_count(1)
    page.get_by_label('Закрепить запись').click()
    expect(page.locator('.clipboard-card.pinned')).to_have_count(1)
    page.get_by_label('Поиск в буфере обмена').fill('')
    expect(page.locator('.clipboard-card')).to_have_count(3)
    expect(page.locator('.clipboard-card').first).to_contain_text('Привет')
    passed('Clipboard displays images, searches Cyrillic and orders pinned entries first')
    page.get_by_label('Приостановить запись буфера').click()
    expect(page.get_by_label('Возобновить запись буфера')).to_be_visible()
    page.get_by_label('Возобновить запись буфера').click()
    card=page.locator('.clipboard-card').filter(has_text='Local clipboard')
    card.get_by_label('Удалить запись').click()
    card.get_by_role('button',name='Отмена',exact=True).click()
    expect(card).to_be_visible()
    card.get_by_label('Удалить запись').click()
    card.get_by_role('button',name='Удалить',exact=True).click()
    expect(card).to_have_count(0)
    page.screenshot(path=str(OUT/'clipboard-history.png'))
    passed('Capture pause/resume and explicit deletion confirmation work')
    page.get_by_role('button',name='Вставить текст: Привет, островок',exact=True).click()
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
    assert page.evaluate("qaCalls.filter(c=>['copy_clipboard_entry','hide_island','paste_to_previous_window'].includes(c.cmd)).slice(-3).map(c=>c.cmd)")==['copy_clipboard_entry','hide_island','paste_to_previous_window']
    passed('Clicking a record copies, hides, then requests paste in the previous window')
    page.evaluate("qaFail='paste_to_previous_window';qaReveal()")
    page.locator('.pill').click()
    page.get_by_role('button',name='Вставить текст: Привет, островок',exact=True).click()
    expect(page.locator('.utility-error')).to_contain_text('QA simulated failure')
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
    page.evaluate('qaFail=null')
    passed('Paste failure restores the dashboard and displays a recoverable error')
    page.evaluate('qaReveal()'); page.locator('.pill').click()
    page.get_by_role('button',name='Музыка',exact=True).click()
    expect(page.locator('.music-empty')).to_be_visible()
    page.evaluate("qaMedia={sessions:[{id:'yandexmusic.exe',label:'Яндекс Музыка'}],session_id:'yandexmusic.exe',source:'Яндекс Музыка',title:'Тихий город',artist:'Тестовый исполнитель',artwork:null,playing:true,position:61,duration:201,can_toggle:true,can_previous:true,can_next:true};qaEmit('media-changed',qaMedia)")
    expect(page.locator('.track-info h2')).to_have_text('Тихий город',timeout=4000)
    page.locator('.music-panel').get_by_label('Приостановить музыку').click()
    expect(page.locator('.music-panel').get_by_label('Продолжить музыку')).to_be_visible()
    page.locator('.music-panel').get_by_label('Следующий трек').click()
    assert page.evaluate("qaCalls.filter(c=>c.cmd==='media_command').at(-1).args")=={'sessionId':'yandexmusic.exe','action':'next'}
    page.screenshot(path=str(OUT/'music-player.png'))
    passed('Music empty state, metadata, pause and selected-session transport work')
    assert not errors,errors
    video=page.video; context.close(); video.save_as(str(OUT/'extensions-motion.webm')); browser.close()
(OUT/'extensions-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
