"""Measured-audio canvas response, onset/decay and hidden/reduced-motion gating."""
import json,sys
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/qa'
OUT.mkdir(parents=True,exist_ok=True)
RESULTS=[]
def passed(name,**values):
    RESULTS.append({'test':name,'status':'passed',**values})
    print(name,values,flush=True)

with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':480,'height':196},reduced_motion='no-preference')
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.add_init_script((ROOT/'scripts/qa-ipc.js').read_text(encoding='utf8'))
    if '--liquid-off' in sys.argv:
        # A pre-existing profile can disable the ambient edge without opting
        # out of a music equalizer. This was the real regression trigger.
        page.add_init_script("localStorage.setItem('personal-island.appearance.v1',JSON.stringify({style:'island',liquid:false}))")
    page.goto('http://127.0.0.1:1420/')
    expect(page.locator('.island-shell')).to_have_attribute('data-shortcut-ready','true')
    page.mouse.move(5,180)
    page.evaluate('''()=>{
      qaMedia={sessions:[{id:'qa',label:'QA'}],session_id:'qa',source:'QA',title:'Audio response',artist:'QA',artwork:null,playing:true,position:0,duration:200,can_toggle:true,can_previous:true,can_next:true};
      qaReveal('manual');
      window.audioFeed=value=>{clearInterval(window.audioTimer);qaEmit('island-audio',value);window.audioTimer=setInterval(()=>qaEmit('island-audio',value),33)};
    }''')
    page.wait_for_function('qaAudioEnabled===true')
    page.wait_for_timeout(650)
    def feed(bass,impact,bands=None):
        page.evaluate('value=>audioFeed(value)',{'available':True,'bass':bass,'impact':impact,'level':bass,'bands':bands or [bass]*10})
    def bounds():
        return page.evaluate('''()=>{
          const canvas=document.querySelector('.liquid-surface'),ctx=canvas.getContext('2d');
          const {data,width,height}=ctx.getImageData(0,0,canvas.width,canvas.height);
          const scale=width/480;
          let lowest=0;
          for(let y=Math.round(45*scale);y<Math.min(height,130*scale);y++)for(let x=Math.round(100*scale);x<380*scale;x++){
            const i=(y*width+x)*4;
            if(data[i+3]>25&&data[i+1]>data[i]+15&&data[i+1]>data[i+2]+15)lowest=Math.max(lowest,y/scale);
          }
          return lowest;
        }''')
    def body_bottom():
        return page.evaluate('''()=>{
          const canvas=document.querySelector('.liquid-surface'),ctx=canvas.getContext('2d');
          const {data,width,height}=ctx.getImageData(0,0,canvas.width,canvas.height),scale=width/480;
          let bottom=0;
          for(let y=40*scale|0;y<100*scale;y++)for(let x=130*scale|0;x<350*scale;x++){
            const i=(y*width+x)*4;
            if(data[i+3]>=250&&data[i]<8&&data[i+1]<8&&data[i+2]<8)bottom=Math.max(bottom,y/scale);
          }
          return bottom;
        }''')
    feed(.06,0)
    page.wait_for_timeout(350)
    quiet=bounds()
    quiet_body=body_bottom()
    page.screenshot(path=str(OUT/'audio-quiet.png'))
    feed(.35,0)
    page.wait_for_timeout(100)
    passage=bounds()
    assert passage>=quiet+5,(quiet,passage)
    passed('Ordinary music has visible peaks without requiring a bass transient',quiet_y=quiet,passage_y=passage)
    feed(1,1,[1,1,.9,.7,.5,.3,.2,.1,.1,.05])
    page.wait_for_timeout(35)
    drop=bounds()
    drop_body=body_bottom()
    page.screenshot(path=str(OUT/'audio-drop.png'))
    assert drop>=quiet+24,(quiet,drop)
    assert abs(drop_body-quiet_body)<=1,(quiet_body,drop_body)
    expect(page.locator('.compact-stage')).to_have_css('height','56px')
    expect(page.locator('.dashboard')).to_have_attribute('aria-hidden','true')
    passed('The waveform punches outward within 35 ms; the filled body keeps its exact lower boundary',quiet_y=quiet,drop_y=drop,quiet_body=quiet_body,drop_body=drop_body)
    feed(.06,0)
    page.wait_for_timeout(180)
    settled=bounds()
    assert abs(settled-quiet)<3,(quiet,settled)
    page.evaluate('clearInterval(audioTimer)')
    page.wait_for_timeout(900)
    silent=bounds()
    assert silent<quiet+2,(silent,quiet)
    passed('The hit releases within 180 ms and stale audio frames fall back to a quiet edge',settled_y=settled,silent_y=silent)
    page.evaluate('qaMedia.playing=false;qaEmit("media-changed",structuredClone(qaMedia))')
    page.wait_for_function('qaAudioEnabled===false')
    page.evaluate('qaMedia.playing=true;qaEmit("media-changed",structuredClone(qaMedia))')
    page.wait_for_function('qaAudioEnabled===true')
    page.emulate_media(reduced_motion='reduce')
    page.wait_for_function('qaAudioEnabled===false')
    page.emulate_media(reduced_motion='no-preference')
    page.wait_for_function('qaAudioEnabled===true')
    page.evaluate('qaEmit("island-toggle",null)')
    expect(page.locator('.island-shell')).to_have_attribute('aria-hidden','true')
    page.wait_for_function('qaAudioEnabled===false')
    page.wait_for_timeout(500)
    page.evaluate('''()=>{
      window.hiddenDraws=0;
      const clear=CanvasRenderingContext2D.prototype.clearRect;
      CanvasRenderingContext2D.prototype.clearRect=function(...args){hiddenDraws++;return clear.apply(this,args)};
    }''')
    page.wait_for_timeout(800)
    assert page.evaluate('hiddenDraws')<=2
    passed('Pause, reduced motion and hiding disable audio analysis; a hidden island does not keep an ambient RAF loop running')
    page.set_viewport_size({'width':760,'height':520})
    page.evaluate("qaReveal('manual')")
    page.locator('.compact-stage .compact-open').first.click()
    page.get_by_role('button',name='Настройки',exact=True).click()
    page.get_by_label('Жидкий край',exact=True).uncheck()
    page.wait_for_function('qaAudioEnabled===true')
    equalizer=page.get_by_label('Эквалайзер музыки',exact=True)
    expect(equalizer).to_be_checked()
    equalizer.uncheck()
    page.wait_for_function('qaAudioEnabled===false')
    saved=page.evaluate("JSON.parse(localStorage.getItem('personal-island.appearance.v1'))")
    assert saved['liquid'] is False and saved['equalizer'] is False,saved
    equalizer.check()
    page.wait_for_function('qaAudioEnabled===true')
    saved=page.evaluate("JSON.parse(localStorage.getItem('personal-island.appearance.v1'))")
    assert saved['liquid'] is False and saved['equalizer'] is True,saved
    passed('The equalizer works with the ambient edge disabled, and its own setting persists independently')
    assert not errors,errors
    browser.close()

name='audio-reactivity-no-liquid-results.json' if '--liquid-off' in sys.argv else 'audio-reactivity-ui-results.json'
(OUT/name).write_text(json.dumps(RESULTS,indent=2),encoding='utf8')
