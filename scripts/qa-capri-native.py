"""Native Capri appearance with isolated task DB and isolated WebView2 profile."""
import json
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import tempfile
import time
from threading import Event, Thread
import urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/qa'
RESULTS = []


def passed(name):
    RESULTS.append({'test': name, 'status': 'passed'})
    print(name, flush=True)


with tempfile.TemporaryDirectory(prefix='island-capri-native-') as temporary:
    folder = Path(temporary)
    env = dict(os.environ, PERSONAL_ISLAND_DB=str(folder / 'tasks.sqlite3'),
        PERSONAL_ISLAND_QA_DISABLE_SHORTCUT='1',
        WEBVIEW2_USER_DATA_FOLDER=str(folder / 'webview'),
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    children = []
    parking_done = Event()
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    def park_test_windows():
        # Keep the isolated test instance out of the owner's workspace. CDP
        # operates in WebView coordinates without moving the system cursor.
        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(window, parameter):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
            if pid.value in {child.pid for child in children if child.poll() is None}:
                rect = wintypes.RECT()
                user32.GetWindowRect(window, ctypes.byref(rect))
                if rect.right - rect.left >= 336 and rect.left != -8000:
                    user32.SetWindowPos(window, None, -8000, -8000, 0, 0, 0x15)
            return True
        while not parking_done.wait(.05):
            user32.EnumWindows(visit, 0)
    parking = Thread(target=park_test_windows, daemon=True)
    parking.start()
    with (OUT / 'capri-native-stderr.log').open('w', encoding='utf8') as log:
      try:
        with sync_playwright() as p:
          def start():
            app = subprocess.Popen([str(ROOT / 'target/debug/personal-island-desktop.exe'), '--show'],
                env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
            children.append(app)
            end = time.monotonic() + 30
            while True:
                assert app.poll() is None, 'Application exited'
                try:
                    urllib.request.urlopen('http://127.0.0.1:9222/json/version', timeout=1).close()
                    break
                except OSError:
                    assert time.monotonic() < end, 'WebView2 unavailable'
                    time.sleep(.2)
            browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
            page = browser.contexts[0].pages[0]
            page.emulate_media(reduced_motion='reduce')
            expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready', 'true')
            return app, browser, page

          def invoke(command, arguments=None):
            return page.evaluate('([c,a])=>window.__TAURI_INTERNALS__.invoke(c,a)', [command, arguments or {}])

          def stop(app, browser):
            page.evaluate("setTimeout(()=>window.__TAURI_INTERNALS__.invoke('exit_app'),50)")
            app.wait(timeout=10)
            browser.close()

          def open_settings():
            page.locator('.header-actions button[aria-expanded]').evaluate('(e)=>e.click()')
            expect(page.locator('.appearance-picker')).to_be_visible()

          app, browser, page = start()
          errors = []
          page.on('pageerror', lambda error: errors.append(str(error)))
          # Ensure the isolated browser profile is actually in use.
          assert (folder / 'webview').is_dir()
          assert page.evaluate('localStorage.getItem("personal-island.appearance.v1")') is None
          invoke('toggle_island_shortcut')
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
          invoke('toggle_island_shortcut')
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
          passed('The actual native shortcut command hides and reopens the Classic island')
          page.locator('.compact-stage [aria-label="Развернуть список задач"]').evaluate('(e)=>e.click()')
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden', 'false')
          page.locator('.pin-button').evaluate('(e)=>{if(e.getAttribute("aria-pressed")!=="true")e.click()}')
          open_settings()
          page.get_by_role('radio', name='Капри', exact=True).locator('..').evaluate('(e)=>e.click()')
          expect(page.get_by_role('radio', name='Капри', exact=True)).to_be_checked()
          page.screenshot(path=str(OUT / 'capri-native-settings.png'))
          page.locator('.settings-panel input[type=checkbox]').evaluate('(e)=>{e.checked=false;e.dispatchEvent(new Event("change",{bubbles:true}))}')
          page.locator('.collapse-button').evaluate('(e)=>e.click()')
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden', 'true')
          invoke('register_island_shortcut')
          face = page.locator('.capri-face')
          expect(face).to_be_visible()
          page.wait_for_timeout(450)
          assert page.evaluate('innerWidth') == 384 and page.evaluate('innerHeight') == 148
          assert face.bounding_box()['width'] == 272 and face.bounding_box()['height'] == 104
          expect(page.locator('.liquid-surface')).to_have_css('opacity', '0')
          page.screenshot(path=str(OUT / 'capri-native.png'))
          passed('Native compact bounds shrink to 384x148; the 272x104 Capri face remains readable and unclipped')

          invoke('toggle_island_shortcut')
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
          invoke('toggle_island_shortcut')
          expect(face).to_be_visible()
          assert page.evaluate('innerWidth') == 384

          face.locator('.capri-summary').evaluate('(e)=>e.click()')
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden', 'false')
          assert page.evaluate('innerWidth') == 760
          expect(page.locator('.dashboard')).to_have_css('background-color','rgb(8, 15, 13)')
          page.screenshot(path=str(OUT / 'capri-native-expanded.png'))
          page.locator('.pin-button').evaluate('(e)=>{if(e.getAttribute("aria-pressed")!=="true")e.click()}')
          expect(page.locator('.liquid-surface')).to_have_css('opacity', '1')
          invoke('toggle_island_shortcut')
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
          passed('The native shortcut hides Capri both compact and expanded/pinned without changing its bounds or appearance')
          stop(app, browser)
          assert not errors, errors

          app, browser, page = start()
          expect(page.locator('.capri-face')).to_be_visible()
          page.locator('.capri-clock').evaluate('(e)=>e.click()')
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden', 'false')
          page.locator('.pin-button').evaluate('(e)=>{if(e.getAttribute("aria-pressed")!=="true")e.click()}')
          open_settings()
          expect(page.get_by_role('radio', name='Капри', exact=True)).to_be_checked()
          expect(page.locator('.settings-panel input[type=checkbox]')).not_to_be_checked()
          expect(page.locator('.dashboard')).to_have_css('background-color','rgb(8, 15, 13)')
          passed('Capri and liquid preferences survive a real restart; eye clicks open the themed dashboard')

          page.get_by_role('radio', name='Островок', exact=True).locator('..').evaluate('(e)=>e.click()')
          page.locator('.collapse-button').evaluate('(e)=>e.click()')
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden', 'true')
          invoke('register_island_shortcut')
          expect(page.locator('.capri-face')).to_have_count(0)
          expect(page.locator('.compact-stage .pill')).to_be_visible()
          assert len(invoke('list_tasks', {'includeCompleted': True})) == 0
          passed('Classic appearance can be restored; tests leave personal tasks and the real browser profile untouched')
          stop(app, browser)
      except Exception:
        try:
            print('Native appearance state:', page.evaluate('''()=>({
                presentation:document.querySelector('.island-shell')?.dataset.presentation,
                hidden:document.querySelector('.island-shell')?.getAttribute('aria-hidden'),
                dashboardHidden:document.querySelector('.dashboard')?.getAttribute('aria-hidden'),
                shape:document.querySelector('.island-shell')?.getAttribute('style'),
                dashboardClip:getComputedStyle(document.querySelector('.dashboard')).clipPath,
                width:innerWidth
            })'''), flush=True)
            page.screenshot(path=str(OUT / 'capri-native-failure.png'))
        except Exception:
            pass
        raise
      finally:
        parking_done.set()
        parking.join(timeout=2)
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
        # WebView processes release their profile files shortly after the host.
        time.sleep(1)
        (OUT / 'capri-native-results.json').write_text(json.dumps(RESULTS, indent=2), encoding='utf8')
