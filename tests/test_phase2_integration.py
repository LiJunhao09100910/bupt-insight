import json
import time

import pytest

from core.analysis import analyze_row, rules
from core.database import Database
from core.notifications import dispatch, Result
from core.pipeline import sync, database
from core.profile import Profile
from core.locking import single_run
from core.cli import main


def configured(cfg, monkeypatch):
    monkeypatch.setattr('core.security.get_secret', lambda _: None)
    cfg['push']['channels']={'desktop': {'enabled':True}}
    cfg['smart']={'enabled': True}
    cfg['ai']={'mode':'mock', 'max_per_run':10}
    return cfg


def test_digest_durable_retry_and_reanalysis_does_not_replay(cfg, notice, monkeypatch):
    configured(cfg, monkeypatch)
    db=database(cfg)
    notice.body='虚构校园活动安排。'; notice.title='虚构校园活动'
    db.upsert(notice, ['desktop'])
    row=db.db.execute('SELECT * FROM notices').fetchone()
    analyze_row(db,row,Profile(),cfg['ai'])
    calls=[]
    def failed(*args): calls.append(args); return Result('failed','fictional failure')
    dispatch(cfg,db,failed)
    assert len(calls)==1 and db.db.execute('SELECT status FROM deliveries').fetchone()[0]=='digest_waiting'
    db.close(); db=database(cfg)
    def success(*args): calls.append(args); return Result('submitted','fictional success')
    dispatch(cfg,db,success)
    assert len(calls)==2
    db.upsert(notice,['desktop'])
    analyze_row(db,row,Profile(goals=['不同目标']),cfg['ai'])
    dispatch(cfg,db,success)
    assert len(calls)==2
    db.close()


def test_slow_model_and_backup_failure_do_not_lose_or_block_base_push(cfg, notice, monkeypatch):
    configured(cfg,monkeypatch)
    cfg['ai']={'mode':'api','base_url':'https://example.test/v1','allow_private_cloud': True,'budget_seconds':.15}
    def timeout(*args): raise ValueError('fictional timeout')
    monkeypatch.setattr('core.analysis.api_call',timeout)
    monkeypatch.setattr('core.backup.automatic',lambda *a: (_ for _ in ()).throw(OSError('fake secret disk path')))
    calls=[]
    monkeypatch.setattr('core.notifications.desktop',lambda *a: (calls.append(a) or Result('submitted','fictional')))
    def fetch(*a,**kw):return {'test':[notice]}, {}, []
    report=sync(cfg,names=['portal'],push=True,fetchers={'portal':fetch})
    assert report['sources']['portal']['new']==1 and report['backup']['status']=='failed'
    assert report['analysis']['results'][0]['status']=='fallback' and len(calls)==1
    db=database(cfg); assert db.status()['notices']==1; db.close()


def test_partial_body_never_calls_api_but_media_base_reminder_works(cfg, notice, monkeypatch):
    configured(cfg,monkeypatch)
    cfg['ai']={'mode':'api','base_url':'https://example.test/v1','allow_private_cloud':True}
    def forbidden(*a):pytest.fail('incomplete body must not call API')
    monkeypatch.setattr('core.analysis.api_call',forbidden)
    notice.extra['body_status']='image_only'; notice.body='图片内容尚未提取。'
    db=database(cfg); db.upsert(notice,['desktop'])
    from core.analysis import run_pending
    run_pending(cfg,db)
    calls=[]
    dispatch(cfg,db,lambda *a: (calls.append(a) or Result('submitted','fictional')))
    assert len(calls)==1 and '图片文字尚未识别' in calls[0][2]
    db.close()


def test_ai_success_but_sender_failure_preserves_cache_and_retry(cfg, notice, monkeypatch):
    configured(cfg,monkeypatch)
    notice.title='虚构考试'; notice.body='考试必须办理。'
    db=database(cfg); db.upsert(notice,['desktop'])
    row=db.db.execute('SELECT * FROM notices').fetchone()
    analyze_row(db,row,Profile(),cfg['ai'])
    dispatch(cfg,db,lambda *a:Result('failed','fictional'))
    assert len(db.pending(['desktop']))==1
    assert analyze_row(db,row,Profile(),cfg['ai'])['cached']
    dispatch(cfg,db,lambda *a:Result('submitted','fictional'))
    assert not db.pending(['desktop'])
    db.close()


def test_backup_cli_refused_when_scan_has_lock(cfg, monkeypatch, capsys):
    configured(cfg,monkeypatch)
    monkeypatch.setattr('core.cli.load_config',lambda:cfg)
    from core.config import resolve
    with single_run(resolve(cfg,cfg['paths']['data_dir'])/'run.lock'):
        assert main(['backup','create'])==1
    assert 'already_running' in capsys.readouterr().out


def test_profile_cli_and_mock_demo_do_not_expose_profile(cfg, monkeypatch, capsys):
    configured(cfg,monkeypatch)
    monkeypatch.setattr('core.cli.load_config',lambda:cfg)
    assert main(['profile','init'])==0
    assert main(['profile','validate'])==0
    assert main(['ai','demo'])==0
    out=capsys.readouterr().out
    assert 'mock-rules' in out and 'simulation' in out


def test_smart_demo_notification_is_fictional_and_saved(cfg,monkeypatch,capsys):
    configured(cfg,monkeypatch)
    monkeypatch.setattr('core.cli.load_config',lambda:cfg)
    calls=[]
    monkeypatch.setattr('core.notifications.desktop',lambda *a:(calls.append(a) or Result('submitted','fictional')))
    assert main(['ai','demo','--notify'])==0
    assert len(calls)==1 and '背景与通知均虚构' in calls[0][1]
    db=database(cfg)
    assert db.db.execute('SELECT source FROM notices').fetchone()[0]=='test'
    assert db.db.execute('SELECT status FROM deliveries').fetchone()[0]=='submitted'
    db.close()


def test_analysis_plugin_failure_still_sends_base_notification(cfg,notice,monkeypatch):
    configured(cfg,monkeypatch)
    db=database(cfg);db.upsert(notice,['desktop'])
    def broken(*a):raise RuntimeError('fictional broken analysis component')
    monkeypatch.setattr('core.smart.enrich',broken)
    calls=[]
    dispatch(cfg,db,lambda *a:(calls.append(a) or Result('submitted','fictional')))
    assert len(calls)==1 and notice.body in calls[0][2]
    db.close()


def test_digest_unknown_held_and_explicit_retry_reuses_batch(cfg,notice,monkeypatch):
    configured(cfg,monkeypatch)
    monkeypatch.setattr('core.cli.load_config',lambda:cfg)
    notice.title='虚构普通活动';notice.body='虚构安排。'
    db=database(cfg);db.upsert(notice,['desktop'])
    row=db.db.execute('SELECT * FROM notices').fetchone();analyze_row(db,row,Profile(),cfg['ai'])
    dispatch(cfg,db,lambda *a:Result('unknown','fictional'))
    assert not dispatch(cfg,db,lambda *a:pytest.fail('unknown must not resend'))
    db.close()
    assert main(['delivery','retry','1'])==0
    db=database(cfg);result=dispatch(cfg,db,lambda *a:Result('submitted','fictional'))
    assert len(result)==1 and result[0]['kind']=='digest'
    assert db.db.execute('SELECT count(*) FROM digest_batches').fetchone()[0]==1
    db.close()
