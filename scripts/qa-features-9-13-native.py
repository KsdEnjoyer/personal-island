"""Exercise real media, settings and timer flows on a temporary DB/profile only.

Requires a debug desktop build, the qa-media Rust example and Python Playwright.
Uses a silent local test player; never sends commands to the owner's music.
"""
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Event, Thread
import time
import urllib.request
import wave
from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/qa'
OUT.mkdir(parents=True, exist_ok=True)
RESULTS = []


def passed(name):
    RESULTS.append({'test': name, 'status': 'passed'})
    print(name, flush=True)


with tempfile.TemporaryDirectory(prefix='island-features-9-13-') as temporary:
    folder = Path(temporary)
    env = dict(os.environ, PERSONAL_ISLAND_DB=str(folder/'tasks.sqlite3'),
               PERSONAL_ISLAND_QA_REVEAL_SECONDS='4',
               WEBVIEW2_USER_DATA_FOLDER=str(folder/'webview'),
               WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    # The real keyboard observer is intentionally enabled for rebinding tests.
    env.pop('PERSONAL_ISLAND_QA_DISABLE_SHORTCUT', None)
    app = None
    fixture = None
    parking_done = Event()
    user32 = ctypes.WinDLL('user32')
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]

    def park():
        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(window, parameter):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
            if app and app.poll() is None and owner.value == app.pid:
                user32.SetWindowPos(window, None, -8000, -8000, 0, 0, 0x15)
            return True
        while not parking_done.wait(.05):
            user32.EnumWindows(visit, 0)

    parking = Thread(target=park, daemon=True)
    parking.start()
    with (OUT/'features-9-13-stderr.log').open('w', encoding='utf8') as log:
      try:
        with wave.open(str(folder/'silence.wav'), 'wb') as audio:
            audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            audio.writeframes(b'\0\0' * 8000 * 180)
        Image.new('RGB', (96, 96), '#637e68').save(folder/'cover.png')
        fixture = subprocess.Popen([str(ROOT/'target/debug/examples/qa-media.exe'), str(folder)],
                                   env=dict(os.environ, PERSONAL_ISLAND_QA_MEDIA_ID=folder.name),
                                   stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        with sync_playwright() as p:
          def start():
              global app
              app = subprocess.Popen([str(ROOT/'target/debug/personal-island-desktop.exe')],
                                     env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
              deadline = time.monotonic()+30
              while True:
                  assert app.poll() is None, 'Application exited'
                  try:
                      urllib.request.urlopen('http://127.0.0.1:9222/json/version', timeout=1).close()
                      break
                  except OSError:
                      assert time.monotonic() < deadline, 'WebView unavailable'
                      time.sleep(.1)
              browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
              page = browser.contexts[0].pages[0]
              page.emulate_media(reduced_motion='reduce')
              expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready', 'true')
              return browser, page

          def invoke(command, args=None):
              return page.evaluate('([c,a])=>window.__TAURI_INTERNALS__.invoke(c,a)', [command, args or {}])

          def wait(predicate, message, seconds=15):
              until = time.monotonic()+seconds
              while not predicate():
                  assert time.monotonic() < until, message
                  page.wait_for_timeout(100)

          def stop():
              page.evaluate("setTimeout(()=>window.__TAURI_INTERNALS__.invoke('exit_app'),30)")
              app.wait(timeout=10)
              browser.close()
              time.sleep(.5)

          def show_dashboard():
              invoke('reveal_island_shortcut')
              expect(page.locator('.island-shell')).to_have_attribute('aria-hidden', 'false')
              page.wait_for_timeout(100)
              page.locator('.compact-stage button[aria-label="Развернуть список задач"]').first.evaluate('(button)=>button.click()')
              expect(page.locator('.island-shell')).to_have_class(__import__('re').compile(r'expanded'))
              page.get_by_role('button', name='Закрепить островок', exact=True).click()

          def global_combo():
              for key in [0x11, 0x12, 0x49]: user32.keybd_event(key, 0, 0, 0)
              for key in [0x49, 0x12, 0x11]: user32.keybd_event(key, 0, 2, 0)

          browser, page = start()
          page.wait_for_timeout(2300)
          settings = invoke('get_widget_settings')
          assert settings['review_interval_minutes'] == 30 and settings['shortcut']['key'] == 192
          settings['review_interval_minutes'] = 0
          invoke('set_widget_settings', {'settings': settings})
          show_dashboard()
          page.get_by_role('button', name='Настройки', exact=True).click()
          page.get_by_label('Интервал автопоказа', exact=True).select_option('0')
          wait(lambda: invoke('get_widget_settings')['review_interval_minutes']==0, 'Periodic off switch was not saved')
          page.get_by_role('button', name='Закрыть настройки', exact=True).click()
          page.get_by_role('button', name='Музыка', exact=True).click()
          wait(lambda: any('qa-media' in s['id'].lower() for s in invoke('get_media_state', {'preferred': None})['sessions']), 'Fixture not registered')
          state = invoke('get_media_state', {'preferred': None})
          source = next(s['id'] for s in state['sessions'] if 'qa-media' in s['id'].lower())
          page.get_by_label('Источник музыки').select_option(source)
          expect(page.locator('.track-info h2')).to_have_text('QA Track 1')
          (folder/'pause-media').touch()
          wait(lambda: not invoke('get_media_state', {'preferred': source})['playing'], 'External pause not observed')
          page.get_by_role('button', name='Свернуть', exact=True).click()
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden', 'true')
          invoke('reveal_island_shortcut')
          expect(page.locator('.music-pill .compact-cover')).to_have_attribute('aria-label', 'Продолжить музыку')
          expect(page.locator('.compact-seek input')).to_be_enabled()
          passed('External pause survives hide/reveal and retains the compact player')
          slider = page.locator('.compact-seek input')
          bounds = slider.bounding_box()
          assert bounds
          slider.evaluate("el=>{window.__seekEvents=[];for(const type of ['pointerdown','pointercancel','input','change','blur'])el.addEventListener(type,()=>window.__seekEvents.push({type,value:el.value}));}")
          slider.click(position={'x':bounds['width']/3, 'y':bounds['height']/2})
          wait(lambda: (folder/'media-position.txt').exists() and abs(int((folder/'media-position.txt').read_text())/10_000_000-60)<3, 'The real test player did not seek')
          try:
              wait(lambda: abs(invoke('get_media_state', {'preferred': source})['position']-60)<3, 'Native seek did not move the paused fixture')
          except AssertionError:
              state = invoke('get_media_state', {'preferred':source})
              print(json.dumps({'fixture_actual_position':(folder/'media-position.txt').read_text() if (folder/'media-position.txt').exists() else None,'fixture_seek_event':(folder/'seek-received.txt').read_text() if (folder/'seek-received.txt').exists() else None}),flush=True)
              print(json.dumps({'seek_events':page.evaluate('window.__seekEvents'),'position':state['position'],'duration':state['duration'],'seek_status':page.locator('.compact-seek .track-seek').get_attribute('data-seek-status'),'seek_errors':page.locator('.compact-seek .seek-error').all_text_contents()}),flush=True)
              raise
          assert not invoke('get_media_state', {'preferred': source})['playing']
          page.wait_for_timeout(500)
          page.screenshot(path=str(OUT/'features-9-13-paused.png'))
          passed('Compact slider performs a real native seek without resuming or expanding')
          show_dashboard()
          page.get_by_role('button', name='Сегодня', exact=True).click()
          timer = page.locator('.focus-panel .focus-timer')
          timer.get_by_label('Время таймера, минуты').fill('17')
          timer.get_by_role('button', name='Задать', exact=True).click()
          expect(timer.locator('strong')).to_have_text('17:00')
          timer.get_by_role('button', name='Запустить таймер', exact=True).click()
          timer.get_by_label('Время таймера, минуты').fill('3')
          timer.get_by_role('button', name='Добавить', exact=True).click()
          expect(timer.get_by_role('button', name='Приостановить таймер', exact=True)).to_be_visible()
          expect(timer.locator('.timer-meta')).to_contain_text('Всего 20 мин')
          page.get_by_role('button', name='Заметки', exact=True).click()
          expect(page.locator('.focus-panel .focus-timer .timer-meta')).to_contain_text('Всего 20 мин')
          page.locator('.focus-panel').get_by_role('button', name='Приостановить таймер', exact=True).click()
          page.screenshot(path=str(OUT/'features-9-13-notes.png'))
          passed('Today and Notes share the same timer; custom additions keep a running timer running')
          page.get_by_role('button', name='Настройки', exact=True).click()
          recorder = page.get_by_label('Сочетание для показа островка')
          recorder.click()
          recorder.press('Control+Alt+i')
          expect(recorder).to_have_value('Ctrl + Alt + I')
          saved = invoke('get_widget_settings')
          assert saved['shortcut'] == {'key':73,'ctrl':True,'alt':True,'shift':False}
          reserved = next((key for key in [0x4F,0x50,0x55] if user32.RegisterHotKey(None,99,3,key)), None)
          assert reserved, 'Could not reserve a fixture shortcut'
          try:
              conflict = dict(saved, shortcut={'key':reserved,'ctrl':True,'alt':True,'shift':False})
              try:
                  invoke('set_widget_settings', {'settings':conflict})
                  raise AssertionError('Conflicting shortcut was accepted')
              except Exception as error:
                  assert 'AssertionError' not in type(error).__name__
              assert invoke('get_widget_settings')['shortcut']==saved['shortcut']
          finally:
              user32.UnregisterHotKey(None,99)
          passed('A Windows shortcut conflict is rejected without losing the previous saved binding')
          page.get_by_role('button', name='Закрыть настройки', exact=True).click()
          page.get_by_role('button', name='Свернуть', exact=True).click()
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden', 'true')
          global_combo()
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden', 'false')
          global_combo()
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden', 'true')
          page.wait_for_timeout(5500)
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden', 'true')
          passed('A recorded Ctrl+Alt+I really toggles the island globally; disabled periodic shows stay disabled')
          show_dashboard()
          page.get_by_role('button', name='Настройки', exact=True).click()
          page.get_by_label('Интервал автопоказа', exact=True).select_option('-1')
          page.get_by_label('Свой интервал автопоказа, минуты').fill('45')
          page.get_by_role('button', name='Применить', exact=True).click()
          wait(lambda: invoke('get_widget_settings')['review_interval_minutes']==45, 'Custom interval not saved')
          page.screenshot(path=str(OUT/'features-9-13-settings.png'))
          stop()
          browser, page = start()
          restored = invoke('get_widget_settings')
          assert restored['review_interval_minutes']==45 and restored['shortcut']['key']==73
          restored['review_interval_minutes']=0
          invoke('set_widget_settings', {'settings':restored})
          show_dashboard()
          expect(page.locator('.home-panel kbd')).to_have_count(0)
          expect(page.locator('.focus-timer strong')).to_have_text('17:00')
          passed('Custom shortcut, interval and chosen timer duration survive a native restart; redundant home hint is gone')
          # Closed fixture disappears instead of persisting as a stale paused player.
          (folder/'stop-media').touch()
          fixture.wait(timeout=8)
          wait(lambda: not any(s['id']==source for s in invoke('get_media_state', {'preferred':source})['sessions']), 'Closed player is still published')
          page.get_by_role('button', name='Свернуть', exact=True).click()
          future = (datetime.now(timezone.utc)+timedelta(seconds=3)).isoformat()
          task = invoke('create_task', {'task':{'title':'QA exact reminder with periodic disabled','due_at':future,'reminder_at':future}})
          expect(page.locator('.compact-stage .reminder-notice strong')).to_have_text(task['title'], timeout=20000)
          assert invoke('list_tasks', {'includeCompleted':True})[0]['status']=='open'
          passed('Closing the player removes its session; exact task reminders still arrive with periodic shows disabled')
          stop()
      finally:
        if app and app.poll() is None: app.terminate(); app.wait(timeout=10)
        if fixture and fixture.poll() is None:
            (folder/'stop-media').touch()
            fixture.wait(timeout=10)
        parking_done.set(); parking.join(timeout=2)
        fragment=(folder.name+'\\webview').replace("'","''")
        cleanup="$profileFragment='"+fragment+"'; Get-CimInstance Win32_Process -Filter \"Name='msedgewebview2.exe'\" | Where-Object {$_.CommandLine -and $_.CommandLine.ToLowerInvariant().Contains($profileFragment.ToLowerInvariant())} | ForEach-Object {Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue}"
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',cleanup], stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
        time.sleep(1)

(OUT/'features-9-13-results.json').write_text(json.dumps(RESULTS,indent=2),encoding='utf8')
