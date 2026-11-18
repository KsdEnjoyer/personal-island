"""Single-owner OAuth gateway. Calendar data remains on the Windows PC.

OAuthLib validates grants, redirects and PKCE. One Gunicorn worker with threads
serializes token grants; SQLite stores only hashes of opaque codes/tokens.
"""
from contextlib import closing
from datetime import timedelta
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

from flask import Flask, Response, abort, jsonify, render_template_string, request, session
from oauthlib.oauth2 import RequestValidator, Server, OAuth2Error
import requests
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

READ_TOOLS = {'get_current_time', 'list_tasks', 'list_schedule', 'get_task'}
WRITE_TOOLS = {'create_task', 'create_tasks', 'update_task', 'reschedule_task',
               'complete_task', 'reopen_task', 'delete_task'}
SCOPES = {'tasks:read', 'tasks:write'}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, path):
        self.path = path
        with closing(self.connect()) as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS clients(id TEXT PRIMARY KEY, redirects TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS codes(hash TEXT PRIMARY KEY, client TEXT, redirect TEXT,
                challenge TEXT, scopes TEXT, resource TEXT, expires REAL);
            CREATE TABLE IF NOT EXISTS tokens(access TEXT PRIMARY KEY, refresh TEXT UNIQUE,
                client TEXT, scopes TEXT, resource TEXT, expires REAL, refresh_expires REAL,
                family TEXT, used INTEGER DEFAULT 0, revoked INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS attempts(bucket TEXT PRIMARY KEY, count INTEGER, expires REAL);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def one(self, sql, args=()):
        with closing(self.connect()) as db:
            row = db.execute(sql, args).fetchone()
            return dict(row) if row else None

    def execute(self, sql, args=()):
        with closing(self.connect()) as db, db:
            db.execute(sql, args)

    def limit(self, bucket, maximum, seconds):
        now = time.time()
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE expires < ?', (now,))
            db.execute('INSERT INTO attempts VALUES (?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=count+1',
                       (bucket, now+seconds))
            count = db.execute('SELECT count FROM attempts WHERE bucket=?', (bucket,)).fetchone()[0]
            return count <= maximum


class Validator(RequestValidator):
    def __init__(self, store, resource):
        self.store, self.resource = store, resource

    def validate_client_id(self, client_id, request, *args, **kwargs):
        if not self.store.one('SELECT id FROM clients WHERE id=?', (client_id,)):
            return False
        request.client = SimpleNamespace(client_id=client_id)
        return True

    authenticate_client_id = validate_client_id

    def client_authentication_required(self, request, *args, **kwargs):
        return False  # Public clients, protected by mandatory S256 PKCE.

    def validate_redirect_uri(self, client_id, redirect_uri, request, *args, **kwargs):
        client = self.store.one('SELECT redirects FROM clients WHERE id=?', (client_id,))
        return bool(client and redirect_uri in json.loads(client['redirects']))

    def get_default_redirect_uri(self, client_id, request, *args, **kwargs):
        client = self.store.one('SELECT redirects FROM clients WHERE id=?', (client_id,))
        return json.loads(client['redirects'])[0] if client else None

    def validate_response_type(self, client_id, response_type, client, request, *args, **kwargs):
        return response_type == 'code'

    def validate_grant_type(self, client_id, grant_type, client, request, *args, **kwargs):
        return grant_type in {'authorization_code', 'refresh_token'}

    def get_default_scopes(self, client_id, request, *args, **kwargs):
        return sorted(SCOPES)

    def validate_scopes(self, client_id, scopes, client, request, *args, **kwargs):
        return bool(scopes) and set(scopes) <= SCOPES

    def is_pkce_required(self, client_id, request):
        return True

    def save_authorization_code(self, client_id, code, request, *args, **kwargs):
        self.store.execute('INSERT INTO codes VALUES (?,?,?,?,?,?,?)',
            (digest(code['code']), client_id, request.redirect_uri, request.code_challenge,
             ' '.join(request.scopes), self.resource, time.time()+300))

    def code(self, code):
        return self.store.one('SELECT * FROM codes WHERE hash=? AND expires>?', (digest(code), time.time()))

    def validate_code(self, client_id, code, client, request, *args, **kwargs):
        saved = self.code(code)
        if not saved or saved['client'] != client_id or request.resource != self.resource:
            return False
        request.user = 'owner'
        request.scopes = saved['scopes'].split()
        return True

    def confirm_redirect_uri(self, client_id, code, redirect_uri, client, request, *args, **kwargs):
        saved = self.code(code)
        return bool(saved and saved['client'] == client_id and hmac.compare_digest(saved['redirect'], redirect_uri))

    def get_code_challenge(self, code, request):
        saved = self.code(code)
        return saved['challenge'] if saved else None

    def get_code_challenge_method(self, code, request):
        return 'S256'

    def invalidate_authorization_code(self, client_id, code, request, *args, **kwargs):
        self.store.execute('DELETE FROM codes WHERE hash=? AND client=?', (digest(code), client_id))

    def save_bearer_token(self, token, request, *args, **kwargs):
        family = secrets.token_urlsafe(24)
        if request.grant_type == 'refresh_token':
            previous = self.store.one('SELECT family FROM tokens WHERE refresh=?', (digest(request.refresh_token),))
            family = previous['family']
            self.store.execute('UPDATE tokens SET used=1,revoked=1 WHERE refresh=?', (digest(request.refresh_token),))
        self.store.execute('INSERT INTO tokens(access,refresh,client,scopes,resource,expires,refresh_expires,family) VALUES (?,?,?,?,?,?,?,?)',
            (digest(token['access_token']), digest(token['refresh_token']), request.client.client_id,
             token['scope'], self.resource, time.time()+token['expires_in'], time.time()+30*86400, family))

    def validate_refresh_token(self, refresh_token, client, request, *args, **kwargs):
        saved = self.store.one('SELECT * FROM tokens WHERE refresh=?', (digest(refresh_token),))
        if not saved or saved['client'] != client.client_id or request.resource != self.resource:
            return False
        if saved['used']:
            self.store.execute('UPDATE tokens SET revoked=1 WHERE family=?', (saved['family'],))
            return False
        if saved['revoked'] or saved['refresh_expires'] <= time.time():
            return False
        request.user = 'owner'
        return True

    def get_original_scopes(self, refresh_token, request, *args, **kwargs):
        return self.store.one('SELECT scopes FROM tokens WHERE refresh=?', (digest(refresh_token),))['scopes'].split()

    def revoke_token(self, token, token_type_hint, request, *args, **kwargs):
        saved = self.store.one('SELECT family,client FROM tokens WHERE access=? OR refresh=?', (digest(token), digest(token)))
        if saved and saved['client'] == request.client.client_id:
            self.store.execute('UPDATE tokens SET revoked=1 WHERE family=?', (saved['family'],))


LOGIN = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Personal Island · доступ</title><style>
body{background:#111310;color:#edf1e9;font:16px system-ui;margin:0;display:grid;place-items:center;min-height:100vh}
main{width:min(420px,85vw);padding:32px}h1{font-size:27px}p{color:#b2bbae;line-height:1.6}
input,button{box-sizing:border-box;width:100%;padding:14px;border-radius:12px;font:inherit;margin:8px 0}
input{background:#20251f;color:white;border:1px solid #445040}button{background:#c7dfae;border:0;color:#14210b;cursor:pointer}
small{color:#bbc5b5} .error{color:#ffb2a8}</style><main><h1>Personal Island</h1>
<p>Разрешить ChatGPT доступ к твоему островку?</p><p>{{ description }}</p>
<form method="post"><input type="hidden" name="csrf" value="{{ csrf }}">
<label>Пароль подключения</label><input name="password" type="password" autocomplete="current-password" required maxlength="256">
<button name="decision" value="allow">Разрешить доступ</button></form>
<p class="error">{{ error }}</p><small>Это пароль островка. Ключ OpenAI не нужен.</small></main></html>'''


def create_app(config=None):
    if config is None:
        config = json.loads(Path(os.environ.get('ISLAND_GATEWAY_CONFIG', '/etc/personal-island-mcp/config.json')).read_text())
    base = config['public_base'].rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or parsed.query or parsed.fragment or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('HTTPS public_base required')
    for name in ('session_secret', 'bridge_token'):
        value = config.get(name, '')
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', value) or len(set(value)) < 8:
            raise ValueError(name + ' must be a separately generated random secret; use the config generator')
    password_hash = config.get('owner_password_hash', '')
    if not isinstance(password_hash, str) or not password_hash.startswith('scrypt:') or len(password_hash) < 80:
        raise ValueError('A scrypt owner_password_hash is required; plaintext passwords are not accepted')
    prefix = parsed.path
    resource = base+'/mcp'
    app = Flask(__name__)
    app.logger.setLevel(logging.INFO)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    app.config.update(SECRET_KEY=config['session_secret'], MAX_CONTENT_LENGTH=256*1024,
        SESSION_COOKIE_NAME='island_mcp_auth', SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_PATH=prefix,
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=10), TRUSTED_HOSTS=[parsed.hostname])
    store = Store(config['database'])
    validator = Validator(store, resource)
    oauth = Server(validator, token_expires_in=600,
                   token_generator=lambda req: secrets.token_urlsafe(32),
                   refresh_token_generator=lambda req: secrets.token_urlsafe(32))
    grant_lock = threading.RLock()
    bridge_token = config['bridge_token'].strip()
    app.extensions['island_store'] = store

    def rate(name, maximum, seconds):
        bucket = name+':'+digest(request.remote_addr or 'unknown')
        if not store.limit(bucket, maximum, seconds):
            abort(429)

    def challenge(status=401, scope='tasks:read'):
        response = jsonify(error='authentication_required' if status == 401 else 'insufficient_scope')
        response.status_code = status
        error = 'invalid_token' if status == 401 else 'insufficient_scope'
        response.headers['WWW-Authenticate'] = f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource", error="{error}", error_description="Authorize Personal Island to continue", scope="{scope}"'
        return response

    def tool_scope_challenge(body):
        # A read-only grant remains read-only. ChatGPT needs an MCP error result
        # with this metadata to offer consent for the additional write scope.
        auth = challenge(403, 'tasks:read tasks:write').headers['WWW-Authenticate']
        app.logger.warning('MCP write consent required: tool=%s', body['params']['name'])
        response = jsonify(jsonrpc='2.0', id=body.get('id'), result={
            'isError':True,
            'content':[{'type':'text','text':'Для изменения задач переподключи Personal Island и разреши tasks:read tasks:write. Запись не выполнена.'}],
            '_meta':{'mcp/www_authenticate':[auth]}})
        response.headers['WWW-Authenticate'] = auth
        return response

    def oauth_response(result):
        headers, body, status = result
        return Response(body, status=status, headers=headers)

    @app.after_request
    def secure_headers(response):
        response.headers.update({'Cache-Control':'no-store', 'Pragma':'no-cache',
            # Keep the same-origin POST Origin, while hiding OAuth parameters on
            # the cross-origin redirect. form-action must allow that callback.
            'Referrer-Policy':'same-origin', 'X-Content-Type-Options':'nosniff',
            'X-Frame-Options':'DENY', 'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://chatgpt.com; frame-ancestors 'none'; base-uri 'none'"})
        return response

    @app.get(prefix+'/.well-known/oauth-protected-resource')
    @app.get('/.well-known/oauth-protected-resource'+prefix+'/mcp')
    def protected_resource():
        return jsonify(resource=resource, authorization_servers=[base], scopes_supported=sorted(SCOPES),
                       bearer_methods_supported=['header'])

    @app.get(prefix+'/.well-known/oauth-authorization-server')
    @app.get('/.well-known/oauth-authorization-server'+prefix)
    @app.get(prefix+'/.well-known/openid-configuration')
    def metadata():
        return jsonify(issuer=base, authorization_endpoint=base+'/authorize', token_endpoint=base+'/token',
            registration_endpoint=base+'/register', revocation_endpoint=base+'/revoke',
            response_types_supported=['code'], grant_types_supported=['authorization_code','refresh_token'],
            token_endpoint_auth_methods_supported=['none'], code_challenge_methods_supported=['S256'],
            scopes_supported=sorted(SCOPES), authorization_response_iss_parameter_supported=True)

    @app.post(prefix+'/register')
    def register():
        rate('register', 30, 3600)
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='invalid_client_metadata'), 400
        redirects = data.get('redirect_uris')
        if not isinstance(redirects, list) or not 1 <= len(redirects) <= 5:
            return jsonify(error='invalid_redirect_uri'), 400
        for redirect in redirects:
            if not isinstance(redirect, str) or len(redirect) > 512:
                return jsonify(error='invalid_redirect_uri'), 400
            uri = urlsplit(redirect)
            # Exact ChatGPT callback paths only. Never fetch arbitrary client URLs.
            if uri.scheme != 'https' or uri.netloc != 'chatgpt.com' or uri.query or uri.fragment or not (
                    uri.path == '/connector_platform_oauth_redirect' or
                    re.fullmatch(r'/connector/oauth/[A-Za-z0-9_-]{1,160}', uri.path)):
                return jsonify(error='invalid_redirect_uri'), 400
        grants = data.get('grant_types', ['authorization_code','refresh_token'])
        if data.get('token_endpoint_auth_method', 'none') != 'none' or not isinstance(grants, list) or not grants or any(not isinstance(grant, str) or grant not in {'authorization_code','refresh_token'} for grant in grants):
            return jsonify(error='invalid_client_metadata'), 400
        if data.get('response_types', ['code']) != ['code']:
            return jsonify(error='invalid_client_metadata'), 400
        client_id = secrets.token_urlsafe(32)
        store.execute('INSERT INTO clients VALUES (?,?)', (client_id, json.dumps(redirects)))
        return jsonify(client_id=client_id, client_id_issued_at=int(time.time()), redirect_uris=redirects,
            token_endpoint_auth_method='none', response_types=['code'], grant_types=['authorization_code','refresh_token']), 201

    @app.route(prefix+'/authorize', methods=['GET','POST'])
    def authorize():
        rate('authorize', 60, 900)
        error = ''
        if request.method == 'GET':
            query = request.query_string.decode('ascii', errors='strict')
            values = parse_qs(query)
            if len(query) > 3000 or values.get('resource') != [resource] or values.get('code_challenge_method') != ['S256'] or not re.fullmatch(r'[A-Za-z0-9_-]{43}', values.get('code_challenge',[''])[0]):
                return jsonify(error='invalid_request'), 400
            try:
                scopes, credentials = oauth.validate_authorization_request(base+'/authorize?'+query)
            except OAuth2Error:
                return jsonify(error='invalid_request'), 400
            session.clear()
            session.permanent = True
            session.update(query=query, csrf=secrets.token_urlsafe(32), scopes=scopes)
        else:
            if request.headers.get('Origin') not in (None, parsed.scheme+'://'+parsed.netloc):
                app.logger.warning('OAuth consent rejected: cross_origin_post')
                abort(403)
            if not session.get('query') or not hmac.compare_digest(request.form.get('csrf',''), session.get('csrf','!')):
                app.logger.warning('OAuth consent rejected: expired_or_mismatched_form')
                abort(403)
            rate('password', 10, 900)
            password = request.form.get('password', '')
            if not 1 <= len(password) <= 256 or not check_password_hash(config['owner_password_hash'], password):
                error = 'Неверный пароль подключения.'
            else:
                uri = base+'/authorize?'+session['query']
                app.logger.info('OAuth owner consent granted: scopes=%s', ' '.join(session['scopes']))
                try:
                    with grant_lock:
                        result = oauth.create_authorization_response(uri, scopes=session['scopes'], credentials={'user':'owner'})
                except OAuth2Error:
                    return jsonify(error='invalid_request'), 400
                session.clear()
                headers, body, status = result
                if 'Location' in headers:
                    headers['Location'] += ('&' if '?' in headers['Location'] else '?')+urlencode({'iss':base})
                return oauth_response((headers, body, status))
        description = 'Чтение задач и расписания.'
        if 'tasks:write' in session.get('scopes', []):
            description += ' Добавление, изменение и удаление задач по твоим командам.'
        return render_template_string(LOGIN, csrf=session.get('csrf'), description=description, error=error)

    @app.post(prefix+'/token')
    def token():
        rate('token', 120, 900)
        body = request.get_data(as_text=True)
        if request.form.getlist('resource') != [resource]:
            return jsonify(error='invalid_target'), 400
        if request.headers.get('Authorization') or request.form.get('client_secret'):
            return jsonify(error='invalid_client'), 400
        if request.form.get('grant_type') not in {'authorization_code','refresh_token'}:
            return jsonify(error='unsupported_grant_type'), 400
        try:
            with grant_lock:
                return oauth_response(oauth.create_token_response(base+'/token', http_method='POST',
                    body=body, headers={'Content-Type':'application/x-www-form-urlencoded'}))
        except OAuth2Error:
            return jsonify(error='invalid_request'), 400

    @app.post(prefix+'/revoke')
    def revoke():
        rate('revoke', 60, 900)
        with grant_lock:
            return oauth_response(oauth.create_revocation_response(base+'/revoke', http_method='POST',
                body=request.get_data(as_text=True), headers={'Content-Type':'application/x-www-form-urlencoded'}))

    @app.route(prefix+'/mcp', methods=['GET','POST','DELETE'])
    def mcp():
        auth = request.headers.get('Authorization','')
        if not auth.startswith('Bearer ') or len(auth) > 256:
            return challenge()
        saved = store.one('SELECT * FROM tokens WHERE access=? AND expires>? AND revoked=0 AND resource=?',
                          (digest(auth[7:]), time.time(), resource))
        if not saved:
            return challenge()
        if 'tasks:read' not in saved['scopes'].split():
            return challenge(403)
        if request.method != 'POST':
            return Response(status=405, headers={'Allow':'POST'})
        rate('mcp', 600, 60)
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get('jsonrpc') != '2.0':
            return jsonify(error='invalid_request'), 400
        method = body.get('method')
        if not isinstance(method, str) or method not in {'initialize','notifications/initialized','notifications/cancelled','ping','tools/list','tools/call'}:
            return jsonify(jsonrpc='2.0', id=body.get('id'), error={'code':-32601,'message':'Method not available'}), 200
        if method == 'tools/call':
            params = body.get('params')
            if not isinstance(params, dict) or not isinstance(params.get('name'), str) or params['name'] not in READ_TOOLS | WRITE_TOOLS:
                return jsonify(error='unknown_tool'), 400
            if params['name'] in WRITE_TOOLS and 'tasks:write' not in saved['scopes'].split():
                return tool_scope_challenge(body)
        headers = {'Authorization':'Bearer '+bridge_token, 'Content-Type':'application/json',
                   'Accept':'application/json, text/event-stream', 'MCP-Protocol-Version':'2025-11-25'}
        try:
            # A fixed loopback destination; no caller URL or header passthrough.
            with requests.Session() as http:
                http.trust_env = False
                upstream = http.post('http://127.0.0.1:18741/mcp', json=body, headers=headers, timeout=(2,25), allow_redirects=False)
            if upstream.status_code not in {200,202,204}:
                return jsonify(error='island_unavailable'), 503
            if not upstream.content:
                return Response(status=upstream.status_code)
            data = upstream.json()
            if method == 'tools/call' and body['params']['name'] in WRITE_TOOLS:
                app.logger.info('MCP write result: tool=%s is_error=%s', body['params']['name'], bool(data.get('result',{}).get('isError')))
            if method == 'tools/list' and isinstance(data.get('result'),dict):
                for tool in data['result'].get('tools',[]):
                    schemes = [{'type':'oauth2','scopes':['tasks:read']+(['tasks:write'] if tool['name'] in WRITE_TOOLS else [])}]
                    tool['securitySchemes'] = schemes
                    tool.setdefault('_meta', {})['securitySchemes'] = schemes
            return jsonify(data), upstream.status_code
        except (requests.RequestException, ValueError):
            return jsonify(error='island_offline', message='Запусти островок и подключение на компьютере.'), 503

    return app


if __name__ == '__main__':
    create_app().run('127.0.0.1', 18740)
