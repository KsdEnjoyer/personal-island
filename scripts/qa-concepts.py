"""Capture the two standalone design directions and check their interactions."""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/concepts/island-study'
with sync_playwright() as p:
    exe=sorted((Path(os.environ['LOCALAPPDATA'])/'ms-playwright').glob('chromium_headless_shell-*/**/chrome-headless-shell.exe'))[-1]
    browser=p.chromium.launch(executable_path=str(exe));page=browser.new_page(viewport={'width':1160,'height':1050},device_scale_factor=1.5,reduced_motion='reduce')
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto((OUT/'index.html').as_uri())
    expect(page.locator('#track-title')).to_have_text('Ночной Петербург')
    page.get_by_label('Следующий трек',exact=True).click();expect(page.locator('#track-title')).to_have_text('После дождя')
    page.get_by_label('Показать громкость').click();page.get_by_label('Громкость плеера',exact=True).fill('38');expect(page.locator('output')).to_have_text('38%')
    page.get_by_label('Пауза',exact=True).click();expect(page.get_by_label('Продолжить',exact=True)).to_be_visible()
    page.get_by_role('button',name='Сбросить демонстрацию').click()
    page.screenshot(path=str(OUT/'concept-01-quiet.png'),full_page=True)
    page.get_by_role('button',name='02 · Обложка и атмосфера',exact=True).click()
    expect(page.locator('body')).to_have_attribute('data-direction','scene')
    page.get_by_role('button',name='Повторить появление ↗').click()
    page.screenshot(path=str(OUT/'concept-02-scene.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert not errors,errors
    browser.close()
(OUT/'checks.json').write_text(json.dumps({'status':'passed','checks':['both design directions','track switching','volume slider','pause','appearance replay','desktop bounds','no JS exceptions']},indent=2),encoding='utf-8')
print('Both interactive concepts and their previews passed',flush=True)
