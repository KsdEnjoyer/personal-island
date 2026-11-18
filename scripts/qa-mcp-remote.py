"""Real stdio + Streamable HTTP against a temporary database. No personal tasks.

Build: cargo build -p task-mcp --features http --bins
"""
import json
from contextlib import closing
import os
from pathlib import Path
from queue import Queue
import secrets
import sqlite3
import subprocess
import tempfile
from threading import Thread
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BIN = Path(os.environ.get('PERSONAL_ISLAND_QA_BIN_DIR', ROOT/'target/debug'))
OUT = ROOT / 'artifacts/qa'
RESULTS = []
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def passed(name):
    RESULTS.append({'test': name, 'status': 'passed'})
    print(name, flush=True)


class Stdio:
    def __init__(self, env, log):
        self.process = subprocess.Popen(
            [str(BIN/'task-mcp.exe')], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
            text=True, encoding='utf8', creationflags=subprocess.CREATE_NO_WINDOW)
        self.messages = Queue()
        Thread(target=lambda: [self.messages.put(json.loads(line)) for line in self.process.stdout], daemon=True).start()
        self.sequence = 0
        self.call('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'island-qa', 'version': '1'}})
        self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def send(self, message):
        self.process.stdin.write(json.dumps(message)+'\n')
        self.process.stdin.flush()

    def call(self, method, params):
        self.sequence += 1
        self.send({'jsonrpc': '2.0', 'id': self.sequence, 'method': method, 'params': params})
        while True:
            message = self.messages.get(timeout=15)
            if message.get('id') == self.sequence:
                assert 'error' not in message, message
                return message['result']

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)


def value(result):
    assert not result.get('isError'), result
    return json.loads(result['content'][0]['text'])


with tempfile.TemporaryDirectory(prefix='island-remote-mcp-') as folder:
    folder = Path(folder)
    db = folder/'tasks.sqlite3'
    token = secrets.token_hex(32)
    token_file = folder/'bridge.token'
    token_file.write_text(token, encoding='ascii')
    env = dict(os.environ, PERSONAL_ISLAND_DB=str(db), PERSONAL_ISLAND_TIMEZONE='Europe/Moscow',
               PERSONAL_ISLAND_MCP_TOKEN_FILE=str(token_file), PERSONAL_ISLAND_MCP_BIND='127.0.0.1:0')
    env.pop('PERSONAL_ISLAND_MCP_TOKEN', None)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT/'mcp-remote-stderr.log').open('w', encoding='utf8') as log:
        server = subprocess.Popen([str(BIN/'task-mcp-http.exe')], env=env,
                                  stdout=log, stderr=subprocess.PIPE, text=True, encoding='utf8',
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        lines = Queue()
        Thread(target=lambda: [lines.put(line) for line in server.stderr], daemon=True).start()
        stdio = None
        try:
            deadline = time.monotonic()+30
            while True:
                line = lines.get(timeout=30)
                log.write(line); log.flush()
                if 'listening at http://' in line:
                    base = line.split('http://', 1)[1].split('/mcp', 1)[0]
                    base = 'http://'+base
                    break
                assert server.poll() is None and time.monotonic()<deadline

            def request(body=None, headers=None, authenticated=True, path='/mcp'):
                head = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                        'MCP-Protocol-Version': '2025-11-25'}
                if authenticated: head['Authorization'] = 'Bearer '+token
                head.update(headers or {})
                data = json.dumps(body).encode() if body is not None else None
                req = urllib.request.Request(base+path, data=data, headers=head)
                try:
                    with HTTP.open(req, timeout=15) as response:
                        raw = response.read()
                        return response.status, json.loads(raw) if raw else None
                except urllib.error.HTTPError as error:
                    return error.code, None

            sequence = 0

            def rpc(method, params):
                global sequence
                sequence += 1
                status, message = request({'jsonrpc': '2.0', 'id': sequence, 'method': method, 'params': params})
                assert status == 200, (status, method)
                assert 'error' not in message, message
                return message['result']

            def tool(name, args):
                return rpc('tools/call', {'name': name, 'arguments': args})

            assert request(path='/health', authenticated=False)[0] == 401
            assert request(path='/health', headers={'Authorization': 'Bearer invalid'})[0] == 401
            assert request(path='/health')[1]['status'] == 'ready'
            assert request(path='/health', headers={'Origin': 'https://untrusted.example'})[0] == 403
            assert request({'jsonrpc':'2.0','id':1,'method':'tools/list'}, headers={'Host':'untrusted.example'})[0] == 403
            assert request({'padding':'x'*(270*1024)})[0] == 413
            passed('HTTP rejects missing/wrong credentials, browser origins, foreign hosts and oversized bodies')

            initialized = rpc('initialize', {'protocolVersion':'2025-11-25', 'capabilities':{}, 'clientInfo':{'name':'island-http-qa','version':'1'}})
            assert 'Personal Island' in initialized['instructions']
            tools = {item['name']: item for item in rpc('tools/list', {})['tools']}
            assert len(tools) == 11, tools.keys()
            assert tools['list_schedule']['annotations']['readOnlyHint'] is True
            assert tools['create_tasks']['annotations']['readOnlyHint'] is False
            assert tools['delete_task']['annotations']['destructiveHint'] is True
            clock = tool('get_current_time', {})
            assert clock['structuredContent']['timezone'] == 'Europe/Moscow'
            assert '+03:00' in clock['structuredContent']['local_time']
            passed('Streamable HTTP discovers eleven annotated tools and returns the configured Moscow time')

            missing_key = tool('create_task', {'title':'No request key'})
            assert missing_key['isError'] is True
            first = value(tool('create_task', {'title':'QA single task', 'request_key':'qa-single', 'due_at':'2030-01-02T10:00:00+03:00'}))
            retry = value(tool('create_task', {'title':'QA single task', 'request_key':'qa-single', 'due_at':'2030-01-02T07:00:00Z'}))
            assert first['id'] == retry['id']
            assert tool('create_task', {'title':'Changed intent','request_key':'qa-single'})['isError'] is True
            bad = tool('create_tasks', {'request_key':'qa-plan','tasks':[{'title':'Valid'},{'title':'  '}]})
            assert bad['isError'] is True
            assert len(value(tool('list_tasks', {}))) == 1
            plan = {'request_key':'qa-plan', 'tasks':[{'title':'QA morning','due_at':'2030-01-02T09:00:00+03:00'}, {'title':'QA next day','due_at':'2030-01-03T12:00:00+03:00'}]}
            created = value(tool('create_tasks', plan))
            assert [t['id'] for t in created] == [t['id'] for t in value(tool('create_tasks', plan))]
            schedule = value(tool('list_schedule', {'start_at':'2030-01-02T00:00:00+03:00','end_at':'2030-01-03T00:00:00+03:00'}))
            assert {t['title'] for t in schedule} == {'QA morning','QA single task'}
            passed('HTTP writes are atomic, reject key conflicts and replay without duplicates; schedule uses local-day boundaries')

            stdio = Stdio(env, log)
            all_tasks = value(stdio.call('tools/call', {'name':'list_tasks','arguments':{}}))
            assert len(all_tasks) == 3
            assert value(stdio.call('tools/call', {'name':'get_task','arguments':{'id':first['id']}}))['id'] == first['id']
            # Legacy stdio clients retain creation without a request key.
            legacy = value(stdio.call('tools/call', {'name':'create_task','arguments':{'title':'QA legacy stdio'}}))
            assert value(tool('get_task', {'id':legacy['id']}))['title'] == 'QA legacy stdio'
            with closing(sqlite3.connect(db)) as connection:
                assert connection.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 4
            value(tool('delete_task', {'id':first['id']}))
            assert tool('create_task', {'title':'QA single task','request_key':'qa-single','due_at':'2030-01-02T07:00:00Z'})['isError'] is True
            assert len(value(tool('list_tasks', {}))) == 3
            passed('Stdio and HTTP share one database; legacy clients work and retries never resurrect deleted tasks')
        finally:
            if stdio is not None: stdio.close()
            if server.poll() is None: server.terminate(); server.wait(timeout=10)
            (OUT/'mcp-remote-results.json').write_text(json.dumps(RESULTS, indent=2), encoding='utf8')
