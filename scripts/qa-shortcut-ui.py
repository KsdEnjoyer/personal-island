"""Shortcut toggle, expanded/pinned closing and interrupted exit regression."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/qa'
RESULTS = []

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport={'width':480,'height':196}, reduced_motion='reduce')
    errors = []
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf8'))
    page.goto('http://127.0.0.1:1420/')
    shell = page.locator('.island-shell')
    expect(shell).to_have_attribute('data-shortcut-ready','true')

    def toggle():
        page.evaluate("window.__TAURI_INTERNALS__.invoke('toggle_island_shortcut')")

    def passed(name):
        RESULTS.append({'test':name,'status':'passed'})
        print(name,flush=True)

    for style in ['island','portrait']:
        page.evaluate('(style)=>localStorage.setItem("personal-island.appearance.v1",JSON.stringify({style,liquid:false}))',style)
        page.reload()
        expect(shell).to_have_attribute('data-shortcut-ready','true')
        expect(shell).to_have_attribute('aria-hidden','true')
        toggle()
        expect(shell).to_have_attribute('aria-hidden','false')
        expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
        toggle()
        expect(shell).to_have_attribute('aria-hidden','true')
        toggle()
        expect(shell).to_have_attribute('aria-hidden','false')
        page.locator('.compact-stage [aria-label="Развернуть список задач"]').click()
        page.set_viewport_size({'width':760,'height':520})
        expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
        page.locator('.pin-button').click()
        toggle()
        expect(shell).to_have_attribute('aria-hidden','true')
        page.set_viewport_size({'width':480,'height':196})
        passed(f'{style}: shortcut shows, hides, reopens and closes an expanded pinned panel')

    page.emulate_media(reduced_motion='no-preference')
    toggle()
    expect(shell).to_have_attribute('aria-hidden','false')
    page.wait_for_timeout(400)
    page.evaluate('''()=>{
      qaEmit('island-toggle',null);
      setTimeout(()=>qaEmit('island-toggle',null),40);
    }''')
    page.wait_for_timeout(800)
    expect(shell).to_have_attribute('aria-hidden','false')
    assert not page.evaluate('document.querySelector(".island-shell").classList.contains("dismissing")')
    passed('A new press during the exit animation reopens the island; the stale exit does not hide it')
    toggle()
    expect(shell).to_have_attribute('aria-hidden','true')
    page.evaluate('qaReveal("hourly")')
    expect(shell).to_have_attribute('aria-hidden','false')
    page.evaluate('qaReveal("hourly")')
    page.wait_for_timeout(350)
    expect(shell).to_have_attribute('aria-hidden','false')
    passed('Scheduled reveals always show rather than toggle; no browser errors')
    assert not errors,errors
    browser.close()

OUT.mkdir(parents=True,exist_ok=True)
(OUT/'shortcut-ui-results.json').write_text(json.dumps(RESULTS,indent=2),encoding='utf8')
