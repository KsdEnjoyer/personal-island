"""Visual, motion and interaction checks using isolated Tauri IPC test data.

Run Vite on 127.0.0.1:1420, then `python scripts/qa-ui.py`.
Requires Python Playwright and Chromium. Never opens a task database.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/qa'
OUT.mkdir(parents=True, exist_ok=True)
MOCK = (ROOT / 'scripts/qa-ipc.js').read_text(encoding='utf-8')
BACKDROP = 'html,body,#app{background:linear-gradient(145deg,#2d4895,#644291 65%,#d48060)!important}.island-shell{width:760px;height:520px;margin:auto}'
results = []
errors = []

def passed(name):
    results.append({'test':name,'status':'passed'})
    print(name, flush=True)

def setup(page):
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script(MOCK)
    page.goto('http://127.0.0.1:1420/')
    page.add_style_tag(content=BACKDROP)
    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')

with sync_playwright() as p:
    candidates = sorted((Path(os.environ['LOCALAPPDATA'])/'ms-playwright').glob('chromium_headless_shell-*/**/chrome-headless-shell.exe'))
    browser = p.chromium.launch(executable_path=str(candidates[-1]) if candidates else None)
    context = browser.new_context(viewport={'width':1000,'height':640},timezone_id='Europe/Moscow',
        record_video_dir=str(OUT/'motion'),record_video_size={'width':1000,'height':640})
    page = context.new_page()
    setup(page)
    page.evaluate('qaReveal()')
    expect(page.locator('.compact-stage')).to_have_attribute('aria-hidden','false')
    page.screenshot(path=str(OUT/'redesign-collapsed.png'))
    page.evaluate('qaReveal()'); page.locator('.pill').click()
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
    page.get_by_role('button',name='Закрепить островок').click()
    page.mouse.move(990,630)
    page.wait_for_timeout(1000)
    assert abs(float(page.locator('.island-shell').evaluate("el => parseFloat(el.style.getPropertyValue('--shape-width'))"))-704) < .5
    page.screenshot(path=str(OUT/'redesign-expanded.png'))
    passed('Click expands the compact island; spring settles at the expanded size')

    expect(page.locator('.task-name')).to_have_count(2)
    page.get_by_role('button',name='Далее',exact=True).click()
    expect(page.locator('.task-name')).to_have_text(['Протестировать на втором мониторе'])
    page.get_by_role('button',name='Входящие',exact=True).click()
    expect(page.locator('.task-name')).to_have_text(['Записать идеи для островка'])
    page.get_by_role('button',name='Готово',exact=True).click()
    expect(page.locator('.task-name')).to_have_text(['Подготовить рабочее окружение'])
    passed('Today, Upcoming, Inbox and Done filters')

    page.locator('.add-task').click()
    expect(page.get_by_role('button',name='Создать',exact=True)).to_be_disabled()
    expect(page.get_by_label('Название задачи')).to_be_focused()
    page.get_by_label('Название задачи').fill('QA created')
    page.get_by_label('Заметка к задаче').fill('Notes survive saving')
    page.get_by_label('Приоритет',exact=True).select_option('2')
    page.screenshot(path=str(OUT/'redesign-composer.png'))
    page.get_by_role('button',name='Создать',exact=True).click()
    row = page.locator('.task-item').filter(has_text='QA created')
    expect(row).to_be_visible()
    assert page.evaluate("qaTasks.find(t => t.title === 'QA created').notes") == 'Notes survive saving'
    passed('Create task with notes and priority; empty title is disabled')
    row.get_by_label('Сменить приоритет').click()
    assert page.evaluate("qaTasks.find(t => t.title === 'QA created').priority") == 0
    row.get_by_label('Изменить статус задачи').click()
    expect(row).to_have_count(0)
    page.get_by_role('button',name='Готово',exact=True).click()
    row.get_by_label('Изменить статус задачи').click()
    page.get_by_role('button',name='Входящие',exact=True).click()
    expect(row).to_be_visible()
    passed('Priority, complete and reopen retain task data')

    row.hover(); row.get_by_label('Изменить дедлайн').click()
    row.get_by_label('Новый дедлайн').fill('2030-01-02T17:00')
    row.get_by_label('Сохранить срок').click()
    assert page.evaluate("qaTasks.find(t => t.title === 'QA created').due_at") == '2030-01-02T14:00:00.000Z'
    page.get_by_role('button',name='Далее',exact=True).click()
    row.hover(); row.get_by_label('Изменить дедлайн').click()
    row.get_by_label('Новый дедлайн').fill('')
    row.get_by_label('Сохранить срок').click()
    page.get_by_role('button',name='Входящие',exact=True).click()
    expect(row).to_be_visible()
    passed('Reschedule and clear deadline with correct Moscow UTC conversion')
    row.hover(); row.get_by_label('Удалить задачу').click()
    row.get_by_role('button',name='Отмена',exact=True).click()
    expect(row).to_be_visible()
    row.get_by_label('Удалить задачу').click()
    row.get_by_role('button',name='Удалить навсегда',exact=True).click()
    expect(row).to_have_count(0)
    passed('Inline deletion requires confirmation and can be cancelled')

    page.evaluate("qaFail = 'create_task'")
    page.locator('.add-task').click()
    page.get_by_label('Название задачи').fill('QA retry')
    page.get_by_role('button',name='Создать',exact=True).click()
    expect(page.locator('.error')).to_contain_text('QA simulated failure')
    page.wait_for_timeout(5300)
    expect(page.locator('.error')).to_contain_text('QA simulated failure')
    expect(page.get_by_label('Название задачи')).to_have_value('QA retry')
    page.evaluate('qaFail = null')
    page.get_by_role('button',name='Создать',exact=True).click()
    expect(page.locator('.error')).to_have_count(0)
    passed('Save failure survives background polling; retry succeeds')
    page.evaluate("qaTasks.push({...qaTasks[3], id:99, title:'QA external'})")
    expect(page.locator('.task-item').filter(has_text='QA external')).to_be_visible(timeout=7000)
    passed('Polling shows changes from another process')

    page.get_by_role('button',name='Запустить таймер').click()
    expect(page.locator('.timer-value')).not_to_have_text('25:00',timeout=3500)
    page.get_by_role('button',name='Приостановить таймер').click()
    paused = page.locator('.timer-value').inner_text()
    page.wait_for_timeout(1200)
    assert page.locator('.timer-value').inner_text() == paused
    page.get_by_role('button',name='15 мин',exact=True).click()
    expect(page.locator('.timer-value')).to_have_text('15:00')
    passed('Focus timer starts, pauses and changes preset')

    page.get_by_role('button',name='Сегодня',exact=True).click()
    page.get_by_role('button',name='Закрепить островок').click()
    # Re-enter and leave the persistent hitbox to exercise automatic collapse.
    page.locator('.panel-heading').hover(); page.mouse.move(990,630)
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true',timeout=3000)
    page.wait_for_timeout(1000)
    passed('Leaving the island collapses when it is not pinned')
    page.evaluate('qaReveal()'); page.locator('.pill').click()
    page.get_by_role('button',name='Закрепить островок').click()
    page.wait_for_timeout(800)
    before = page.evaluate("qaCalls.filter(c => c.cmd === 'set_island_expanded' && !c.args.expanded).length")
    page.get_by_role('button',name='Свернуть',exact=True).click()
    page.wait_for_timeout(110)
    assert page.evaluate("qaCalls.filter(c => c.cmd === 'set_island_expanded' && !c.args.expanded).length") == before
    page.wait_for_timeout(1100)
    assert page.evaluate("qaCalls.filter(c => c.cmd === 'set_island_expanded' && !c.args.expanded).length") == before+1
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
    passed('Native window shrinks after the visual transition; close stays closed')

    page.evaluate('qaReveal()'); page.locator('.pill').click()
    page.wait_for_timeout(100)
    page.keyboard.press('Escape')
    page.evaluate('qaReveal()'); page.locator('.pill').click()
    page.wait_for_timeout(1100)
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
    assert page.evaluate("qaCalls.filter(c => c.cmd === 'set_island_expanded').at(-1).args.expanded")
    passed('Rapid opening and closing cannot apply a stale native resize')
    page.get_by_role('button',name='Настройки').click()
    page.get_by_role('button',name='Закрыть настройки').click()
    page.mouse.move(990,630)
    page.wait_for_timeout(400)
    canvas = page.locator('canvas')
    before = canvas.evaluate("el => el.getContext('2d').getImageData(el.width/2,463,1,1).data[3]")
    page.mouse.move(500,462)
    page.wait_for_timeout(320)
    after = canvas.evaluate("el => el.getContext('2d').getImageData(el.width/2,463,1,1).data[3]")
    assert before < 200 and after > 220, (before,after)
    page.screenshot(path=str(OUT/'redesign-liquid-pull.png'))
    passed('Liquid silhouette actually stretches toward the pointer')

    extra = browser.new_context(viewport={'width':1000,'height':640},timezone_id='Europe/Moscow',reduced_motion='reduce')
    reduced = extra.new_page(); setup(reduced)
    reduced.evaluate('qaReveal()'); reduced.locator('.pill').click()
    expect(reduced.locator('.dashboard')).to_have_attribute('aria-hidden','false')
    reduced.wait_for_timeout(100)
    assert reduced.locator('.island-shell').evaluate("el => el.style.getPropertyValue('--shape-width')") == '704px'
    passed('Reduced-motion preference skips spring and liquid animation')
    midnight = extra.new_page()
    midnight.clock.install(time=datetime(2030,1,2,20,59,50,tzinfo=timezone.utc))
    setup(midnight); midnight.evaluate('qaReveal()'); midnight.locator('.pill').click()
    before = midnight.locator('.meta').inner_text()
    midnight.clock.fast_forward(70000)
    assert midnight.locator('.meta').inner_text() != before
    passed('Date updates after midnight')
    assert not errors, errors
    passed('No JavaScript exceptions')
    video = page.video
    extra.close(); context.close()
    video.save_as(str(OUT/'island-motion.webm'))
    browser.close()

(OUT/'ui-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'{len(results)} checks passed')
