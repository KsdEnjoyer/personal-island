"""Measure IPC and DOM work, verifying event-stream recovery and live updates."""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/qa';results=[]
def passed(name,**measurements):results.append({'test':name,'status':'passed',**measurements});print(name,measurements,flush=True)
with sync_playwright() as p:
    exe=sorted((Path(os.environ['LOCALAPPDATA'])/'ms-playwright').glob('chromium_headless_shell-*/**/chrome-headless-shell.exe'))[-1]
    browser=p.chromium.launch(executable_path=str(exe));context=browser.new_context(viewport={'width':760,'height':520},reduced_motion='reduce')
    page=context.new_page();page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf-8'));page.clock.install()
    page.goto('http://127.0.0.1:1420/');expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
    def calls(name):return page.evaluate('name=>qaCalls.filter(c=>c.cmd===name).length',name)
    initial=calls('list_tasks');page.clock.run_for(60_000)
    assert calls('list_tasks')==initial
    passed('Hidden island does not poll task SQLite',avoided_task_reads_per_minute=12)
    page.evaluate('qaReveal()');page.clock.run_for(100);page.locator('.pill').click();page.clock.run_for(100);page.get_by_label('Закрепить островок').click()
    before=calls('list_tasks');page.evaluate("qaTasks.push({...qaTasks[3],id:101,title:'Live external change'})");page.clock.run_for(5100)
    assert calls('list_tasks')>before
    page.get_by_role('button',name='Задачи',exact=True).click();expect(page.locator('.task-name').filter(has_text='Live external change')).to_be_visible()
    passed('Visible dashboard retains five-second external-task refresh')
    before=calls('get_media_state')
    for _ in range(15):
        page.evaluate("qaEmit('media-changed',qaMedia)");page.clock.run_for(2000)
    assert calls('get_media_state')==before
    passed('Healthy native media events eliminate duplicate frontend media polling',avoided_media_reads_in_30_seconds=15)
    page.clock.run_for(20000)
    assert calls('get_media_state')>before
    passed('Media polling recovers when native events stop')
    page.emulate_media(reduced_motion='no-preference');page.clock.run_for(2000)
    page.evaluate("window.qaLayoutWrites=0;window.qaLayoutObserver=new MutationObserver(ms=>qaLayoutWrites+=ms.length);qaLayoutObserver.observe(document.querySelector('.island-interaction'),{attributes:true,attributeFilter:['style']})")
    page.clock.run_for(1200)
    writes=page.evaluate('qaLayoutWrites');assert writes<=2,writes
    passed('Idle liquid canvas does not rewrite DOM size every frame',style_mutations_in_1_2_seconds=writes)
    page.evaluate('qaLayoutObserver.disconnect()')
    assert not page.evaluate("document.querySelector('.dashboard').scrollWidth>704")
    browser.close()
(OUT/'performance-results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
