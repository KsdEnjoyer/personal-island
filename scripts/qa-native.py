"""Native Tauri + SQLite + MCP smoke test using a fresh temporary database.

Requires debug binaries built with Tauri --no-bundle, Python Playwright,
and a free loopback port 9222. Never opens the default task database.
Pass --notifications to include one island reminder. Prefer the current
qa-reminder-native.py suite for reminder delivery and presentation.
"""
import json
import os
from pathlib import Path
from queue import Queue, Empty
import sqlite3
import subprocess
import sys
import tempfile
from threading import Thread
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect
from qa_win import press_reveal

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'qa'
OUT.mkdir(parents=True, exist_ok=True)
RESULTS = []


class MCP:
    def __init__(self, env, stderr):
        self.proc = subprocess.Popen([str(ROOT / 'target/debug/task-mcp.exe')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
            text=True, encoding='utf-8', env=env,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.messages = Queue()
        self.seq = 0
        Thread(target=self.read, daemon=True).start()
        result = self.call('initialize', {'protocolVersion':'2024-11-05',
            'capabilities':{}, 'clientInfo':{'name':'personal-island-qa','version':'1.0'}})
        assert 'protocolVersion' in result, result
        self.send({'jsonrpc':'2.0','method':'notifications/initialized'})

    def read(self):
        for line in self.proc.stdout:
            self.messages.put(json.loads(line))

    def send(self, message):
        self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
        self.proc.stdin.flush()

    def call(self, method, params):
        self.seq += 1
        self.send({'jsonrpc':'2.0','id':self.seq,'method':method,'params':params})
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                reply = self.messages.get(timeout=max(0.1, deadline-time.monotonic()))
            except Empty:
                raise TimeoutError(f'MCP timeout: {method}')
            if reply.get('id') == self.seq:
                assert 'error' not in reply, reply
                return reply['result']
        raise TimeoutError(method)

    def tool(self, name, args):
        result = self.call('tools/call', {'name':name, 'arguments':args})
        assert not result.get('isError'), result
        value = '\n'.join(part['text'] for part in result['content'] if part['type'] == 'text')
        assert not value.startswith('ERROR:'), value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=5)


def passed(name):
    RESULTS.append({'test':name,'status':'passed'})
    print(name, flush=True)


def wait_cdp(proc):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        assert proc.poll() is None, f'Desktop exited with {proc.returncode}'
        try:
            with urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1):
                return
        except OSError:
            time.sleep(.25)
    raise TimeoutError('WebView2 debug endpoint did not open')


with tempfile.TemporaryDirectory(prefix='personal-island-qa-') as temp:
    db = Path(temp) / 'tasks.sqlite3'
    env = dict(os.environ, PERSONAL_ISLAND_DB=str(db),
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    desktop = None
    mcp = None
    with (OUT / 'native-stderr.log').open('w',encoding='utf-8') as log:
        try:
            mcp = MCP(env,log)
            tools = mcp.call('tools/list',{})['tools']
            assert len(tools) == 11, [tool['name'] for tool in tools]
            passed('MCP initialize and discover eleven tools')
            assert 'Local time:' in mcp.tool('get_current_time',{})
            task = mcp.tool('create_task', {'title':'QA native shared task','priority':2})
            task_id = task['id']
            assert mcp.tool('list_tasks',{})[0]['id'] == task_id
            mcp.tool('update_task',{'id':task_id,'notes':'Local test only'})
            task = mcp.tool('reschedule_task',{'id':task_id,'due_at':'2030-01-02T17:00:00+03:00'})
            assert task['due_at'] == '2030-01-02T14:00:00Z'
            assert task['reminder_at'] == '2030-01-02T13:30:00Z'
            mcp.tool('complete_task',{'id':task_id})
            assert mcp.tool('list_tasks',{}) == []
            mcp.tool('reopen_task',{'id':task_id})
            passed('MCP create, list, update, reschedule, complete and reopen')

            desktop = subprocess.Popen([str(ROOT / 'target/debug/personal-island-desktop.exe')],
                env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
            wait_cdp(desktop)
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
                page = browser.contexts[0].pages[0]
                assert page.evaluate('innerWidth') == 480
                expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
                press_reveal()
                page.locator('.pill').click()
                page.get_by_role('button',name='Закрепить островок').click()
                page.wait_for_timeout(900)
                assert page.evaluate('innerWidth === Math.min(960, screen.availWidth)')
                passed('Native window grows before the liquid spring expands')
                page.get_by_role('button',name='Далее',exact=True).click()
                expect(page.locator('.task-name')).to_have_text(['QA native shared task'])
                passed('Native WebView displays task persisted by MCP')
                page.screenshot(path=str(OUT / 'native-shared-task.png'))

                page.get_by_role('button',name='Добавить задачу').click()
                page.get_by_placeholder('Что нужно сделать?').fill('QA native UI task')
                page.get_by_role('button',name='Создать').click()
                expect(page.locator('.task-name')).to_have_text(['QA native UI task'])
                tasks = mcp.tool('list_tasks',{})
                ui_id = next(t['id'] for t in tasks if t['title'] == 'QA native UI task')
                passed('Native UI creates task visible through MCP')

                row = page.locator('.task-item').filter(has_text='QA native UI task')
                row.get_by_label('Изменить статус задачи').click()
                page.get_by_role('button',name='Готово',exact=True).click()
                expect(row).to_be_visible()
                assert next(t for t in mcp.tool('list_tasks',{'include_completed':True}) if t['id'] == ui_id)['status'] == 'done'
                row.get_by_label('Изменить статус задачи').click()
                page.get_by_role('button',name='Входящие',exact=True).click()
                expect(row).to_be_visible()
                passed('Native complete and reopen persist through SQLite')

                external = mcp.tool('create_task',{'title':'QA native external polling'})
                expect(page.locator('.task-item').filter(has_text='QA native external polling')).to_be_visible(timeout=7000)
                passed('Native UI polls changes from separate MCP process')
                disposable = mcp.tool('create_task',{'title':'QA native delete UI'})
                delete_row = page.locator('.task-item').filter(has_text='QA native delete UI')
                try:
                    expect(delete_row).to_be_visible(timeout=7000)
                except Exception:
                    page.screenshot(path=str(OUT/'native-failure.png'))
                    print('Native diagnostics:',json.dumps(page.evaluate('''async () => ({
                      visibility:document.visibilityState,
                      pinned:document.querySelector('.pin-button').getAttribute('aria-pressed'),
                      expanded:document.querySelector('.dashboard').getAttribute('aria-hidden'),
                      activeTab:document.querySelector('.tabs .active').getAttribute('aria-label'),
                      visibleTasks:[...document.querySelectorAll('.task-name')].map(el => el.textContent),
                      backendTasks:await window.__TAURI_INTERNALS__.invoke('list_tasks',{includeCompleted:true})
                    })'''),ensure_ascii=True),flush=True)
                    raise
                delete_row.hover()
                delete_row.get_by_label('Удалить задачу').click()
                delete_row.get_by_role('button',name='Отмена',exact=True).click()
                expect(delete_row).to_be_visible()
                delete_row.get_by_label('Удалить задачу').click()
                delete_row.get_by_role('button',name='Удалить навсегда',exact=True).click()
                expect(delete_row).to_have_count(0)
                assert all(t['id'] != disposable['id'] for t in mcp.tool('list_tasks',{}))
                passed('Native delete confirmation cancels and accepts correctly')
                # Optional legacy reminder check; presentation now uses the island.
                if '--notifications' in sys.argv:
                    reminder = mcp.tool('create_task',{'title':'QA reminder test', 'reminder_at':'2020-01-01T00:00:00Z'})
                    deadline = time.monotonic() + 25
                    sent = None
                    while time.monotonic() < deadline:
                        with sqlite3.connect(db) as con:
                            sent = con.execute('SELECT notification_sent_at FROM tasks WHERE id=?',(reminder['id'],)).fetchone()[0]
                        if sent:
                            break
                        page.wait_for_timeout(500)
                    assert sent, 'Island reminder presentation not recorded; see native-stderr.log'
                    passed('Island reminder presentation recorded')

                mcp.tool('delete_task',{'id':external['id']})
                expect(page.locator('.task-item').filter(has_text='QA native external polling')).to_have_count(0,timeout=7000)
                passed('MCP delete is reflected in native UI')
                page.get_by_role('button',name='Запустить таймер').click()
                expect(page.locator('.timer-value')).not_to_have_text('25:00',timeout=3500)
                page.get_by_role('button',name='Приостановить таймер').click()
                passed('Focus timer works in the native WebView')
                page.get_by_role('button',name='Свернуть',exact=True).click()
                page.wait_for_timeout(1400)
                assert page.evaluate('innerWidth') == 480
                expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
                passed('Native window shrinks after the silhouette settles and stays closed')
                press_reveal()
                page.locator('.pill').click()
                page.get_by_role('button',name='Настройки').click()
                page.get_by_role('button',name='Выход',exact=True).click()
                desktop.wait(timeout=10)
                passed('Native exit command shuts down process')
                browser.close()

            desktop = subprocess.Popen([str(ROOT / 'target/debug/personal-island-desktop.exe')],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            wait_cdp(desktop)
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
                page = browser.contexts[0].pages[0]
                expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
                press_reveal()
                page.locator('.pill').click()
                page.get_by_role('button',name='Закрепить островок').click()
                page.get_by_role('button',name='Входящие',exact=True).click()
                expect(page.locator('.task-item').filter(has_text='QA native UI task')).to_be_visible()
                passed('Tasks survive a native application restart')
                page.get_by_role('button',name='Настройки').click()
                page.get_by_role('button',name='Выход',exact=True).click()
                desktop.wait(timeout=10)
                browser.close()
        finally:
            if desktop is not None and desktop.poll() is None:
                desktop.terminate()
                desktop.wait(timeout=10)
            if mcp is not None:
                mcp.close()
            (OUT / 'native-results.json').write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2),encoding='utf-8')
