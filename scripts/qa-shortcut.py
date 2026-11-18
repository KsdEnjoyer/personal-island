"""Launch the actual Desktop shortcut, verify --show and single-instance behavior.

Leaves the normal application running, with no test/debug environment.
"""
import ctypes,json,os,subprocess,time
from pathlib import Path
from ctypes import wintypes
ROOT=Path(__file__).resolve().parents[1]
link=Path(os.environ['USERPROFILE'])/'Desktop/Personal Island.lnk'
assert link.is_file(),link
u=ctypes.windll.user32
u.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
u.IsWindowVisible.argtypes=[wintypes.HWND]
u.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
CALLBACK=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
def processes():
    data=subprocess.check_output(['powershell.exe','-NoProfile','-Command',"@(Get-CimInstance Win32_Process -Filter \"name='personal-island-desktop.exe'\" | Select-Object ProcessId,ExecutablePath,CommandLine) | ConvertTo-Json -Compress"],creationflags=subprocess.CREATE_NO_WINDOW).decode('utf-8-sig').strip()
    if not data:return []
    result=json.loads(data);return result if isinstance(result,list) else [result]
assert not processes(),'Stop test instances before launching the normal shortcut'
os.startfile(str(link))
deadline=time.monotonic()+20
while not processes():
    assert time.monotonic()<deadline,'Shortcut did not start the application'
    time.sleep(.2)
first=processes();assert len(first)==1,first
pid=first[0]['ProcessId']
assert Path(first[0]['ExecutablePath']).resolve()==(ROOT/'target/debug/personal-island-desktop.exe').resolve()
assert '--show' in first[0]['CommandLine']
def visible():
    found=[]
    def visit(hwnd,_):
        process=wintypes.DWORD();u.GetWindowThreadProcessId(hwnd,ctypes.byref(process))
        title=ctypes.create_unicode_buffer(256);u.GetWindowTextW(hwnd,title,256)
        if process.value==pid and title.value=='Personal Island' and u.IsWindowVisible(hwnd):found.append(hwnd)
        return True
    u.EnumWindows(CALLBACK(visit),0);return bool(found)
while not visible():
    assert time.monotonic()<deadline,'Shortcut launched without showing the compact island'
    time.sleep(.1)
os.startfile(str(link));time.sleep(1)
second=processes();assert len(second)==1 and second[0]['ProcessId']==pid,second
assert visible(),'Reopening the shortcut did not reveal the island'
result={'shortcut':str(link),'pid':pid,'tests':[{'test':'Desktop shortcut launches the normal built application with --show and displays the compact island','status':'passed'},{'test':'Reopening the shortcut reveals the existing process without creating a duplicate','status':'passed'}]}
(ROOT/'artifacts/qa/shortcut-results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2),flush=True)
