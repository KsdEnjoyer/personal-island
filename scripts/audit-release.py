"""Audit Git publication candidates without printing matching secret values."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = {
    'private-key': r'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----',
    'provider-token': r'(?<![A-Za-z0-9])(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})',
    'telegram-token': r'\b\d{8,}:[A-Za-z0-9_-]{30,}\b',
    'personal-windows-path': r'(?i)[A-Z]:[/\\]Users[/\\](?!YOUR_USER\b|example\b)[^/\\\s"<>]+',
}
FORBIDDEN_PARTS = {'artifacts','.local','node_modules','target','dist','__pycache__','.pytest_cache','.venv-mcp-gateway'}
FORBIDDEN_SUFFIXES = {'.sqlite','.sqlite3','.db','.log','.pid','.token','.pem','.key','.pfx','.p12','.mp4','.webm','.exe','.msi','.pyc'}


def git(*args):
    return subprocess.check_output(['git','-C',str(ROOT),*args])


def candidates():
    raw = git('ls-files','--cached','--others','--exclude-standard','-z')
    return sorted(set(item.decode('utf8') for item in raw.split(b'\0') if item))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,help='Copy only clean publication files to a new directory under .local or artifacts')
    args = parser.parse_args()
    files = candidates()
    findings = []
    for name in files:
        path = ROOT/name
        if not path.is_file():
            findings.append((name,0,'missing-or-nonregular-file'));continue
        private_name = path.name in {'owner.json','process.json','.env'} or (path.name.startswith('.env.') and path.name!='.env.example') or path.name.endswith(('.local.json','.local.toml'))
        if private_name or path.is_symlink() or FORBIDDEN_PARTS.intersection(path.relative_to(ROOT).parts) or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append((name,0,'private-or-runtime-file'));continue
        if path.stat().st_size > 2*1024*1024:
            findings.append((name,0,'unexpected-large-file'));continue
        try:
            source = path.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:
            if path.suffix.lower() not in {'.png','.ico'}:findings.append((name,0,'unexpected-binary'))
            continue
        for line_number,line in enumerate(source.splitlines(),1):
            for rule,pattern in SECRET_PATTERNS.items():
                if re.search(pattern,line):findings.append((name,line_number,rule))
            for address in re.findall(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])',line):
                try:
                    if ipaddress.ip_address(address).is_global:findings.append((name,line_number,'literal-public-ip'))
                except ValueError:pass
    private_samples = ['artifacts/screenshot.png','.local/relay.json','.env.production','owner.json','secret.token','key.pem','tasks.sqlite3','notes.db','.venv-mcp-gateway/pyvenv.cfg']
    for sample in private_samples:
        result = subprocess.run(['git','-C',str(ROOT),'check-ignore','--no-index','-q',sample])
        if result.returncode != 0:findings.append(('.gitignore',0,'unprotected-'+sample))
    for name,line,rule in findings:
        print(f'{name}:{line}: {rule} (value redacted)')
    print(json.dumps({'publication_files':len(files),'findings':len(findings)}))
    if findings:return 1
    if args.snapshot:
        target = args.snapshot.resolve()
        if not any(target.is_relative_to(ROOT/parent) for parent in ('.local','artifacts')) or target.exists():
            parser.error('Snapshot must be a new directory under .local or artifacts')
        target.mkdir(parents=True)
        for name in files:
            destination = target/name
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/name,destination)
        print('Clean publication snapshot created; no Git history or runtime files copied.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
