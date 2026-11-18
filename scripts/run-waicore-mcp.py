"""Windowless Windows supervisor. No console, model API, or external dependencies."""
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import traceback
import urllib.request
from relay_config import load_config

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=Path(os.environ['LOCALAPPDATA'])/'PersonalIsland/waicore-mcp'
LOCAL=PRIVATE.parent
BINARY=ROOT/'target/debug/task-mcp-http.exe'
STATE=PRIVATE/'process.json'
HTTP=urllib.request.build_opener(urllib.request.ProxyHandler({}))
KERNEL=ctypes.WinDLL('kernel32',use_last_error=True)
KERNEL.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
KERNEL.CreateMutexW.restype=wintypes.HANDLE
KERNEL.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
KERNEL.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
KERNEL.OpenProcess.restype=wintypes.HANDLE
KERNEL.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
KERNEL.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
KERNEL.CloseHandle.argtypes=[wintypes.HANDLE]
KERNEL.ReleaseMutex.argtypes=[wintypes.HANDLE]
KERNEL.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]


def identity(pid):
    handle=KERNEL.OpenProcess(0x1000,False,pid)
    if not handle: return None
    try:
        buffer=ctypes.create_unicode_buffer(32768)
        size=wintypes.DWORD(len(buffer))
        times=[wintypes.FILETIME() for _ in range(4)]
        if not KERNEL.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)): return None
        if not KERNEL.GetProcessTimes(handle,*[ctypes.byref(value) for value in times]): return None
        created=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
        return {'pid':pid,'executable':buffer.value,'creation_ticks':str(created),
            'started_utc':datetime.fromtimestamp(created/10000000-11644473600,timezone.utc).isoformat()}
    finally: KERNEL.CloseHandle(handle)


def stop_previous(ssh):
    if not STATE.exists(): return
    saved=json.loads(STATE.read_text(encoding='utf-8-sig'))
    current=identity(int(saved['pid']))
    if not current or os.path.normcase(current['executable'])!=os.path.normcase(ssh): return
    if saved.get('creation_ticks'):
        same=current['creation_ticks']==saved['creation_ticks']
    else:
        # PowerShell writes seven fractional digits; Python 3.10 accepts six.
        previous_time=re.sub(r'(\.\d{6})\d+',r'\1',saved['started_utc']).replace('Z','+00:00')
        same=abs((datetime.fromisoformat(current['started_utc'])-datetime.fromisoformat(previous_time)).total_seconds())<2
    if same:
        handle=KERNEL.OpenProcess(0x1001,False,current['pid'])
        if handle:
            try: KERNEL.TerminateProcess(handle,0)
            finally: KERNEL.CloseHandle(handle)
        time.sleep(1)


def ready(token):
    try:
        req=urllib.request.Request('http://127.0.0.1:18741/health',headers={'Authorization':'Bearer '+token})
        with HTTP.open(req,timeout=2) as response:
            result=json.load(response)
            return result.get('status')=='ready' and result.get('service')=='personal-island-mcp'
    except Exception: return False


def main():
    mutex=KERNEL.CreateMutexW(None,False,'Local\\PersonalIslandWaicoreMcpNative')
    if not mutex: raise ctypes.WinError(ctypes.get_last_error())
    ownership=KERNEL.WaitForSingleObject(mutex,0)
    if ownership not in (0,0x80):
        KERNEL.CloseHandle(mutex)
        return
    relay=None
    try:
        config=load_config()
        ssh=shutil.which('ssh.exe')
        key=Path(config['ssh_identity'])
        if not ssh or not key.exists(): raise RuntimeError('Dedicated SSH relay is not configured')
        token_file=LOCAL/'mcp-bridge.token'
        token=token_file.read_text().strip()
        stop_previous(ssh)
        env=dict(os.environ,PERSONAL_ISLAND_MCP_BIND='127.0.0.1:18741',PERSONAL_ISLAND_MCP_TOKEN_FILE=str(token_file),PERSONAL_ISLAND_TIMEZONE='Europe/Moscow')
        env.pop('PERSONAL_ISLAND_MCP_TOKEN',None)
        delay=2
        with (PRIVATE/'supervisor.log').open('a',encoding='utf8') as log:
            while True:
                if not ready(token):
                    backend=subprocess.Popen([str(BINARY)],env=env,cwd=ROOT,stdin=subprocess.DEVNULL,
                        stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                    for _ in range(30):
                        if ready(token): break
                        if backend.poll() is not None: raise RuntimeError('HTTP bridge exited; see supervisor.log')
                        time.sleep(.2)
                    else: raise RuntimeError('HTTP bridge readiness timed out')
                    (LOCAL/'mcp-http-18741.pid').write_text(str(backend.pid))
                relay=subprocess.Popen([ssh,'-N','-T','-i',str(key),'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                    '-o','ConnectTimeout=10','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3',
                    '-R','127.0.0.1:18741:127.0.0.1:18741',config['ssh_target']],
                    cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                observed=identity(relay.pid)
                if observed:
                    temporary=STATE.with_suffix('.tmp')
                    temporary.write_text(json.dumps(observed),encoding='utf8')
                    temporary.replace(STATE)
                started=time.monotonic()
                while relay.poll() is None:
                    time.sleep(3)
                    if not ready(token):
                        relay.terminate(); relay.wait(timeout=5)
                        break
                if time.monotonic()-started>300: delay=2
                log.write('Relay disconnected; retrying in %s seconds\n'%delay); log.flush()
                time.sleep(delay)
                delay=min(30,delay*2)
    finally:
        if relay and relay.poll() is None: relay.terminate(); relay.wait(timeout=5)
        KERNEL.ReleaseMutex(mutex); KERNEL.CloseHandle(mutex)


if __name__=='__main__':
    try: main()
    except Exception:
        with (PRIVATE/'supervisor-error.txt').open('a',encoding='utf8') as error:
            traceback.print_exc(file=error)
        raise
