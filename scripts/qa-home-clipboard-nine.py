"""Explicit overview transport and latest-nine clipboard view, isolated IPC."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/qa'
OUT.mkdir(parents=True,exist_ok=True)
RESULTS=[]
def passed(name):
    RESULTS.append({'test':name,'status':'passed'})
    print(name,flush=True)

with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':760,'height':520},reduced_motion='reduce')
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf8'))
    page.goto('http://127.0.0.1:1420/')
    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
    page.evaluate('''()=>{
      qaClipboard=Array.from({length:22},(_,i)=>({id:i+1,kind:'text',text:'Copy '+(i+1),pinned:i===0,captured_at:Date.now()+i,thumbnail:null,width:null,height:null,files:[]}));
      qaClipboard[20]={...qaClipboard[20],kind:'image',text:null,width:80,height:60,thumbnail:'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="80" height="60"><rect width="80" height="60" fill="%235879a1"/></svg>'};
      qaClipboard[19]={...qaClipboard[19],kind:'files',text:'photo.png',files:[{name:'photo.png',path:'C:/QA/photo.png'}],thumbnail:qaClipboard[20].thumbnail};
      qaMedia={sessions:[{id:'qa',label:'QA Player'}],session_id:'qa',source:'QA Player',title:'Test Track',artist:'QA Artist',playing:false,artwork:null,position:0,duration:200,can_toggle:true,can_previous:true,can_next:true};
      qaReveal();
    }''')
    page.locator('.compact-stage [aria-label="Развернуть список задач"]').click()
    page.locator('.pin-button').click()
    play=page.locator('.home-transport .home-play')
    expect(play).to_be_visible()
    expect(play).to_have_attribute('aria-label','Продолжить музыку')
    play.click()
    expect(play).to_have_attribute('aria-label','Приостановить музыку')
    play.click()
    expect(play).to_have_attribute('aria-label','Продолжить музыку')
    page.locator('.home-transport [aria-label="Следующий трек"]').click()
    assert page.evaluate('qaCalls.some(c=>c.cmd==="media_command"&&c.args.action==="next")')
    expect(page.locator('.home-panel')).to_be_visible()
    expect(page.locator('.clipboard-stats')).to_contain_text('9 записей')
    page.add_style_tag(content='html,body,#app{background:#30333b!important}')
    page.screenshot(path=str(OUT/'home-explicit-play.png'))
    passed('The overview has an explicit play/pause control between the skips and reports nine recent clipboard items')

    page.get_by_label('Открыть буфер обмена',exact=True).click()
    cards=page.locator('.clipboard-card')
    expect(cards).to_have_count(9)
    expect(cards.first).to_contain_text('Copy 22')
    expect(cards.last).to_contain_text('Copy 14')
    expect(cards.last).to_be_in_viewport()
    assert page.locator('.clipboard-grid').evaluate('e=>e.scrollHeight<=e.clientHeight+2')
    expect(page.locator('.clipboard-card img')).to_have_count(2)
    page.wait_for_function('Array.from(document.querySelectorAll(".clipboard-card img")).every(e=>e.complete&&e.naturalWidth>0)')
    page.screenshot(path=str(OUT/'clipboard-latest-nine.png'))
    search=page.get_by_label('Поиск в буфере обмена',exact=True)
    search.fill('Copy 1')
    expect(cards).to_have_count(6)
    search.fill('Copy 1 ')
    expect(cards).to_have_count(0)
    page.get_by_role('button',name='Закреплённые',exact=True).click()
    expect(cards).to_have_count(1)
    expect(cards.first).to_contain_text('Copy 1')
    page.get_by_role('button',name='Последние 9',exact=True).click()
    expect(cards).to_have_count(9)
    passed('Latest nine fit a 3x3 grid with image/file previews; search stays within that window and older pins have their own filter')

    page.evaluate('''()=>{
      qaClipboard.push({id:23,kind:'text',text:'Copy 23',pinned:false,captured_at:Date.now()+10000,files:[]});
      qaEmit('clipboard-changed',null);
    }''')
    expect(cards).to_have_count(9)
    expect(cards.first).to_contain_text('Copy 23')
    expect(cards.last).to_contain_text('Copy 15')
    cards.first.get_by_label('Закрепить запись',exact=True).click()
    page.get_by_role('button',name='Закреплённые',exact=True).click()
    expect(cards).to_have_count(2)
    expect(cards.first).to_contain_text('Copy 23')
    expect(cards.last).to_contain_text('Copy 1')
    passed('A new copy replaces the oldest visible entry; pinning preserves both new and old pinned items')

    page.get_by_role('button',name='Главная',exact=True).click()
    page.evaluate('''()=>{
      qaMedia={...qaMedia,sessions:[],session_id:null,playing:false,title:'',can_toggle:false};
      qaEmit('media-changed',structuredClone(qaMedia));
    }''')
    expect(play).to_have_attribute('aria-label','Включить Яндекс Музыку')
    play.click()
    expect(play).to_have_attribute('aria-label','Приостановить музыку')
    assert page.evaluate('qaCalls.some(c=>c.cmd==="start_yandex_music")')
    passed('The same explicit play control starts Yandex Music when no media session exists')
    assert not errors,errors
    browser.close()

(OUT/'home-clipboard-nine-results.json').write_text(json.dumps(RESULTS,indent=2),encoding='utf8')
