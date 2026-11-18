"""Download the pinned official Gitleaks release and verify its release checksum."""
import hashlib
import io
import os
from pathlib import Path
import platform
import tarfile
import urllib.request
import zipfile

VERSION = '8.30.1'
ROOT = Path(__file__).resolve().parents[1]


def fetch(url):
    request = urllib.request.Request(url,headers={'User-Agent':'personal-island-security-check'})
    with urllib.request.urlopen(request,timeout=60) as response:
        return response.read()


def main():
    if platform.system() not in {'Windows','Linux'}:
        raise SystemExit('Install the official Gitleaks binary for your operating system manually.')
    if platform.machine().lower() not in {'amd64','x86_64'}:
        raise SystemExit('This helper supports x64; install the verified official binary for your platform manually.')
    windows = os.name == 'nt'
    asset = f'gitleaks_{VERSION}_'+('windows_x64.zip' if windows else 'linux_x64.tar.gz')
    base = f'https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/'
    checks = fetch(base+f'gitleaks_{VERSION}_checksums.txt').decode()
    expected = next(line.split()[0] for line in checks.splitlines() if line.split()[-1].lstrip('*')==asset)
    data = fetch(base+asset)
    if hashlib.sha256(data).hexdigest()!=expected:
        raise SystemExit('Gitleaks checksum mismatch; nothing installed')
    executable = 'gitleaks.exe' if windows else 'gitleaks'
    if windows:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            payload = archive.read(executable)
    else:
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
            payload = archive.extractfile(executable).read()
    destination = ROOT/'.local/tools'/executable
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(payload)
    destination.chmod(0o700)
    print('Verified official Gitleaks',VERSION)


if __name__=='__main__':
    main()
