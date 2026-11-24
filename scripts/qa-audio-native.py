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
from PIL import Image
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
    fixture=None
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
        # Use a unique silent player to exercise the real frontend enable
        # condition. No transport commands are sent to the owner's music.
        with wave.open(str(folder/'silence.wav'),'wb') as output:
            output.setparams((1,2,8000,0,'NONE','not compressed'))
            output.writeframes(b'\0\0'*8000*180)
        Image.new('RGB',(96,96),'#637e68').save(folder/'cover.png')
        fixture=subprocess.Popen([str(ROOT/'target/debug/examples/qa-media.exe'),str(folder)],
            env=dict(os.environ,PERSONAL_ISLAND_QA_MEDIA_ID=folder.name),
            stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
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
          page.evaluate("localStorage.setItem('personal-island.appearance.v1',JSON.stringify({style:'island',liquid:false}))")
          page.reload()
          expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
          # Let startup and the fixture's first metadata notification settle
          # before opening a panel; neither is the action under test here.
          page.wait_for_timeout(2300)
          page.evaluate("window.__TAURI_INTERNALS__.invoke('reveal_island_shortcut')")
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
          page.wait_for_timeout(150)
          page.locator('.compact-stage .pill,.compact-stage .compact-open,.track-peek .peek-art').first.evaluate('(e)=>e.click()')
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
          page.locator('.pin-button').evaluate('(e)=>e.click()')
          def invoke(command,args=None):
              return page.evaluate('([cmd,args])=>window.__TAURI_INTERNALS__.invoke(cmd,args)',[command,args or {}])
          page.get_by_role('button',name='Музыка',exact=True).click()
          limit=time.monotonic()+15
          while True:
              source=next((s['id'] for s in invoke('get_media_state',{'preferred':None})['sessions'] if folder.name in s['id']),None)
              if source:break
              assert time.monotonic()<limit,'Silent test player did not register'
              page.wait_for_timeout(100)
          page.get_by_label('Источник музыки').select_option(source)
          expect(page.locator('.track-info h2')).to_have_text('QA Track 1')
          page.evaluate('''async()=>{
            window.qaAudioFrames=[];
            const handler=window.__TAURI_INTERNALS__.transformCallback(event=>qaAudioFrames.push({...event.payload,time:performance.now()}));
            await window.__TAURI_INTERNALS__.invoke('plugin:event|listen',{event:'island-audio',target:{kind:'Any'},handler});
          }''')
          limit=time.monotonic()+5
          while not invoke('get_audio_reactivity')['streaming']:
              assert time.monotonic()<limit,invoke('get_audio_reactivity')
              page.wait_for_timeout(100)
          assert invoke('get_audio_reactivity')['enabled']
          assert page.evaluate("JSON.parse(localStorage.getItem('personal-island.appearance.v1')).liquid") is False
          passed('Real playback automatically opens Windows loopback with the ambient edge disabled')
          page.evaluate('''()=>{
            window.qaWaveMetrics=[];
            window.qaWaveTimer=setInterval(()=>{
              const canvas=document.querySelector('.liquid-surface'),ctx=canvas.getContext('2d');
              const {data,width,height}=ctx.getImageData(0,0,canvas.width,canvas.height);
              const ratio=width/canvas.getBoundingClientRect().width;
              let bottom=0;
              for(let y=20;y<height;y++)for(let x=width*.35|0;x<width*.65;x++){
                const i=(y*width+x)*4;
                if(data[i+3]>40&&data[i+1]>data[i]+15&&data[i+1]>data[i+2]+15)bottom=Math.max(bottom,y/ratio);
              }
              qaWaveMetrics.push({time:performance.now(),bottom});
            },80);
          }''')

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
          wave_metrics=page.evaluate('clearInterval(qaWaveTimer);qaWaveMetrics')
          quiet=[m['bottom'] for m in wave_metrics if start+500<m['time']<start+1300]
          drops=[m['bottom'] for m in wave_metrics if start+1400<m['time']<start+3300]
          assert quiet and drops,(quiet,drops)
          assert max(drops)>min(quiet)+5,(min(quiet),max(drops))
          passed('Real Windows audio moves the rendered waveform while the ambient edge is off',quiet_y=min(quiet),drop_y=max(drops))

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
        if fixture and fixture.poll() is None:
            (folder/'stop-media').touch();fixture.wait(timeout=10)
        fragment=(folder.name+'\\webview').replace("'","''")
        cleanup="$profileFragment='"+fragment+"'; Get-CimInstance Win32_Process -Filter \"Name='msedgewebview2.exe'\" | Where-Object {$_.CommandLine -and $_.CommandLine.ToLowerInvariant().Contains($profileFragment.ToLowerInvariant())} | ForEach-Object {Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue}"
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',cleanup],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
        time.sleep(1)
        (OUT/'audio-native-results.json').write_text(json.dumps(RESULTS,indent=2),encoding='utf8')
