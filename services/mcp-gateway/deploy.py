"""Deploy only this gateway and private relay. No literal secrets in arguments/output."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

from werkzeug.security import generate_password_hash

ROOT=Path(__file__).resolve().parents[2]
PRIVATE=Path(os.environ['LOCALAPPDATA'])/'PersonalIsland/waicore-mcp'
sys.path.insert(0,str(ROOT/'scripts'))
from relay_config import load_config, admin_ssh
CONFIG=load_config()
KEY=Path(CONFIG['ssh_identity'])
SSH=admin_ssh(CONFIG)


def main():
    if '--run' not in sys.argv:
        raise SystemExit('Explicit --run required for deployment')
    if not KEY.exists():
        subprocess.run(['ssh-keygen','-t','ed25519','-N','','-C','personal-island-relay','-f',str(KEY)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Restrict the dedicated Windows private key before use.
    sid=subprocess.check_output(['powershell.exe','-NoProfile','-Command',
        '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],text=True).strip()
    subprocess.run(['icacls.exe',str(KEY),'/inheritance:r','/grant:r','*'+sid+':(F)','*S-1-5-18:(F)'],
                   check=True,stdout=subprocess.DEVNULL)
    credentials=json.loads((PRIVATE/'owner.json').read_text(encoding='utf-8-sig'))
    token=(Path(os.environ['LOCALAPPDATA'])/'PersonalIsland/mcp-bridge.token').read_text().strip()
    payload=dict(files={name:base64.b64encode((Path(__file__).parent/name).read_bytes()).decode()
        for name in ['gateway.py','requirements.txt']},public_key=KEY.with_suffix('.pub').read_text().strip(),
        owner_hash=generate_password_hash(credentials['owner_password']),bridge_token=token,
        public_base=credentials['public_base'])
    bootstrap=(Path(__file__).parent/'deploy_remote.py').read_text()
    # The entire bootstrap travels over encrypted SSH stdin, never argv or a public upload.
    script='PAYLOAD='+repr(payload)+'\n'+bootstrap
    subprocess.run(SSH+['sudo -n python3 -'],input=script.encode(),check=True)


if __name__=='__main__':
    main()
