"""Operator-specific settings live outside the source tree; never log credentials."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


def private_dir():
    local = os.environ.get('LOCALAPPDATA')
    if not local:
        raise RuntimeError('Relay helpers require Windows LOCALAPPDATA')
    # Keep this legacy directory name for existing installations; any VPS works.
    return Path(local) / 'PersonalIsland' / 'waicore-mcp'


def load_config():
    path = Path(os.environ.get('PERSONAL_ISLAND_RELAY_CONFIG', private_dir() / 'relay.json'))
    if not path.is_file():
        raise RuntimeError('Relay config missing. Copy examples/relay.example.json to the protected local relay directory and configure your own server.')
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    base = config.get('public_base', '').rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Relay public_base must be your HTTPS URL without credentials, query or fragment')
    host = config.get('ssh_host', '')
    user = config.get('ssh_user', '')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:-]{0,252}', host):
        raise ValueError('Invalid relay SSH host')
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', user):
        raise ValueError('Invalid relay SSH user')
    config['public_base'] = base
    config['ssh_target'] = user + '@' + host
    config['ssh_identity'] = str(Path(config.get('ssh_identity', '~/.ssh/personal_island_relay_ed25519')).expanduser())
    return config


def admin_ssh(config):
    target = config.get('admin_target', '')
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9][A-Za-z0-9.:-]{0,252}', target):
        raise ValueError('Configure admin_target in your local relay config before deployment/audit')
    identity = str(Path(config.get('admin_identity', '~/.ssh/id_ed25519')).expanduser())
    return ['ssh', '-i', identity, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=10', target]
