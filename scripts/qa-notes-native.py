"""Built WebView2 editor, SQLite restart persistence and safe exit, with a temp DB."""
import json,os,subprocess,tempfile,time,urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from qa_win import press_reveal
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/qa'
results=[]
def passed(name):results.append({'test':name,'status':'passed'});print(name,flush=True)
with tempfile.TemporaryDirectory(prefix='island-notes-qa-') as temp:
    folder=Path(temp);children=[];receiver=None
    env=dict(os.environ,PERSONAL_ISLAND_DB=str(folder/'tasks.sqlite3'),WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    with (OUT/'notes-native-stderr.log').open('w',encoding='utf8') as log:
        try:
            # Backup/restore the real clipboard through the existing native fixture.
            receiver=subprocess.Popen(['powershell.exe','-NoProfile','-STA','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/qa-clipboard-target.ps1'),'-Folder',str(folder)],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            deadline=time.monotonic()+15
            while not (folder/'ready').exists():
                assert receiver.poll() is None
                assert time.monotonic()<deadline,'Clipboard fixture startup failed'
                time.sleep(.1)
            with sync_playwright() as p:
                def start():
                    proc=subprocess.Popen([str(ROOT/'target/debug/personal-island-desktop.exe')],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW);children.append(proc)
                    deadline=time.monotonic()+30
                    while True:
                        assert proc.poll() is None,'App startup failed'
                        try:urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1).close();break
                        except OSError:
                            assert time.monotonic()<deadline,'WebView2 unavailable';time.sleep(.25)
                    browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222');page=browser.contexts[0].pages[0]
                    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
                    press_reveal();page.locator('.pill').click();page.get_by_role('button',name='Закрепить островок').click()
                    page.get_by_role('button',name='Заметки',exact=True).click()
                    expect(page.get_by_role('textbox',name='Текст заметки')).to_have_attribute('contenteditable','true',timeout=20000)
                    return proc,browser,page
                proc,browser,page=start();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                def invoke(cmd,args=None):return page.evaluate('([cmd,args])=>__TAURI_INTERNALS__.invoke(cmd,args)',[cmd,args or {}])
                title=page.get_by_label('Название записи');edit=page.get_by_role('textbox',name='Текст заметки')
                title.fill('Нативная заметка Ё');edit.fill('Не потерять курсив')
                edit.press('Control+a');page.get_by_role('toolbar',name='Форматирование выделенного текста',exact=True).get_by_role('button',name='Курсив',exact=True).click()
                expect(edit.locator('em')).to_have_text('Не потерять курсив')
                page.get_by_role('button',name='Копировать заметку').click()
                expect(page.locator('.note-message')).to_have_text('Заметка скопирована')
                passed('Built WebView2 editor formats Unicode text and copies rich content to the Windows clipboard')
                page.get_by_role('tab',name='Идеи',exact=True).click();title.fill('Идея после перезапуска');edit.fill('Светлая мысль')
                page.get_by_role('tab',name='Покупки',exact=True).click();title.fill('Продукты на выходные');edit.locator('p').fill('Молоко')
                edit.locator('input[type=checkbox]').check()
                page.get_by_role('button',name='Напомнить о заметке').click()
                page.get_by_label('Текст напоминания из заметки').fill('Купить молоко')
                page.get_by_role('button',name='Создать напоминание',exact=True).click()
                expect(page.locator('.note-message')).to_have_text('Напоминание добавлено')
                task=next(task for task in invoke('list_tasks',{'includeCompleted':True}) if task['title']=='Купить молоко')
                assert task['due_at']==task['reminder_at'] and task['status']=='open'
                quick=page.get_by_role('textbox',name='Быстрое напоминание',exact=True);quick.fill('Проверить островок через 30 мин');quick.press('Enter')
                expect(quick).to_have_value('')
                tasks=invoke('list_tasks',{'includeCompleted':True});assert len(tasks)==2 and tasks[-1]['reminder_at']
                passed('Both note and natural-language reminders create real scheduled tasks with an exact reminder time')
                # Exit immediately after a title edit; the 400ms debounce must not lose it.
                title.fill('Продукты — сохранено при выходе')
                page.get_by_role('button',name='Настройки',exact=True).click();page.get_by_role('button',name='Выход',exact=True).click()
                proc.wait(timeout=15);browser.close()
                proc,browser,page=start()
                title=page.get_by_label('Название записи');edit=page.get_by_role('textbox',name='Текст заметки')
                expect(title).to_have_value('Нативная заметка Ё');expect(edit.locator('em')).to_have_text('Не потерять курсив')
                page.get_by_role('tab',name='Идеи',exact=True).click();expect(title).to_have_value('Идея после перезапуска')
                page.get_by_role('tab',name='Покупки',exact=True).click();expect(title).to_have_value('Продукты — сохранено при выходе')
                expect(edit.locator('input[type=checkbox]')).to_be_checked();expect(edit).to_contain_text('Молоко')
                assert page.locator('.note-editor').evaluate('e=>e.scrollHeight<=e.clientHeight+1'),'Short native notes must not overflow'
                assert len(invoke('list_notes'))==3 and len(invoke('list_tasks',{'includeCompleted':True}))==2
                passed('Real restart preserves all three sections, italic marks, checked items, reminders and the final exit edit')
                page.screenshot(path=str(OUT/'notes-native-shopping.png'))
                assert not errors,errors
                page.get_by_role('button',name='Настройки',exact=True).click();page.get_by_role('button',name='Выход',exact=True).click();proc.wait(timeout=15);browser.close()
        finally:
            if receiver and receiver.poll() is None:
                (folder/'command.json').write_text(json.dumps({'action':'stop','id':999}),encoding='utf8')
                try:receiver.wait(timeout=8)
                except subprocess.TimeoutExpired:receiver.terminate();receiver.wait(timeout=5)
            for child in children:
                if child.poll() is None:child.terminate();child.wait(timeout=5)
            (OUT/'notes-native-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
