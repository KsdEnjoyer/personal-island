"""Selection formatting, persistence and unsafe-input checks with isolated IPC."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/qa'
OUT.mkdir(parents=True,exist_ok=True)
results=[]
def passed(name):
    results.append({'test':name,'status':'passed'})
    print(name,flush=True)

with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':760,'height':520},reduced_motion='reduce')
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf8'))
    page.goto('http://127.0.0.1:1420/')
    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
    page.evaluate('qaReveal()')
    page.locator('.pill').click()
    page.get_by_role('button',name='Закрепить островок',exact=True).click()
    page.get_by_role('button',name='Заметки',exact=True).click()
    edit=page.get_by_role('textbox',name='Текст заметки',exact=True)
    expect(edit).to_have_attribute('contenteditable','true')
    edit.fill('Текст для оформления')
    edit.press('Control+a')
    toolbar=page.get_by_role('toolbar',name='Форматирование выделенного текста',exact=True)
    expect(toolbar).to_be_visible()
    for label,selector in [('Жирный','strong'),('Курсив','em'),('Подчёркнутый','u'),('Зачёркнутый','s'),('Выделить цветом','mark')]:
        toolbar.get_by_role('button',name=label,exact=True).click()
        expect(edit.locator(selector)).to_have_text('Текст для оформления')
        assert page.evaluate('getSelection().toString()')=='Текст для оформления'
    page.screenshot(path=str(OUT/'selection-formatting-notes.png'))
    edit.press('Control+s')
    expect(page.get_by_label('Запись сохранена',exact=True)).to_be_visible()
    saved=page.evaluate('qaNotes[0].document')
    for mark in ['bold','italic','underline','strike','highlight']: assert mark in saved
    passed('The floating toolbar preserves the selected range and saves all five formatting marks')
    edit.press('Alt+F10')
    expect(toolbar.get_by_role('button',name='Жирный',exact=True)).to_be_focused()
    page.wait_for_function("JSON.parse(document.querySelector('.island-shell').dataset.presentation).shortcutEditing===true")
    page.keyboard.press('Escape')
    expect(toolbar).to_have_count(0)
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
    page.get_by_label('Название записи',exact=True).click()
    expect(toolbar).to_have_count(0)
    for section in ['Идеи','Покупки']:
        page.get_by_role('tab',name=section,exact=True).click()
        edit.locator('p').first.fill('Выделенный текст')
        edit.press('Control+a')
        expect(toolbar).to_be_visible()
        toolbar.get_by_role('button',name='Жирный',exact=True).click()
        expect(edit.locator('strong')).to_have_text('Выделенный текст')
    page.get_by_role('tab',name='Заметки',exact=True).click()
    expect(edit.locator('u')).to_have_text('Текст для оформления')
    passed('The same toolbar works in ideas and shopping; keyboard dismissal keeps the widget open')
    page.get_by_role('button',name='Задачи',exact=True).click()
    page.locator('.add-task').click()
    page.get_by_label('Название задачи',exact=True).fill('Оформленная задача')
    field=page.get_by_role('textbox',name='Заметка к задаче',exact=True)
    field.fill('Описание с оформлением')
    field.press('Control+a')
    for label in ['Жирный','Подчёркнутый','Зачёркнутый','Выделить цветом']:
        toolbar.get_by_role('button',name=label,exact=True).click()
    page.get_by_role('button',name='Создать',exact=True).click()
    row=page.locator('.task-item').filter(has_text='Оформленная задача')
    for selector in ['strong','u','s','mark']: expect(row.locator('.task-notes '+selector)).to_have_count(1)
    original=page.evaluate("qaTasks.find(t=>t.title==='Оформленная задача').notes")
    page.get_by_role('button',name='Сегодня',exact=True).click()
    page.get_by_role('button',name='Задачи',exact=True).click()
    expect(row.locator('mark')).to_have_text('Описание с оформлением')
    assert page.evaluate("qaTasks.find(t=>t.title==='Оформленная задача').notes")==original
    passed('Task descriptions store readable Markdown and render the same formatting after navigation')
    page.get_by_role('button',name='Календарь',exact=True).click()
    expect(page.locator('.dashboard')).to_have_attribute('aria-busy','false')
    page.locator('.calendar-day.selected').dblclick()
    expect(page.get_by_label('Вид календаря')).to_be_visible()
    page.set_viewport_size({'width':1280,'height':820})
    page.get_by_role('button',name='Записать мысль',exact=True).click()
    quick=page.get_by_role('textbox',name='Быстрая заметка календаря',exact=True)
    quick.fill('Идея с подсветкой')
    quick.press('Control+a')
    toolbar.get_by_role('button',name='Выделить цветом',exact=True).click()
    page.locator('.calendar-note-form').get_by_role('button',name='Сохранить',exact=True).click()
    note=page.evaluate("qaNotes.find(n=>n.title==='Идея с подсветкой')")
    assert 'highlight' in note['document']
    page.get_by_role('button',name='Новое событие',exact=True).click()
    page.get_by_label('Название события',exact=True).fill('Событие с оформлением')
    details=page.get_by_role('textbox',name='Описание события',exact=True)
    details.fill('Детали события')
    details.press('Control+a')
    toolbar.get_by_role('button',name='Курсив',exact=True).click()
    page.get_by_role('button',name='Добавить событие',exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    event=page.evaluate("qaTasks.find(t=>t.title==='Событие с оформлением')")
    assert '*' in event['notes'],event
    page.screenshot(path=str(OUT/'selection-formatting-calendar.png'))
    passed('Calendar quick notes retain rich JSON and calendar descriptions retain formatted text')
    security=page.evaluate('''async()=>{
      const {richText}=await import('/src/lib/rich-text.ts');
      const unsafe='<img src=x onerror="window.badFormatting=true"><script>window.badFormatting=true</script>[bad](javascript:alert(1))';
      const safe=richText(unsafe).html;
      const container=document.createElement('div');container.innerHTML=safe;
      return {danger:container.querySelectorAll('script,img,iframe,a,[onerror],[onclick]').length,executed:!!window.badFormatting};
    }''')
    assert security=={'danger':0,'executed':False},security
    page.evaluate('qaEmit("island-toggle",null)')
    expect(toolbar).to_have_count(0)
    assert not errors,errors
    passed('Untrusted descriptions cannot add scripts, event handlers or executable links; hiding closes the toolbar')
    browser.close()

(OUT/'selection-formatting-results.json').write_text(json.dumps(results,indent=2),encoding='utf8')
