"""Read-only server audit; outputs policy booleans and bound addresses only."""
from pathlib import Path
import subprocess

script = r'''
from pathlib import Path
import json, subprocess
policy=subprocess.check_output(['/usr/sbin/sshd','-T','-C','user=islandrelay,host=localhost,addr=127.0.0.1'],text=True).splitlines()
settings=dict(line.split(' ',1) for line in policy)
assert settings['allowtcpforwarding']=='remote'
assert settings['gatewayports']=='no'
assert settings['permitlisten']=='127.0.0.1:18741'
assert settings['permitopen']=='none'
assert settings['forcecommand']=='/bin/false'
listeners=[]
for line in subprocess.check_output(['ss','-lntH'],text=True).splitlines():
    address=line.split()[3]
    if address.endswith(':18740') or address.endswith(':18741'):
        assert address.startswith('127.0.0.1:'), 'Public private-relay listener detected'
        listeners.append(address)
assert len(listeners)==2
assert subprocess.check_output(['systemctl','is-active','personal-island-mcp'],text=True).strip()=='active'
print(json.dumps({'relay_policy':'restricted_remote_forward_only','private_listeners':listeners,'gateway':'active'}))
'''
from relay_config import load_config, admin_ssh
ssh=admin_ssh(load_config())+['sudo -n python3 -']
subprocess.run(ssh,input=script.encode(),check=True)
