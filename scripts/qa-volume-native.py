"""Hover/wheel volume in WebView2 against a silent, uniquely named test player.

Uses a temporary database/profile. Never changes the owner's player or master gain.
Requires a debug desktop build, qa-media example, Pillow and Playwright.
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from threading import Event, Thread
import time
import urllib.request
import wave
from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'artifacts/qa'
OUT.mkdir(parents=True, exist_ok=True)
RESULTS = []

def master_volume():
    return float(subprocess.check_output(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT/'scripts/qa-master-volume.ps1')],
        text=True, creationflags=subprocess.CREATE_NO_WINDOW).strip())

with tempfile.TemporaryDirectory(prefix='island-volume-') as temporary:
    folder = Path(temporary)
    fixture_name = folder.name+'.exe'
    # A unique executable ID lets Core Audio match only this silent process.
    shutil.copy2(ROOT/'target/debug/examples/qa-media.exe', folder/fixture_name)
    with wave.open(str(folder/'silence.wav'), 'wb') as audio:
        audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0\0'*8000*180)
    Image.new('RGB', (96, 96), '#637e68').save(folder/'cover.png')
    env = dict(os.environ, PERSONAL_ISLAND_DB=str(folder/'tasks.sqlite3'),
               PERSONAL_ISLAND_QA_DISABLE_SHORTCUT='1',
               WEBVIEW2_USER_DATA_FOLDER=str(folder/'webview'),
               WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    env.pop('PERSONAL_ISLAND_QA_MEDIA_ID', None)
    app = fixture = None
    done = Event()
    user32 = ctypes.WinDLL('user32')
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    def park():
        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(window, parameter):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
            if app and owner.value == app.pid:
                user32.SetWindowPos(window, None, -8000, -8000, 0, 0, 0x15)
            return True
        while not done.wait(.05): user32.EnumWindows(visit, 0)
    parking = Thread(target=park, daemon=True)
    parking.start()
    initial_master = master_volume()
    with (OUT/'volume-native-stderr.log').open('w', encoding='utf8') as log:
      try:
        fixture = subprocess.Popen([str(folder/fixture_name), str(folder)], env=env,
            stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        app = subprocess.Popen([str(ROOT/'target/debug/personal-island-desktop.exe'), '--show'], env=env,
            stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        limit = time.monotonic()+30
        while True:
            assert app.poll() is None, 'Application exited'
            try:
                urllib.request.urlopen('http://127.0.0.1:9222/json/version', timeout=1).close()
                break
            except OSError:
                assert time.monotonic()<limit, 'WebView unavailable'
                time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
            page = browser.contexts[0].pages[0]
            page.emulate_media(reduced_motion='reduce')
            def invoke(command, args=None):
                return page.evaluate('([c,a])=>window.__TAURI_INTERNALS__.invoke(c,a)', [command, args or {}])
            def wait_volume(expected):
                limit = time.monotonic()+8
                while abs(invoke('player_volume', {'sessionId':source, 'level':None})['level']-expected)>.006:
                    assert time.monotonic()<limit, 'Actual Core Audio player volume did not change'
                    page.wait_for_timeout(100)
            def wait_overlay(opened):
                limit = time.monotonic()+8
                while True:
                    height = page.evaluate('() => window.innerHeight')
                    if (opened and height>=248) or (not opened and height<220): return
                    assert time.monotonic()<limit, f'Native overlay size did not update: {height}'
                    page.wait_for_timeout(100)
            expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
            page.wait_for_timeout(2300)
            invoke('reveal_island_shortcut')
            page.wait_for_timeout(150)
            page.locator('.compact-stage button.pill,.compact-stage .compact-open,.track-peek .peek-art').first.evaluate('(e)=>e.click()')
            expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
            page.locator('.pin-button').evaluate('(e)=>e.click()')
            page.get_by_role('button',name='Музыка',exact=True).click()
            source = None
            limit = time.monotonic()+15
            while not source:
                source = next((s['id'] for s in invoke('get_media_state', {'preferred':None})['sessions']
                               if fixture_name.lower() in s['id'].lower()), None)
                assert time.monotonic()<limit, 'Unique silent player did not register'
                page.wait_for_timeout(100)
            page.get_by_label('Источник музыки').select_option(source)
            expect(page.locator('.track-info h2')).to_have_text('QA Track 1')
            # Let the newly selected player's first-track notification settle.
            page.wait_for_timeout(2300)
            invoke('reveal_island_shortcut')
            page.wait_for_timeout(150)
            page.locator('.compact-stage button.pill,.compact-stage .compact-open,.track-peek .peek-art').first.evaluate('(e)=>e.click()')
            expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
            page.locator('.pin-button').evaluate('(e)=>e.click()')
            assert invoke('player_volume', {'sessionId':source, 'level':.65})['available']
            trigger = page.locator('.music-panel .volume-trigger')
            slider = page.locator('.music-panel .volume-popover input')
            trigger.hover()
            expect(slider).to_be_enabled()
            page.mouse.wheel(0,100)
            wait_volume(.60)
            expect(page.locator('.music-panel .volume-popover output')).to_have_text('60%')
            page.mouse.wheel(0,-200)
            wait_volume(.70)
            expect(page.locator('.music-panel .volume-popover output')).to_have_text('70%')
            page.mouse.move(20,480)
            expect(slider).to_have_count(0)
            expect(trigger).to_have_attribute('aria-expanded','false')
            trigger.focus(); trigger.press('Enter')
            expect(slider).to_be_focused()
            slider.press('Escape')
            expect(slider).to_have_count(0)
            # Exercise the actual compact artwork, not just the speaker icon.
            page.get_by_role('button',name='Свернуть',exact=True).evaluate('(e)=>e.click()')
            invoke('reveal_island_shortcut')
            cover = page.locator('.compact-cover')
            expect(cover).to_be_visible()
            cover.hover()
            cover_slider = page.locator('.cover-volume .volume-popover input')
            expect(cover_slider).to_have_count(0)
            page.mouse.wheel(0,100)
            wait_volume(.65)
            expect(cover_slider).to_be_enabled()
            wait_overlay(True)
            expect(page.locator('.cover-volume output')).to_have_text('65%')
            cover_slider.hover();page.wait_for_timeout(350)
            expect(cover_slider).to_be_visible()
            cover_slider.fill('60');wait_volume(.60)
            cover.hover()
            page.mouse.wheel(0,-100)
            wait_volume(.65)
            expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
            expect(page.locator('.compact-stage')).to_have_css('height','56px')
            page.mouse.move(20,480)
            expect(cover_slider).to_have_count(0)
            wait_overlay(False)
            cover.hover()
            expect(cover_slider).to_have_count(0)
            assert invoke('get_media_state', {'preferred':source})['playing']
            assert abs(master_volume()-initial_master)<.0001, 'Master system volume changed'
            RESULTS.append({'test':'Native icon and compact artwork wheel change only the silent player; no pause or expansion; auto-close and keyboard work; master gain unchanged','status':'passed'})
            print(RESULTS[-1]['test'], flush=True)
            page.evaluate("setTimeout(()=>window.__TAURI_INTERNALS__.invoke('exit_app'),30)")
            app.wait(timeout=10)
            browser.close()
      finally:
        if app and app.poll() is None: app.terminate(); app.wait(timeout=10)
        if fixture and fixture.poll() is None:
            (folder/'stop-media').touch(); fixture.wait(timeout=10)
        done.set(); parking.join(timeout=2)
        fragment = (folder.name+'\\webview').replace("'", "''")
        cleanup = "$profileFragment='"+fragment+"'; Get-CimInstance Win32_Process -Filter \"Name='msedgewebview2.exe'\" | Where-Object {$_.CommandLine -and $_.CommandLine.ToLowerInvariant().Contains($profileFragment.ToLowerInvariant())} | ForEach-Object {Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue}"
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',cleanup],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        time.sleep(1)

(OUT/'volume-native-results.json').write_text(json.dumps(RESULTS,indent=2),encoding='utf8')
