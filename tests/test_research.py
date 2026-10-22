from datetime import date

import pytest

from core.curation import assess
from core.profile import Interest, Profile
from core.research import opportunity


CURRENT = date(2026, 10, 21)


def article(title='虚构科研合作招募', body='', published='2026-10-08'):
    return dict(source='byr', title=title, body=body, published=published)


def test_ongoing_and_authorship_require_separate_literal_evidence():
    item = article(body='欢迎本科生参与。项目已有初稿，尚未投稿，需要补实验。根据贡献协商二作、三作。')
    result = opportunity(item, CURRENT)
    assert result['candidate'] and result['eligibility'] == 'explicit'
    assert result['priority'] == 4
    for field in ('undergraduate', 'ongoing', 'authorship', 'recruitment'):
        assert result[field] and result[field] in item['title'] + '\n' + item['body']


def test_publication_goal_and_prior_author_experience_do_not_promise_authorship():
    result = opportunity(article(body='面向本校大二，大三学生招募科研实习生，参与顶会论文的发表。以主要作者身份发表过论文者优先。'), CURRENT)
    assert result['candidate'] and result['undergraduate']
    assert not result['ongoing'] and not result['authorship']


@pytest.mark.parametrize('title,body', [
    ('虚构科研助理招募', '仅限硕士研究生申请。'),
    ('虚构实验室博士生招聘', '招收博士研究生。'),
    ('虚构科研实习招聘', '学历要求：硕士、博士（在读）均可投递。'),
    ('虚构研究院实习招聘', '任职资格：计算机相关专业，硕士研究生及以上。'),
    ('虚构科研实习招聘', '学历要求：计算机相关专业在读硕士或博士研究生。'),
    ('虚构科研本科生招募', '目前不接受本科生。'),
    ('虚构科研合作招募', '欢迎本科生，现已招满。'),
    ('虚构求导师指导本科生论文', '希望有科研老师提供指导，寻求合作。'),
    ('虚构财务报销通知', '科研人员可以申请报销。'),
    ('虚构实习招聘', '工作要求有科研和竞赛经历。'),
    ('虚构校招软件工程师招聘', '还没投递简历的可以联系，最好和本身的研究方向匹配。'),
])
def test_ineligible_closed_seeking_and_incidental_research_are_excluded(title, body):
    assert not opportunity(article(title, body), CURRENT)['candidate']


def test_mixed_degrees_are_supported_without_inventing_eligibility():
    assert opportunity(article(body='招收本科生、硕士研究生和博士研究生。'), CURRENT)['candidate']
    result = opportunity(article(body='欢迎对科研感兴趣的同学，至少投入6个月。'), CURRENT)
    assert result['candidate'] and result['eligibility'] == 'unknown'
    assert not result['undergraduate']
    assert opportunity(article(body='相关专业，本科高年级或硕博研究生。'), CURRENT)['undergraduate']


def test_resume_submission_is_not_paper_submission():
    result = opportunity(article(body='面向本科生科研招募，还没投递简历的同学欢迎联系。'), CURRENT)
    assert result['candidate'] and not result['ongoing']


def test_existing_framework_is_ongoing_evidence_but_does_not_prove_unsubmitted():
    body = '目前数据、任务定义和论文框架已经具备，希望招募同学共同完成实验与论文。可以立即开始，未来两周能够集中投入。'
    result = opportunity(article(body=body), CURRENT)
    assert result['candidate'] and result['ongoing'] in body
    assert result['time_commitment'] in body
    assert '未投稿' not in result['ongoing']
    assert not result['authorship']


def test_research_team_and_body_recruitment_with_a_generic_title():
    assert opportunity(article('虚构大学研究团队招收本科实习生', '欢迎本科生，参与科研工作。'), CURRENT)['candidate']
    assert opportunity(article('虚构校内机器人实习', '某教授团队面向校内招募同学，参与科研和实验室项目。'), CURRENT)['candidate']


def test_first_author_benefit_is_extracted_without_using_prior_achievements():
    result = opportunity(article(body='面向本科生招聘。\n加入你将获得\no 一作发表一篇相关论文\no 实习证明'), CURRENT)
    assert result['authorship'] and '一作发表一篇' in result['authorship']
    previous = opportunity(article(body='欢迎本科生，导师曾以第一作者发表论文。'), CURRENT)
    assert not previous['authorship']


def test_month_day_deadline_uses_publication_year_and_unknown_is_retained():
    expired = opportunity(article(body='面向本科生，简历投递截止时间为9月22日晚上。', published='2026-09-17'), CURRENT)
    assert not expired['candidate'] and expired['deadline'] == '2026-09-22'
    assert expired['deadline_inferred'] and expired['deadline_evidence'] in '简历投递截止时间为9月22日晚上。'
    assert opportunity(article(body='欢迎本科生申请。'), CURRENT)['candidate']
    ambiguous = opportunity(article(body='科研招募第一批截止9月22日，第二批截止11月22日。'), CURRENT)
    assert ambiguous['candidate'] and not ambiguous['deadline']


def test_highlighted_replies_cannot_supply_authorship_or_close_recruitment():
    result = opportunity(article(body='面向本科生科研招募。\n精彩回复\n已经招满，可以给二作。'), CURRENT)
    assert result['candidate'] and not result['authorship']


def test_research_intern_is_classified_as_research_before_general_internships():
    item = article('虚构科研实习生招募', '面向本科生科研实习，导师指导参与论文。')
    profile = Profile(stage='本科', interests=[Interest(name='本科科研', terms=['科研'])])
    category, protected, relevance, reasons = assess(item, profile, {})
    assert category == 'research' and not protected and relevance == 'high'
    assert '具体招募条件与申请方式请查看详情' in reasons[0]['text']
