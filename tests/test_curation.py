"""Fictional counterexamples, never real portal bodies."""
from datetime import date

import pytest

from core.curation import assess, eligible, shortlist
from core.profile import Profile, Interest


@pytest.fixture
def profile():
    return Profile(stage='本科', grade='大二', interests=[
        Interest(name='本科科研', terms=['科研'], intents=['招募', '申请']),
        Interest(name='实习', terms=['实习']),
        Interest(name='竞赛', terms=['竞赛']),
        Interest(name='校园活动', terms=['活动']),
    ])


@pytest.mark.parametrize('title,body,category,relevance', [
    ('虚构夫妻两地分居办理通知', '面向学校事业编制人员，科研人员可申请。', 'administration', 'low'),
    ('虚构职称评审', '科研项目申请、竞赛获奖可作为材料。', 'administration', 'low'),
    ('虚构科研项目本科生招募', '欢迎本科生报名。', 'research', 'high'),
    ('虚构Python实习招聘', '必须了解科研和竞赛。', 'internship', 'high'),
    ('虚构校园活动报名', '欢迎在校生参加。', 'event', 'high'),
    ('虚构数学建模竞赛', '报名资格请核对。', 'competition', 'high'),
    ('虚构财务报销说明', '科研项目经费申请要求。', 'general', 'unknown'),
    ('虚构科研交流活动圆满结束', '同学们参加了科研招募讲解。', 'research', 'medium'),
    ('虚构通知', '岗位条件、科研和竞赛等材料均需提交。', 'general', 'unknown'),
    ('虚构研究助理招聘', '仅限博士研究生申请。', 'internship', 'low'),
])
def test_subject_and_audience_override_incidental_keywords(profile, title, body, category, relevance):
    item = dict(title=title, body=body, source='portal')
    c, protected, r, reasons = assess(item, profile, {'reasons': []})
    assert (c, r) == (category, relevance)
    assert not protected
    for reason in reasons:
        assert reason['evidence'] in title + '\n' + body


def test_exam_protected_but_job_requirements_are_not(profile):
    c, protected, _, _ = assess(dict(title='虚构学籍核对考试通知', body='科研同学也要办理。', source='portal'), profile, {})
    assert c == 'mandatory_academic' and protected
    assert not assess(dict(title='虚构实习招聘', body='必须有考试经验。', source='byr'), profile, {})[1]


def candidate(**kw):
    return dict(hidden=False, unread=True, historical=False, published='2026-10-17',
                importance='normal', category='internship', relevance='high', feedback=None,
                deadline={'value': None}, **kw)


@pytest.mark.parametrize('change', [
    {'unread':False}, {'hidden':True}, {'historical':True}, {'published':'2007-03-22'},
    {'published':''}, {'published':'2027-01-01'}, {'deadline':{'value':'2026-10-16'}},
    {'category':'administration'}, {'relevance':'medium'},
])
def test_old_read_expired_or_uncertain_is_not_daily_pick(change):
    item=candidate(); item.update(change)
    assert not eligible(item, date(2026,10,17))


def test_important_academic_not_lost_in_topic_cap():
    ordinary=[candidate() for _ in range(20)]
    academic=candidate();academic.update(importance='high',category='mandatory_academic',relevance='unknown')
    result=shortlist(ordinary+[academic])
    assert result[0] is academic and len(result)==4
    assert eligible(academic,date(2026,10,17))
    mixed=[]
    for category in ('internship','competition','research','event'):
        for _ in range(4):
            item=candidate();item['category']=category;mixed.append(item)
    assert len(shortlist(mixed))==8


def test_empty_profile_does_not_invent_personal_interest():
    assert assess(dict(title='虚构科研招募',body='报名',source='portal'),Profile(),{})[2]=='unknown'
