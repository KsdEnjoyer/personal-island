"""Native calendar resize, right-edge hover, SQLite changes and compact restoration."""
import ctypes,json,os,subprocess,tempfile,time,urllib.request
from ctypes import wintypes
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from qa_win import user32
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/qa';results=[]
try:user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except AttributeError:pass
original=wintypes.POINT();user32.GetCursorPos(ctypes.byref(original))
def passed(name):results.append({'test':name,'status':'passed'});print(name,flush=True)
with tempfile.TemporaryDirectory(prefix='island-calendar-') as temp:
    folder=Path(temp);children=[]
    env=dict(os.environ,PERSONAL_ISLAND_DB=str(folder/'tasks.sqlite3'),WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    with (OUT/'calendar-native-stderr.log').open('w',encoding='utf8') as log:
        try:
            with sync_playwright() as p:
                def start():
                    proc=subprocess.Popen([str(ROOT/'target/debug/personal-island-desktop.exe'),'--show'],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW);children.append(proc)
                    deadline=time.monotonic()+30
                    while True:
                        assert proc.poll() is None,'Native app exited'
                        try:urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1).close();break
                        except OSError:
                            assert time.monotonic()<deadline,'WebView2 unavailable';time.sleep(.2)
                    browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222');page=browser.contexts[0].pages[0]
                    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
                    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false');page.locator('.pill').click();page.get_by_role('button',name='Закрепить островок').click()
                    return proc,browser,page
                proc,browser,page=start();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                def invoke(cmd,args=None):return page.evaluate('([cmd,args])=>__TAURI_INTERNALS__.invoke(cmd,args)',[cmd,args or {}])
                dashboard_size=page.evaluate('[Math.min(960, screen.availWidth), Math.min(640, screen.availHeight)]')
                assert page.evaluate('[innerWidth,innerHeight]')==dashboard_size
                page.get_by_role('button',name='Календарь',exact=True).click();expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
                assert page.evaluate('[innerWidth,innerHeight]')==dashboard_size
                expect(page.locator('.time-grid')).to_have_count(0)
                page.locator('.calendar-day.selected').click()
                assert page.evaluate('[innerWidth,innerHeight]')==dashboard_size
                page.screenshot(path=str(OUT/'calendar-native-compact.png'))
                page.locator('.calendar-day.selected').dblclick();expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
                size=page.evaluate('({w:innerWidth,h:innerHeight,sw:screen.width,sh:screen.height})')
                assert size['w']<=size['sw']-31 and size['h']<=size['sh']-69,size # WebView rounds physical pixels to CSS pixels.
                assert size['w']<=1280 and size['h']<=820,size
                expect(page.locator('.time-grid')).to_be_visible()
                assert page.locator('.dashboard').evaluate('e=>e.clientWidth')==size['w']-56
                passed('Native calendar stays compact on entry/single click; a double click opens the monitor-fitted weekly planner')
                when=page.evaluate("()=>{let d=new Date();d.setDate(d.getDate()+2);d.setHours(14,30,0,0);return new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,16)}")
                page.get_by_role('button',name='Новое событие',exact=True).click();page.get_by_label('Название события').fill('Нативная встреча календаря')
                page.get_by_label('Время события',exact=True).fill(when);page.get_by_label('Описание события').fill('Проверить сохранение срока');page.get_by_label('Приоритет события').select_option('1')
                page.get_by_role('button',name='Добавить событие',exact=True).click();expect(page.get_by_role('dialog')).to_have_count(0)
                created=invoke('list_tasks',{'includeCompleted':True})[0]
                assert created['title']=='Нативная встреча календаря' and created['priority']==1 and created['reminder_at']
                page.get_by_label('Поиск по событиям').fill('Нативная встреча');page.locator('.search-result').click()
                moved=page.evaluate("s=>{let d=new Date(s);d.setHours(16,0,0,0);return new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,16)}",when)
                page.get_by_label('Новый срок события').fill(moved);page.get_by_role('button',name='Сохранить срок',exact=True).click();expect(page.get_by_role('dialog')).to_have_count(0)
                saved=invoke('list_tasks',{'includeCompleted':True})[0]
                assert saved['due_at']!=created['due_at'] and saved['reminder_at']!=created['reminder_at']
                page.get_by_role('button',name='Очистить поиск событий').click()
                page.get_by_role('button',name='Завершить: Нативная встреча календаря',exact=True).click()
                expect(page.get_by_role('button',name='Вернуть: Нативная встреча календаря',exact=True)).to_be_visible()
                page.get_by_role('button',name='Записать мысль',exact=True).click();page.get_by_label('Быстрая заметка календаря').fill('Заметка из нового календаря\nДетали сохранились')
                page.get_by_role('button',name='Сохранить',exact=True).click();expect(page.locator('.quick-note-list')).to_contain_text('Заметка из нового календаря')
                passed('Calendar UI creates, reschedules and completes real tasks, and saves quick notes to native SQLite')
                # Move the actual Windows cursor into the new rightmost part of the window.
                user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
                user32.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
                found=[];callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
                def visit(hwnd,_):
                    pid=wintypes.DWORD();user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                    if pid.value==proc.pid and user32.IsWindowVisible(hwnd):found.append(hwnd)
                    return True
                user32.EnumWindows(callback(visit),0);assert found
                rect=wintypes.RECT();user32.GetWindowRect(found[0],ctypes.byref(rect))
                ratio=(rect.right-rect.left)/size['w']
                page.get_by_role('button',name='Закрепить островок').click()
                user32.SetCursorPos(round(rect.left+(size['w']-45)*ratio),round(rect.top+300*ratio))
                expect(page.locator('.island-shell')).to_have_attribute('data-native-hover','true')
                page.wait_for_timeout(1600);expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
                page.get_by_role('button',name='Закрепить островок').click()
                passed('Native hover includes the expanded right sidebar and does not dismiss the wider calendar')
                page.screenshot(path=str(OUT/'calendar-native.png'))
                page.get_by_role('button',name='Открыть все заметки').click();expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
                expect(page.get_by_label('Название записи')).to_have_value('Заметка из нового календаря',timeout=20000)
                assert page.evaluate('[innerWidth,innerHeight]')==dashboard_size
                page.get_by_role('button',name='Календарь',exact=True).click();expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
                assert page.evaluate('[innerWidth,innerHeight]')==dashboard_size
                page.locator('.calendar-day.selected').dblclick();expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
                old_generation=json.loads(page.locator('.island-shell').get_attribute('data-presentation'))['activeGeneration']
                page.keyboard.press('Escape');expect(page.locator('.compact-month')).to_be_visible();expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
                assert page.evaluate('[innerWidth,innerHeight]')==dashboard_size
                page.keyboard.press('Escape');expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
                assert page.evaluate('[innerWidth,innerHeight]')==[480,196]
                invoke('register_island_shortcut');expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
                invoke('set_island_expanded',{'expanded':True,'calendar':True,'generation':old_generation})
                assert page.evaluate('[innerWidth,innerHeight]')==[480,196],'An old generation must not restore the calendar'
                expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
                page.locator('.pill').click();expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false');expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
                assert page.evaluate('[innerWidth,innerHeight]')==dashboard_size
                expect(page.locator('.time-grid')).to_have_count(0)
                passed('Leaving calendar restores normal size; Escape returns to compact size and a manual native reveal reopens the island correctly')
                page.get_by_role('button',name='Настройки',exact=True).click();page.get_by_role('button',name='Выход',exact=True).click();proc.wait(timeout=15);browser.close()
                proc,browser,page=start()
                final=invoke('list_tasks',{'includeCompleted':True});note=invoke('list_notes')[0]
                assert len(final)==1 and final[0]['status']=='done' and final[0]['due_at']==saved['due_at']
                assert note['title']=='Заметка из нового календаря' and 'Детали сохранились' in note['document']
                assert not errors,errors
                passed('A real restart retains calendar task status, the moved deadline and the shared quick note')
                page.get_by_role('button',name='Настройки',exact=True).click();page.get_by_role('button',name='Выход',exact=True).click();proc.wait(timeout=15);browser.close()
        finally:
            user32.SetCursorPos(original.x,original.y)
            for child in children:
                if child.poll() is None:child.terminate();child.wait(timeout=5)
            (OUT/'calendar-native-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
