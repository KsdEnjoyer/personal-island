import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import patch

import pytest
from werkzeug.security import generate_password_hash

spec = importlib.util.spec_from_file_location('gateway', Path(__file__).with_name('gateway.py'))
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)
BASE = 'https://island.example.com/island-mcp'
CALLBACK = 'https://chatgpt.com/connector_platform_oauth_redirect'


@pytest.fixture
def ctx(tmp_path):
    password = secrets.token_urlsafe(24)
    config = dict(public_base=BASE, session_secret=secrets.token_hex(32),
                  database=str(tmp_path/'oauth.db'), owner_password_hash=generate_password_hash(password),
                  bridge_token=secrets.token_hex(32))
    app = gateway.create_app(config)
    app.testing = True
    return app, app.test_client(), password


def send(client, path, method='get', **kwargs):
    return getattr(client, method)(path, base_url='https://island.example.com', **kwargs)


def registration(client, redirects=None):
    response = send(client, '/island-mcp/register', 'post', json={
        'redirect_uris': redirects or [CALLBACK], 'token_endpoint_auth_method':'none'})
    assert response.status_code == 201, response.data
    return response.json['client_id']


def authorize(ctx, scope='tasks:read tasks:write', client_id=None):
    app, client, password = ctx
    client_id = client_id or registration(client)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    params = dict(client_id=client_id, response_type='code', redirect_uri=CALLBACK, state='qa-state',
        scope=scope, resource=BASE+'/mcp', code_challenge=challenge, code_challenge_method='S256')
    response = send(client, '/island-mcp/authorize?'+urlencode(params))
    assert response.status_code == 200, response.data
    csrf = re.search(r'name="csrf" value="([^"]+)"', response.text)[1]
    response = send(client, '/island-mcp/authorize', 'post', data={'csrf':csrf,'password':password})
    assert response.status_code == 302, response.data
    result = parse_qs(urlsplit(response.headers['Location']).query)
    assert result['state'] == ['qa-state']
    assert result['iss'] == [BASE]
    return dict(grant_type='authorization_code', client_id=client_id, code=result['code'][0],
                redirect_uri=CALLBACK, code_verifier=verifier, resource=BASE+'/mcp')


def exchange(ctx, scope='tasks:read tasks:write'):
    args = authorize(ctx, scope)
    response = send(ctx[1], '/island-mcp/token', 'post', data=args)
    assert response.status_code == 200, response.data
    return args, response.json


def test_discovery_and_unauthenticated_access(ctx):
    _, client, _ = ctx
    response = send(client, '/island-mcp/mcp', 'post', json={'jsonrpc':'2.0','id':1,'method':'tools/list'})
    assert response.status_code == 401
    assert 'resource_metadata=' in response.headers['WWW-Authenticate']
    for path in ['/island-mcp/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/island-mcp/mcp']:
        assert send(client,path).json['resource'] == BASE+'/mcp'
    for path in ['/island-mcp/.well-known/oauth-authorization-server','/.well-known/oauth-authorization-server/island-mcp']:
        assert send(client,path).json['code_challenge_methods_supported'] == ['S256']
    assert send(client,'/island-mcp/register','post',json={'redirect_uris':['https://attacker.example/callback']}).status_code == 400
    assert send(client,'/island-mcp/register','post',json={'redirect_uris':['https://chatgpt.com.evil.example/connector_platform_oauth_redirect']}).status_code == 400
    assert send(client,'/island-mcp/register','post',json={'redirect_uris':[CALLBACK+'?evil=1']}).status_code == 400
    assert registration(client,['https://chatgpt.com/connector/oauth/abc-123'])


def test_owner_password_csrf_and_s256_required(ctx):
    _, client, password = ctx
    client_id = registration(client)
    params = dict(client_id=client_id,response_type='code',redirect_uri=CALLBACK,resource=BASE+'/mcp')
    assert send(client,'/island-mcp/authorize?'+urlencode(params)).status_code == 400
    params.update(code_challenge='a'*43,code_challenge_method='plain')
    assert send(client,'/island-mcp/authorize?'+urlencode(params)).status_code == 400
    params['code_challenge_method']='S256'
    response = send(client,'/island-mcp/authorize?'+urlencode(params))
    assert response.headers['Referrer-Policy']=='same-origin'
    assert "form-action 'self' https://chatgpt.com" in response.headers['Content-Security-Policy']
    csrf = re.search(r'name="csrf" value="([^"]+)"',response.text)[1]
    assert send(client,'/island-mcp/authorize','post',data={'password':password,'csrf':'wrong'}).status_code == 403
    response = send(client,'/island-mcp/authorize','post',data={'password':'wrong','csrf':csrf})
    assert response.status_code == 200 and 'Неверный пароль' in response.text
    assert send(client,'/island-mcp/authorize','post',data={'password':password,'csrf':csrf},headers={'Origin':'https://evil.example'}).status_code == 403


def test_codes_require_correct_resource_verifier_redirect_client_and_are_single_use(ctx):
    app, client, _ = ctx
    args = authorize(ctx)
    for field, value in [('resource','https://evil.example'),('code_verifier','b'*64),('redirect_uri',CALLBACK+'/wrong'),('client_id','nonexistent')]:
        bad = dict(args, **{field:value})
        assert send(client,'/island-mcp/token','post',data=bad).status_code in {400,401}
    response = send(client,'/island-mcp/token','post',data=args)
    assert response.status_code == 200, response.data
    token = response.json
    assert token['expires_in'] == 600 and token['refresh_token']
    assert send(client,'/island-mcp/token','post',data=args).status_code == 400
    db = Path(app.extensions['island_store'].path).read_bytes()
    assert token['access_token'].encode() not in db
    assert token['refresh_token'].encode() not in db


def test_refresh_rotation_replay_revokes_family_and_revoke_endpoint(ctx):
    _, client, _ = ctx
    args, token = exchange(ctx)
    refresh = dict(grant_type='refresh_token',client_id=args['client_id'],
                   refresh_token=token['refresh_token'],resource=BASE+'/mcp')
    response = send(client,'/island-mcp/token','post',data=refresh)
    assert response.status_code == 200, response.data
    second = response.json
    assert second['refresh_token'] != token['refresh_token']
    assert send(client,'/island-mcp/mcp','post',json={},headers={'Authorization':'Bearer '+token['access_token']}).status_code == 401
    assert send(client,'/island-mcp/token','post',data=refresh).status_code == 400
    assert send(client,'/island-mcp/mcp','post',json={},headers={'Authorization':'Bearer '+second['access_token']}).status_code == 401
    args, token = exchange(ctx)
    assert send(client,'/island-mcp/revoke','post',data={'client_id':args['client_id'],'token':token['access_token']}).status_code == 200
    assert send(client,'/island-mcp/mcp','post',json={},headers={'Authorization':'Bearer '+token['access_token']}).status_code == 401


def test_read_scope_cannot_write_and_headers_are_not_forwarded(ctx):
    _, client, _ = ctx
    _, token = exchange(ctx, 'tasks:read')
    headers = {'Authorization':'Bearer '+token['access_token'],'Origin':'https://evil.example','X-Forwarded-Host':'evil.example'}
    def tool(name):
        return send(client,'/island-mcp/mcp','post',headers=headers,
            json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':{}}})
    with patch.object(gateway.requests.Session, 'post') as blocked:
        denied=tool('create_task')
        assert denied.status_code == 200
        assert denied.json['result']['isError'] is True
        challenge=denied.json['result']['_meta']['mcp/www_authenticate'][0]
        assert 'error="insufficient_scope"' in challenge
        assert 'error_description=' in challenge
        assert 'scope="tasks:read tasks:write"' in challenge
        blocked.assert_not_called()
    assert tool('shell_exec').status_code == 400
    with patch.object(gateway.requests.Session, 'post') as post:
        post.return_value.status_code = 200
        post.return_value.content = b'{}'
        post.return_value.json.return_value = {'jsonrpc':'2.0','id':1,'result':{'ok':True}}
        assert tool('get_current_time').status_code == 200
        assert post.call_args.args == ('http://127.0.0.1:18741/mcp',)
        sent = post.call_args.kwargs['headers']
        assert 'Origin' not in sent and 'X-Forwarded-Host' not in sent
        assert sent['Authorization'] != headers['Authorization']
        assert post.call_args.kwargs['allow_redirects'] is False


@pytest.mark.parametrize('field,value', [
    ('session_secret','change-me'), ('bridge_token','x'*64),
    ('owner_password_hash','plaintext-is-not-a-password-hash'),
    ('public_base','https://name:password@island.example.com/island-mcp'),
])
def test_insecure_gateway_configuration_fails_before_serving(tmp_path, field, value):
    config = dict(public_base=BASE, session_secret=secrets.token_hex(32),
        database=str(tmp_path/'oauth.db'), owner_password_hash=generate_password_hash(secrets.token_urlsafe(24)),
        bridge_token=secrets.token_hex(32))
    config[field] = value
    with pytest.raises(ValueError):
        gateway.create_app(config)


def test_limits_expiry_and_offline_bridge_fail_closed(ctx):
    app, client, _ = ctx
    _, token = exchange(ctx)
    headers = {'Authorization':'Bearer '+token['access_token']}
    body = {'jsonrpc':'2.0','id':1,'method':'tools/list'}
    with patch.object(gateway.requests.Session, 'post', side_effect=gateway.requests.ConnectionError):
        assert send(client,'/island-mcp/mcp','post',headers=headers,json=body).status_code == 503
    assert send(client,'/island-mcp/mcp','post',headers=headers,data='x'*270000,content_type='application/json').status_code == 413
    app.extensions['island_store'].execute('UPDATE tokens SET expires=0')
    assert send(client,'/island-mcp/mcp','post',headers=headers,json=body).status_code == 401
    for index in range(32):
        response=send(client,'/island-mcp/register','post',json={'redirect_uris':[CALLBACK]})
    assert response.status_code == 429


def test_malformed_client_metadata_and_refresh_scope_escalation(ctx):
    _, client, _ = ctx
    for invalid in [None, {}, ['authorization_code', {}], 'authorization_code']:
        response = send(client,'/island-mcp/register','post',json={'redirect_uris':[CALLBACK],'grant_types':invalid})
        assert response.status_code == 400
    args, token = exchange(ctx, 'tasks:read')
    refresh = dict(grant_type='refresh_token',client_id=args['client_id'],refresh_token=token['refresh_token'],
                   resource=BASE+'/mcp',scope='tasks:read tasks:write')
    assert send(client,'/island-mcp/token','post',data=refresh).status_code == 400
    headers={'Authorization':'Bearer '+token['access_token']}
    assert send(client,'/island-mcp/mcp','post',headers=headers,json={'jsonrpc':'2.0','id':1,'method':[]}).status_code == 200
    assert send(client,'/island-mcp/mcp','post',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':[]}}).status_code == 400


def test_write_scope_requires_new_owner_consent_and_tool_metadata_advertises_it(ctx):
    _, client, _ = ctx
    args, read_token=exchange(ctx,'tasks:read')
    write_args=authorize(ctx,'tasks:read tasks:write',client_id=args['client_id'])
    issued=send(client,'/island-mcp/token','post',data=write_args)
    assert issued.status_code==200
    write_token=issued.json['access_token']
    body={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'create_task','arguments':{'title':'QA','request_key':'qa'}}}
    with patch.object(gateway.requests.Session, 'post') as post:
        post.return_value.status_code=200
        post.return_value.content=b'{}'
        post.return_value.json.return_value={'jsonrpc':'2.0','id':1,'result':{'isError':False}}
        assert send(client,'/island-mcp/mcp','post',headers={'Authorization':'Bearer '+read_token['access_token']},json=body).json['result']['isError'] is True
        post.assert_not_called()
        assert send(client,'/island-mcp/mcp','post',headers={'Authorization':'Bearer '+write_token},json=body).json['result']['isError'] is False
        assert post.call_count==1
        post.return_value.json.return_value={'jsonrpc':'2.0','id':2,'result':{'tools':[{'name':'get_current_time'},{'name':'create_task'}]}}
        tools=send(client,'/island-mcp/mcp','post',headers={'Authorization':'Bearer '+write_token},json={'jsonrpc':'2.0','id':2,'method':'tools/list'}).json['result']['tools']
        assert tools[0]['_meta']['securitySchemes']==[{'type':'oauth2','scopes':['tasks:read']}]
        assert tools[1]['_meta']['securitySchemes']==[{'type':'oauth2','scopes':['tasks:read','tasks:write']}]
