"""Capri appearance: persistence, eye data, compact media controls and reminders."""
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
    page = browser.new_page(viewport={'width': 480, 'height': 196}, reduced_motion='reduce', timezone_id='Europe/Moscow')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script((ROOT / 'scripts/qa-ipc.js').read_text(encoding='utf8'))

    def load():
        page.goto('http://127.0.0.1:1420/')
        expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready', 'true')

    def settings():
        page.set_viewport_size({'width': 760, 'height': 520})
        page.locator('.header-actions button[aria-expanded]').click()

    load()
    page.evaluate('qaReveal("manual")')
    expect(page.locator('.pill')).to_be_visible()
    page.locator('.pill').click()
    settings()
    page.get_by_role('radio', name='Капри', exact=True).locator('..').click()
    expect(page.get_by_role('radio', name='Капри', exact=True)).to_be_checked()
    page.add_style_tag(content='html,body,#app{background:#30333b!important}')
    page.screenshot(path=str(OUT / 'capri-settings.png'))
    page.locator('.collapse-button').click()
    page.set_viewport_size({'width': 480, 'height': 196})
    page.evaluate('qaReveal("manual")')
    face = page.locator('.compact-stage .capri-face')
    expect(face).to_be_visible()
    assert face.bounding_box()['width'] == 272 and face.bounding_box()['height'] == 104
    expect(face.locator('.capri-summary strong')).to_have_text('4 задачи')
    expect(face.locator('.capri-clock span')).to_have_text('25:00')
    expect(page.locator('.liquid-surface')).to_have_css('opacity', '0')
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden', 'true')
    page.screenshot(path=str(OUT / 'capri-overview.png'))
    passed('Appearance selector applies the 272x104 Capri face; time, timer and tasks occupy its eyes; classic canvas is hidden')

    load()
    page.evaluate('qaReveal("manual")')
    expect(face).to_be_visible()
    assert page.evaluate('qaCalls.some(c=>c.cmd==="set_island_appearance"&&c.args.portrait)')
    page.evaluate('''()=>{
        qaMedia={sessions:[{id:'qa-player',label:'QA Player'}],session_id:'qa-player',source:'QA Player',title:'Neon Night',artist:'QA',artwork:null,playing:true,position:1,duration:200,can_toggle:true,can_previous:true,can_next:true};
        qaEmit('media-changed',structuredClone(qaMedia));
    }''')
    player = face.locator('.capri-player')
    expect(player).to_be_visible()
    player.get_by_label('Следующий трек', exact=True).click()
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden', 'true')
    assert page.evaluate('qaCalls.some(c=>c.cmd==="media_command"&&c.args.action==="next")')
    player.get_by_label('Приостановить музыку', exact=True).click()
    expect(player.get_by_label('Продолжить музыку', exact=True)).to_be_visible()
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden', 'true')
    player.get_by_label('Продолжить музыку', exact=True).click()
    expect(player.get_by_label('Приостановить музыку', exact=True)).to_be_visible()
    page.add_style_tag(content='html,body,#app{background:#30333b!important}')
    page.screenshot(path=str(OUT / 'capri-music.png'))
    passed('The face survives reload and registers its native hover shape; previous/next and cover pause/resume stay compact')

    page.evaluate('qaReveal("track")')
    expect(page.locator('.track-peek')).to_be_visible()
    expect(face).to_have_count(0)
    expect(page.locator('.track-peek')).to_have_css('height', '76px')
    page.evaluate('qaReveal("manual")')
    expect(face).to_be_visible()
    page.evaluate('''()=>{
      const task={...qaTasks[0],id:999,title:'QA Capri reminder',reminder_at:new Date(Date.now()-1000).toISOString(),notification_sent_at:null};
      qaTasks.push(task);qaEmit('island-reminders',[structuredClone(task)]);
    }''')
    notice = page.locator('.compact-stage .reminder-notice')
    expect(notice.locator('strong')).to_have_text('QA Capri reminder', timeout=8000)
    expect(face).to_have_count(0)
    notice.locator('.reminder-dismiss').click()
    page.evaluate('qaReveal("manual")')
    expect(face).to_be_visible()
    passed('Track popups and bell reminders retain their own layout; manual reveal restores the selected face')

    face.locator('.capri-clock').click()
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden', 'false')
    page.set_viewport_size({'width': 760, 'height': 520})
    expect(page.locator('.island-shell.capri-theme.expanded')).to_have_count(1)
    page.locator('.pin-button').click()
    page.evaluate('''()=>{
      const now=Math.floor(Date.now()/1000);
      qaWeather={stale:false,error:null,data:{city:'Saint Petersburg',fetched_at:now,
        current:{time:now,temperature_2m:3,apparent_temperature:0,relative_humidity_2m:82,is_day:1,weather_code:2,wind_speed_10m:4,wind_direction_10m:270,precipitation:0},
        hourly:Array.from({length:8},(_,i)=>({time:now+i*3600,temperature:3+i%3,precipitation:10,code:2,is_day:true})),
        daily:Array.from({length:7},(_,i)=>({time:now+i*86400,low:i-2,high:i+4,code:2,precipitation:0,sunrise:now-18000,sunset:now+18000}))}};
    }''')
    for tab in ['home', 'tasks', 'calendar', 'notes', 'music', 'weather', 'clipboard', 'done']:
        # Real tab handlers, including lazy notes. Theme must survive every view.
        index = ['home','today','tasks','calendar','notes','music','weather','clipboard','done'].index(tab)
        page.locator('.tabs button').nth(index).click()
        expect(page.locator('.tabs button').nth(index)).to_have_attribute('aria-current','page')
        expect(page.locator('.dashboard')).to_have_css('background-color','rgb(8, 15, 13)')
        expect(page.locator('.island-shell')).to_have_css('--amber','#38ed8b')
        if tab == 'notes':
            expect(page.locator('.note-paper')).to_have_css('background-color','rgb(17, 27, 22)')
            expect(page.locator('.note-sections button.active')).to_have_css('color','rgb(173, 255, 208)')
        if tab == 'weather':
            page.get_by_label('Обновить погоду',exact=True).click()
            expect(page.locator('.weather-city')).to_be_visible()
            expect(page.locator('.weather-hours')).to_have_css('background-color','rgb(17, 27, 22)')
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / f'capri-expanded-{tab}.png'))
    passed('All expanded sections keep the Capri palette, including lazy notes, calendar, player and settings')
    settings()
    page.get_by_role('radio', name='Островок', exact=True).locator('..').click()
    page.locator('.collapse-button').click()
    page.set_viewport_size({'width': 480, 'height': 196})
    page.evaluate('qaReveal("manual")')
    expect(face).to_have_count(0)
    expect(page.locator('.pill.music-pill')).to_be_visible()
    expect(page.locator('.liquid-surface')).to_have_css('opacity', '1')
    assert not page.locator('.capri-theme').count()
    page.evaluate('localStorage.setItem("personal-island.appearance.v1","bad-json")')
    load()
    page.evaluate('qaReveal("manual")')
    expect(page.locator('.pill')).to_be_visible()
    assert not errors, errors
    passed('Eye clicks open the themed dashboard; Classic restores the original palette; corrupt settings recover safely without browser errors')
    browser.close()

(OUT / 'capri-ui-results.json').write_text(json.dumps(RESULTS, indent=2), encoding='utf8')
