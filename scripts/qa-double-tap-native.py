"""Real keyboard hook against an isolated WinForms editor and WebView profile."""
import ctypes
from ctypes import wintypes
import json
import os
import sqlite3
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect
from qa_win import press_reveal as send_reveal, focus_process, user32

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'artifacts/qa'
OUT.mkdir(parents=True,exist_ok=True)
RESULTS = []
user32.LoadKeyboardLayoutW.argtypes=[wintypes.LPCWSTR,wintypes.UINT]
user32.LoadKeyboardLayoutW.restype=ctypes.c_void_p
user32.GetKeyboardLayout.argtypes=[wintypes.DWORD]
user32.GetKeyboardLayout.restype=ctypes.c_void_p
user32.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
user32.SetForegroundWindow.argtypes=[wintypes.HWND]
user32.SetCursorPos.argtypes=[ctypes.c_int,ctypes.c_int]
user32.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
user32.mouse_event.argtypes=[wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.c_size_t]
original_cursor=wintypes.POINT()
user32.GetCursorPos(ctypes.byref(original_cursor))
original_foreground=user32.GetForegroundWindow()
original_layout=user32.GetKeyboardLayout(user32.GetWindowThreadProcessId(original_foreground,None)) if original_foreground else None
allowed_pids=set()

def guard_focus():
    process=wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(),ctypes.byref(process))
    assert process.value in allowed_pids,'QA focus changed; refusing to type into another app'

def press_reveal():
    guard_focus()
    send_reveal()

def read(path):
    try: return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError,json.JSONDecodeError): return {}

def passed(name):
    RESULTS.append({'test':name,'status':'passed'})
    print(name,flush=True)

def key(vk):
    guard_focus()
    user32.keybd_event(vk,0,0,0)
    time.sleep(.02)
    user32.keybd_event(vk,0,2,0)

with tempfile.TemporaryDirectory(prefix='island-double-tap-') as temporary:
    folder=Path(temporary)
    env=dict(os.environ,PERSONAL_ISLAND_DB=str(folder/'tasks.sqlite3'),
        WEBVIEW2_USER_DATA_FOLDER=str(folder/'webview'),
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    env.pop('PERSONAL_ISLAND_QA_DISABLE_SHORTCUT',None)
    children=[]
    editor_browser=None
    with (OUT/'double-tap-native-stderr.log').open('w',encoding='utf8') as log:
      try:
        app=subprocess.Popen([str(ROOT/'target/debug/personal-island-desktop.exe')],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        children.append(app)
        end=time.monotonic()+30
        while True:
            assert app.poll() is None,'Application exited'
            try:
                urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1).close()
                break
            except OSError:
                assert time.monotonic()<end,'WebView2 unavailable'
                time.sleep(.2)
        receiver=subprocess.Popen(['powershell.exe','-NoProfile','-STA','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/qa-double-tap-target.ps1'),'-Folder',str(folder)],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        children.append(receiver)
        allowed_pids.update([app.pid,receiver.pid])
        while not (folder/'ready').exists():
            assert receiver.poll() is None,'QA editor exited'
            assert time.monotonic()<end,'QA editor unavailable'
            time.sleep(.05)
        with sync_playwright() as p:
          browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222')
          page=browser.contexts[0].pages[0]
          page.emulate_media(reduced_motion='reduce')
          errors=[]
          page.on('pageerror',lambda error:errors.append(str(error)))
          shell=page.locator('.island-shell')
          expect(shell).to_have_attribute('data-shortcut-ready','true')
          sequence=0

          def invoke(cmd,args=None):
              return page.evaluate('([c,a])=>window.__TAURI_INTERNALS__.invoke(c,a)',[cmd,args or {}])

          # Only this suite's temporary database is seeded; the system clipboard
          # and the owner's clipboard database are never written.
          with sqlite3.connect(folder/'clipboard.sqlite3') as connection:
              copied=int(time.time()*1000)+60000
              for i in range(22):
                  connection.execute('INSERT INTO clipboard_history(digest,kind,text,pinned,captured_at) VALUES(?,?,?,?,?)',
                      (f'qa-copy-{i}'.encode(),'text',f'QA copy {i+1}',i==0,copied+i))
          connection.close()
          recent=invoke('list_clipboard',{'search':''})['entries']
          assert len(recent)==9
          assert recent[0]['text']=='QA copy 22' and recent[-1]['text']=='QA copy 14'
          saved=invoke('list_clipboard',{'search':'','pinnedOnly':True})['entries']
          assert len(saved)==1 and saved[0]['text']=='QA copy 1'
          summary=invoke('get_widget_summary')
          assert summary['clipboard']==9 and summary['pinned']==1
          passed('Real native clipboard IPC returns nine recent items, exposes older pins separately and matches the overview count')

          def command(action,**args):
              global sequence
              sequence+=1
              temporary_command=folder/'command.tmp'
              temporary_command.write_text(json.dumps({'id':sequence,'action':action,**args}),encoding='utf8')
              temporary_command.replace(folder/'command.json')
              limit=time.monotonic()+5
              while read(folder/f'ack-{sequence}.json').get('id')!=sequence:
                  if time.monotonic()>=limit:
                      error_path=folder/'target-error.txt'
                      raise AssertionError(error_path.read_text(encoding='utf-8-sig') if error_path.exists() else f'No editor reply to {action}')
                  time.sleep(.01)
              return sequence

          def typed():
              reply=command('read')
              return read(folder/f'typed-{reply}.json')

          def prepare():
              if shell.get_attribute('aria-hidden')!='true':
                  invoke('toggle_island_shortcut')
                  expect(shell).to_have_attribute('aria-hidden','true')
              time.sleep(1.6)
              command('prepare',text='prefix ')
              focus_process(receiver.pid)
              user32.SetCursorPos(30,500)
              assert typed()['first']=='prefix '

          for layout_id,char in [('00000409','`'),('00000419','ё')]:
              prepare()
              target=user32.GetForegroundWindow()
              thread=user32.GetWindowThreadProcessId(target,None)
              layout=user32.LoadKeyboardLayoutW(layout_id,0)
              user32.PostMessageW(target,0x50,0,layout)
              limit=time.monotonic()+2
              while user32.GetKeyboardLayout(thread)!=layout:
                  assert time.monotonic()<limit,'Keyboard layout did not change'
                  time.sleep(.02)
              press_reveal()
              expect(shell).to_have_attribute('aria-hidden','false')
              assert typed()['first']=='prefix '+char,typed()
              time.sleep(1.0)
              press_reveal()
              expect(shell).to_have_attribute('aria-hidden','true')
              assert typed()['first']=='prefix ',typed()
              assert user32.GetForegroundWindow()==target,'Island stole focus'
              passed(f'{layout_id}: a real double tap removes both characters and closes the island without stealing focus')

          prepare()
          press_reveal()
          time.sleep(1.7)
          assert typed()['first']=='prefix ё'
          press_reveal()
          expect(shell).to_have_attribute('aria-hidden','true')
          assert typed()['first']=='prefix ёё',typed()
          passed('Single and slow repeated yo presses remain ordinary text')

          prepare()
          press_reveal()
          assert typed()['first']=='prefix ё'
          key(0x20);press_reveal()
          expect(shell).to_have_attribute('aria-hidden','true')
          assert typed()['first']=='prefix ё ё',typed()
          prepare()
          press_reveal()
          assert typed()['first']=='prefix ё'
          key(0x25);press_reveal()
          expect(shell).to_have_attribute('aria-hidden','true')
          assert typed()['first']=='prefix ёё',typed()
          passed('An intervening character or caret key cancels deletion and preserves surrounding text')

          prepare()
          point=typed()
          press_reveal()
          user32.SetCursorPos(point['x'],point['y'])
          user32.mouse_event(0x02,0,0,0,0);user32.mouse_event(0x04,0,0,0,0)
          time.sleep(.03)
          press_reveal()
          expect(shell).to_have_attribute('aria-hidden','true')
          clicked=typed()['first']
          assert clicked.count('ё')==2 and clicked.replace('ё','')=='prefix ',repr(clicked)
          prepare()
          press_reveal();command('focus-second');press_reveal()
          expect(shell).to_have_attribute('aria-hidden','true')
          assert typed()['first']=='prefix ё' and typed()['second']=='second ё',typed()
          passed('Mouse clicks and focus changes within the same window cancel cleanup')

          prepare()
          guard_focus()
          user32.keybd_event(0xC0,0x29,0,0)
          time.sleep(.04)
          user32.keybd_event(0xC0,0x29,0,0)
          time.sleep(.04)
          user32.keybd_event(0xC0,0x29,2,0)
          press_reveal()
          expect(shell).to_have_attribute('aria-hidden','true')
          assert typed()['first']=='prefix ёёё',typed()
          passed('Held-key repeat is not mistaken for a double tap')

          # Web editors use a shared renderer HWND rather than a WinForms edit
          # control. Exercise that actual input path too, with a fresh profile.
          editor_browser=p.chromium.launch(channel='msedge',headless=False,args=['--window-position=80,230','--window-size=460,280'])
          editor=editor_browser.new_page()
          editor.set_content('<title>Island double tap browser QA</title><textarea id="text" style="width:95%;height:160px">prefix </textarea>')
          editor.locator('#text').click()
          editor.locator('#text').press('End')
          windows=[]
          @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
          def find_editor(window,parameter):
              title=ctypes.create_unicode_buffer(256)
              user32.GetWindowTextW(window,title,256)
              if 'Island double tap browser QA' in title.value:
                  process=wintypes.DWORD()
                  user32.GetWindowThreadProcessId(window,ctypes.byref(process))
                  windows.append((window,process.value))
              return True
          user32.EnumWindows(find_editor,0)
          assert windows,'QA browser window was not found'
          allowed_pids.add(windows[0][1])
          focus_process(windows[0][1])
          time.sleep(1.6)
          press_reveal()
          expect(shell).to_have_attribute('aria-hidden','false')
          value=editor.locator('#text').input_value()
          assert value in ['prefix ё','prefix `'],repr(value)
          press_reveal()
          expect(shell).to_have_attribute('aria-hidden','true')
          expect(editor.locator('#text')).to_have_value('prefix ')
          editor_browser.close()
          editor_browser=None
          passed('A real Chromium textarea also removes the double tap without changing its surrounding text')

          prepare()
          press_reveal()
          page.locator('.compact-stage [aria-label="Развернуть список задач"]').evaluate('(e)=>e.click()')
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
          page.locator('.pin-button').evaluate('(e)=>e.click()')
          page.locator('.tabs button').nth(2).evaluate('(e)=>e.click()')
          page.locator('.add-small').evaluate('(e)=>e.click()')
          focus_process(app.pid)
          target=user32.GetForegroundWindow()
          thread=user32.GetWindowThreadProcessId(target,None)
          layout=user32.LoadKeyboardLayoutW('00000419',0)
          user32.PostMessageW(target,0x50,0,layout)
          page.wait_for_timeout(100)
          field=page.get_by_label('Название задачи',exact=True)
          field.fill('local ')
          page.wait_for_timeout(150)
          press_reveal();press_reveal()
          expect(field).to_have_value('local ёё')
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
          assert len(invoke('list_tasks',{'includeCompleted':True}))==0
          assert not errors,errors
          passed('Editing inside the island keeps both yo letters; no personal tasks or clipboard were changed')
          page.get_by_role('button',name='Отмена',exact=True).evaluate('(e)=>e.click()')
          page.get_by_role('button',name='Главная',exact=True).evaluate('(e)=>e.click()')
          expect(page.locator('.home-transport .home-play')).to_be_visible()
          expect(page.locator('.clipboard-stats')).to_contain_text('9 записей')
          page.get_by_label('Открыть буфер обмена',exact=True).evaluate('(e)=>e.click()')
          expect(page.locator('.clipboard-card')).to_have_count(9)
          expect(page.locator('.clipboard-card').last).to_be_in_viewport()
          page.screenshot(path=str(OUT/'clipboard-nine-native.png'))
          page.get_by_role('button',name='Закреплённые',exact=True).evaluate('(e)=>e.click()')
          expect(page.locator('.clipboard-card')).to_have_count(1)
          expect(page.locator('.clipboard-card')).to_contain_text('QA copy 1')
          passed('The packaged app renders the dedicated play button and latest-nine clipboard grid with a working Pinned filter')
          page.evaluate("setTimeout(()=>window.__TAURI_INTERNALS__.invoke('exit_app'),50)")
          app.wait(timeout=10)
          browser.close()
          command('stop')
          receiver.wait(timeout=5)
      finally:
        if editor_browser:
            try: editor_browser.close()
            except Exception: pass
        for child in reversed(children):
            if child.poll() is None:
                child.terminate();child.wait(timeout=10)
        user32.SetCursorPos(original_cursor.x,original_cursor.y)
        if original_foreground:
            user32.SetForegroundWindow(original_foreground)
            if original_layout: user32.PostMessageW(original_foreground,0x50,0,original_layout)
        time.sleep(1)
        (OUT/'double-tap-native-results.json').write_text(json.dumps(RESULTS,indent=2),encoding='utf8')
