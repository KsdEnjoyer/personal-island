"""Read-only live diagnostics. Does not print credentials, codes, tokens or task titles."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import parse_qs, urlsplit

import requests

LOCAL=Path(os.environ['LOCALAPPDATA'])/'PersonalIsland'
from relay_config import load_config
RELAY_CONFIG=load_config()
BASE=RELAY_CONFIG['public_base']
CALLBACK='https://chatgpt.com/connector_platform_oauth_redirect'


def main():
    owner=json.loads((LOCAL/'waicore-mcp/owner.json').read_text(encoding='utf-8-sig'))
    internal=(LOCAL/'mcp-bridge.token').read_text().strip()
    with requests.Session() as http:
        http.trust_env=False
        health=http.get('http://127.0.0.1:18741/health',headers={'Authorization':'Bearer '+internal},timeout=3)
        assert health.status_code==200 and health.json()['status']=='ready'
        registered=http.post(BASE+'/register',json={'redirect_uris':[CALLBACK],'token_endpoint_auth_method':'none'},timeout=15)
        assert registered.status_code==201
        client_id=registered.json()['client_id']
        verifier=secrets.token_urlsafe(48)
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        login=http.get(BASE+'/authorize',params=dict(client_id=client_id,redirect_uri=CALLBACK,response_type='code',
            scope='tasks:read',resource=BASE+'/mcp',state='read-only-check',code_challenge=challenge,code_challenge_method='S256'),timeout=15)
        csrf=re.search(r'name="csrf" value="([^"]+)"',login.text)[1]
        approved=http.post(BASE+'/authorize',data={'csrf':csrf,'password':owner['owner_password']},allow_redirects=False,timeout=15)
        assert approved.status_code==302
        query=parse_qs(urlsplit(approved.headers['Location']).query)
        issued=http.post(BASE+'/token',data=dict(grant_type='authorization_code',client_id=client_id,
            code=query['code'][0],code_verifier=verifier,redirect_uri=CALLBACK,resource=BASE+'/mcp'),timeout=15)
        assert issued.status_code==200
        token=issued.json()['access_token']
        try:
            response=http.post(BASE+'/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'get_current_time','arguments':{}}},
                headers={'Authorization':'Bearer '+token},timeout=35)
            assert response.status_code==200
            result=response.json()['result']
            assert not result.get('isError')
            assert result['structuredContent']['timezone']=='Europe/Moscow'
            print(json.dumps({'local_bridge':'ready','https_oauth':'passed','remote_clock':'passed',
                'timezone':'Europe/Moscow','personal_task_changes':0}))
        finally:
            assert http.post(BASE+'/revoke',data={'client_id':client_id,'token':token},timeout=15).status_code==200


if __name__=='__main__': main()
