"""Compact-first calendar, deliberate week expansion, shared styling and unified tasks."""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/qa';results=[]
def passed(name):results.append({'test':name,'status':'passed'});print(name,flush=True)
with sync_playwright() as p:
    exe=sorted((Path(os.environ['LOCALAPPDATA'])/'ms-playwright').glob('chromium_headless_shell-*/**/chrome-headless-shell.exe'))[-1]
    browser=p.chromium.launch(executable_path=str(exe))
    context=browser.new_context(viewport={'width':760,'height':520},timezone_id='Europe/Moscow',reduced_motion='reduce')
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf8'));page.goto('http://127.0.0.1:1420/')
    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
    page.add_style_tag(content='html,body,#app{background:#30333b!important}')
    page.evaluate('qaReveal()');page.locator('.pill').click();page.get_by_label('Закрепить островок').click()
    expect(page.get_by_role('button',name='Далее',exact=True)).to_have_count(0)
    expect(page.get_by_role('button',name='Входящие',exact=True)).to_have_count(0)
    page.get_by_role('button',name='Задачи',exact=True).click()
    expect(page.locator('.task-item')).to_have_count(4)
    assert {1,2,3,4}==set(page.evaluate("qaTasks.filter(t=>t.status==='open').map(t=>t.id)"))
    expect(page.locator('.task-item').filter(has_text='Записать идеи для островка')).to_be_visible()
    expect(page.locator('.task-item').filter(has_text='Протестировать на втором мониторе')).to_be_visible()
    page.get_by_role('button',name='Со сроком',exact=True).click();expect(page.locator('.task-item')).to_have_count(3)
    page.get_by_role('button',name='Без срока',exact=True).click();expect(page.locator('.task-item')).to_have_count(1)
    page.get_by_role('button',name='Все',exact=True).click();page.screenshot(path=str(OUT/'tasks-unified.png'))
    page.get_by_role('button',name='Новая задача',exact=True).click();page.get_by_label('Название задачи',exact=True).fill('Новая задача без срока')
    page.get_by_role('button',name='Создать',exact=True).click();expect(page.locator('.task-item')).to_have_count(5)
    assert len(page.evaluate('qaTasks'))==6
    page.get_by_role('button',name='Заметки',exact=True).click();expect(page.get_by_label('Название записи')).to_be_visible(timeout=20000)
    page.get_by_label('Название записи').fill('Отдельная заметка');page.get_by_role('textbox',name='Текст заметки').fill('Текст записи')
    page.get_by_role('button',name='Задачи',exact=True).click();expect(page.locator('.task-item')).to_have_count(5)
    assert len(page.evaluate('qaTasks'))==6 and len(page.evaluate('qaNotes'))==1
    passed('Unified Tasks contains dated/undated work; filters and creation work; notes remain independent without losing tasks')
    page.get_by_role('button',name='Календарь',exact=True).click()
    expect(page.locator('.compact-month')).to_be_visible();expect(page.locator('.time-grid')).to_have_count(0)
    assert page.locator('.dashboard').evaluate('e=>e.clientWidth')==704
    assert not page.evaluate("qaCalls.some(c=>c.cmd==='set_island_expanded' && c.args.calendar)")
    day=page.locator('.calendar-day:not(.outside)').nth(9)
    key=day.get_attribute('data-date');day.click()
    expect(page.locator('.calendar-day.selected')).to_have_attribute('data-date',key)
    expect(page.locator('.time-grid')).to_have_count(0)
    # Allow the existing button colour transition to settle before visual capture.
    page.wait_for_function("getComputedStyle(document.querySelector('.calendar-day.selected')).backgroundColor === 'rgb(51, 43, 30)'")
    page.screenshot(path=str(OUT/'calendar-compact.png'))
    passed('Opening Calendar and single-clicking a date retain the small month with day tasks and no weekly grid')
    page.set_viewport_size({'width':1280,'height':820})
    day.dblclick();expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
    expect(page.locator('.day-column')).to_have_count(7)
    assert page.locator('.dashboard').evaluate('e=>e.clientWidth')==1224
    for surface in page.locator('.calendar-surface').all():
        colors=surface.evaluate('e=>({color:getComputedStyle(e).backgroundColor,image:getComputedStyle(e).backgroundImage})')
        assert colors=={'color':'rgb(16, 16, 16)','image':'none'},colors
    assert page.locator('.new-event').evaluate('e=>getComputedStyle(e).backgroundImage')=='none'
    assert not any(text in page.locator('.dashboard').inner_text() for text in ['ТВОЙ РИТМ','Место для дел','И для жизни между ними','Дыши свободнее'])
    page.screenshot(path=str(OUT/'calendar-planner-neutral.png'))
    page.get_by_role('button',name='К месяцу',exact=True).click();expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
    expect(page.locator('.compact-month')).to_be_visible();assert page.locator('.dashboard').evaluate('e=>e.clientWidth')==704
    passed('Double click expands exactly the selected week; planner shares application surfaces and the back button restores the month')
    page.locator('.calendar-day.selected').press('Control+Enter');expect(page.locator('.day-column')).to_have_count(7);expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
    page.keyboard.press('Escape');expect(page.locator('.compact-month')).to_be_visible();expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
    target=page.locator('.calendar-day.selected')
    target.dispatch_event('pointerup',{'pointerType':'touch'});expect(page.locator('.time-grid')).to_have_count(0)
    target.dispatch_event('pointerup',{'pointerType':'touch'});expect(page.locator('.day-column')).to_have_count(7);expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
    page.get_by_role('button',name='Задачи',exact=True).click();expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
    page.get_by_role('button',name='Календарь',exact=True).click();expect(page.locator('.compact-month')).to_be_visible()
    expect(page.locator('.time-grid')).to_have_count(0)
    assert page.locator('.dashboard').evaluate('e=>e.clientWidth')==704
    passed('Keyboard and touch double tap open the week; Escape and tab re-entry restore the compact calendar')
    assert not errors,errors
    browser.close()
(OUT/'calendar-flow-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
