"""Record the real Tauri reminder animation in an isolated local instance."""
import base64
import ctypes
from ctypes import wintypes
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request

import cv2
import imageio_ffmpeg
import numpy as np
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/demo'
OUT.mkdir(parents=True,exist_ok=True)
VIDEO=OUT/'personal-island-reminder.mp4'
PREVIEW=OUT/'personal-island-reminder.png'
DESKTOP=Path.home()/'Desktop'/'Personal Island — уведомление.mp4'
EXE=ROOT/'target/debug/personal-island-desktop.exe'
BACKGROUND=(30,25,21)  # BGR, matching #15191e in the WebView.
FPS=30
user32=ctypes.WinDLL('user32',use_last_error=True)
user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
user32.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]

def park(pid):
    @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def visit(window,parameter):
        owner=wintypes.DWORD()
        user32.GetWindowThreadProcessId(window,ctypes.byref(owner))
        if owner.value==pid:
            user32.SetWindowPos(window,None,-8000,-8000,0,0,0x15)
        return True
    user32.EnumWindows(visit,0)

def compose(data):
    frame=cv2.imdecode(np.frombuffer(data,dtype=np.uint8),cv2.IMREAD_COLOR)
    assert frame is not None,'Invalid captured frame'
    height=round(frame.shape[0]*960/frame.shape[1])
    resized=cv2.resize(frame,(960,height),interpolation=cv2.INTER_LANCZOS4)
    canvas=np.empty((720,1280,3),dtype=np.uint8)
    canvas[:]=BACKGROUND
    canvas[:height,160:1120]=resized
    return cv2.cvtColor(canvas,cv2.COLOR_BGR2RGB)

with tempfile.TemporaryDirectory(prefix='island-reminder-film-') as temporary:
    folder=Path(temporary)
    env=dict(os.environ,PERSONAL_ISLAND_DB=str(folder/'tasks.sqlite3'),
        PERSONAL_ISLAND_QA_DISABLE_SHORTCUT='1',WEBVIEW2_USER_DATA_FOLDER=str(folder/'webview'),
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222 --disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows')
    app=None
    with (OUT/'recording.log').open('w',encoding='utf8') as log:
      try:
        app=subprocess.Popen([str(EXE)],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        deadline=time.monotonic()+30
        while True:
            assert app.poll() is None,'Demo instance exited'
            try:
                urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1).close()
                break
            except OSError:
                assert time.monotonic()<deadline,'WebView2 did not start'
                time.sleep(.1)
        with sync_playwright() as p:
          browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222')
          page=browser.contexts[0].pages[0]
          expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
          page.evaluate('localStorage.setItem("personal-island.appearance.v1",JSON.stringify({style:"portrait",liquid:true}))')
          page.reload()
          expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
          page.emulate_media(reduced_motion='no-preference')
          page.add_style_tag(content='html,body,#app{background:#15191e!important}')
          page.evaluate('''()=>{
            window.demoTimeline=[];
            new MutationObserver(()=>{
              const phase=document.querySelector('.island-shell').getAttribute('aria-hidden')==='true'?'hidden':document.querySelector('.compact-stage .reminder-notice')?.dataset.phase;
              if(phase && demoTimeline.at(-1)?.phase!==phase)demoTimeline.push({phase,time:Date.now()});
            }).observe(document.querySelector('.island-shell'),{subtree:true,childList:true,attributes:true,attributeFilter:['data-phase','aria-hidden']});
          }''')
          session=page.context.new_cdp_session(page)
          frames=[(time.time(),page.screenshot())]
          def frame(event):
              frames.append((time.time(),base64.b64decode(event['data'])))
              session.send('Page.screencastFrameAck',{'sessionId':event['sessionId']})
          session.on('Page.screencastFrame',frame)
          session.send('Page.startScreencast',{'format':'jpeg','quality':95,'maxWidth':1280,'maxHeight':720,'everyNthFrame':1})
          page.wait_for_timeout(800)
          now=datetime.now(timezone.utc)
          task=page.evaluate('task=>window.__TAURI_INTERNALS__.invoke("create_task",{task})',{
              'title':'Через 5 минут — созвон','notes':None,'priority':0,
              'due_at':(now+timedelta(minutes=5)).isoformat(),
              'reminder_at':(now-timedelta(seconds=1)).isoformat()})
          notice=page.locator('.compact-stage .reminder-notice')
          expect(notice).to_have_attribute('data-phase','bell',timeout=8000)
          park(app.pid)
          print('Recording bell strike and expansion',flush=True)
          expect(notice).to_have_attribute('data-phase','message',timeout=5000)
          expect(notice.locator('strong')).to_have_text('Через 5 минут — созвон')
          page.wait_for_timeout(450)
          PREVIEW.write_bytes(page.screenshot())
          frames.append((time.time(),PREVIEW.read_bytes()))
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true',timeout=12000)
          ended=time.time()
          page.wait_for_timeout(900)
          frames.append((time.time(),page.screenshot()))
          session.send('Page.stopScreencast')
          timeline=page.evaluate('demoTimeline')
          phases=[entry['phase'] for entry in timeline]
          assert all(phase in phases for phase in ['bell','opening','message','hidden']),timeline
          # Keep a short lead-in and tail, preserving the real eight-second read time.
          started=next(entry['time']/1000 for entry in timeline if entry['phase']=='bell')-.8
          finished=ended+.8
          frames.sort(key=lambda item:item[0])
          writer=imageio_ffmpeg.write_frames(str(VIDEO),(1280,720),fps=FPS,codec='libx264',pix_fmt_in='rgb24',pix_fmt_out='yuv420p',quality=8,output_params=['-movflags','+faststart','-preset','medium'])
          writer.send(None)
          index=0
          last_index=-1
          pixels=None
          count=round((finished-started)*FPS)
          try:
              for i in range(count):
                  at=started+i/FPS
                  while index+1<len(frames) and frames[index+1][0]<=at:index+=1
                  if index!=last_index:
                      pixels=compose(frames[index][1]);last_index=index
                  writer.send(pixels)
          finally:writer.close()
          shutil.copy2(VIDEO,DESKTOP)
          metadata={'video':str(VIDEO),'desktop':str(DESKTOP),'seconds':round(count/FPS,2),'size':[1280,720],
              'fps':FPS,'captured_frames':len(frames),'timeline':timeline,'task_id_in_temporary_db':task['id']}
          (OUT/'recording.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf8')
          print(json.dumps(metadata,ensure_ascii=True),flush=True)
          page.evaluate("setTimeout(()=>window.__TAURI_INTERNALS__.invoke('exit_app'),50)")
          app.wait(timeout=10)
          browser.close()
      finally:
        if app and app.poll() is None:
            app.terminate();app.wait(timeout=10)
        time.sleep(1)
