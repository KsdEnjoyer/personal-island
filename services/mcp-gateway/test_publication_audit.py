import importlib.util
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('publication_audit',ROOT/'scripts/audit-release.py')
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_force_added_private_files_are_rejected_without_logging_their_values(tmp_path,monkeypatch,capsys):
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    (tmp_path/'.gitignore').write_text((ROOT/'.gitignore').read_text(encoding='utf8'),encoding='utf8')
    marker='private-value-that-must-never-be-printed'
    for name in ('.env.production','owner.json','relay.local.json'):
        (tmp_path/name).write_text(marker,encoding='utf8')
        subprocess.run(['git','-C',str(tmp_path),'add','-f',name],check=True)
    monkeypatch.setattr(audit,'ROOT',tmp_path)
    monkeypatch.setattr('sys.argv',['audit-release.py'])
    assert audit.main()==1
    output=capsys.readouterr().out
    assert 'private-or-runtime-file' in output
    assert marker not in output
