"""Actual Windows hotkey / hidden-window tests with a temporary database."""
import ctypes
from ctypes import wintypes
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect
from qa_win import press_reveal, user32

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'artifacts/qa'
results = []
def passed(name):
    results.append({'test':name,'status':'passed'})
    print(name,flush=True)

user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
user32.SetCursorPos.argtypes = [ctypes.c_int,ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
def find_window(pid):
    found = []
    def visit(hwnd,_):
        process = wintypes.DWORD(); user32.GetWindowThreadProcessId(hwnd,ctypes.byref(process))
        title = ctypes.create_unicode_buffer(256); user32.GetWindowTextW(hwnd,title,256)
        if process.value == pid and title.value == 'Personal Island': found.append(hwnd)
        return True
    user32.EnumWindows(CALLBACK(visit),0)
    return found[0] if found else None

with tempfile.TemporaryDirectory(prefix='personal-island-hotkey-') as temp:
    env = dict(os.environ,PERSONAL_ISLAND_DB=str(Path(temp)/'tasks.sqlite3'),
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    original_cursor = wintypes.POINT(); user32.GetCursorPos(ctypes.byref(original_cursor))
    foreground = user32.GetForegroundWindow()
    user32.SetCursorPos(20,500)
    with (OUT/'hotkey-native-stderr.log').open('w',encoding='utf-8') as log:
        proc = subprocess.Popen([str(ROOT/'target/debug/personal-island-desktop.exe')],env=env,
            stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic()+30
            while True:
                assert proc.poll() is None,proc.returncode
                try:
                    urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1).close(); break
                except OSError:
                    if time.monotonic()>deadline: raise TimeoutError('WebView2 unavailable')
                    time.sleep(.25)
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
                page = browser.contexts[0].pages[0]
                expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
                hwnd = find_window(proc.pid); assert hwnd
                assert not user32.IsWindowVisible(hwnd)
                passed('Native startup is hidden, global shortcut registered')
                foreground = user32.GetForegroundWindow()
                press_reveal()
                expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
                expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
                assert page.evaluate('innerWidth') == 336
                assert user32.IsWindowVisible(hwnd)
                assert user32.GetForegroundWindow() != hwnd, 'Reveal took keyboard focus'
                assert user32.GetForegroundWindow() == foreground, f'Foreground changed: {foreground} -> {user32.GetForegroundWindow()}, island {hwnd}'
                passed('Physical OEM grave/yo key opens the window from another app without taking focus')
                user32.SetCursorPos(20,500)
                try:
                    deadline = time.monotonic()+7.5
                    while time.monotonic() < deadline and page.locator('.island-shell').get_attribute('aria-hidden') != 'true':
                        user32.SetCursorPos(20,500)
                        page.wait_for_timeout(100)
                    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true',timeout=100)
                except Exception:
                    print('Presentation diagnostic:',json.dumps(page.evaluate('''() => ({
                      visibility:document.visibilityState,focus:document.hasFocus(),
                      time:Date.now(), state:document.querySelector('.island-shell').dataset.presentation,
                      shapeWidth:document.querySelector('.island-shell').style.getPropertyValue('--shape-width'),
                      shapeHeight:document.querySelector('.island-shell').style.getPropertyValue('--shape-height'),
                      cssHover:document.querySelector('.island-interaction').matches(':hover'),
                      root:document.querySelector('.island-shell').outerHTML.slice(0,350)
                    })''')),flush=True)
                    raise
                assert not user32.IsWindowVisible(hwnd)
                passed('Unattended native window fully disappears after five seconds')

                press_reveal()
                expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
                expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
                page.wait_for_timeout(900)
                rect = wintypes.RECT(); user32.GetWindowRect(hwnd,ctypes.byref(rect))
                seen_native_hover = False
                deadline = time.monotonic()+2
                while time.monotonic() < deadline:
                    user32.SetCursorPos((rect.left+rect.right)//2,rect.top+30)
                    page.wait_for_timeout(100)
                    seen_native_hover |= page.locator('.island-shell').get_attribute('data-native-hover') == 'true'
                assert seen_native_hover, 'Native cursor heartbeat never saw the pointer inside the island'
                deadline = time.monotonic()+5.6
                while time.monotonic() < deadline:
                    user32.SetCursorPos((rect.left+rect.right)//2,rect.top+30)
                    page.wait_for_timeout(100)
                    assert user32.IsWindowVisible(hwnd)
                user32.SetCursorPos(20,500)
                expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true',timeout=2500)
                assert not user32.IsWindowVisible(hwnd)
                passed('Native hover keeps the panel alive; leaving dismisses it')

                press_reveal()
                page.locator('.pill').click()
                expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
                page.get_by_role('button',name='Закрепить островок').click()
                user32.SetForegroundWindow(hwnd)
                page.locator('.add-task').click()
                page.get_by_label('Название задачи').fill('Native text ')
                page.wait_for_timeout(200)
                assert page.evaluate('document.hasFocus()'), 'Native window could not receive focus'
                press_reveal()
                expect(page.get_by_label('Название задачи')).to_have_value(re.compile(r'^Native text [`ёЁ]$'))
                passed('The real grave/yo key types normally inside the task input')
                page.get_by_role('button',name='Отмена',exact=True).click()
                page.get_by_role('button',name='Свернуть',exact=True).click()
                expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
                page.wait_for_timeout(200)
                press_reveal()
                expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
                expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
                passed('Shortcut is restored after editing and hiding')

                # A previous reveal's late hide command must never hide a new reveal.
                page.evaluate("window.__TAURI_INTERNALS__.invoke('hide_island',{generation:1})")
                assert user32.IsWindowVisible(hwnd)
                passed('Stale hide generation is ignored by the native host')
                page.locator('.pill').click()
                page.get_by_role('button',name='Настройки').click()
                page.get_by_role('button',name='Выход',exact=True).click()
                proc.wait(timeout=10); browser.close()
        finally:
            if proc.poll() is None: proc.terminate(); proc.wait(timeout=10)
            user32.SetCursorPos(original_cursor.x,original_cursor.y)
            if foreground: user32.SetForegroundWindow(foreground)
            (OUT/'hotkey-native-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
