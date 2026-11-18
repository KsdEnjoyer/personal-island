"""Terminate only verified bridge-owned processes and check automatic recovery.

Read-only with respect to all personal tasks. Requires the installed supervisor.
"""
import importlib.util
import json
import os
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('supervisor',ROOT/'scripts/run-waicore-mcp.py')
supervisor=importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)
RESULTS=[]


def kill_verified(process_id, expected_path, creation=None):
    current=supervisor.identity(process_id)
    assert current and os.path.normcase(current['executable'])==os.path.normcase(str(expected_path))
    if creation: assert current['creation_ticks']==creation
    handle=supervisor.KERNEL.OpenProcess(0x1001,False,process_id)
    assert handle
    try: assert supervisor.KERNEL.TerminateProcess(handle,0)
    finally: supervisor.KERNEL.CloseHandle(handle)


def wait_for(check, seconds=40):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if check(): return
        time.sleep(.5)
    raise AssertionError('Background recovery timed out')


token=(supervisor.LOCAL/'mcp-bridge.token').read_text().strip()
wait_for(lambda: supervisor.ready(token))
before=json.loads(supervisor.STATE.read_text(encoding='utf-8-sig'))
kill_verified(before['pid'],before['executable'],before.get('creation_ticks'))
def relay_replaced():
    current=json.loads(supervisor.STATE.read_text(encoding='utf-8-sig'))
    return current['pid']!=before['pid'] and supervisor.identity(current['pid']) is not None
wait_for(relay_replaced)
RESULTS.append({'test':'SSH process loss is recovered without a terminal','status':'passed'})
pid_file=supervisor.LOCAL/'mcp-http-18741.pid'
old_backend=int(pid_file.read_text())
kill_verified(old_backend,supervisor.BINARY)
wait_for(lambda: pid_file.exists() and int(pid_file.read_text())!=old_backend and supervisor.ready(token))
RESULTS.append({'test':'HTTP backend loss is recovered with the same local database and credentials','status':'passed'})
for result in RESULTS: print(result['test'])
(ROOT/'artifacts/qa/mcp-recovery-results.json').write_text(json.dumps(RESULTS,indent=2))
