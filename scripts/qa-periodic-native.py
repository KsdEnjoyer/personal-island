"""Real native periodic reveal, accelerated only in the debug build."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect
from qa_win import user32

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'artifacts/qa'
results=[]
def passed(name):
    results.append({'test':name,'status':'passed'})
    print(name,flush=True)

original = wintypes.POINT(); user32.GetCursorPos(ctypes.byref(original))
foreground = user32.GetForegroundWindow()
with tempfile.TemporaryDirectory(prefix='personal-island-periodic-') as temp:
    env=dict(os.environ, PERSONAL_ISLAND_DB=str(Path(temp)/'tasks.sqlite3'),
        PERSONAL_ISLAND_QA_REVEAL_SECONDS='10',
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    with (OUT/'periodic-native-stderr.log').open('w',encoding='utf-8') as log:
        proc=subprocess.Popen([str(ROOT/'target/debug/personal-island-desktop.exe')],env=env,
            stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline=time.monotonic()+30
            while True:
                assert proc.poll() is None
                try:
                    urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1).close(); break
                except OSError:
                    if time.monotonic()>deadline: raise TimeoutError('WebView unavailable')
                    time.sleep(.25)
            with sync_playwright() as p:
                browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222')
                page=browser.contexts[0].pages[0]
                expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
                user32.SetCursorPos(20,500)
                expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
                page.wait_for_timeout(1200)
                expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
                passed('Periodic scheduler waits for its first interval')
                expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false',timeout=12000)
                expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
                assert page.evaluate('innerWidth') == 336
                assert user32.GetForegroundWindow() == foreground
                passed('Native scheduler reveals only the compact island without taking focus')
                deadline=time.monotonic()+7
                while time.monotonic()<deadline and page.locator('.island-shell').get_attribute('aria-hidden')!='true':
                    user32.SetCursorPos(20,500); page.wait_for_timeout(100)
                expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
                passed('Unattended automatic reveal expires after five seconds')
                expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false',timeout=12000)
                page.locator('.pill').click()
                page.get_by_role('button',name='Закрепить островок').click()
                page.locator('.add-task').click()
                page.get_by_label('Название задачи').fill('Unsaved periodic draft')
                page.wait_for_timeout(11000)
                expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
                expect(page.get_by_label('Название задачи')).to_have_value('Unsaved periodic draft')
                passed('A scheduled tick leaves the active dashboard and draft intact')
                page.get_by_role('button',name='Отмена',exact=True).click()
                page.get_by_role('button',name='Настройки').click()
                page.get_by_role('button',name='Выход',exact=True).click()
                proc.wait(timeout=10); browser.close()
        finally:
            if proc.poll() is None: proc.terminate(); proc.wait(timeout=10)
            user32.SetCursorPos(original.x,original.y)
            (OUT/'periodic-native-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
