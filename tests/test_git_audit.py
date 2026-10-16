import json
import subprocess

from tools import audit_git


def test_history_private_path_detected_even_if_same_blob_is_now_public(tmp_path,monkeypatch):
    def git(*args):
        return subprocess.run(['git',*args],cwd=tmp_path,capture_output=True,check=True).stdout
    git('init');git('config','user.name','Fictional Test');git('config','user.email','test@example.test')
    (tmp_path/'README.md').write_text('fictional identical content')
    (tmp_path/'config.yaml').write_text('fictional identical content')
    git('add','.');git('commit','-m','fictional first')
    git('rm','config.yaml');git('commit','-m','fictional remove')
    monkeypatch.setattr(audit_git,'git',git)
    monkeypatch.setattr('core.security.get_secret',lambda _:None)
    result=audit_git.audit()
    assert not result['passed']
    assert any(r['path']=='config.yaml' for r in result['violations'])


def test_staged_known_secret_detected_without_echoing_value(tmp_path,monkeypatch):
    def git(*args):
        return subprocess.run(['git',*args],cwd=tmp_path,capture_output=True,check=True).stdout
    git('init');git('config','user.name','Fictional Test');git('config','user.email','test@example.test')
    (tmp_path/'README.md').write_text('fictional initial')
    git('add','.');git('commit','-m','fictional')
    secret='FICTIONALSECRET123'
    (tmp_path/'next.txt').write_text(secret);git('add','next.txt')
    monkeypatch.setattr(audit_git,'git',git)
    monkeypatch.setattr('core.security.get_secret',lambda n:json.dumps({'password':secret}) if n=='portal' else None)
    result=audit_git.audit(True)
    assert not result['passed'] and secret not in json.dumps(result)
