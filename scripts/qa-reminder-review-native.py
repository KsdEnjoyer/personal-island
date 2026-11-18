"""Real startup and accelerated half-hour reviews, using only a temporary DB/profile."""
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Event, Thread
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/qa'
OUT.mkdir(parents=True, exist_ok=True)
RESULTS = []

def passed(name):
    RESULTS.append({'test':name,'status':'passed'})
    print(name, flush=True)

with tempfile.TemporaryDirectory(prefix='island-reminder-review-') as temporary:
    folder = Path(temporary)
    env = dict(os.environ, PERSONAL_ISLAND_DB=str(folder/'tasks.sqlite3'),
        PERSONAL_ISLAND_QA_DISABLE_SHORTCUT='1', PERSONAL_ISLAND_QA_REVEAL_SECONDS='10',
        WEBVIEW2_USER_DATA_FOLDER=str(folder/'webview'),
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    app = None
    parking_done = Event()
    user32 = ctypes.WinDLL('user32')
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.SetWindowPos.argtypes = [wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
    def park():
        @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        def visit(window, parameter):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
            if app and app.poll() is None and owner.value == app.pid:
                user32.SetWindowPos(window,None,-8000,-8000,0,0,0x15)
            return True
        while not parking_done.wait(.05):
            user32.EnumWindows(visit,0)
    parking = Thread(target=park,daemon=True)
    parking.start()
    with (OUT/'reminder-review-native-stderr.log').open('w',encoding='utf8') as log:
      try:
        with sync_playwright() as p:
          def start():
              global app
              # Deliberately omit --show: normal startup must reveal the review.
              app = subprocess.Popen([str(ROOT/'target/debug/personal-island-desktop.exe')],
                  env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
              deadline = time.monotonic()+30
              while True:
                  assert app.poll() is None, 'Application exited'
                  try:
                      urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1).close()
                      break
                  except OSError:
                      assert time.monotonic()<deadline, 'WebView unavailable'
                      time.sleep(.1)
              browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
              page = browser.contexts[0].pages[0]
              page.emulate_media(reduced_motion='reduce')
              expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
              expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
              return browser,page
          def invoke(command, args=None):
              return page.evaluate('([c,a])=>window.__TAURI_INTERNALS__.invoke(c,a)',[command,args or {}])
          def stop():
              page.evaluate("setTimeout(()=>window.__TAURI_INTERNALS__.invoke('exit_app'),50)")
              app.wait(timeout=10)
              browser.close()
              time.sleep(.5)

          browser,page = start()
          passed('A normal packaged launch without --show reveals the compact island')
          assert invoke('list_clipboard',{'search':'','pinnedOnly':False})['enabled'] is False
          policy = page.evaluate('''async()=>{
            const violations=[];
            const collect=e=>violations.push(e.violatedDirective);
            document.addEventListener('securitypolicyviolation',collect);
            try {await fetch('http://127.0.0.1:18741/health',{credentials:'omit'})} catch {}
            await new Promise(resolve=>setTimeout(resolve,100));
            document.removeEventListener('securitypolicyviolation',collect);
            return violations;
          }''')
          assert any('connect-src' in item for item in policy), policy
          passed('A fresh packaged profile has clipboard recording disabled and production CSP blocks direct loopback HTTP from the WebView')
          due = (datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
          task = invoke('create_task',{'task':{'title':'Native missed reminder fixture','due_at':due,'reminder_at':due}})
          stop()

          browser,page = start()
          review = page.locator('.reminder-review')
          expect(review).to_have_attribute('data-task-id',str(task['id']))
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
          expect(page.locator('.compact-stage')).to_have_css('height','56px')
          page.wait_for_function('''async id=>{
            const tasks=await window.__TAURI_INTERNALS__.invoke('list_tasks',{includeCompleted:true});
            return tasks.some(t=>t.id===id&&t.status==='open'&&t.notification_sent_at);
          }''',arg=task['id'])
          passed('A reminder missed while the app was stopped is painted and acknowledged without completing its task')
          generation = page.evaluate('JSON.parse(document.querySelector(".island-shell").dataset.presentation).activeGeneration')
          page.wait_for_function('previous=>JSON.parse(document.querySelector(".island-shell").dataset.presentation).activeGeneration>previous',arg=generation,timeout=16000)
          expect(review).to_have_attribute('data-task-id',str(task['id']))
          assert page.locator('.reminder-notice').count()==0
          passed('The real accelerated scheduler repeats the unfinished reminder in the same compact review without a duplicate bell')
          stop()

          env.pop('PERSONAL_ISLAND_QA_REVEAL_SECONDS', None)
          browser,page = start()
          expect(page.locator('.reminder-review')).to_have_attribute('data-task-id',str(task['id']))
          stored = invoke('list_tasks',{'includeCompleted':True})
          assert len(stored)==1 and stored[0]['status']=='open' and stored[0]['notification_sent_at']
          passed('Restarting still reviews a previously delivered unfinished task; no duplicate task is created')
          future = (datetime.now(timezone.utc)+timedelta(seconds=3)).isoformat()
          fresh = invoke('create_task',{'task':{'title':'Native punctual bell fixture','due_at':future,'reminder_at':future}})
          invoke('toggle_island_shortcut')
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
          expect(page.locator('.compact-stage .reminder-notice strong')).to_have_text(fresh['title'],timeout=20000)
          page.wait_for_function('''async id=>{
            const tasks=await window.__TAURI_INTERNALS__.invoke('list_tasks',{includeCompleted:true});
            return tasks.some(t=>t.id===id&&t.status==='open'&&t.notification_sent_at);
          }''',arg=fresh['id'])
          passed('A fresh reminder still arrives as a punctual bell after startup and is acknowledged without completing the task')
          stop()
      finally:
        if app and app.poll() is None:
            app.terminate()
            app.wait(timeout=10)
        parking_done.set()
        parking.join(timeout=2)
        # WebView crash handlers may outlive the test app and lock its profile.
        # Stop only WebViews whose command line names this unique test profile.
        fragment = (folder.name+'\\webview').replace("'","''")
        cleanup = "$profileFragment='"+fragment+"'; Get-CimInstance Win32_Process -Filter \"Name='msedgewebview2.exe'\" | Where-Object {$_.CommandLine -and $_.CommandLine.ToLowerInvariant().Contains($profileFragment.ToLowerInvariant())} | ForEach-Object {Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue}"
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',cleanup],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
        time.sleep(1)

(OUT/'reminder-review-native-results.json').write_text(json.dumps(RESULTS,indent=2),encoding='utf8')
