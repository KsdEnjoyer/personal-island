"""Executed by deploy.py over SSH stdin as root. PAYLOAD is never logged."""
import base64
import grp
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import time
from urllib.parse import urlsplit
import re


def run(*args):
    subprocess.run(args,check=True)


public=urlsplit(PAYLOAD['public_base'])
if public.scheme!='https' or not re.fullmatch(r'[A-Za-z0-9.-]+', public.netloc) or public.path!='/island-mcp' or public.query or public.fragment:
    raise ValueError('Deployment requires https://YOUR-HOST/island-mcp')

os.umask(0o022)
for name,home in [('islandmcp','/var/lib/personal-island-mcp'),('islandrelay','/var/lib/personal-island-relay')]:
    try: pwd.getpwnam(name)
    except KeyError: run('useradd','--system','--create-home','--home-dir',home,'--shell','/usr/sbin/nologin',name)
account=pwd.getpwnam('islandmcp')
root=Path('/opt/personal-island-mcp')
root.mkdir(mode=0o755,exist_ok=True)
root.chmod(0o755)
state=Path('/var/lib/personal-island-mcp')
state.mkdir(mode=0o700,exist_ok=True)
state.chmod(0o700)
os.chown(state,account.pw_uid,account.pw_gid)
for name,encoded in PAYLOAD['files'].items():
    if name not in {'gateway.py','requirements.txt'}: raise ValueError('Unexpected deployment file')
    destination=root/name
    destination.write_bytes(base64.b64decode(encoded))
    destination.chmod(0o644)
venv=root/'venv'
if not (venv/'bin/pip').exists():
    if subprocess.run(['python3','-c','import ensurepip'],capture_output=True).returncode:
        os.environ['DEBIAN_FRONTEND']='noninteractive'
        os.environ['NEEDRESTART_MODE']='l'
        run('apt-get','update','-qq')
        run('apt-get','install','-y','--no-install-recommends','python3-venv')
    run('python3','-m','venv',str(venv))
run(str(venv/'bin/pip'),'install','--disable-pip-version-check','-q','-r',str(root/'requirements.txt'))
os.umask(0o077)
etc=Path('/etc/personal-island-mcp')
etc.mkdir(mode=0o750,exist_ok=True)
etc.chmod(0o750)
os.chown(etc,0,account.pw_gid)
config_path=etc/'config.json'
if config_path.exists():
    config=json.loads(config_path.read_text())
else:
    config={'session_secret':secrets.token_hex(32)}
config.update(public_base=PAYLOAD['public_base'],database=str(state/'oauth.sqlite3'),
              owner_password_hash=PAYLOAD['owner_hash'],bridge_token=PAYLOAD['bridge_token'])
config_path.write_text(json.dumps(config))
config_path.chmod(0o640)
os.chown(config_path,0,account.pw_gid)
relay=pwd.getpwnam('islandrelay')
ssh_dir=Path(relay.pw_dir)/'.ssh'
ssh_dir.mkdir(mode=0o700,exist_ok=True)
os.chown(ssh_dir,relay.pw_uid,relay.pw_gid)
authorized=ssh_dir/'authorized_keys'
authorized.write_text('restrict,port-forwarding,permitlisten="127.0.0.1:18741" '+PAYLOAD['public_key']+'\n')
authorized.chmod(0o600); os.chown(authorized,relay.pw_uid,relay.pw_gid)
ssh_config=Path('/etc/ssh/sshd_config.d/70-personal-island.conf')
ssh_config.write_text('''Match User islandrelay
    AuthenticationMethods publickey
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AllowTcpForwarding remote
    GatewayPorts no
    PermitListen 127.0.0.1:18741
    PermitOpen none
    PermitTTY no
    X11Forwarding no
    ForceCommand /bin/false
Match all
''')
ssh_config.chmod(0o600)
run('/usr/sbin/sshd','-t')
run('systemctl','reload','ssh')
unit=Path('/etc/systemd/system/personal-island-mcp.service')
unit.write_text('''[Unit]
Description=Personal Island OAuth MCP gateway
After=network-online.target
Wants=network-online.target
[Service]
User=islandmcp
Group=islandmcp
WorkingDirectory=/opt/personal-island-mcp
Environment=ISLAND_GATEWAY_CONFIG=/etc/personal-island-mcp/config.json
ExecStart=/opt/personal-island-mcp/venv/bin/gunicorn --workers 1 --threads 4 --bind 127.0.0.1:18740 --timeout 40 --error-logfile - gateway:create_app()
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/personal-island-mcp
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
[Install]
WantedBy=multi-user.target
''')
unit.chmod(0o644)
run('systemctl','daemon-reload')
run('systemctl','enable','personal-island-mcp')
run('systemctl','restart','personal-island-mcp')
for attempt in range(20):
    import urllib.request
    try:
        req=urllib.request.Request('http://127.0.0.1:18740/island-mcp/.well-known/oauth-authorization-server',headers={'Host':public.netloc})
        with urllib.request.urlopen(req,timeout=2) as response: assert response.status==200
        break
    except Exception:
        if attempt==19: raise RuntimeError('Gateway did not become ready; public route was not installed')
        time.sleep(0.5)
snippet=Path('/etc/nginx/snippets/personal-island-mcp.conf')
common='''
        proxy_pass http://127.0.0.1:18740;
        proxy_http_version 1.1;
        proxy_set_header Host HOST_PLACEHOLDER;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 35s;
        proxy_connect_timeout 3s;
        client_max_body_size 256k;
        access_log off;
'''
common=common.replace('HOST_PLACEHOLDER',public.netloc)
snippet.write_text('''# Personal Island: this prefix only; static site remains unchanged.
    location ^~ /island-mcp/ {
'''+common+'''    }
    location = /.well-known/oauth-authorization-server/island-mcp {
'''+common+'''    }
    location = /.well-known/oauth-protected-resource/island-mcp/mcp {
'''+common+'''    }
''')
snippet.chmod(0o644)
print('Gateway and restricted relay configured. Include /etc/nginx/snippets/personal-island-mcp.conf inside your own HTTPS server block, then run nginx -t and reload nginx. No existing virtual host was edited.',flush=True)
