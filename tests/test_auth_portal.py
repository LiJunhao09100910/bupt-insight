from pathlib import Path
from urllib.parse import quote

import pytest
import requests

from core.errors import InsightError, safe_error
from core.http import SchoolHTTP, is_auth, school_url
from core.portal_auth import login_form, validate_service, PortalAuthenticator, follow_portal_landing
from sources.portal import parse_list, parse_body, verify_html, clean_link

FIXTURES = Path(__file__).parent / "fixtures"
CAS = "https://auth.bupt.edu.cn/authserver/login"
SERVICE = "http://my.bupt.edu.cn:80/system/resource/code/auth/clogin.jsp?owner=fixture"
LOGIN = CAS + "?service=" + quote(SERVICE, safe="")


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def response(url, status=200, html="", location=None):
    r = requests.Response()
    r.url, r.status_code, r._content, r.encoding = url, status, html.encode(), "utf-8"
    if location:
        r.headers["Location"] = location
    return r


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
        self.cookies = requests.cookies.RequestsCookieJar()
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_dynamic_form_fields():
    action, fields = login_form(fixture("cas_login.html"), LOGIN)
    assert action == LOGIN
    assert fields["execution"] == "fixture-dynamic-execution-only"
    assert fields["csrf"] == "fixture-csrf&value"
    assert "password" not in fields


@pytest.mark.parametrize("url", ["http://auth.bupt.edu.cn/authserver/login", "https://auth.bupt.edu.cn.evil.test/authserver/login", "https://user:pw@auth.bupt.edu.cn/authserver/login", "https://auth.bupt.edu.cn:8443/authserver/login"])
def test_password_destination_rejected(url):
    with pytest.raises(InsightError):
        login_form(fixture("cas_login.html"), url)


def test_form_action_injection_rejected():
    html = fixture("cas_login.html").replace('method="post"', 'method="post" action="https://evil.test"')
    with pytest.raises(InsightError, match="目标"):
        login_form(html, LOGIN)


def test_challenge_requires_human():
    html = fixture("cas_login.html") + '<input name="captcha">'
    with pytest.raises(InsightError) as exc:
        login_form(html, LOGIN)
    assert exc.value.status == "interaction_required"
    assert login_form(html, LOGIN, allow_manual=True)


def test_missing_execution_not_guessed():
    with pytest.raises(InsightError):
        login_form('<form><input name="password"></form>', LOGIN)


def test_no_ucloud_service_reuse():
    assert validate_service(LOGIN) == SERVICE
    with pytest.raises(InsightError):
        validate_service(CAS + "?service=https://ucloud.bupt.edu.cn")


def test_cookie_or_200_is_not_login(cfg):
    with pytest.raises(InsightError) as exc:
        verify_html('<div>HTTP 200 and fake cookie</div>', "http://my.bupt.edu.cn/", cfg["sources"]["portal"])
    assert exc.value.status == "structure_changed"
    with pytest.raises(InsightError) as exc:
        verify_html(fixture("cas_login.html"), LOGIN, cfg["sources"]["portal"])
    assert exc.value.status == "login_expired"


def test_authorized_content_and_notice_body(cfg, entry):
    verify_html(fixture("portal_list.html"), "http://my.bupt.edu.cn/notices", cfg["sources"]["portal"])
    items = parse_list(fixture("portal_list.html"), entry["url"], entry)
    assert len(items) == 2 and items[0].published == "2026-10-12"
    assert items[0].channel == "虚构科研处" and items[0].private
    assert items[0].key() != items[1].key()
    body = parse_body(fixture("portal_body.html"), "#content")
    assert "虚构测试正文" in body and "导航" not in body and "alert" not in body


def test_empty_distinguished_from_structure_changed(entry):
    assert parse_list('<p class="empty">暂无通知</p>', entry["url"], entry) == []
    with pytest.raises(InsightError) as exc:
        parse_list('<p>未知页面</p>', entry["url"], entry)
    assert exc.value.status == "structure_changed"


def test_partial_metadata_rejected(entry):
    html = fixture("portal_list.html").replace('class="origin"', 'class="changed"')
    with pytest.raises(InsightError):
        parse_list(html, entry["url"], entry)


def test_wrong_account_marker_rejected(cfg):
    with pytest.raises(InsightError) as exc:
        verify_html(fixture("portal_list.html"), "http://my.bupt.edu.cn/notices", cfg["sources"]["portal"], expected_account="another-fictional-user")
    assert exc.value.status == "wrong_account"


def test_sensitive_ticket_removed():
    assert clean_link("http://my.bupt.edu.cn/view?id=123&ticket=ST-fake&jsessionid=fixture") == "http://my.bupt.edu.cn/view?id=123"


def test_callback_consumes_ticket_without_forwarding_password():
    callback = SERVICE + "&ticket=ST-fixture-only"
    fake = FakeSession([response(LOGIN, 302, location=callback), response(callback, html="business")])
    SchoolHTTP(fake).request("POST", LOGIN, data={"password": "synthetic-only"}, callback_expected=SERVICE)
    assert fake.calls[1][0] == "GET" and "data" not in fake.calls[1][2]


@pytest.mark.parametrize("target", ["https://evil.test/callback?ticket=ST-fake", "http://my.bupt.edu.cn/other?ticket=ST-fake", SERVICE, SERVICE.replace("fixture", "wrong") + "&ticket=ST-fake"])
def test_wrong_or_missing_ticket_callback(target):
    fake = FakeSession([response(LOGIN, 302, location=target)])
    with pytest.raises(InsightError):
        SchoolHTTP(fake).request("POST", LOGIN, data={"password": "synthetic-only"}, callback_expected=SERVICE)
    assert len(fake.calls) == 1


def test_307_cannot_forward_password():
    fake = FakeSession([response(LOGIN, 307, location=SERVICE + "&ticket=ST-fake")])
    with pytest.raises(InsightError):
        SchoolHTTP(fake).request("POST", LOGIN, data={"password": "synthetic-only"})


def test_network_error_does_not_leak_password():
    fake = FakeSession([requests.ConnectionError("password=synthetic-secret&ticket=ST-secret")])
    with pytest.raises(InsightError) as exc:
        SchoolHTTP(fake).request("GET", "http://my.bupt.edu.cn")
    assert exc.value.status == "network_failed" and "synthetic" not in str(exc.value)
    assert "synthetic" not in safe_error(RuntimeError("synthetic-secret"))[1]


def test_full_mock_http_login(cfg, monkeypatch):
    fake = FakeSession([response("http://my.bupt.edu.cn", 302, location=LOGIN),
                        response(LOGIN, html=fixture("cas_login.html")),
                        response(LOGIN, 302, location=SERVICE + "&ticket=ST-fixture-only"),
                        response(SERVICE, html=fixture("portal_list.html"))])
    monkeypatch.setattr("core.portal_auth.requests.Session", lambda: fake)
    monkeypatch.setattr("core.portal_auth.read_state", lambda _: None)
    monkeypatch.setattr("core.portal_auth.credentials", lambda: {"account": "demo-only", "password": " synthetic-only "})
    saved = []
    monkeypatch.setattr("core.portal_auth.write_state", lambda path, value: saved.append(value))
    PortalAuthenticator(cfg).http_session()
    assert len(saved) == 1
    assert fake.calls[2][2]["data"]["execution"] == "fixture-dynamic-execution-only"
    assert fake.calls[2][2]["data"]["password"] == "synthetic-only"
    assert fake.calls[2][2]["headers"]["Origin"] == "https://auth.bupt.edu.cn"
    assert fake.calls[2][2]["headers"]["Referer"] == LOGIN
    assert all("password" not in c[2].get("data", {}) for c in (fake.calls[0], fake.calls[1], fake.calls[3]))


@pytest.mark.parametrize("html,status", [
    ('<div id="errorDiv"><p>Invalid credentials.</p></div>', "invalid_credentials"),
    ('<div id="errorDiv">验证码错误</div>', "interaction_required"),
    ('<div id="errorDiv">Account locked</div>', "account_restricted"),
    ('<div id="captchaParent" style="display:none">Validation Code</div>', "auth_failed")])
def test_auth_401_classification_without_guessing_or_leaking(html, status):
    fake = FakeSession([response(LOGIN, 401, html=html + '<input value="synthetic-private-value">')])
    with pytest.raises(InsightError) as exc:
        SchoolHTTP(fake).request("POST", LOGIN, data={"password": "synthetic-only"})
    assert exc.value.status == status
    assert "synthetic" not in str(exc.value)
    assert len(fake.calls) == 1


def test_observed_portal_landing_redirect_is_followed_without_evaluating_js():
    landing = response("http://my.bupt.edu.cn/index.jsp", html='<script>window.location.href="xs_index.jsp?urltype=tree.TreeTempUrl&amp;wbtreeid=1541"</script>')
    target = response("http://my.bupt.edu.cn/xs_index.jsp", html='<div>虚构受保护业务</div>')
    fake = FakeSession([target])
    assert follow_portal_landing(SchoolHTTP(fake), landing) is target
    assert len(fake.calls) == 1 and fake.calls[0][0] == "GET"


def test_landing_script_cannot_send_cookie_to_another_site():
    landing = response("http://my.bupt.edu.cn/index.jsp", html='<script>window.location.href="https://evil.test/"</script>')
    fake = FakeSession([])
    with pytest.raises(InsightError):
        follow_portal_landing(SchoolHTTP(fake), landing)
    assert not fake.calls


def test_arbitrary_script_is_never_evaluated():
    landing = response("http://my.bupt.edu.cn/index.jsp", html='<script>window.location.href=unknownFunction()</script>')
    fake = FakeSession([])
    assert follow_portal_landing(SchoolHTTP(fake), landing) is landing


def test_actual_portal_attachment_pattern_not_fabricated_body():
    from sources.portal import parse_notice_body
    html = '<div id="vsb_content"><div class="v_news_content"></div></div><a href="/system/_content/download.jsp?wbfileid=fixture">虚构附件.pdf</a>'
    body, status, attachments = parse_notice_body(html, "#vsb_content .v_news_content", "http://my.bupt.edu.cn/xntz_content.jsp")
    assert body == "" and status == "attachment_only"
    assert attachments[0]["name"] == "虚构附件.pdf"
    with pytest.raises(InsightError):
        parse_notice_body(html, "#changed-selector", "http://my.bupt.edu.cn/xntz_content.jsp")


def test_empty_body_without_attachment_still_fails():
    from sources.portal import parse_notice_body
    with pytest.raises(InsightError):
        parse_notice_body('<div id="content"></div>', "#content", "http://my.bupt.edu.cn/view")


def test_image_only_body_is_recorded_without_claiming_ocr():
    from sources.portal import parse_notice_body
    body,status,media = parse_notice_body('<div id="content"><img src="/__local/fixture.png"></div>', "#content", "http://my.bupt.edu.cn/view")
    assert body == "" and status == "image_only"
    assert media[0]["url"] == "http://my.bupt.edu.cn/__local/fixture.png"


def test_calibrated_bupt_layout_fixture_extracts_required_fields():
    html = fixture("portal_bupt_list.html")
    src = {"identity_selector": ".topinner", "business_selector": "#tzxw"}
    verify_html(html, "http://my.bupt.edu.cn/xs_index.jsp", src, expected_account="demo-only")
    entry = {"row_selector": "ul.newslist > li", "link_selector": 'a[href*="xntz_content.jsp"]', "date_selector": ".time", "source_selector": ".author"}
    items = parse_list(html, "http://my.bupt.edu.cn/list.jsp", entry)
    assert len(items) == 2
    assert items[1].title == "虚构最新通知" and items[1].published == "2026-10-14"
    assert items[1].channel == "虚构部门乙"
    assert "wbnewsid=900002" in items[1].url and items[1].private
