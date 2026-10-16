import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core import backup
from core.database import Database, identity
from core.errors import InsightError
from core.health import inspect


def test_online_backup_and_restore_preserves_later_receipts(tmp_path, notice):
    path = tmp_path / 'scope' / 'insight.sqlite3'
    db = Database(path)
    db.upsert(notice, ['desktop'])
    saved = backup.create(path)
    assert backup.verify(path, saved['name'])['valid']
    db.delivery(1, 'submitted')
    db.close()
    preview = backup.restore(path, saved['name'])
    assert preview['status'] == 'confirmation_required'
    assert backup.restore(path, saved['name'], 'wrong')['status'] == 'confirmation_required'
    result = backup.restore(path, saved['name'], preview['confirm'])
    assert result['status'] == 'restored' and result['safety_backup']
    db = Database(path)
    assert db.db.execute('select status from deliveries').fetchone()[0] == 'submitted'
    db.upsert(notice, ['desktop'])
    assert not db.pending(['desktop'])
    db.close()


def test_restore_merges_receipts_for_notice_missing_in_old_backup(tmp_path, notice):
    path = tmp_path / 'scope' / 'insight.sqlite3'
    db = Database(path)
    saved = backup.create(path)
    db.upsert(notice, ['desktop']); db.delivery(1, 'received'); db.close()
    backup.restore(path, saved['name'], backup.digest(path))
    db = Database(path)
    db.upsert(notice, ['desktop'])
    assert not db.pending(['desktop'])
    db.close()


def test_snapshot_failure_keeps_valid_backup_and_cleans_temporary(tmp_path, notice, monkeypatch):
    path = tmp_path / 'scope' / 'insight.sqlite3'
    db = Database(path); db.upsert(notice); db.close()
    saved = backup.create(path)
    original = backup.digest(backup.selected(path, saved['name']))
    monkeypatch.setattr(backup.os, 'replace', lambda *a: (_ for _ in ()).throw(OSError('fictional disk full')))
    with pytest.raises(OSError): backup.create(path)
    assert backup.digest(backup.selected(path, saved['name'])) == original
    assert not list(backup.backup_dir(path).glob('*.tmp'))


def test_corrupt_backup_and_cross_scope_rejected(tmp_path, notice):
    path = tmp_path / 'scope' / 'insight.sqlite3'
    db = Database(path); db.upsert(notice); db.close()
    saved = backup.create(path)
    with pytest.raises(InsightError): backup.verify(path, '../insight.sqlite3')
    candidate = backup.selected(path, saved['name'])
    candidate.write_bytes(b'fictional corruption')
    with pytest.raises(InsightError): backup.verify(path, saved['name'])
    assert backup.digest(path) != backup.digest(candidate)


def test_online_snapshot_does_not_include_uncommitted_writer(tmp_path, notice):
    path=tmp_path/'scope'/'insight.sqlite3'
    db=Database(path);db.upsert(notice)
    # A concurrent RESERVED writer leaves the last committed snapshot readable.
    writer=sqlite3.connect(path)
    writer.execute("UPDATE notices SET title='fictional uncommitted update'")
    saved=backup.create(path)
    writer.rollback();writer.close();db.close()
    con=sqlite3.connect(backup.selected(path,saved['name']))
    assert con.execute('SELECT title FROM notices').fetchone()[0]==notice.title
    con.close()


def test_manifest_scope_and_retention(tmp_path):
    path = tmp_path / 'scope' / 'insight.sqlite3'
    Database(path).close()
    a = backup.create(path)
    b = backup.create(path, 'before-restore')
    meta = backup.selected(path, a['name']).with_suffix('.json')
    data = json.loads(meta.read_text()); data['scope'] = 'other'; meta.write_text(json.dumps(data))
    with pytest.raises(InsightError): backup.verify(path, a['name'])
    assert backup.automatic(path, {'keep': 1})['status'] == 'ok'
    assert len([r for r in backup.listing(path) if r['valid'] and r['name'].startswith('snapshot-')]) == 1
    assert backup.verify(path, b['name'])['valid']
    assert backup.automatic(path, {})['status'] == 'not_due'


def test_corrupt_current_never_overwritten_and_recover_copy_is_held(tmp_path, notice):
    path = tmp_path / 'scope' / 'insight.sqlite3'
    db = Database(path); db.upsert(notice, ['desktop']); db.close()
    saved = backup.create(path)
    path.write_bytes(b'fictional corrupt current')
    with pytest.raises(sqlite3.Error): backup.restore(path, saved['name'], backup.digest(path))
    result = backup.recover_copy(path, saved['name'])
    assert result['active_database_unchanged'] and path.read_bytes() == b'fictional corrupt current'
    db = Database(result['path'])
    assert not db.pending(['desktop'])
    db.close()


def test_health_no_new_empty_and_stale_are_not_the_same(cfg, tmp_path):
    db = Database(tmp_path / 'db.sqlite3')
    assert inspect(cfg, db)['status'] == 'attention'
    for name in ('portal', 'byr'):
        run = db.start_run(name); db.finish_run(run, 'no_new', {'unchanged': 2})
    assert inspect(cfg, db)['backup']['status'] == 'missing'
    backup.create(tmp_path / 'db.sqlite3')
    assert inspect(cfg, db)['status'] == 'healthy'
    future = datetime.now(timezone.utc) + timedelta(days=2)
    assert inspect(cfg, db, future)['sources']['portal']['status'] == 'stale'
    run = db.start_run('portal'); db.finish_run(run, 'no_new', {})
    assert inspect(cfg, db)['sources']['portal']['hours_since_data'] is not None
    run = db.start_run('portal'); db.finish_run(run, 'login_expired')
    assert inspect(cfg, db)['sources']['portal']['status'] == 'latest_failed'
    db.close()
