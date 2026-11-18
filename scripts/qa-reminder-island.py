"""Reminder presentation, queue, interruption and draft preservation in a UI double."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/qa'
RESULTS=[]


def passed(name):
    RESULTS.append({'test':name,'status':'passed'})
    print(name,flush=True)


with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':480,'height':196},timezone_id='Europe/Moscow',reduced_motion='reduce')
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf8'))
    page.goto('http://127.0.0.1:1420/')
    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
    page.add_style_tag(content='html,body,#app{background:#30333b!important}')
    def send(title='Подготовиться к созвону',count=1):
        return page.evaluate('''([title,count])=>{
          const items=Array.from({length:count},(_,index)=>({id:100+qaTasks.length+index,title:index ? title+' '+(index+1) : title,
            notes:null,status:'open',due_at:new Date().toISOString(),reminder_at:new Date(Date.now()-2000).toISOString(),
            notification_sent_at:null,priority:0,created_at:new Date().toISOString(),completed_at:null}));
          qaTasks.push(...items);qaEmit('island-reminders',structuredClone(items));return items;
        }''',[title,count])
    compact=page.locator('.compact-stage .reminder-notice')
    incoming=send()
    expect(compact.locator('strong')).to_have_text('Подготовиться к созвону')
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
    assert compact.bounding_box()['width']==272 and compact.bounding_box()['height']==56
    page.wait_for_function("qaCalls.some(call=>call.cmd==='acknowledge_island_reminder')")
    page.evaluate("items=>qaEmit('island-reminders',items)",incoming)
    assert page.evaluate("qaCalls.filter(call=>call.cmd==='acknowledge_island_reminder').length")==1
    page.screenshot(path=str(OUT/'reminder-island.png'))
    passed('Reduced motion reveals the message immediately at the normal 272x56 size and acknowledges it only once')
    page.mouse.move(240,45)
    page.wait_for_timeout(8500)
    expect(compact.locator('strong')).to_have_text('Подготовиться к созвону')
    page.mouse.move(5,180)
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true',timeout=2500)
    passed('The reminder stays while hovered and leaves after its eight-second lease')

    incoming=send('Несколько напоминаний',3)
    expect(compact.locator('strong')).to_have_text('Несколько напоминаний')
    expect(compact.locator('small')).to_have_text('+2')
    # A queued task was completed externally; never acknowledge or show it.
    page.evaluate('id=>qaTasks.find(task=>task.id===id).status="done"',incoming[1]['id'])
    page.evaluate('qaReveal("track")')
    expect(compact.locator('strong')).to_have_text('Несколько напоминаний')
    compact.get_by_label('Закрыть напоминание').click()
    expect(compact.locator('strong')).to_have_text('Несколько напоминаний 3',timeout=3500)
    assert not page.evaluate('id=>qaCalls.some(call=>call.cmd==="acknowledge_island_reminder"&&call.args.id===id)',incoming[1]['id'])
    compact.locator('.reminder-open').click()
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
    expect(page.locator(f'[data-task-id="{incoming[2]["id"]}"]')).to_have_class('task-item reminder-highlight')
    passed('Simultaneous reminders queue; a completed queued task is skipped; Open highlights the original task')

    page.set_viewport_size({'width':760,'height':520})
    page.get_by_label('Новая задача',exact=True).click()
    field=page.get_by_label('Название задачи',exact=True)
    field.fill('Несохранённый черновик')
    page.emulate_media(reduced_motion='no-preference')
    send('Напоминание во время работы')
    banner=page.locator('.dashboard .reminder-notice')
    expect(banner.locator('strong')).to_have_text('Напоминание во время работы')
    expect(field).to_have_value('Несохранённый черновик')
    assert page.evaluate('document.activeElement?.getAttribute("aria-label")')=='Название задачи'
    assert page.locator('.dashboard').get_attribute('aria-hidden')=='false'
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT/'reminder-island-expanded.png'))
    banner.get_by_label('Закрыть напоминание').click()
    expect(banner).to_have_count(0)
    expect(field).to_have_value('Несохранённый черновик')
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
    passed('An expanded island displays an inline reminder without changing focus, tab, size or unsaved form content')

    page.get_by_role('button',name='Отмена',exact=True).click()
    page.get_by_label('Свернуть',exact=True).click()
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')

    ack_count=page.evaluate("qaCalls.filter(call=>call.cmd==='acknowledge_island_reminder').length")
    page.evaluate('''()=>{
      window.qaReminderPhases=[];
      const observer=new MutationObserver(records=>{
        for(const record of records){
          const phase=record.target.dataset?.phase;
          if(phase && qaReminderPhases.at(-1)?.phase!==phase)
            qaReminderPhases.push({phase,acks:qaCalls.filter(c=>c.cmd==='acknowledge_island_reminder').length});
        }
      });
      observer.observe(document.querySelector('.compact-stage'),{subtree:true,attributes:true,attributeFilter:['data-phase']});
      window.qaReminderPhaseObserver=observer;
    }''')
    incoming=send('Колокольчик, затем суть напоминания')
    expect(compact).to_have_attribute('data-phase','bell')
    expect(compact.locator('strong')).to_have_count(0)
    expect(page.locator('.compact-stage')).to_have_css('width','96px')
    expect(page.locator('.compact-stage')).to_have_css('height','40px')
    page.evaluate("items=>qaEmit('island-reminders',items)",incoming)
    assert page.evaluate("qaCalls.filter(call=>call.cmd==='acknowledge_island_reminder').length")==ack_count
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT/'reminder-bell-strike.png'))
    expect(compact).to_have_attribute('data-phase','message')
    expect(page.locator('.compact-stage')).to_have_css('width','272px')
    phases=page.evaluate('qaReminderPhases')
    assert any(item['phase']=='opening' and item['acks']==ack_count for item in phases),phases
    page.evaluate('qaReminderPhaseObserver.disconnect()')
    expect(compact.locator('strong')).to_have_text(incoming[0]['title'])
    page.wait_for_function('count=>qaCalls.filter(call=>call.cmd==="acknowledge_island_reminder").length===count+1',arg=ack_count)
    page.wait_for_timeout(350)
    page.screenshot(path=str(OUT/'reminder-bell-message.png'))
    page.mouse.move(5,180)
    page.wait_for_timeout(6500)
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true',timeout=3500)
    passed('Bell strike precedes expansion and text; duplicate events do not acknowledge the bell; the eight-second reading lease starts after content')

    incoming=send('Отменённая анимация')
    expect(compact).to_have_attribute('data-phase','bell')
    page.evaluate('qaReveal("manual")')
    expect(compact).to_have_count(0)
    page.wait_for_timeout(1700)
    expect(compact).to_have_count(0)
    assert not page.evaluate('id=>qaCalls.some(call=>call.cmd==="acknowledge_island_reminder"&&call.args.id===id)',incoming[0]['id'])
    page.evaluate('id=>qaTasks.find(task=>task.id===id).status="done"',incoming[0]['id'])
    page.emulate_media(reduced_motion='reduce')
    page.wait_for_timeout(3800)

    long='Очень длинное напоминание о важном деле, которое нужно прочитать и открыть в списке задач. '*3
    send(long)
    expect(compact.locator('strong')).to_have_text(long)
    page.wait_for_timeout(450)
    assert compact.evaluate('e=>e.scrollHeight<=e.clientHeight+1 && e.scrollWidth<=e.clientWidth+1')
    page.screenshot(path=str(OUT/'reminder-island-long.png'))
    assert not errors,errors
    passed('Manual reveal cancels stale bell choreography without consuming it; long content fits two lines without browser errors')
    browser.close()
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'reminder-island-results.json').write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2),encoding='utf8')
