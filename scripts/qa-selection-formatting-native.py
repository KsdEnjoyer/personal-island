"""Real WebView2 selection formatting and SQLite restart, on a temp DB/profile."""
import ctypes
from ctypes import wintypes
import json,os,subprocess,tempfile,time,urllib.request
from pathlib import Path
from threading import Event,Thread
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/qa'
OUT.mkdir(parents=True,exist_ok=True)
results=[]
with tempfile.TemporaryDirectory(prefix='island-formatting-') as temporary:
    folder=Path(temporary)
    env=dict(os.environ,PERSONAL_ISLAND_DB=str(folder/'tasks.sqlite3'),PERSONAL_ISLAND_QA_DISABLE_SHORTCUT='1',
        WEBVIEW2_USER_DATA_FOLDER=str(folder/'webview'),WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    app=None
    done=Event()
    user32=ctypes.WinDLL('user32')
    user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user32.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
    def park():
        @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        def visit(window,param):
            owner=wintypes.DWORD();user32.GetWindowThreadProcessId(window,ctypes.byref(owner))
            if app and app.poll() is None and owner.value==app.pid:user32.SetWindowPos(window,None,-8000,-8000,0,0,0x15)
            return True
        while not done.wait(.05):user32.EnumWindows(visit,0)
    thread=Thread(target=park,daemon=True);thread.start()
    with (OUT/'selection-formatting-native.log').open('w',encoding='utf8') as log:
      try:
        with sync_playwright() as p:
          def invoke(command,args=None):return page.evaluate('([c,a])=>__TAURI_INTERNALS__.invoke(c,a)',[command,args or {}])
          def start():
              global app,page,browser
              app=subprocess.Popen([str(ROOT/'target/debug/personal-island-desktop.exe'),'--show'],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
              deadline=time.monotonic()+30
              while True:
                  assert app.poll() is None,'Application exited'
                  try:urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1).close();break
                  except OSError:
                      assert time.monotonic()<deadline,'WebView unavailable';time.sleep(.1)
              browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222');page=browser.contexts[0].pages[0]
              page.emulate_media(reduced_motion='reduce')
              expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
              page.wait_for_timeout(2300)
              invoke('reveal_island_shortcut');page.wait_for_timeout(150)
              page.locator('.compact-stage .pill,.compact-stage .compact-open,.track-peek .peek-art').first.evaluate('(e)=>e.click()')
              expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
              page.locator('.pin-button').evaluate('(e)=>e.click()')
          def stop():
              page.evaluate("setTimeout(()=>__TAURI_INTERNALS__.invoke('exit_app'),30)")
              app.wait(timeout=10);browser.close();time.sleep(.7)
          start()
          page.get_by_role('button',name='Заметки',exact=True).click()
          page.get_by_label('Название записи',exact=True).fill('Проверка оформления')
          edit=page.get_by_role('textbox',name='Текст заметки',exact=True)
          edit.fill('Оформление сохраняется');edit.press('Control+a')
          toolbar=page.get_by_role('toolbar',name='Форматирование выделенного текста',exact=True)
          for label in ['Жирный','Подчёркнутый','Зачёркнутый','Выделить цветом']:toolbar.get_by_role('button',name=label,exact=True).click()
          edit.press('Control+s')
          expect(page.get_by_label('Запись сохранена',exact=True)).to_be_visible()
          note=invoke('list_notes')[0]
          for name in ['bold','underline','strike','highlight']:assert name in note['document']
          page.screenshot(path=str(OUT/'selection-formatting-native.png'))
          page.get_by_role('button',name='Задачи',exact=True).click();page.locator('.add-task').click()
          page.get_by_label('Название задачи',exact=True).fill('Задача с оформлением')
          details=page.get_by_role('textbox',name='Заметка к задаче',exact=True)
          details.fill('Оформленное описание');details.press('Control+a')
          for label in ['Курсив','Подчёркнутый','Выделить цветом']:toolbar.get_by_role('button',name=label,exact=True).click()
          page.get_by_role('button',name='Создать',exact=True).click()
          expect(page.locator('.task-item').filter(has_text='Задача с оформлением').locator('mark')).to_be_visible()
          task=invoke('list_tasks',{'includeCompleted':True})[0]
          assert task['notes'] and '<u>' in task['notes'] and '==' in task['notes']
          stop();start()
          page.get_by_role('button',name='Заметки',exact=True).click()
          edit=page.get_by_role('textbox',name='Текст заметки',exact=True)
          for selector in ['strong','u','s','mark']:expect(edit.locator(selector)).to_have_text('Оформление сохраняется')
          page.get_by_role('button',name='Задачи',exact=True).click()
          row=page.locator('.task-item').filter(has_text='Задача с оформлением')
          for selector in ['em','u','mark']:expect(row.locator(selector)).to_have_text('Оформленное описание')
          assert len(invoke('list_tasks',{'includeCompleted':True}))==1
          assert len(invoke('list_notes'))==1
          results.append({'test':'Native selection commands and both rich-note/Markdown-task formats survive a real restart','status':'passed'})
          print(results[-1]['test'],flush=True)
          stop()
      finally:
        done.set();thread.join(timeout=2)
        if app and app.poll() is None:app.terminate();app.wait(timeout=10)
        fragment=(folder.name+'\\webview').replace("'","''")
        cleanup="$profileFragment='"+fragment+"'; Get-CimInstance Win32_Process -Filter \"Name='msedgewebview2.exe'\" | Where-Object {$_.CommandLine -and $_.CommandLine.ToLowerInvariant().Contains($profileFragment.ToLowerInvariant())} | ForEach-Object {Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue}"
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',cleanup],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
        time.sleep(1)
(OUT/'selection-formatting-native-results.json').write_text(json.dumps(results,indent=2),encoding='utf8')
