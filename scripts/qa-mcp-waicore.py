"""Real HTTPS OAuth -> VPS -> restricted SSH -> temporary local task DB.

Explicit --run; never opens the personal task database or uses OpenAI API.
"""
import base64
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlsplit

import requests

ROOT=Path(__file__).resolve().parents[1]
LOCAL=Path(os.environ['LOCALAPPDATA'])/'PersonalIsland'
from relay_config import load_config
RELAY_CONFIG=load_config()
BASE=RELAY_CONFIG['public_base']
CALLBACK='https://chatgpt.com/connector_platform_oauth_redirect'
OUT=ROOT/'artifacts/qa/mcp-waicore-results.json'
RESULTS=[]


def passed(name):
    RESULTS.append({'test':name,'status':'passed'})
    print(name,flush=True)


def main():
    if '--run' not in sys.argv: raise SystemExit('Explicit --run required')
    owner=json.loads((LOCAL/'waicore-mcp/owner.json').read_text(encoding='utf-8-sig'))
    backend=None; relay=None; token=None; client_id=None
    with tempfile.TemporaryDirectory(prefix='island-waicore-qa-') as folder:
        folder=Path(folder)
        env=dict(os.environ, PERSONAL_ISLAND_DB=str(folder/'tasks.sqlite3'),
            PERSONAL_ISLAND_MCP_TOKEN_FILE=str(LOCAL/'mcp-bridge.token'), PERSONAL_ISLAND_MCP_BIND='127.0.0.1:18741')
        env.pop('PERSONAL_ISLAND_MCP_TOKEN',None)
        with (folder/'process.log').open('w') as log, requests.Session() as http:
            http.trust_env=False
            try:
                assert http.get(urlsplit(BASE).scheme+'://'+urlsplit(BASE).netloc+'/',timeout=15).status_code == 200
                assert http.post(BASE+'/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/list'},timeout=15).status_code == 401
                metadata=http.get(urlsplit(BASE).scheme+'://'+urlsplit(BASE).netloc+'/.well-known/oauth-authorization-server'+urlsplit(BASE).path,timeout=15)
                assert metadata.status_code == 200 and metadata.json()['code_challenge_methods_supported']==['S256']
                passed('Public HTTPS discovery is correct, anonymous MCP is blocked, existing website returns 200')
                backend=subprocess.Popen([str(ROOT/'target/debug/task-mcp-http.exe')],env=env,stdout=log,stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                relay=subprocess.Popen(['ssh','-N','-T','-i',str(Path(RELAY_CONFIG['ssh_identity'])),
                    '-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10',
                    '-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3',
                    '-R','127.0.0.1:18741:127.0.0.1:18741',RELAY_CONFIG['ssh_target']],
                    stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                time.sleep(2)
                assert relay.poll() is None, 'Private SSH relay failed'
                assert backend.poll() is None, 'Temporary backend failed'
                response=http.post(BASE+'/register',json={'redirect_uris':[CALLBACK],'token_endpoint_auth_method':'none'},timeout=15)
                assert response.status_code == 201, response.status_code
                client_id=response.json()['client_id']
                verifier=secrets.token_urlsafe(48)
                challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
                response=http.get(BASE+'/authorize',params=dict(client_id=client_id,redirect_uri=CALLBACK,
                    response_type='code',scope='tasks:read tasks:write',resource=BASE+'/mcp',
                    code_challenge=challenge,code_challenge_method='S256',state='private-qa'),timeout=15)
                assert response.status_code == 200
                csrf=re.search(r'name="csrf" value="([^"]+)"',response.text)[1]
                response=http.post(BASE+'/authorize',data={'csrf':csrf,'password':owner['owner_password']},allow_redirects=False,timeout=15)
                assert response.status_code == 302
                callback=urlsplit(response.headers['Location'])
                assert callback.netloc == 'chatgpt.com'
                query=parse_qs(callback.query)
                assert query['state']==['private-qa'] and query['iss']==[BASE]
                response=http.post(BASE+'/token',data=dict(grant_type='authorization_code',client_id=client_id,
                    code=query['code'][0],redirect_uri=CALLBACK,code_verifier=verifier,resource=BASE+'/mcp'),timeout=15)
                assert response.status_code == 200, response.status_code
                token=response.json()['access_token']
                passed('Real HTTPS owner login, dynamic registration, issuer callback and PKCE token exchange succeed')
                sequence=0
                def rpc(method, params):
                    nonlocal sequence
                    sequence+=1
                    response=http.post(BASE+'/mcp',json=dict(jsonrpc='2.0',id=sequence,method=method,params=params),
                        headers={'Authorization':'Bearer '+token},timeout=35)
                    assert response.status_code == 200, (method,response.status_code,response.json().get('error'))
                    message=response.json()
                    assert 'error' not in message, message.get('error')
                    return message['result']
                def tool(name, args):
                    result=rpc('tools/call',dict(name=name,arguments=args))
                    assert not result.get('isError'), result
                    return result.get('structuredContent')
                rpc('initialize',dict(protocolVersion='2025-11-25',capabilities={},clientInfo={'name':'island-private-qa','version':'1'}))
                tools=rpc('tools/list',{})['tools']
                assert len(tools)==11
                assert all(t['securitySchemes'][0]['type']=='oauth2' for t in tools)
                assert tool('get_current_time',{})['timezone']=='Europe/Moscow'
                plan=dict(request_key='waicore-qa-'+secrets.token_hex(8),tasks=[
                    {'title':'QA temporary HTTPS task','due_at':'2030-01-02T10:00:00+03:00'},
                    {'title':'QA temporary HTTPS task 2','due_at':'2030-01-02T12:00:00+03:00'}])
                first=tool('create_tasks',plan)['tasks']
                second=tool('create_tasks',plan)['tasks']
                assert [t['id'] for t in first]==[t['id'] for t in second]
                schedule=tool('list_schedule',dict(start_at='2030-01-02T00:00:00+03:00',end_at='2030-01-03T00:00:00+03:00'))['tasks']
                assert len(schedule)==2
                with closing(sqlite3.connect(folder/'tasks.sqlite3')) as db:
                    assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==2
                passed('All eleven tools are discovered; HTTPS batch saves only in the temporary PC database and retries create no duplicates')
                response=http.post(BASE+'/revoke',data={'client_id':client_id,'token':token},timeout=15)
                assert response.status_code==200
                assert http.post(BASE+'/mcp',json={},headers={'Authorization':'Bearer '+token},timeout=15).status_code==401
                token=None
                passed('Revocation immediately blocks further use of the issued access token')
            finally:
                if token and client_id:
                    http.post(BASE+'/revoke',data={'client_id':client_id,'token':token},timeout=15)
                for process in (relay,backend):
                    if process and process.poll() is None:
                        process.terminate(); process.wait(timeout=10)
                OUT.parent.mkdir(parents=True,exist_ok=True)
                OUT.write_text(json.dumps(RESULTS,indent=2),encoding='utf8')


if __name__=='__main__': main()
