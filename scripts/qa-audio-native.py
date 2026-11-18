"""Real WASAPI loopback, bounded events and suspend/resume with an isolated app."""
import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time
import urllib.request
import wave
import winsound
from threading import Event,Thread
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/qa'
RESULTS=[]
def passed(name,**metrics):
    RESULTS.append({'test':name,'status':'passed',**metrics})
    print(name,metrics,flush=True)

with tempfile.TemporaryDirectory(prefix='island-audio-') as temporary:
    folder=Path(temporary)
    env=dict(os.environ,PERSONAL_ISLAND_DB=str(folder/'tasks.sqlite3'),PERSONAL_ISLAND_QA_DISABLE_SHORTCUT='1',
        WEBVIEW2_USER_DATA_FOLDER=str(folder/'webview'),WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    app=None
    parked=Event()
    user32=ctypes.WinDLL('user32')
    user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user32.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
    def park():
        @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        def visit(window,parameter):
            owner=wintypes.DWORD()
            user32.GetWindowThreadProcessId(window,ctypes.byref(owner))
            if app and owner.value==app.pid:
                user32.SetWindowPos(window,None,-8000,-8000,0,0,0x15)
            return True
        while not parked.wait(.05):user32.EnumWindows(visit,0)
    parking=Thread(target=park,daemon=True)
    parking.start()
    with (OUT/'audio-native-stderr.log').open('w',encoding='utf8') as log:
      try:
        app=subprocess.Popen([str(ROOT/'target/debug/personal-island-desktop.exe'),'--show'],env=env,
            stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        deadline=time.monotonic()+30
        while True:
            assert app.poll() is None,'Application exited'
            try:urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1).close();break
            except OSError:
                assert time.monotonic()<deadline,'WebView unavailable'
                time.sleep(.1)
        with sync_playwright() as p:
          browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222')
          page=browser.contexts[0].pages[0]
          expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
          page.emulate_media(reduced_motion='no-preference')
          page.locator('.compact-stage [aria-label="Развернуть список задач"]').evaluate('(e)=>e.click()')
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
          page.locator('.pin-button').evaluate('(e)=>e.click()')
          def invoke(command,args=None):
              return page.evaluate('([cmd,args])=>window.__TAURI_INTERNALS__.invoke(cmd,args)',[command,args or {}])
          page.evaluate('''async()=>{
            window.qaAudioFrames=[];
            const handler=window.__TAURI_INTERNALS__.transformCallback(event=>qaAudioFrames.push({...event.payload,time:performance.now()}));
            await window.__TAURI_INTERNALS__.invoke('plugin:event|listen',{event:'island-audio',target:{kind:'Any'},handler});
          }''')
          invoke('set_audio_reactivity',{'enabled':True})
          limit=time.monotonic()+5
          while not invoke('get_audio_reactivity')['streaming']:
              assert time.monotonic()<limit,invoke('get_audio_reactivity')
              page.wait_for_timeout(100)
          passed('The packaged app opens the real Windows render loopback')

          # Modest 75 Hz test kicks. No master or player volume setting changes.
          path=folder/'bass.wav'
          with wave.open(str(path),'wb') as output:
              output.setparams((2,2,48000,0,'NONE','not compressed'))
              for i in range(48000*4):
                  t=i/48000
                  amplitude=.002 if t<1.4 else (.14*math.exp(-((t-1.4)%.4)*12) if t<3.2 else 0)
                  value=round(math.sin(2*math.pi*75*t)*amplitude*32767)
                  output.writeframesraw(struct.pack('<hh',value,value))
          start=page.evaluate('performance.now()')
          winsound.PlaySound(str(path),winsound.SND_FILENAME|winsound.SND_ASYNC)
          page.wait_for_timeout(4250)
          winsound.PlaySound(None,0)
          frames=page.evaluate('qaAudioFrames')
          measured=[f for f in frames if f['available'] and start+1400<=f['time']<=start+3300]
          assert len(measured)>20,len(measured)
          bass=max(f['bass'] for f in measured)
          impact=max(f['impact'] for f in measured)
          assert bass>.1 and impact>.1,(bass,impact)
          assert all(len(f['bands'])==10 and all(math.isfinite(x) and 0<=x<=1 for x in f['bands']) for f in frames)
          rate=len([f for f in frames if start<=f['time']<=start+4000])/4
          assert 8<rate<=32,rate
          passed('Real output bass reaches the native analyser and event stream',bass=round(bass,3),impact=round(impact,3),events_per_second=round(rate,1))

          invoke('toggle_island_shortcut')
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
          # Even a stale enable cannot keep loopback alive behind a hidden window.
          invoke('set_audio_reactivity',{'enabled':True})
          page.wait_for_timeout(350)
          assert not invoke('get_audio_reactivity')['streaming']
          invoke('toggle_island_shortcut')
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
          invoke('set_audio_reactivity',{'enabled':True})
          page.wait_for_timeout(350)
          assert invoke('get_audio_reactivity')['streaming']
          invoke('set_audio_reactivity',{'enabled':False})
          page.wait_for_timeout(250)
          assert not invoke('get_audio_reactivity')['streaming']
          assert not invoke('list_tasks',{'includeCompleted':True})
          passed('Hide suspends capture, reveal resumes it, and disabling releases the audio stream; personal tasks are untouched')
          page.evaluate("setTimeout(()=>window.__TAURI_INTERNALS__.invoke('exit_app'),50)")
          app.wait(timeout=10)
          browser.close()
      finally:
        winsound.PlaySound(None,0)
        parked.set();parking.join(timeout=2)
        if app and app.poll() is None:app.terminate();app.wait(timeout=10)
        time.sleep(1)
        (OUT/'audio-native-results.json').write_text(json.dumps(RESULTS,indent=2),encoding='utf8')
