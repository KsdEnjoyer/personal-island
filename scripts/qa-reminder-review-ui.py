"""Startup and half-hour reviews recover missed reminders without completing tasks."""
from datetime import datetime
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/qa'
OUT.mkdir(parents=True, exist_ok=True)
RESULTS = []

def passed(name):
    RESULTS.append({'test': name, 'status': 'passed'})
    print(name, flush=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport={'width':480,'height':196}, timezone_id='Europe/Moscow', reduced_motion='reduce')
    page.clock.install(time=datetime.fromisoformat('2026-11-18T13:01:00+03:00'))
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf8'))
    page.add_init_script('''(()=>{
      qaStartup=true;
      const base={notes:null,status:'open',priority:0,created_at:'2026-11-18T09:00:00+03:00',completed_at:null,notification_sent_at:null};
      qaTasks=[
        {...base,id:701,title:'Дело на 13:00',due_at:'2026-11-18T13:00:00+03:00',reminder_at:'2026-11-18T13:00:00+03:00'},
        {...base,id:702,title:'Уже показано, но не выполнено',due_at:'2026-11-18T12:00:00+03:00',reminder_at:'2026-11-18T12:00:00+03:00',notification_sent_at:'2026-11-18T12:00:01+03:00'},
        {...base,id:703,title:'Ближайшее дело',due_at:'2026-11-18T13:20:00+03:00',reminder_at:'2026-11-18T13:20:00+03:00'},
        {...base,id:704,title:'Позднее',due_at:'2026-11-18T15:00:00+03:00',reminder_at:'2026-11-18T15:00:00+03:00'},
        {...base,id:705,title:'Готовое',status:'done',due_at:'2026-11-18T13:00:00+03:00',reminder_at:'2026-11-18T13:00:00+03:00'},
        {...base,id:706,title:'Без срока',due_at:null,reminder_at:null}
      ];
    })()''')
    page.goto('http://127.0.0.1:1420/')
    page.mouse.move(5,180)
    shell = page.locator('.island-shell')
    review = page.locator('.reminder-review')
    expect(shell).to_have_attribute('data-shortcut-ready','true')
    expect(shell).to_have_attribute('aria-hidden','false')
    expect(review).to_have_attribute('data-task-id','701')
    expect(review.locator('.review-clock strong')).to_have_text('13:01')
    expect(review.locator('.review-next')).to_have_text('1/3')
    expect(page.locator('.compact-stage')).to_have_css('height','56px')
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
    page.wait_for_function("qaCalls.some(c=>c.cmd==='acknowledge_island_review'&&c.args.id===701)")
    assert page.evaluate('qaTasks.every(t=>t.id===705||t.status==="open")')
    page.add_style_tag(content='html,body,#app{background:#19242c!important}')
    page.screenshot(path=str(OUT/'reminder-review-startup.png'))
    passed('Starting at 13:01 immediately shows the missed 13:00 task in the compact island and preserves task status')

    review.get_by_label('Следующее напоминание').click()
    expect(review).to_have_attribute('data-task-id','702')
    review.get_by_label('Следующее напоминание').click()
    expect(review).to_have_attribute('data-task-id','703')
    assert not page.evaluate("qaCalls.some(c=>c.cmd==='acknowledge_island_review'&&c.args.id===703)")
    passed('Review includes previously delivered unfinished reminders and the next 30 minutes, excludes completed/undated/far-future tasks, and never consumes a future alert')

    review.locator('.review-task').click()
    page.set_viewport_size({'width':760,'height':520})
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
    expect(page.locator('.task-item[data-task-id="703"]')).to_have_class('task-item reminder-highlight')
    page.evaluate('qaTasks.find(t=>t.id===701).status="done";qaEmit("island-toggle",null)')
    expect(shell).to_have_attribute('aria-hidden','true')
    page.set_viewport_size({'width':480,'height':196})
    page.clock.fast_forward(29*60_000)
    page.evaluate('qaReveal("hourly")')
    expect(review).to_have_attribute('data-task-id','703')
    expect(review.locator('.review-clock strong')).to_have_text('13:30')
    expect(review.locator('.review-next')).to_have_text('1/2')
    review.get_by_label('Следующее напоминание').click()
    expect(review).to_have_attribute('data-task-id','702')
    passed('Click opens and highlights the original task; the 13:30 review repeats unfinished work and removes an externally completed task')

    page.mouse.move(5,180)
    page.evaluate('qaReveal("manual")')
    expect(review).to_have_count(0)
    expect(page.locator('.pill')).to_be_visible()
    page.evaluate('qaTasks.forEach(t=>t.status="done");qaReveal("hourly")')
    expect(review).to_have_count(0)
    expect(page.locator('.pill')).to_be_visible()
    page.clock.fast_forward(6_000)
    expect(shell).to_have_attribute('aria-hidden','true')
    passed('Manual hotkey keeps its default island; an empty scheduled review uses the default pill and hides normally')
    assert not errors, errors
    browser.close()

(OUT/'reminder-review-ui-results.json').write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2),encoding='utf8')
