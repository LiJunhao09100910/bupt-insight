import csv
import json
from datetime import date

import pytest

from core.database import Database,identity
from core.profile import Profile,Interest,Preferences
from core.personalization import decide,occurrence
from core.analysis import rules
from core.smart import route,feedback_route,enrich
from core.feedback import record,latest
from core import evaluation
from core.errors import InsightError


def profile():
    return Profile(stage='本科',interests=[Interest(name='本科科研',terms=['科研','实验室','research assistant'],intents=['招募','申请','开放']),
        Interest(name='实习',terms=['实习','internship'])],preferences=Preferences(relevant='digest'))


def test_intent_alias_and_case_with_provenance():
    p=profile()
    item={'title':'虚构LAB Research Assistant招募','body':'实验室开放招募，具体条件待定。'}
    d=decide(item,p)
    assert d.relevance=='high'
    assert d.reasons[0]['evidence'] in item['title']+'\n'+item['body']
    value=rules(item,p)
    assert value.reasons[0].basis=='inferred' and value.eligibility_match=='unknown'
    assert route(item,value,'ok',p,date(2026,10,16))=='digest'


def test_direction_only_discussion_is_not_claimed_to_be_opportunity():
    item={'title':'虚构科研讨论','body':'科研方向有什么建议？'}
    assert decide(item,profile()).relevance=='medium'


def test_ascii_substring_false_match_and_negative_conflict():
    assert occurrence('email paid rain','AI') is None
    assert occurrence('AI agent','ai')
    p=profile();p.uninterested=['实习']
    assert decide({'title':'虚构实习','body':'欢迎报名'},p).relevance=='medium'


def test_empty_profile_and_no_match_are_unknown():
    assert decide({'title':'虚构通知','body':'未知内容'},Profile()).relevance=='unknown'


def test_explicit_feedback_bound_to_content_and_profile_without_deliveries(tmp_path,notice):
    db=Database(tmp_path/'db.sqlite3');db.upsert(notice,['desktop'])
    row=db.db.execute('SELECT * FROM notices').fetchone();p=profile()
    before=[tuple(r) for r in db.db.execute('SELECT * FROM deliveries')]
    record(db,row,p,'irrelevant')
    assert latest(db,row,p)['label']=='irrelevant'
    assert latest(db,row,Profile()) is None
    notice.body+='虚构修改';db.upsert(notice,['desktop'])
    changed=db.db.execute('SELECT * FROM notices').fetchone()
    assert latest(db,changed,p) is None
    assert tuple(db.db.execute('SELECT * FROM deliveries WHERE id=1').fetchone())==before[0]
    db.close()


def test_feedback_never_hides_mandatory_urgent_or_failed_analysis():
    p=profile();item={'title':'虚构普通信息','body':'说明内容。'};a=rules(item,p)
    assert feedback_route(item,a,'ok',p,{'label':'irrelevant'})=='archive'
    assert feedback_route(item,a,'fallback',p,{'label':'irrelevant'})!='archive'
    mandatory={'title':'虚构学籍注册','body':'必须办理。'}
    assert feedback_route(mandatory,rules(mandatory,p),'ok',p,{'label':'irrelevant'})=='immediate'
    urgent={'title':'虚构报名','body':'报名截止2026年10月17日。'}
    assert feedback_route(urgent,rules(urgent,p),'ok',p,{'label':'irrelevant'},date(2026,10,16))=='immediate'


def test_freeze_deterministic_scope_and_no_delivery_mutation(cfg,tmp_path,notice,monkeypatch):
    monkeypatch.setattr('core.security.get_secret',lambda _:None)
    db=Database(tmp_path/'db.sqlite3');db.upsert(notice,['desktop'])
    before=[tuple(r) for r in db.db.execute('SELECT * FROM deliveries')]
    batch=evaluation.freeze(cfg,db,profile())
    dest,data=evaluation.read(cfg,batch['batch'])
    assert len(data['samples'])==1 and data['profile_hash']==profile().fingerprint()
    report=evaluation.evaluate(cfg,batch['batch'])
    assert report['labels_n']==0
    assert report['methods']['interest']['test_metrics']['important_recall'] is None
    assert report['methods']['api']['actual_model_successes']==0
    evaluation.label(cfg,batch['batch'],'n001','irrelevant')
    report=evaluation.evaluate(cfg,batch['batch'])
    assert report['labels_n']==1
    assert [tuple(r) for r in db.db.execute('SELECT * FROM deliveries')]==before
    assert db.db.execute('SELECT count(*) FROM feedback').fetchone()[0]==0
    assert not list(dest.glob('*.tmp'))
    db.close()


def test_frozen_data_tamper_and_other_account_path_rejected(cfg,tmp_path,notice,monkeypatch):
    monkeypatch.setattr('core.security.get_secret',lambda _:None)
    db=Database(tmp_path/'db.sqlite3');db.upsert(notice)
    batch=evaluation.freeze(cfg,db,profile())
    dest=evaluation.folder(cfg,batch['batch'])
    raw=(dest/'dataset.json').read_bytes();(dest/'dataset.json').write_bytes(raw+b' ')
    with pytest.raises(InsightError):evaluation.read(cfg,batch['batch'])
    with pytest.raises(InsightError):evaluation.folder(cfg,'../../other')
    db.close()


def test_metrics_null_for_no_positive_and_reports_no_fake_recall():
    pred=[{'sample':'a','status':'ok','relevance':'unknown','route':'digest','evidence':[]}]
    assert evaluation.metrics(pred,{'a':{'label':'irrelevant'}})['important_recall'] is None
    assert evaluation.metrics(pred,{'a':{'label':'irrelevant'}})['irrelevant_reminder_ratio']==1
    assert evaluation.metrics(pred,{'a':{'label':'important'}})['important_recall']==1
    assert evaluation.metrics(pred,{'a':{'label':'unsure'}})['labeled_evaluable']==0


def test_no_api_if_not_configured_and_private_not_sent(cfg,tmp_path,notice,monkeypatch):
    monkeypatch.setattr('core.security.get_secret',lambda _:None)
    db=Database(tmp_path/'db.sqlite3');db.upsert(notice)
    batch=evaluation.freeze(cfg,db,profile())
    cfg['ai']={'base_url':'','model':''}
    assert evaluation.evaluate(cfg,batch['batch'],'api')['methods']['api']['status']=='not_configured'
    cfg['ai']={'base_url':'https://example.test/v1','model':'fake','allow_private_cloud':False}
    def forbidden(*a):pytest.fail('must not send private portal')
    report=evaluation.evaluate(cfg,batch['batch'],'api',forbidden)
    assert report['methods']['api']['prediction_counts']=={'fallback_not_ai':1}
    assert report['methods']['api']['test_metrics']['labeled_evaluable']==0
    db.close()


def test_explanation_ratings_bound_to_method_and_explanation(cfg,tmp_path,notice,monkeypatch):
    monkeypatch.setattr('core.security.get_secret',lambda _:None)
    db=Database(tmp_path/'db.sqlite3');db.upsert(notice)
    batch=evaluation.freeze(cfg,db,profile())
    evaluation.evaluate(cfg,batch['batch'])
    evaluation.rate(cfg,batch['batch'],'n001','interest',4)
    report=evaluation.evaluate(cfg,batch['batch'])
    assert report['methods']['interest']['test_metrics']['explanation_human_mean']==4
    assert report['methods']['legacy']['test_metrics']['explanation_human_mean'] is None
    with pytest.raises(InsightError):evaluation.rate(cfg,batch['batch'],'n001','api',5)
    with pytest.raises(InsightError):evaluation.rate(cfg,batch['batch'],'n001','interest',6)
    evaluation.rate(cfg,batch['batch'],'n001','legacy',0)
    assert evaluation.evaluate(cfg,batch['batch'])['methods']['legacy']['test_metrics']['explanation_human_mean']==0
    db.close()


def test_review_markdown_cannot_load_untrusted_images(cfg,tmp_path,notice,monkeypatch):
    monkeypatch.setattr('core.security.get_secret',lambda _:None)
    notice.body='![remote](https://example.test/private)\n<img src="https://example.test/track">'
    db=Database(tmp_path/'db.sqlite3');db.upsert(notice)
    batch=evaluation.freeze(cfg,db,profile())
    review=(evaluation.folder(cfg,batch['batch'])/'review.md').read_text(encoding='utf-8')
    assert '\n\n    ![remote]' in review and '\n    <img' in review
    db.close()


def test_feedback_cli_and_recommend_preview_do_not_send_or_rewrite_receipts(cfg,notice,monkeypatch,capsys):
    from core.cli import main
    from core.pipeline import database
    monkeypatch.setattr('core.security.get_secret',lambda _:None)
    monkeypatch.setattr('core.cli.load_config',lambda:cfg)
    monkeypatch.setattr('core.notifications.desktop',lambda *a:pytest.fail('preview cannot send'))
    db=database(cfg);db.upsert(notice,['desktop']);key=identity(notice);db.close()
    assert main(['feedback','add','--id',key,'--label','irrelevant'])==0
    assert main(['recommend','--id',key])==0
    db=database(cfg)
    assert db.db.execute('SELECT status FROM deliveries').fetchone()[0]=='pending'
    assert db.db.execute('SELECT count(*) FROM feedback').fetchone()[0]==1
    db.close()
