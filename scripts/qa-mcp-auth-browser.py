"""Real browser OAuth consent; never captures password/code/token screenshots or URLs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlencode, parse_qs, urlsplit

from playwright.sync_api import sync_playwright
import requests

from relay_config import load_config
RELAY_CONFIG=load_config()
BASE=RELAY_CONFIG['public_base']
CALLBACK='https://chatgpt.com/connector_platform_oauth_redirect'
owner=json.loads((Path(os.environ['LOCALAPPDATA'])/'PersonalIsland/waicore-mcp/owner.json').read_text(encoding='utf-8-sig'))
http=requests.Session(); http.trust_env=False
registered=http.post(BASE+'/register',json={'redirect_uris':[CALLBACK],'token_endpoint_auth_method':'none'},timeout=15)
assert registered.status_code==201
client_id=registered.json()['client_id']
verifier=secrets.token_urlsafe(48)
challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
params=dict(client_id=client_id,redirect_uri=CALLBACK,response_type='code',scope='tasks:read',
    resource=BASE+'/mcp',state='browser-qa',code_challenge=challenge,code_challenge_method='S256')
result={}
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True, channel='msedge')
    page=browser.new_page()
    responses=[]
    failures=[]
    page.on('response', lambda response: responses.append(response) if urlsplit(response.url).path=='/island-mcp/authorize' and response.request.method=='POST' else None)
    page.on('console', lambda message: failures.append('form_policy') if 'form-action' in message.text else None)
    page.on('requestfailed', lambda req: failures.append('request_failed'))
    # Do not transmit this QA authorization code to a real ChatGPT callback.
    page.route('https://chatgpt.com/**',lambda route: route.fulfill(status=200,body='OAuth browser check'))
    page.goto(BASE+'/authorize?'+urlencode(params))
    page.locator('input[name=password]').fill(owner['owner_password'])
    page.locator('button').click()
    page.wait_for_timeout(3000)
    response=responses[-1] if responses else None
    origin=response.request.headers.get('origin','missing') if response else 'missing'
    result.update(form_status=response.status if response else 'not_observed',origin=origin if origin in {'null',urlsplit(BASE).scheme+'://'+urlsplit(BASE).netloc,'missing'} else 'other',browser_policy_events=failures)
    if response and response.status==302:
        page.wait_for_url('https://chatgpt.com/**',timeout=15000)
        query=parse_qs(urlsplit(page.url).query)
        assert query['state']==['browser-qa']
        issued=http.post(BASE+'/token',data=dict(grant_type='authorization_code',client_id=client_id,
            code=query['code'][0],code_verifier=verifier,redirect_uri=CALLBACK,resource=BASE+'/mcp'),timeout=15)
        assert issued.status_code==200
        assert http.post(BASE+'/revoke',data={'client_id':client_id,'token':issued.json()['access_token']},timeout=15).status_code==200
        result['browser_callback']='passed'
    browser.close()
print(json.dumps(result))
assert result.get('browser_callback')=='passed', 'Browser consent failed; no secrets were logged'
