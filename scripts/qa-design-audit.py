"""Review every tab, selected-date contrast, long content and panel bounds."""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from qa_weather import fixture
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/qa/design-audit';OUT.mkdir(exist_ok=True)
results=[]
with sync_playwright() as p:
    exe=sorted((Path(os.environ['LOCALAPPDATA'])/'ms-playwright').glob('chromium_headless_shell-*/**/chrome-headless-shell.exe'))[-1]
    browser=p.chromium.launch(executable_path=str(exe))
    context=browser.new_context(viewport={'width':760,'height':520},timezone_id='Europe/Moscow',reduced_motion='reduce')
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf-8'))
    page.goto('http://127.0.0.1:1420/')
    page.add_style_tag(content='html,body,#app{background:#343b47!important}')
    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
    page.evaluate('data=>{qaWeather=data;qaReveal()}',fixture())
    page.locator('.pill').click();page.get_by_label('Закрепить островок').click()
    for tab in ['Сегодня','Задачи','Календарь','Музыка','Погода','Буфер обмена','Готово']:
        page.get_by_role('button',name=tab,exact=True).first.click()
        page.wait_for_timeout(100)
        bounds=page.locator('.dashboard').evaluate('el=>({width:el.clientWidth,scroll:el.scrollWidth,height:el.clientHeight,scrollY:el.scrollHeight})')
        assert bounds['scroll']<=bounds['width']+1,(tab,bounds)
        assert bounds['scrollY']<=bounds['height']+1,(tab,bounds)
        nav=page.locator('.header').evaluate('el=>({width:el.clientWidth,scroll:el.scrollWidth})')
        assert nav['scroll']<=nav['width']+1,(tab,nav)
        page.screenshot(path=str(OUT/f'tab-{len(results)}.png'))
        results.append({'tab':tab,'bounds':bounds,'status':'passed'})
    page.get_by_role('button',name='Календарь',exact=True).click()
    page.locator('.calendar-day:not(.outside)').nth(9).click()
    page.wait_for_timeout(200)
    selected=page.locator('.calendar-day.selected').evaluate('el=>({background:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color,date:el.dataset.date})')
    print('Selected calendar day:',json.dumps(selected),flush=True)
    assert selected['background']=='rgb(51, 43, 30)' and selected['color']=='rgb(240, 201, 133)',selected
    page.get_by_role('button',name='Музыка',exact=True).click()
    page.evaluate("qaMedia={sessions:[{id:'qa.exe',label:'QA Player'}],session_id:'qa.exe',source:'QA Player',title:'Очень длинное название трека, которое должно аккуратно помещаться в плеере и уведомлении даже без коротких слов',artist:'Название исполнителя с дополнительной информацией и длинным описанием',artwork:null,playing:true,position:30,duration:200,can_toggle:true,can_previous:true,can_next:true};qaEmit('media-changed',qaMedia)")
    expect(page.locator('.track-info h2')).to_contain_text('Очень длинное')
    page.screenshot(path=str(OUT/'long-track.png'))
    music=page.locator('.music-panel').evaluate('el=>({width:el.clientWidth,scroll:el.scrollWidth,height:el.clientHeight,scrollY:el.scrollHeight})')
    print('Long-track bounds:',music,flush=True)
    assert music['scrollY']<=music['height']+1,music
    assert music['scroll']<=music['width']+1,music
    expect(page.locator('.music-panel input[type=range]')).to_be_in_viewport()
    results.append({'test':'Long track','bounds':music,'status':'passed' if music['scrollY']<=music['height']+1 and music['scroll']<=music['width']+1 else 'needs-fix'})
    page.get_by_role('button',name='Сегодня',exact=True).click()
    page.evaluate("qaTasks.push({...qaTasks[0],id:999,title:'ДлиннаяЗадачаБезПробелов'.repeat(8),notes:'Подробное описание задачи. '.repeat(25)})")
    page.wait_for_timeout(5100)
    row=page.locator('.task-item').filter(has_text='ДлиннаяЗадачаБезПробелов')
    expect(row).to_be_visible()
    assert row.evaluate('el=>el.scrollWidth<=el.clientWidth+1')
    page.screenshot(path=str(OUT/'long-task.png'))
    assert not errors,errors
    (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    browser.close()
