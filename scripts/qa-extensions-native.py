"""Actual clipboard capture/paste and WinRT media session integration.

Uses a temporary DB, a native paste receiver, and a silent local media fixture.
The receiver restores the original clipboard in its finally block.
"""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import wave
import struct,zlib
from playwright.sync_api import sync_playwright, expect
from qa_win import press_reveal, user32, focus_process

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/qa'
results=[]
def passed(name):
    results.append({'test':name,'status':'passed'});print(name,flush=True)
def read(path):
    try:return json.loads(path.read_text(encoding='utf-8-sig'))
    except json.JSONDecodeError:return {}

with tempfile.TemporaryDirectory(prefix='personal-island-extensions-') as temp:
    folder=Path(temp)
    env=dict(os.environ,PERSONAL_ISLAND_DB=str(folder/'tasks.sqlite3'),WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    processes=[]; receiver=None; seq=0
    with (OUT/'extensions-native-stderr.log').open('w',encoding='utf-8') as log:
        try:
            proc=subprocess.Popen([str(ROOT/'target/debug/personal-island-desktop.exe')],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            processes.append(proc)
            deadline=time.monotonic()+30
            while True:
                assert proc.poll() is None
                try:urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1).close();break
                except OSError:
                    if time.monotonic()>deadline:raise TimeoutError('WebView unavailable')
                    time.sleep(.25)
            receiver=subprocess.Popen(['powershell.exe','-NoProfile','-STA','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/qa-clipboard-target.ps1'),'-Folder',str(folder)],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            with sync_playwright() as p:
                browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222')
                page=browser.contexts[0].pages[0]
                expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
                def wait_for(predicate,timeout=10):
                    deadline=time.monotonic()+timeout
                    while not predicate():
                        assert receiver.poll() is None,'Native receiver exited'
                        if time.monotonic()>deadline:raise TimeoutError('Native fixture timed out')
                        page.wait_for_timeout(100)
                wait_for(lambda:(folder/'ready').exists())
                def command(action,**kwargs):
                    global seq
                    if action=='focus':focus_process(receiver.pid)
                    seq+=1
                    (folder/'command.json').write_text(json.dumps(dict(action=action,id=seq,**kwargs)),encoding='utf-8')
                    wait_for(lambda:(folder/'ack.json').exists() and read(folder/'ack.json').get('id')==seq)
                def invoke(cmd,args=None):return page.evaluate('([cmd,args])=>window.__TAURI_INTERNALS__.invoke(cmd,args)',[cmd,args or {}])
                def history(search=''):return invoke('list_clipboard',{'search':search})
                def open_clipboard():
                    press_reveal();page.locator('.pill').click()
                    page.get_by_role('button',name='Закрепить островок').click()
                    page.get_by_role('button',name='Буфер обмена',exact=True).click()
                command('text',text='QA native Привет\n  exact spaces')
                wait_for(lambda:len(history('ПРИВЕТ')['entries'])==1)
                entry=history('ПРИВЕТ')['entries'][0]
                assert entry['text']=='QA native Привет\n  exact spaces'
                open_clipboard()
                expect(page.locator('.clipboard-card')).to_have_count(1)
                page.get_by_label('Закрепить запись').click()
                assert history()['entries'][0]['pinned']
                passed('Windows clipboard captures exact Unicode text and persists pins')
                page.get_by_label('Приостановить запись буфера').click()
                command('text',text='QA paused content')
                page.wait_for_timeout(650)
                assert not history('paused')['entries']
                page.get_by_label('Возобновить запись буфера').click()
                command('image')
                wait_for(lambda:any(e['kind']=='image' for e in history()['entries']))
                image=next(e for e in history()['entries'] if e['kind']=='image')
                assert (image['width'],image['height'])==(80,60)
                expect(page.locator('.clip-content img')).to_be_visible(timeout=5000)
                passed('Pause excludes new copies; real bitmap capture produces a thumbnail')
                command('focus');page.wait_for_timeout(400)
                page.locator('.clip-content').filter(has_text='QA native Привет').click()
                wait_for(lambda:(folder/'pasted.json').exists())
                assert read(folder/'pasted.json')=={'kind':'text','text':'QA native Привет\n  exact spaces'}
                expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
                passed('Click restores the previous native editor and sends real Ctrl+V with exact text')
                (folder/'pasted.json').unlink()
                command('focus');page.wait_for_timeout(300)
                open_clipboard()
                page.get_by_role('button',name='Вставить картинку 80 на 60').click()
                wait_for(lambda:(folder/'pasted.json').exists())
                assert read(folder/'pasted.json')=={'kind':'image','width':80,'height':60}
                passed('Click pastes the original image into the previous native window')
                # A dedicated local media fixture never controls another app's playback.
                with wave.open(str(folder/'silence.wav'),'wb') as wav:
                    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000);wav.writeframes(b'\0\0'*8000*60)
                media_proc=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/qa-media-fixture.ps1'),'-Folder',str(folder)],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                processes.append(media_proc)
                selected=None
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    assert media_proc.poll() is None,'Media fixture failed; see extensions-native-stderr.log'
                    state=invoke('get_media_state',{'preferred':None})
                    for source in state['sessions']:
                        candidate=invoke('get_media_state',{'preferred':source['id']})
                        if candidate['title']=='QA Island Media Track': selected=candidate;break
                    if selected:break
                    page.wait_for_timeout(300)
                assert selected,'Controlled Windows media session not found'
                source=selected['session_id']
                assert selected['artist']=='QA Local Artist'
                invoke('media_command',{'sessionId':source,'action':'toggle'})
                wait_for(lambda:not invoke('get_media_state',{'preferred':source})['playing'])
                invoke('media_command',{'sessionId':source,'action':'toggle'})
                wait_for(lambda:invoke('get_media_state',{'preferred':source})['playing'])
                passed('WinRT reads a real media session and play/pause controls only that source')
                (folder/'stop-media').touch();media_proc.wait(timeout=10)
                command('focus');open_clipboard()
                invoke('set_clipboard_enabled',{'enabled':False})
                page.get_by_role('button',name='Настройки').click()
                page.get_by_role('button',name='Выход',exact=True).click()
                proc.wait(timeout=10);browser.close()
                proc=subprocess.Popen([str(ROOT/'target/debug/personal-island-desktop.exe')],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                processes.append(proc)
                deadline=time.monotonic()+20
                while True:
                    try:urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1).close();break
                    except OSError:
                        if time.monotonic()>deadline:raise TimeoutError('Restart failed')
                        time.sleep(.25)
                browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222')
                page=browser.contexts[0].pages[0]
                expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
                saved=history()
                assert not saved['enabled']
                assert len(saved['entries'])==2
                assert saved['entries'][0]['pinned']
                assert any(e['kind']=='image' for e in saved['entries'])
                passed('Restart retains pinned text, image history and the capture pause setting')
                command('focus');open_clipboard()
                invoke('set_clipboard_enabled',{'enabled':True})
                def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
                photo=folder/'photo.png';document=folder/'brief.pdf'
                pixels=b''.join(b'\x00'+bytes([41,111,143,255])*20 for _ in range(12))
                photo.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',20,12,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b''))
                document.write_bytes(b'%PDF-1.4\n% Local QA fixture only\n')
                command('files',paths=[str(photo),str(document)])
                wait_for(lambda:len(history('photo.png')['entries'])==1)
                file_entry=history('photo.png')['entries'][0]
                assert file_entry['kind']=='files'
                assert [f['path'] for f in file_entry['files']]==[str(photo),str(document)]
                assert file_entry['thumbnail'].startswith('data:image/png;base64,')
                card=page.locator('.clipboard-card').filter(has_text='photo.png')
                expect(card.locator('img')).to_be_visible()
                page.screenshot(path=str(OUT/'clipboard-native-files.png'))
                passed('Explorer-style photo/document group is captured with exact paths, searchable names and photo preview')
                command('focus');open_clipboard()
                (folder/'pasted.json').unlink(missing_ok=True)
                page.get_by_role('button',name='Вставить файлы: photo.png, brief.pdf',exact=True).click()
                wait_for(lambda:(folder/'pasted.json').exists())
                pasted=read(folder/'pasted.json')
                assert pasted['kind']=='files' and pasted['paths']==[str(photo),str(document)],pasted
                assert photo.exists() and document.exists()
                passed('File history restores real CF_HDROP; Ctrl+V receives the original file list and keeps sources intact')
                command('focus');open_clipboard()
                document.unlink()
                page.get_by_role('button',name='Вставить файлы: photo.png, brief.pdf',exact=True).click()
                expect(page.locator('.utility-error')).to_contain_text('перемещён или удалён')
                passed('A missing source file produces a recoverable error instead of pasting a partial group')
                command('png-only',path=str(photo))
                wait_for(lambda:any(e['kind']=='image' and e['width']==20 and e['height']==12 for e in history()['entries']))
                passed('PNG-only clipboard content is captured even without a Windows bitmap or text format')
                page.get_by_role('button',name='Настройки').click()
                page.get_by_role('button',name='Выход',exact=True).click()
                proc.wait(timeout=10);browser.close()
        finally:
            (folder/'stop-media').touch()
            if receiver and receiver.poll() is None:
                seq+=1;(folder/'command.json').write_text(json.dumps({'action':'stop','id':seq}),encoding='utf-8')
                try:receiver.wait(timeout=8)
                except subprocess.TimeoutExpired:receiver.terminate();receiver.wait(timeout=5)
            for child in processes:
                if child.poll() is None:child.terminate();child.wait(timeout=5)
            (OUT/'extensions-native-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
