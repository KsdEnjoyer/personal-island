import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('relay_config',Path(__file__).resolve().parents[2]/'scripts/relay_config.py')
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)


@pytest.fixture
def local_config(tmp_path,monkeypatch):
    path = tmp_path/'relay.json'
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    monkeypatch.setenv('PERSONAL_ISLAND_RELAY_CONFIG',str(path))
    data = dict(public_base='https://island.example.com/island-mcp',ssh_host='vps.example.com',
        ssh_user='islandrelay',admin_target='deploy@vps.example.com',admin_identity='~/.ssh/id_ed25519')
    return path,data


def test_operator_config_is_external_and_admin_arguments_remain_separate(local_config):
    path,data = local_config
    path.write_text(json.dumps(data),encoding='utf8')
    result = relay.load_config()
    assert result['ssh_target']=='islandrelay@vps.example.com'
    args = relay.admin_ssh(result)
    assert args[-1]=='deploy@vps.example.com' and 'StrictHostKeyChecking=yes' in args


@pytest.mark.parametrize('field,value',[
    ('public_base','http://island.example.com/island-mcp'),
    ('public_base','https://name:password@island.example.com/island-mcp'),
    ('ssh_host','-oProxyCommand=anything'),('ssh_user','user;command'),
])
def test_invalid_operator_endpoints_and_ssh_options_are_rejected(local_config,field,value):
    path,data = local_config
    data[field] = value
    path.write_text(json.dumps(data),encoding='utf8')
    with pytest.raises(ValueError):relay.load_config()
