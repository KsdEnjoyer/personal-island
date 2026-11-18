"""Real SPb API/cache and native compact cover from a controlled media session."""
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time
import urllib.request
import wave
import zlib
from playwright.sync_api import sync_playwright, expect
from qa_win import press_reveal
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/qa'
results=[]
def passed(name):results.append({'test':name,'status':'passed'});print(name,flush=True)
def wait_cdp(proc):
    deadline=time.monotonic()+30
    while True:
        assert proc.poll() is None,'App exited'
        try:urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1).close();return
        except OSError:
            if time.monotonic()>deadline:raise TimeoutError('WebView unavailable')
            time.sleep(.25)

with tempfile.TemporaryDirectory(prefix='personal-island-weather-') as temp:
    folder=Path(temp)
    env=dict(os.environ,PERSONAL_ISLAND_DB=str(folder/'tasks.sqlite3'),WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    processes=[]
    with (OUT/'weather-native-stderr.log').open('w',encoding='utf-8') as log:
        try:
            def launch():
                proc=subprocess.Popen([str(ROOT/'target/debug/personal-island-desktop.exe')],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                processes.append(proc);wait_cdp(proc);return proc
            proc=launch()
            with sync_playwright() as p:
                browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222')
                page=browser.contexts[0].pages[0]
                expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
                def invoke(cmd,args=None):return page.evaluate('([cmd,args])=>window.__TAURI_INTERNALS__.invoke(cmd,args)',[cmd,args or {}])
                weather=invoke('get_weather')
                assert weather['data'] and not weather['stale'],weather['error']
                assert weather['data']['city']=='Санкт-Петербург'
                assert len(weather['data']['daily'])==5
                assert (folder/'weather.json').is_file()
                fetched_at=weather['data']['fetched_at']
                assert invoke('get_weather')['data']['fetched_at']==fetched_at
                passed('Native HTTPS fetch returns real SPb weather and reuses the persisted cache')
                # Local test-only artwork; no user images or clipboard content are read.
                def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
                pixels=b''.join(b'\x00'+bytes([142,75,48,255])*64 for _ in range(64))
                png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',64,64,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')
                (folder/'cover.png').write_bytes(png)
                with wave.open(str(folder/'silence.wav'),'wb') as wav:
                    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000);wav.writeframes(b'\0\0'*8000*60)
                fixture=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/qa-media-fixture.ps1'),'-Folder',str(folder)],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                processes.append(fixture)
                selected=None;deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    assert fixture.poll() is None,'Media fixture failed'
                    state=invoke('get_media_state',{'preferred':None})
                    for source in state['sessions']:
                        candidate=invoke('get_media_state',{'preferred':source['id']})
                        if candidate['title']=='QA Island Media Track' and candidate['artwork']:
                            selected=candidate;break
                    if selected:break
                    page.wait_for_timeout(250)
                assert selected,'Native session cover unavailable'
                press_reveal();page.locator('.pill').click()
                page.get_by_role('button',name='Закрепить островок').click()
                page.get_by_role('button',name='Музыка',exact=True).click()
                page.get_by_label('Источник музыки').select_option(selected['session_id'])
                expect(page.locator('.track-info h2')).to_have_text('QA Island Media Track',timeout=6000)
                invoke('media_command',{'sessionId':selected['session_id'],'action':'toggle'})
                expect(page.get_by_label('Продолжить музыку')).to_be_visible(timeout=6000)
                page.get_by_label('Продолжить музыку').focus()
                page.wait_for_timeout(150)
                press_reveal()
                expect(page.locator('.pill-artwork')).to_be_visible(timeout=6000)
                assert page.locator('.pill-artwork').evaluate('el=>el.complete&&el.naturalWidth>0')
                expect(page.locator('.pill-paused')).to_be_visible(timeout=6000)
                expect(page.locator('.pill-weather')).to_be_visible()
                passed('Compact native island renders a real Windows session cover on pause alongside weather')
                page.locator('.pill').click()
                page.get_by_role('button',name='Закрепить островок').click()
                page.get_by_role('button',name='Погода',exact=True).click()
                expect(page.locator('.weather-temperature')).to_be_visible()
                expect(page.locator('.weather-day')).to_have_count(5)
                passed('Native weather tab displays actual forecast data')
                (folder/'stop-media').touch();fixture.wait(timeout=10)
                page.get_by_role('button',name='Настройки').click();page.get_by_role('button',name='Выход',exact=True).click()
                proc.wait(timeout=10);browser.close()
                proc=launch()
                browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222');page=browser.contexts[0].pages[0]
                expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
                assert invoke('get_weather')['data']['fetched_at']==fetched_at
                passed('A native restart retains the same fresh weather cache')
                press_reveal();page.locator('.pill').click()
                page.get_by_role('button',name='Настройки').click();page.get_by_role('button',name='Выход',exact=True).click()
                proc.wait(timeout=10);browser.close()
        finally:
            (folder/'stop-media').touch()
            for child in processes:
                if child.poll() is None:child.terminate();child.wait(timeout=5)
            (OUT/'weather-native-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
