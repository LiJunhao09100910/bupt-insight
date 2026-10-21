import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.database import identity
from core.pipeline import database, database_path
from core.web import create_app
from core.reader import Reader
from core.locking import single_run
from core.config import resolve


@pytest.fixture
def web(cfg,notice,monkeypatch):
    from datetime import date
    monkeypatch.setattr('core.curation.today',lambda:date(2026,10,17))
    monkeypatch.setattr('core.security.get_secret',lambda _:None)
    cfg['push']['channels']={'desktop':{'enabled':True}}
    db=database(cfg);db.upsert(notice,['desktop']);db.close()
    app=create_app(lambda:cfg);app.testing=True
    client=app.test_client();home=client.get('/',base_url='http://127.0.0.1:8765')
    import re
    csrf=re.search(r'name="csrf-token" content="([^"]+)"',home.text).group(1)
    return cfg,notice,app,client,{'X-CSRF-Token':csrf}


def get(client,path):return client.get(path,base_url='http://127.0.0.1:8765')
def post(client,headers,notice,action,value):
    feed=get(client,'/api/feed?view=all').json
    row=next(i for i in feed['items'] if i['id']==identity(notice))
    return client.post('/api/state',base_url='http://127.0.0.1:8765',headers=headers,
                       json={'id':row['id'],'hash':row['hash'],'action':action,'value':value})


def test_feed_detail_search_topics_and_invalid_url(web):
    cfg,notice,app,c,h=web
    all=get(c,'/api/feed?view=all').json
    assert all['total']==1 and all['items'][0]['title']==notice.title
    assert get(c,'/api/feed?view=all&q=not-found').json['total']==0
    assert get(c,'/api/feed?view=all&source=byr').json['total']==0
    assert get(c,'/api/feed?view=all&category=competition').json['total']==1
    assert get(c,'/api/detail?id='+identity(notice)).json['body']==notice.body
    assert get(c,'/api/detail?id=missing').status_code==404


def test_read_and_favorite_survive_app_restart_and_update_returns_unread(web):
    cfg,notice,app,c,h=web
    assert post(c,h,notice,'read',True).status_code==200
    assert post(c,h,notice,'favorite',True).status_code==200
    restarted=create_app(lambda:cfg).test_client()
    row=get(restarted,'/api/feed?view=all').json['items'][0]
    assert row['favorite'] and not row['unread']
    db=database(cfg);notice.body+='虚构正文更新。';db.upsert(notice,['desktop']);db.close()
    row=get(restarted,'/api/feed?view=all').json['items'][0]
    assert row['unread'] and row['revision']==2 and row['favorite']


def test_host_csrf_cross_site_and_payload_validation(web):
    cfg,notice,app,c,h=web
    assert c.get('/api/feed',base_url='http://evil.test:8765').status_code==403
    assert c.get('/api/feed',base_url='http://127.0.0.1:8765',headers={'Origin':'https://evil.test'}).status_code==403
    assert c.get('/api/feed',base_url='http://127.0.0.1:8765',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert c.post('/api/state',base_url='http://127.0.0.1:8765',json={}).status_code==403
    assert post(c,h,notice,'favorite','false').status_code==400
    assert post(c,h,notice,'feedback','made-up').status_code==400
    headers=get(c,'/').headers
    assert headers['Cache-Control']=='no-store' and "frame-ancestors 'none'" in headers['Content-Security-Policy']


def test_ui_actions_during_scan_lock_are_durable_feedback_flushes_once(web):
    cfg,notice,app,c,h=web
    db=database(cfg);before=[tuple(r) for r in db.db.execute('SELECT * FROM deliveries')];db.close()
    with single_run(resolve(cfg,cfg['paths']['data_dir'])/'run.lock'):
        assert post(c,h,notice,'favorite',True).status_code==200
        assert post(c,h,notice,'hidden',True).status_code==200
        assert get(c,'/api/feed?view=hidden').json['total']==1
        assert get(c,'/api/status').json['feedback_pending']==1
        db=database(cfg);assert db.db.execute('SELECT count(*) FROM feedback').fetchone()[0]==0;db.close()
    get(c,'/api/status');get(c,'/api/status')
    db=database(cfg)
    assert db.db.execute('SELECT count(*) FROM feedback').fetchone()[0]==1
    assert [tuple(r) for r in db.db.execute('SELECT * FROM deliveries')]==before
    assert db.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok';db.close()
    assert post(c,h,notice,'hidden',False).status_code==200
    assert get(c,'/api/feed?view=hidden').json['total']==0


def test_mandatory_hidden_is_reversible_and_stays_recommended(web):
    cfg,notice,app,c,h=web
    notice.title='虚构学籍考试通知';notice.body='必须办理学籍注册。'
    db=database(cfg);db.upsert(notice);db.close()
    post(c,h,notice,'hidden',True)
    assert get(c,'/api/feed?view=recommended').json['total']==1
    assert not get(c,'/api/feed?view=all').json['items'][0]['hidden']


def test_updated_content_rejects_stale_actions_and_no_new_keeps_timestamp(web):
    cfg,notice,app,c,h=web
    old=get(c,'/api/feed?view=all').json['items'][0]
    db=database(cfg)
    with db.db:db.db.execute("UPDATE notices SET updated_at='2020-01-01T00:00:00+00:00'")
    stamp=db.db.execute('SELECT updated_at FROM notices').fetchone()[0]
    db.upsert(notice)
    assert db.db.execute('SELECT updated_at FROM notices').fetchone()[0]==stamp
    notice.body+='虚构变化';db.upsert(notice);db.close()
    r=c.post('/api/state',base_url='http://127.0.0.1:8765',headers=h,json={'id':old['id'],'hash':old['hash'],'action':'read','value':True})
    assert r.status_code==409


def test_concurrent_reader_and_source_writes_are_consistent(web):
    cfg,notice,app,c,h=web
    def reader_task():
        client=app.test_client()
        for _ in range(12):
            assert get(client,'/api/feed?view=all').status_code==200
    def writer_task():
        db=database(cfg)
        for i in range(8):notice.body='虚构并发更新'+str(i);db.upsert(notice,['desktop'])
        db.close()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(reader_task),pool.submit(reader_task),pool.submit(writer_task)]
        for f in futures:f.result()
    db=database(cfg);assert db.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert db.db.execute('SELECT count(*) FROM notices').fetchone()[0]==1;db.close()


def test_incomplete_and_new_source_items_visible_with_failure_status(web):
    cfg,notice,app,c,h=web
    notice.extra['body_status']='image_only';notice.body='图片文字尚未识别。'
    db=database(cfg);db.upsert(notice)
    run=db.start_run('portal');db.finish_run(run,'login_expired',errors=['虚构失效'])
    db.close()
    assert get(c,'/api/feed?view=all').json['items'][0]['body_status']=='image_only'
    assert get(c,'/api/status').json['sources']['portal']['status']=='login_expired'


def test_account_scopes_cannot_read_other_reader_state(cfg,notice,monkeypatch):
    scope={'value':'a'*32}
    monkeypatch.setattr('core.security.get_secret',lambda _:json.dumps({'scope':scope['value']}))
    db=database(cfg);db.upsert(notice);db.close()
    p=database_path(cfg);r=Reader(p.parent/'reader.sqlite3')
    from core.profile import Profile
    r.mutate({'id':identity(notice),'hash':'fake'},'favorite',True,Profile())
    scope['value']='b'*32
    db=database(cfg);db.upsert(notice);db.close()
    app=create_app(lambda:cfg).test_client()
    assert not get(app,'/api/feed?view=all').json['items'][0]['favorite']


def test_job_must_requirements_are_not_presented_as_academic_notice(web):
    cfg,notice,app,c,h=web
    notice.source='byr';notice.url='https://bbs.byr.cn/article/ParttimeJob/123';notice.title='虚构实习招聘';notice.body='必须掌握Python。'
    db=database(cfg);db.upsert(notice);db.close()
    rows=get(c,'/api/feed?view=all&source=byr').json['items']
    assert rows[0]['category']=='internship' and rows[0]['importance']=='normal'


def test_old_historical_priority_does_not_bury_current_opportunities(web):
    cfg,notice,app,c,h=web
    notice.source='byr';notice.url='https://bbs.byr.cn/article/Paper/1';notice.title='虚构科研招募';notice.body='科研机会';notice.published='2007-03-22'
    db=database(cfg);db.upsert(notice);db.close()
    row=next(i for i in get(c,'/api/feed?view=all').json['items'] if i['id']==identity(notice))
    assert row['historical']


def test_research_view_uses_publication_date_evidence_and_keeps_read_items(web):
    import copy

    cfg, notice, app, client, headers = web
    db = database(cfg)
    examples = [
        ('new', '2026-10-16', '虚构科研合作招募', '面向本科生，在研项目需要补实验，根据贡献协商二作。'),
        ('older', '2026-09-01', '虚构实验室科研招募', '欢迎本科生报名，导师指导科研。'),
        ('graduate', '2026-10-16', '虚构科研实习招募', '仅限硕士研究生申请。'),
        ('closed', '2026-10-16', '虚构科研合作招募', '欢迎本科生报名，现已招满。'),
        ('expired', '2026-09-01', '虚构科研合作招募', '欢迎本科生报名，截止9月22日晚上。'),
        ('old', '2026-01-01', '虚构科研合作招募', '欢迎本科生报名。'),
        ('unknown', '', '虚构科研合作招募', '欢迎本科生报名。'),
    ]
    for identifier, published, title, body in examples:
        item = copy.deepcopy(notice)
        item.source = 'byr'
        item.url = f'https://bbs.byr.cn/article/Paper/{identifier}'
        item.title, item.body, item.published = title, body, published
        db.upsert(item)
    db.close()
    feed = get(client, '/api/feed?view=research').json
    assert feed['total'] == 2
    assert [row['published'] for row in feed['items']] == ['2026-10-16', '2026-09-01']
    first = feed['items'][0]
    assert first['research']['undergraduate'] and first['research']['ongoing'] and first['research']['authorship']
    assert client.post('/api/state', base_url='http://127.0.0.1:8765', headers=headers,
                       json={'id': first['id'], 'hash': first['hash'], 'action': 'read', 'value': True}).status_code == 200
    assert get(client, '/api/feed?view=research').json['total'] == 2
    assert get(client, '/api/feed?view=all').json['total'] == 8


def test_newly_collected_item_is_visible_without_restarting_web(web):
    import copy
    cfg,notice,app,c,h=web
    first=get(c,'/api/feed?view=all').json
    new=copy.deepcopy(notice);new.url='http://my.bupt.edu.cn/view?id=second';new.title='虚构新增科研报名'
    db=database(cfg);db.upsert(new,['desktop']);db.close()
    second=get(c,'/api/feed?view=all').json
    assert second['total']==first['total']+1 and second['version']!=first['version']
    assert any(i['title']==new.title and i['unread'] for i in second['items'])


def test_daily_picks_are_short_read_items_leave_and_history_is_untouched(web,monkeypatch):
    import copy
    from datetime import date
    from core.profile import Profile, Interest
    cfg,notice,app,c,h=web
    monkeypatch.setattr('core.curation.today',lambda:date(2026,10,17))
    monkeypatch.setattr('core.web.load_profile',lambda _:Profile(interests=[Interest(name='科研与实习',terms=['科研','实习'])]))
    db=database(cfg)
    for i in range(12):
        n=copy.deepcopy(notice);n.url=f'https://bbs.byr.cn/article/ParttimeJob/{i}'
        n.source='byr';n.title=f'虚构实习招聘{i}';n.body='岗位要求：必须具备科研经验。'
        n.published='2026-10-17';db.upsert(n)
    n=copy.deepcopy(notice);n.url='http://my.bupt.edu.cn/view?id=staff'
    n.title='虚构夫妻两地分居事务';n.body='科研人员申请条件。';db.upsert(n)
    before=[tuple(r) for r in db.db.execute('SELECT * FROM notices ORDER BY id')]
    deliveries=[tuple(r) for r in db.db.execute('SELECT * FROM deliveries')];db.close()
    feed=get(c,'/api/feed?view=recommended').json
    assert feed['total']==3 and feed['eligible_total']==12
    picked=feed['items'][0]
    r=c.post('/api/state',base_url='http://127.0.0.1:8765',headers=h,
             json={'id':picked['id'],'hash':picked['hash'],'action':'read','value':True})
    assert r.status_code==200
    assert picked['id'] not in [i['id'] for i in get(c,'/api/feed?view=recommended').json['items']]
    assert get(c,'/api/feed?view=all').json['total']==14
    staff=get(c,'/api/feed?view=all&q=夫妻').json['items'][0]
    assert staff['category']=='administration' and not any('方向及机会意图匹配' in r['text'] for r in staff['reasons'])
    db=database(cfg)
    assert [tuple(r) for r in db.db.execute('SELECT * FROM notices ORDER BY id')]==before
    assert [tuple(r) for r in db.db.execute('SELECT * FROM deliveries')]==deliveries
    db.close()
