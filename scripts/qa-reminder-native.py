"""Real island reminder delivery and persistence, using an isolated SQLite database.

Requires a packaged debug executable and a free WebView2 debug port 9222.
No personal tasks, clipboard contents, music or system volume are changed.
"""
import ctypes
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/qa'
OUT.mkdir(parents=True, exist_ok=True)
RESULTS = []


def passed(name):
    RESULTS.append({'test': name, 'status': 'passed'})
    print(name, flush=True)


def stamp(delta):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta)).isoformat()


user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]


def foreground_pid():
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    return pid.value


with tempfile.TemporaryDirectory(prefix='island-reminder-native-') as temp:
    db = Path(temp) / 'tasks.sqlite3'
    env = dict(os.environ, PERSONAL_ISLAND_DB=str(db),
               WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    children = []
    with (OUT / 'reminder-native-stderr.log').open('w', encoding='utf8') as log:
      try:
        with sync_playwright() as p:
          def start():
            app = subprocess.Popen([str(ROOT / 'target/debug/personal-island-desktop.exe')],
                env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
            children.append(app)
            end = time.monotonic() + 30
            while True:
                assert app.poll() is None, 'Application exited'
                try:
                    urllib.request.urlopen('http://127.0.0.1:9222/json/version', timeout=1).close()
                    break
                except OSError:
                    assert time.monotonic() < end, 'WebView2 unavailable'
                    time.sleep(.2)
            browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
            page = browser.contexts[0].pages[0]
            expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready', 'true')
            return app, browser, page

          def invoke(cmd, args=None):
            return page.evaluate('([cmd,args])=>window.__TAURI_INTERNALS__.invoke(cmd,args)', [cmd, args or {}])

          def create(title, delay=-3):
            return invoke('create_task', {'task': {'title': title, 'due_at': stamp(300),
                'reminder_at': stamp(delay), 'notes': None, 'priority': 0}})

          def create_via_mcp(title):
            messages = [
                {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                    'protocolVersion': '2024-11-05', 'capabilities': {},
                    'clientInfo': {'name': 'reminder-native-qa', 'version': '1.0'}}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
                    'name': 'create_task', 'arguments': {'title': title,
                        'due_at': stamp(300), 'reminder_at': stamp(-3)}}},
            ]
            process = subprocess.run([str(ROOT / 'target/debug/task-mcp.exe')],
                input=''.join(json.dumps(item) + '\n' for item in messages),
                env=env, stdout=subprocess.PIPE, stderr=log, text=True, encoding='utf8',
                timeout=15, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
            reply = next(item for line in process.stdout.splitlines()
                if (item := json.loads(line)).get('id') == 2)
            result = reply['result']
            assert not result.get('isError'), result
            return json.loads(next(item['text'] for item in result['content'] if item['type'] == 'text'))

          def sent(task_id):
            with closing(sqlite3.connect(db)) as connection:
                return connection.execute('SELECT notification_sent_at FROM tasks WHERE id=?', (task_id,)).fetchone()[0]

          def await_sent(task_id):
            end = time.monotonic() + 5
            while not sent(task_id):
                assert time.monotonic() < end, 'Rendered reminder not acknowledged'
                page.wait_for_timeout(100)

          def stop(app, browser):
            page.evaluate("setTimeout(()=>window.__TAURI_INTERNALS__.invoke('exit_app'),50)")
            app.wait(timeout=10)
            browser.close()

          app, browser, page = start()
          errors = []
          page.on('pageerror', lambda error: errors.append(str(error)))
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden', 'true')
          page.evaluate("window.qaReminderFocusCount=0;window.addEventListener('focus',()=>qaReminderFocusCount++)")
          first = create_via_mcp('Подготовиться к созвону')
          second = create('Открыть материалы встречи', -2)
          compact = page.locator('.compact-stage .reminder-notice')
          expect(compact).to_have_attribute('data-phase', 'bell', timeout=12000)
          expect(compact.locator('strong')).to_have_count(0)
          assert not sent(first['id']), 'Bell animation consumed the reminder before showing its text'
          expect(compact.locator('strong')).to_have_text(first['title'], timeout=12000)
          # The entrance scales the whole island for 380 ms; measure the
          # settled geometry rather than an intermediate animation frame.
          page.wait_for_timeout(450)
          # Other applications may change focus while the suite is running.
          # The island must neither become foreground nor receive a focus event.
          assert foreground_pid() != app.pid, 'Reminder became the foreground window'
          assert page.evaluate('qaReminderFocusCount') == 0, 'Reminder received keyboard focus'
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden', 'true')
          assert page.evaluate('innerWidth') == 480
          assert compact.bounding_box()['width'] == 272 and compact.bounding_box()['height'] == 56
          await_sent(first['id'])
          assert not sent(second['id']), 'Queued reminder acknowledged before presentation'
          first_sent = sent(first['id'])
          page.screenshot(path=str(OUT / 'reminder-native.png'))
          passed('A task created through real MCP reveals a compact native reminder without taking focus; only the painted occurrence is acknowledged')

          expect(compact.locator('strong')).to_have_text(second['title'], timeout=12500)
          await_sent(second['id'])
          assert sent(first['id']) == first_sent
          compact.locator('.reminder-open').click()
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden', 'false')
          # CDP pointer events do not move the real Windows cursor. Pin the
          # expanded test panel, as in the other native acceptance suites.
          page.locator('.pin-button').evaluate('(button)=>button.click()')
          expect(page.locator(f'[data-task-id="{second["id"]}"]')).to_have_class(re.compile('reminder-highlight'))
          assert next(task for task in invoke('list_tasks', {'includeCompleted': True}) if task['id'] == second['id'])['status'] == 'open'
          passed('After eight seconds the next due reminder appears; Open highlights the task without completing it')

          page.get_by_label('Новая задача', exact=True).click()
          field = page.get_by_label('Название задачи', exact=True)
          field.fill('Несохранённый черновик')
          current = create('Не потерять черновик')
          banner = page.locator('.dashboard .reminder-notice')
          expect(banner.locator('strong')).to_have_text(current['title'], timeout=10000)
          assert page.evaluate('innerWidth') == 760
          expect(field).to_have_value('Несохранённый черновик')
          assert page.evaluate('document.activeElement?.getAttribute("aria-label")') == 'Название задачи'
          await_sent(current['id'])
          banner.get_by_label('Закрыть напоминание').click()
          expect(banner).to_have_count(0)
          expect(field).to_have_value('Несохранённый черновик')
          expect(page.locator('.dashboard')).to_have_attribute('aria-hidden', 'false')
          passed('An actual native reminder preserves the open panel, input focus and unsaved draft')

          page.get_by_role('button', name='Отмена', exact=True).click()
          forced = create('Закрыть панель с напоминанием')
          expect(banner.locator('strong')).to_have_text(forced['title'], timeout=10000)
          await_sent(forced['id'])
          page.get_by_label('Свернуть', exact=True).click()
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden', 'true')
          stop(app, browser)
          assert not errors, errors

          app, browser, page = start()
          page.wait_for_timeout(6500)
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden', 'true')
          assert sent(first['id']) == first_sent
          assert len(invoke('list_tasks', {'includeCompleted': True})) == 4
          passed('Delivered occurrences survive a real application restart without being replayed')

          changed = invoke('reschedule_task', {'id': first['id'], 'dueAt': stamp(600), 'reminderAt': stamp(-1)})
          assert changed['notification_sent_at'] is None
          expect(page.locator('.compact-stage .reminder-notice strong')).to_have_text(first['title'], timeout=10000)
          await_sent(first['id'])
          assert sent(first['id']) != first_sent
          page.locator('.compact-stage .reminder-dismiss').click()
          expect(page.locator('.island-shell')).to_have_attribute('aria-hidden', 'true')
          passed('Rescheduling the same task delivers its new occurrence and Close dismisses only the reminder')
          stop(app, browser)
      except Exception:
        try:
            print('Native failure state:', page.evaluate('''()=>({
              presentation:document.querySelector('.island-shell')?.dataset.presentation,
              shellHidden:document.querySelector('.island-shell')?.getAttribute('aria-hidden'),
              dashboardHidden:document.querySelector('.dashboard')?.getAttribute('aria-hidden'),
              notices:[...document.querySelectorAll('.reminder-notice')].map(e=>({phase:e.dataset.phase,text:e.textContent})),
              width:innerWidth,errors:[]
            })'''), flush=True)
            print('Browser errors:', errors, flush=True)
            page.screenshot(path=str(OUT / 'reminder-native-failure.png'))
        except Exception:
            pass
        raise
      finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
        (OUT / 'reminder-native-results.json').write_text(json.dumps(RESULTS, indent=2), encoding='utf8')
