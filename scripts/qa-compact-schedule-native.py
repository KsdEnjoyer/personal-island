"""Compact music and wall-clock scheduler using isolated data, without OS keyboard/focus/cursor manipulation."""
import json,os,struct,subprocess,sys,tempfile,time,urllib.request,wave,zlib
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/qa';results=[]
def passed(name,**data):results.append({'test':name,'status':'passed',**data});print(name,data,flush=True)
with tempfile.TemporaryDirectory(prefix='island-compact-clock-') as temp:
    folder=Path(temp);children=[]
    env=dict(os.environ,PERSONAL_ISLAND_DB=str(folder/'tasks.sqlite3'),WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=9222')
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    pixels=b''.join(b'\0'+bytes([40,100,80,255])*64 for _ in range(64))
    (folder/'cover.png').write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',64,64,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b''))
    with wave.open(str(folder/'silence.wav'),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000);wav.writeframes(b'\0\0'*8000*60)
    with (OUT/'compact-schedule-native-stderr.log').open('w',encoding='utf8') as log:
      def spawn(args,environment=env):
        child=subprocess.Popen(args,env=environment,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW);children.append(child);return child
      try:
        with sync_playwright() as p:
          def start(environment=env):
            app=spawn([str(ROOT/'target/debug/personal-island-desktop.exe'),'--show'],environment)
            end=time.monotonic()+30
            while True:
                assert app.poll() is None,'Application exited'
                try:urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=1).close();break
                except OSError:
                    assert time.monotonic()<end,'WebView2 unavailable';time.sleep(.2)
            browser=p.chromium.connect_over_cdp('http://127.0.0.1:9222');page=browser.contexts[0].pages[0]
            expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
            return app,browser,page
          def invoke(cmd,args=None):return page.evaluate('([cmd,args])=>window.__TAURI_INTERNALS__.invoke(cmd,args)',[cmd,args or {}])
          def stop(app,browser):
            page.evaluate("setTimeout(()=>window.__TAURI_INTERNALS__.invoke('exit_app'),50)");app.wait(timeout=10);browser.close()
          if '--schedule-only' not in sys.argv:
            app,browser,page=start()
            page.locator('.compact-stage .pill-clock, .compact-stage .peek-art').first.click()
            page.locator('.pin-button').click()
            page.locator('.tabs button').nth(5).click()
            player=spawn([str(ROOT/'target/debug/examples/qa-media.exe'),str(folder)])
            end=time.monotonic()+20;source=None
            while source is None:
              assert player.poll() is None
              source=next((s['id'] for s in invoke('get_media_state')['sessions'] if 'qa-media' in s['id']),None)
              assert time.monotonic()<end
              if source is None:page.wait_for_timeout(150)
            select=page.locator('.source-select select')
            # Native media events refresh the options; explicitly request a snapshot if needed.
            page.wait_for_timeout(2200)
            select.select_option(source)
            expect(page.locator('.track-info h2')).to_have_text('QA Track 1')
            page.locator('.collapse-button').click();expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
            (folder/'next-media').touch()
            expect(page.locator('.peek-title b')).to_have_text('QA Track 2',timeout=8000)
            body=page.locator('.track-peek').bounding_box()
            assert body['width']==360 and body['height']==76,body
            page.screenshot(path=str(OUT/'music-native-small.png'))
            page.locator('.volume-trigger').first.click()
            slider=page.locator('.track-peek input[type=range]');expect(slider).to_be_enabled()
            popup=page.locator('.track-peek .volume-popover').bounding_box()
            assert popup['y']>body['y']+body['height']
            slider.fill('37')
            expect(page.locator('.track-peek output')).to_have_text('37%')
            state=invoke('player_volume',{'sessionId':source,'level':None})
            end=time.monotonic()+5
            while abs(state['level']-.37)>=.002 and time.monotonic()<end:
                page.wait_for_timeout(100);state=invoke('player_volume',{'sessionId':source,'level':None})
            assert state['scope']=='player' and abs(state['level']-.37)<.002,state
            assert page.locator('.track-peek').bounding_box()['height']==76
            page.screenshot(path=str(OUT/'music-native-small-volume.png'))
            passed('Real compact notification is 360x76; volume stays outside and controls only the silent player')
            (folder/'stop-media').touch();player.wait(timeout=10);stop(app,browser)
          app,browser,page=start(dict(env,PERSONAL_ISLAND_QA_REVEAL_SECONDS='12'))
          page.evaluate("window.qaBoundaryTimes=[];window.__TAURI_INTERNALS__.invoke('plugin:event|listen',{event:'island-reveal',target:{kind:'Any'},handler:window.__TAURI_INTERNALS__.transformCallback(e=>{if(e.payload.reason==='hourly')qaBoundaryTimes.push(Date.now())})})")
          end=time.monotonic()+30
          while len(page.evaluate('qaBoundaryTimes'))<2:
              assert time.monotonic()<end,'Missing aligned scheduler events'
              page.wait_for_timeout(150)
          times=page.evaluate('qaBoundaryTimes')
          assert all(t%12000<1500 for t in times),times
          assert 11500<times[-1]-times[-2]<12500,times
          passed('Native scheduler fires on aligned wall-clock boundaries',milliseconds_after_boundary=[t%12000 for t in times],interval=times[-1]-times[-2])
          stop(app,browser)
      finally:
        (folder/'stop-media').touch()
        for child in reversed(children):
            if child.poll() is None:child.terminate();child.wait(timeout=10)
        (OUT/'compact-schedule-native-results.json').write_text(json.dumps(results,indent=2),encoding='utf8')
