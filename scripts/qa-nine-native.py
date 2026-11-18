"""Acceptance checks against real Win32 input, GSMTC and per-session audio gain."""
import ctypes,json,os,subprocess,tempfile,time,urllib.request,wave,struct,zlib
from datetime import datetime,timezone,timedelta
from pathlib import Path
from ctypes import wintypes
from playwright.sync_api import sync_playwright,expect
from qa_win import press_reveal,user32
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'artifacts/qa'; results=[]
def passed(name): results.append({'test':name,'status':'passed'});print(name,flush=True)
def read(path):
    try:return json.loads(path.read_text(encoding='utf-8-sig'))
    except json.JSONDecodeError:return {}
user32.LoadKeyboardLayoutW.argtypes=[wintypes.LPCWSTR,wintypes.UINT];user32.LoadKeyboardLayoutW.restype=ctypes.c_void_p
user32.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
user32.SetForegroundWindow.argtypes=[wintypes.HWND]
user32.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
original=wintypes.POINT();user32.GetCursorPos(ctypes.byref(original));foreground=user32.GetForegroundWindow()
try:user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except AttributeError:pass
with tempfile.TemporaryDirectory(prefix='island-nine-') as temp:
    folder=Path(temp);processes=[];seq=0
    env=dict(os.environ,PERSONAL_ISLAND_DB=str(folder/'tasks.sqlite3'),WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    with (OUT/'nine-native-stderr.log').open('w',encoding='utf-8') as log:
      def spawn(args,env=env):
        proc=subprocess.Popen(args,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW);processes.append(proc);return proc
      def master():
        return float(subprocess.check_output(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/qa-master-volume.ps1')],creationflags=subprocess.CREATE_NO_WINDOW).decode().strip())
      try:
        app=spawn([str(ROOT/'target/debug/personal-island-desktop.exe')])
        deadline=time.monotonic()+30
        while True:
          assert app.poll() is None,'Application failed to start'
          try:urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1).close();break
          except OSError:
            if time.monotonic()>deadline:raise TimeoutError('WebView unavailable')
            time.sleep(.2)
        with sync_playwright() as p:
          browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222');page=browser.contexts[0].pages[0]
          expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
          def invoke(cmd,args=None):return page.evaluate('([cmd,args])=>window.__TAURI_INTERNALS__.invoke(cmd,args)',[cmd,args or {}])
          def wait(predicate,timeout=15):
            deadline=time.monotonic()+timeout
            while not predicate():
              if time.monotonic()>deadline:raise TimeoutError('Native fixture timed out')
              page.wait_for_timeout(100)
          receiver=spawn(['powershell.exe','-NoProfile','-STA','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/qa-clipboard-target.ps1'),'-Folder',str(folder)])
          wait(lambda:(folder/'ready').exists())
          found=[]
          CALLBACK=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
          def visit(hwnd,_):
            pid=wintypes.DWORD();user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value==receiver.pid and user32.IsWindowVisible(hwnd):found.append(hwnd)
            return True
          user32.EnumWindows(CALLBACK(visit),0);assert found
          receiver_hwnd=found[0]
          def focus_receiver():
            thread=user32.GetWindowThreadProcessId(user32.GetForegroundWindow(),None)
            current=ctypes.windll.kernel32.GetCurrentThreadId()
            user32.ShowWindow(receiver_hwnd,9)
            attached=user32.AttachThreadInput(current,thread,True)
            try:
              result=user32.SetForegroundWindow(receiver_hwnd)
              if not result:
                user32.keybd_event(0x12,0x38,0,0)
                result=user32.SetForegroundWindow(receiver_hwnd)
                user32.keybd_event(0x12,0x38,2,0)
              print('Focus request:',receiver_hwnd,attached,result,flush=True)
            finally:user32.AttachThreadInput(current,thread,False)
          def command(action):
            global seq
            seq+=1;(folder/'command.json').write_text(json.dumps({'id':seq,'action':action}),encoding='utf-8')
            wait(lambda:(folder/'ack.json').exists() and read(folder/'ack.json').get('id')==seq)
          for layout,expected in [('00000419','ё'),('00000409','`')]:
            focus_receiver()
            command('clear-field');target=user32.GetForegroundWindow()
            pid=wintypes.DWORD();user32.GetWindowThreadProcessId(target,ctypes.byref(pid))
            title=ctypes.create_unicode_buffer(256);user32.GetWindowTextW(target,title,256)
            print('Target:',pid.value,receiver.pid,title.value,flush=True)
            assert pid.value==receiver.pid,'Receiver was not the real foreground window'
            hkl=user32.LoadKeyboardLayoutW(layout,0);assert hkl
            user32.PostMessageW(target,0x50,0,hkl);page.wait_for_timeout(250)
            press_reveal()
            expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
            expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
            actual=user32.GetForegroundWindow()
            if actual!=target:
              actual_pid=wintypes.DWORD();user32.GetWindowThreadProcessId(actual,ctypes.byref(actual_pid))
              actual_title=ctypes.create_unicode_buffer(256);user32.GetWindowTextW(actual,actual_title,256)
              raise AssertionError(f'Foreground changed: expected receiver {target}; actual PID {actual_pid.value}, app PID {app.pid}, title {actual_title.value}')
            command('read-field');assert read(folder/'typed.json')['text']==expected,read(folder/'typed.json')
          passed('The physical reveal key types both backquote and Russian yo into another app without stealing focus')
          user32.SetCursorPos(20,500)
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true',timeout=8000)
          passed('Unattended manual reveal animates out and hides the native window')
          focus_receiver();command('focus');press_reveal();page.get_by_role('button',name='Развернуть список задач',exact=True).click()
          expect(page.locator('.home-panel')).to_be_visible()
          page.get_by_label('Закрепить островок').click()
          invoke('save_note',{'id':None,'revision':0,'note':{'title':'QA overview idea','category':'ideas','document':'{"type":"doc","content":[]}'}})
          page.get_by_role('button',name='Задачи',exact=True).click();page.get_by_role('button',name='Главная',exact=True).click()
          summary=invoke('get_widget_summary')
          assert summary['ideas']==1 and isinstance(summary['capturing'],bool),summary
          expect(page.locator('.notes-stats')).to_contain_text('Идеи 1')
          assert page.locator('.home-panel').evaluate('e=>e.scrollHeight<=e.clientHeight+1')
          page.screenshot(path=str(OUT/'home-native-overview.png'))
          passed('Native home opens first, fits its window and reads real lightweight SQLite summaries')
          # Three silent local tracks give real SMTC next/previous commands and artwork.
          def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
          pixels=b''.join(b'\x00'+bytes([40,100,80,255])*64 for _ in range(64))
          (folder/'cover.png').write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',64,64,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b''))
          with wave.open(str(folder/'silence.wav'),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000);wav.writeframes(b'\0\0'*8000*60)
          fixture=spawn([str(ROOT/'target/debug/examples/qa-media.exe'),str(folder)])
          selected_source=None
          def discover():
            global selected_source
            assert fixture.poll() is None,'Silent player exited'
            sources=invoke('get_media_state',{'preferred':None})['sessions']
            selected_source=next((source['id'] for source in sources if 'qa-media' in source['id'].lower()),None)
            return selected_source
          wait(discover,20)
          # Select the test player explicitly; the user's browser may already be playing.
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
          page.get_by_role('button',name='Музыка',exact=True).click()
          page.get_by_label('Источник музыки').select_option(selected_source)
          expect(page.locator('.track-info h2')).to_have_text('QA Track 1',timeout=8000)
          page.get_by_role('button',name='Свернуть',exact=True).click()
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
          (folder/'next-media').touch()
          expect(page.locator('.peek-title b')).to_have_text('QA Track 2',timeout=10000)
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
          expect(page.locator('.equalizer')).to_have_count(0)
          assert page.locator('.pill-artwork').evaluate('el=>el.complete&&el.naturalWidth>0')
          source=selected_source;print('Fixture session:',source,flush=True)
          passed('Native media watcher reveals artwork and title for a newly playing track while the island was hidden')
          page.get_by_label('Следующий трек',exact=True).first.click()
          expect(page.locator('.peek-title b')).to_have_text('QA Track 3',timeout=10000)
          page.get_by_label('Предыдущий трек',exact=True).first.click()
          expect(page.locator('.peek-title b')).to_have_text('QA Track 2',timeout=10000)
          passed('Notification arrows change actual Windows playback to the next and previous track')
          initial=invoke('player_volume',{'sessionId':source,'level':None});assert initial['available'],initial
          before=master()
          try:
            (folder/'mute-session').touch();wait(lambda:(folder/'muted-session').exists())
            assert invoke('player_volume',{'sessionId':source,'level':None})['muted']
            page.locator('.track-peek').get_by_label('Показать громкость плеера').click()
            slider=page.locator('.track-peek').get_by_label('Громкость плеера',exact=True);expect(slider).to_be_enabled()
            expect(slider).to_have_attribute('aria-orientation','vertical')
            box=slider.bounding_box();assert box['height']>box['width']*2
            body=page.locator('.track-peek').bounding_box();popup=page.locator('.track-peek .volume-popover').bounding_box()
            assert popup['y']>body['y']+body['height'] and body['height']==76,(body,popup)
            user32.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
            windows=[]
            def app_window(hwnd,_):
              pid=wintypes.DWORD();user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
              if pid.value==app.pid and user32.IsWindowVisible(hwnd):windows.append(hwnd)
              return True
            user32.EnumWindows(CALLBACK(app_window),0);assert windows
            rect=wintypes.RECT();user32.GetWindowRect(windows[0],ctypes.byref(rect))
            scale=(rect.right-rect.left)/page.evaluate('innerWidth')
            hover_target=(round(rect.left+(box['x']+box['width']/2)*scale),round(rect.top+(box['y']+box['height']*.8)*scale))
            user32.SetCursorPos(*hover_target)
            page.wait_for_timeout(10000)
            actual=wintypes.POINT();user32.GetCursorPos(ctypes.byref(actual))
            print('Volume hover:',{'expected':hover_target,'actual':(actual.x,actual.y),'rect':(rect.left,rect.top,rect.right,rect.bottom),'scale':scale,'slider':box,'viewport':page.evaluate('[innerWidth,innerHeight]')},flush=True)
            expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
            expect(page.locator('.island-shell')).to_have_attribute('data-native-hover','true')
            page.mouse.click(box['x']+box['width']/2,box['y']+box['height']*.65)
            wait(lambda:invoke('player_volume',{'sessionId':source,'level':None})['level']>.1)
            slider.fill('37')
            wait(lambda:abs(invoke('player_volume',{'sessionId':source,'level':None})['level']-.37)<.002)
            changed=invoke('player_volume',{'sessionId':source,'level':None})
            assert abs(changed['level']-.37)<.002 and not changed['muted'],changed
            assert abs(master()-before)<.00001,'System volume changed'
            assert abs(invoke('player_volume',{'sessionId':source,'level':None})['level']-.37)<.002
            expect(slider).to_be_in_viewport()
            page.screenshot(path=str(OUT/'music-native-vertical-volume.png'))
            page.locator('.track-peek').get_by_label('Показать громкость плеера').click()
          finally:invoke('player_volume',{'sessionId':source,'level':initial['level']})
          passed('Detached volume keeps a 76px body, stays hovered outside the island and changes player gain without changing Windows volume')
          user32.SetCursorPos(20,500)
          focus_receiver();command('focus');press_reveal()
          expect(page.locator('.compact-cover')).to_be_visible()
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
          page.locator('.compact-cover').click()
          expect(page.locator('.compact-cover')).to_have_class('compact-cover paused')
          assert not invoke('get_media_state',{'preferred':source})['playing']
          page.locator('.compact-cover').click()
          expect(page.locator('.compact-stage').get_by_label('Приостановить музыку',exact=True)).to_be_visible()
          assert invoke('get_media_state',{'preferred':source})['playing']
          page.screenshot(path=str(OUT/'music-native-compact-controls.png'))
          user32.SetCursorPos(round(rect.left+240*scale),round(rect.top+25*scale))
          page.get_by_label('Следующий трек',exact=True).first.click()
          wait(lambda:invoke('get_media_state',{'preferred':source})['title']=='QA Track 3')
          page.wait_for_timeout(3000)
          expect(page.locator('.compact-cover')).to_be_visible()
          expect(page.locator('.track-peek')).to_have_count(0)
          assert page.locator('.compact-stage').evaluate('e=>e.clientWidth')==272
          page.get_by_label('Предыдущий трек',exact=True).first.click()
          wait(lambda:invoke('get_media_state',{'preferred':source})['title']=='QA Track 2')
          page.wait_for_timeout(3000)
          expect(page.locator('.compact-cover')).to_be_visible()
          expect(page.locator('.track-peek')).to_have_count(0)
          assert page.locator('.compact-stage').evaluate('e=>e.clientWidth')==272
          (folder/'next-media').touch()
          expect(page.locator('.peek-title b')).to_have_text('QA Track 3',timeout=8000)
          passed('Compact arrows change real tracks without expanding; a subsequent external change still shows the notification')
          invoke('media_command',{'sessionId':source,'action':'toggle'})
          expect(page.locator('.track-peek')).to_have_count(0,timeout=6000)
          expect(page.locator('.pill-playing')).to_have_count(0)
          passed('Real playback pause removes the music notification and its equalizer')
          focus_receiver();command('focus');press_reveal();page.get_by_label('Развернуть список задач',exact=True).click();page.get_by_label('Закрепить островок').click()
          page.get_by_role('button',name='Сегодня',exact=True).click()
          page.locator('.add-task').click();page.get_by_label('Название задачи').fill('Unsaved draft')
          invoke('media_command',{'sessionId':source,'action':'toggle'});(folder/'next-media').touch()
          page.wait_for_timeout(3000)
          expect(page.get_by_label('Название задачи')).to_have_value('Unsaved draft')
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
          passed('A track change preserves an open dashboard and unsaved task draft')
          weather=invoke('get_weather');assert weather['data'] and weather['data']['city']=='Санкт-Петербург',weather
          assert len(weather['data']['daily'])==7
          assert weather['data']['current']['wind_direction_10m'] is not None
          assert weather['data']['daily'][0]['sunrise'] is not None
          page.get_by_role('button',name='Отмена',exact=True).click()
          page.get_by_role('button',name='Погода',exact=True).click()
          expect(page.locator('.weather-day')).to_have_count(7)
          expect(page.locator('.weather-hour')).to_have_count(8)
          expect(page.locator('.weather-daylight')).not_to_contain_text('—:—')
          assert page.locator('.weather-board').evaluate('el=>el.scrollHeight<=el.clientHeight+1')
          page.screenshot(path=str(OUT/'weather-native-reference.png'))
          passed('Native weather request returns real Petersburg forecast data')
          (folder/'stop-media').touch();fixture.wait(timeout=10)
          command('stop');receiver.wait(timeout=10)
          page.evaluate("setTimeout(()=>window.__TAURI_INTERNALS__.invoke('exit_app'),250)");app.wait(timeout=10);browser.close()
          # The same wall-clock scheduler uses 12-second boundaries only in debug QA.
          app=spawn([str(ROOT/'target/debug/personal-island-desktop.exe')],dict(env,PERSONAL_ISLAND_QA_REVEAL_SECONDS='12'))
          time.sleep(2)
          browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222');page=browser.contexts[0].pages[0]
          expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
          page.evaluate("window.qaReviewTimes=[];window.__TAURI_INTERNALS__.invoke('plugin:event|listen',{event:'island-reveal',target:{kind:'Any'},handler:window.__TAURI_INTERNALS__.transformCallback(e=>{if(e.payload.reason==='hourly')qaReviewTimes.push(Date.now())})})")
          invoke('create_task',{'task':{'title':'QA hourly deadline','due_at':(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat(),'priority':1}})
          expect(page.locator('.pill-clock')).to_be_visible(timeout=16000)
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
          expect(page.locator('.hourly-peek')).to_have_count(0)
          assert page.locator('.compact-stage').evaluate('e=>e.clientWidth')==272
          assert page.locator('.compact-stage').evaluate('e=>e.clientHeight')==56
          times=page.evaluate('qaReviewTimes')
          if times: assert all(t%12000<1500 for t in times),times
          user32.SetCursorPos(20,500)
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true',timeout=11000)
          passed('Native periodic scheduler shows the default island and auto-hides it; production interval is 1800 seconds, aligned to :00/:30')
          page.evaluate("setTimeout(()=>window.__TAURI_INTERNALS__.invoke('exit_app'),250)");app.wait(timeout=10);browser.close()
      finally:
        (folder/'stop-media').touch()
        if (folder/'ready').exists(): (folder/'command.json').write_text(json.dumps({'id':999,'action':'stop'}),encoding='utf-8')
        time.sleep(.4)
        for proc in reversed(processes):
          if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
        user32.SetCursorPos(original.x,original.y)
        if foreground:user32.SetForegroundWindow(foreground)
        (OUT/'nine-native-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
