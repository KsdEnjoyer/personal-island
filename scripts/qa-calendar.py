"""Reference calendar: real UI actions with isolated IPC, both wide and small windows."""
import json,os
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from qa_weather import fixture
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/qa';OUT.mkdir(exist_ok=True)
results=[]
def passed(name):results.append({'test':name,'status':'passed'});print(name,flush=True)
with sync_playwright() as p:
    exe=sorted((Path(os.environ['LOCALAPPDATA'])/'ms-playwright').glob('chromium_headless_shell-*/**/chrome-headless-shell.exe'))[-1]
    browser=p.chromium.launch(executable_path=str(exe))
    context=browser.new_context(viewport={'width':1280,'height':820},timezone_id='Europe/Moscow',reduced_motion='reduce')
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    today=datetime.now(ZoneInfo('Europe/Moscow'))
    page.clock.set_fixed_time((today+timedelta(days=2-today.weekday())).replace(hour=14,minute=24,second=0,microsecond=0))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf8'));page.goto('http://127.0.0.1:1420/')
    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
    page.add_style_tag(content='html,body,#app{background:#2b2934!important}')
    dates=page.evaluate('''() => {
      const now = new Date(), mon = new Date(now.getFullYear(),now.getMonth(),now.getDate()-(now.getDay()+6)%7);
      const at=(d,h,m=0)=>new Date(mon.getFullYear(),mon.getMonth(),mon.getDate()+d,h,m).toISOString();
      const base={...qaTasks[0],notes:null,notification_sent_at:null,completed_at:null,status:'open'};
      qaTasks=[
        {...base,id:1,title:'Тренировка',priority:1,due_at:at(0,8)},
        {...base,id:2,title:'Звонок с командой',priority:1,due_at:at(0,11)},
        {...base,id:3,title:'Забрать рецепт',priority:0,due_at:at(2,9,30)},
        {...base,id:4,title:'Дизайн-ревью',priority:1,due_at:at(2,11)},
        {...base,id:5,title:'Встреча с командой',priority:0,due_at:at(2,11,15)},
        {...base,id:6,title:'Фокус-время',priority:0,due_at:at(2,13)},
        {...base,id:7,title:'Стоматолог',priority:2,due_at:at(3,12)},
        {...base,id:8,title:'Ужин с друзьями',priority:2,due_at:at(3,19)},
        {...base,id:9,title:'Подготовить макеты',priority:0,due_at:at(2,8),status:'done'},
      ].map(t=>({...t,reminder_at:new Date(Date.parse(t.due_at)-1800000).toISOString()}));
      qaNotes=[{id:1,category:'notes',title:'Идеи для главной страницы',document:'{"type":"doc"}',revision:1},{id:2,category:'notes',title:'Обсудить анимации',document:'{"type":"doc"}',revision:1}];
      return {wed:at(2,0).slice(0,10),create:at(2,14),move:at(3,14,30)};
    }''')
    # ISO date may be the previous local day; derive the day key in the browser.
    selected=page.evaluate("iso=>{let d=new Date(iso);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`}",dates['create'])
    page.evaluate('weather=>{qaWeather=weather;qaReveal()}',fixture());page.locator('.pill').click();page.get_by_role('button',name='Закрепить островок').click()
    page.get_by_role('button',name='Календарь',exact=True).click();expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
    page.locator(f'.calendar-day[data-date="{selected}"]').click()
    expect(page.locator('.time-grid')).to_have_count(0)
    assert page.locator('.dashboard').evaluate('e=>e.clientWidth')==704
    page.locator(f'.calendar-day[data-date="{selected}"]').dblclick()
    expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
    expect(page.get_by_label('Вид календаря')).to_have_value('week');expect(page.locator('.day-column')).to_have_count(7)
    expect(page.locator('.deadline-card')).to_have_count(8)
    first=page.locator('.deadline-card').filter(has_text='Дизайн-ревью').bounding_box();second=page.locator('.deadline-card').filter(has_text='Встреча с командой').bounding_box()
    assert first and second and first['x']+first['width']<=second['x']+1,(first,second)
    assert page.locator('.calendar-right').is_visible()
    expect(page.get_by_role('button',name='Записать мысль',exact=True)).to_be_in_viewport()
    expect(page.locator('.now-line')).to_have_attribute('aria-label','Сейчас 14:24')
    page.screenshot(path=str(OUT/'calendar-week-reference.png'))
    passed('Three-column weekly reference renders real deadlines with collision lanes and selected-date styling')
    # Deterministic edge cases for date boundaries and the midnight card position.
    check=page.evaluate('''async()=>{
      const c=await import('/src/lib/calendar.ts');
      const jan=new Date(2030,0,1),week=c.startOfWeek(jan);
      const t={...qaTasks[0],due_at:new Date(2030,0,1,23,59).toISOString()};
      return {monday:week.getDay(),key:c.dayKey(c.addDays(new Date(2028,1,28),1)),top:c.layoutDeadlines([t],jan)[0].top};
    }''')
    assert check['monday']==1 and check['key']=='2028-02-29' and abs(check['top']-1439*56/60)<.01,check
    page.get_by_label('Показывать: Важные',exact=True).uncheck();expect(page.locator('.deadline-card.blue')).to_have_count(0)
    page.get_by_label('Показывать: Важные',exact=True).check()
    search=page.get_by_label('Поиск по событиям');search.fill('СТОМАТОЛОГ')
    expect(page.locator('.search-result')).to_have_count(1);expect(page.locator('.search-result')).to_contain_text('Стоматолог')
    page.get_by_role('button',name='Очистить поиск событий').click()
    page.get_by_label('Вид календаря').select_option('month');expect(page.locator('.board-month-cell')).to_have_count(42)
    page.screenshot(path=str(OUT/'calendar-month-reference.png'))
    heading=page.locator('.period-navigation h1').inner_text();page.get_by_role('button',name='Следующий период').click();assert page.locator('.period-navigation h1').inner_text()!=heading
    page.get_by_role('button',name='Предыдущий период').click()
    page.get_by_label('Вид календаря').select_option('day');expect(page.locator('.day-column')).to_have_count(1)
    page.get_by_label('Вид календаря').select_option('week')
    passed('Priority filters, global Cyrillic search, week/month/day views, month navigation and date edges work')
    page.get_by_role('button',name='Новое событие',exact=True).click();expect(page.get_by_role('dialog')).to_be_visible()
    page.keyboard.press('Escape');expect(page.get_by_role('dialog')).to_have_count(0);expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
    page.get_by_role('button',name='Новое событие',exact=True).click()
    page.get_by_label('Название события').fill('Обсудить прототип')
    local=page.evaluate("s=>{let d=new Date(s);return new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,16)}",dates['create'])
    page.get_by_label('Время события',exact=True).fill(local);page.get_by_label('Описание события').fill('Проверить переходы и цвета');page.get_by_label('Приоритет события').select_option('2')
    page.get_by_role('button',name='Добавить событие',exact=True).click();expect(page.get_by_role('dialog')).to_have_count(0)
    task=page.evaluate("qaTasks.find(t=>t.title==='Обсудить прототип')");assert task['priority']==2 and task['notes']=='Проверить переходы и цвета' and task['due_at']==dates['create']
    page.locator('.deadline-card').filter(has_text='Обсудить прототип').click()
    local=page.evaluate("s=>{let d=new Date(s);return new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,16)}",dates['move'])
    page.get_by_label('Новый срок события').fill(local);page.get_by_role('button',name='Сохранить срок',exact=True).click();expect(page.get_by_role('dialog')).to_have_count(0)
    task=page.evaluate("qaTasks.find(t=>t.title==='Обсудить прототип')");assert task['due_at']==dates['move'] and (int(__import__('datetime').datetime.fromisoformat(task['due_at'].replace('Z','+00:00')).timestamp())-int(__import__('datetime').datetime.fromisoformat(task['reminder_at'].replace('Z','+00:00')).timestamp()))==1800
    page.get_by_role('button',name='Завершить: Обсудить прототип',exact=True).click()
    expect(page.get_by_role('button',name='Вернуть: Обсудить прототип',exact=True)).to_be_visible()
    page.get_by_label('Показывать завершённые',exact=True).check();expect(page.locator('.deadline-card.done-card').filter(has_text='Обсудить прототип')).to_have_count(1)
    passed('Creation, deadline rescheduling and completion update tasks and preserve the reminder offset; Escape keeps the calendar open')
    page.locator('.deadline-card').filter(has_text='Обсудить прототип').click();page.get_by_role('button',name='Удалить',exact=True).click()
    page.get_by_role('button',name='Отмена',exact=True).click();assert page.evaluate("qaTasks.some(t=>t.title==='Обсудить прототип')")
    page.get_by_role('button',name='Удалить',exact=True).click();page.get_by_role('button',name='Да, удалить',exact=True).click();expect(page.get_by_role('dialog')).to_have_count(0)
    assert not page.evaluate("qaTasks.some(t=>t.title==='Обсудить прототип')")
    page.get_by_role('button',name='Записать мысль',exact=True).click();page.get_by_label('Быстрая заметка календаря').fill('Идея из календаря\nСохранить детали')
    page.get_by_role('button',name='Сохранить',exact=True).click();expect(page.locator('.quick-note-list')).to_contain_text('Идея из календаря')
    note=page.evaluate("qaNotes.find(n=>n.title==='Идея из календаря')");assert 'Сохранить детали' in note['document']
    page.get_by_role('button',name='Открыть все заметки').click();expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
    expect(page.get_by_label('Название записи')).to_have_value('Идея из календаря',timeout=20000)
    assert page.locator('.dashboard').evaluate('e=>e.clientWidth')==704
    passed('Deletion requires confirmation; calendar quick notes open in the shared editor and restore normal window size')
    page.set_viewport_size({'width':760,'height':520});page.get_by_role('button',name='Календарь',exact=True).click();expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
    bounds=page.locator('.calendar-board').evaluate('e=>({w:e.clientWidth,sw:e.scrollWidth,h:e.clientHeight,sh:e.scrollHeight})')
    assert bounds['sw']<=bounds['w']+1 and bounds['sh']<=bounds['h']+1,bounds
    page.screenshot(path=str(OUT/'calendar-small.png'))
    page.keyboard.press('Escape');expect(page.locator('.compact-month')).to_be_visible()
    page.keyboard.press('Escape');expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
    page.evaluate('qaLayoutDelay=350;qaReveal()');page.locator('.pill').click();page.evaluate('qaReveal()')
    page.wait_for_timeout(900)
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
    page.evaluate('qaLayoutDelay=0')
    passed('A new manual reveal cancels an in-flight expansion and keeps the island compact')
    assert not errors,errors
    passed('Calendar adapts to a small laptop viewport without page overflow or JavaScript errors')
    browser.close()
(OUT/'calendar-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
