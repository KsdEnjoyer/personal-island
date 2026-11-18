"""Generate a private gateway config; never accept passwords in command arguments."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit
from werkzeug.security import generate_password_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-base', required=True)
    parser.add_argument('--bridge-token-file', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    base = args.public_base.rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error('Use your HTTPS public base without credentials, query or fragment')
    if not args.database.is_absolute() or not args.output.is_absolute():
        parser.error('Database and output must be absolute private paths outside the checkout')
    root = Path(__file__).resolve().parents[2]
    if args.database.resolve().is_relative_to(root) or args.output.resolve().is_relative_to(root):
        parser.error('Do not create a secret configuration or database inside the source checkout')
    token = args.bridge_token_file.read_text(encoding='utf-8-sig').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', token) or len(set(token)) < 8:
        parser.error('Bridge token must be a generated random token from the local bridge')
    password = getpass.getpass('Owner password (20+ characters; not echoed): ')
    if len(password) < 20 or password != getpass.getpass('Repeat password: '):
        parser.error('Password is too short or does not match')
    config = dict(public_base=base,database=str(args.database),session_secret=secrets.token_hex(32),
        bridge_token=token,owner_password_hash=generate_password_hash(password,method='scrypt'))
    args.output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    # Refuse to overwrite an existing production config.
    fd = os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf8') as file:
        json.dump(config,file,indent=2)
    print('Private configuration created. Restrict its directory and grant only the gateway service account access before starting it.')


if __name__ == '__main__':
    main()
