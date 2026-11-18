"""Deterministic presentation-lease tests using the Tauri IPC double."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'artifacts/qa'
results = []
def passed(name):
    results.append({'test':name,'status':'passed'})
    print(name,flush=True)

with sync_playwright() as p:
    paths = sorted((Path(os.environ['LOCALAPPDATA'])/'ms-playwright').glob('chromium_headless_shell-*/**/chrome-headless-shell.exe'))
    browser = p.chromium.launch(executable_path=str(paths[-1]))
    context = browser.new_context(viewport={'width':1000,'height':640},reduced_motion='reduce')
    page = context.new_page()
    errors = []
    page.on('pageerror',lambda e: errors.append(str(e)))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf-8'))
    page.clock.install()
    page.goto('http://127.0.0.1:1420/')
    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
    page.mouse.move(990,630)
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
    passed('Startup is completely hidden and shortcut listener is ready')

    page.evaluate('qaReveal()'); page.clock.run_for(100)
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
    expect(page.locator('.pill')).to_be_visible()
    assert not page.evaluate("qaCalls.some(c=>c.cmd==='set_island_expanded' && c.args.expanded)")
    page.clock.run_for(3900)
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
    page.clock.run_for(1500)
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
    assert page.evaluate("qaCalls.some(c=>c.cmd==='hide_island')")
    passed('No pointer: panel stays for five seconds and hides the native window')

    page.evaluate('qaReveal()'); page.clock.run_for(100)
    page.locator('.pill').hover()
    page.clock.run_for(7000)
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
    page.mouse.move(990,630); page.clock.run_for(900)
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
    passed('Pointer holds the panel; leaving after the deadline hides it')

    page.evaluate('qaReveal()'); page.clock.run_for(100)
    page.locator('.pill').hover()
    page.mouse.move(990,630); page.clock.run_for(3000)
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
    page.clock.run_for(2400)
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
    passed('Brief pointer visit does not shorten the initial five-second window')

    page.evaluate('qaReveal()'); page.clock.run_for(4000)
    page.evaluate('qaReveal()'); page.clock.run_for(4000)
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
    page.clock.run_for(1500)
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
    passed('A repeated shortcut renews the timeout')

    page.evaluate('qaReveal()'); page.clock.run_for(100)
    page.locator('.pill').click(); page.clock.run_for(100)
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','false')
    page.get_by_role('button',name='Закрепить островок').click()
    page.mouse.move(990,630); page.clock.run_for(7000)
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','false')
    passed('Pin explicitly keeps the panel open')
    page.locator('.add-task').click()
    page.get_by_label('Название задачи').fill('Text ')
    page.keyboard.type('`')
    expect(page.get_by_label('Название задачи')).to_have_value('Text `')
    assert page.evaluate("qaCalls.some(c=>c.cmd==='set_island_shortcut_editing' && c.args.editing)")
    page.get_by_role('button',name='Отмена',exact=True).click()
    assert page.evaluate("qaCalls.filter(c=>c.cmd==='set_island_shortcut_editing').at(-1).args.editing") is False
    passed('Editing releases the global key and restores it after focus leaves')
    page.keyboard.press('Escape'); page.clock.run_for(100)
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
    passed('Escape hides the whole widget')
    assert not errors,errors
    context.close(); browser.close()

(OUT/'hotkey-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
