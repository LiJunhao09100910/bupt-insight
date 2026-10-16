"""Constrained requests for the actual school redirect chain."""
from urllib.parse import urlsplit, urljoin

import requests

from core.errors import InsightError

AUTH_HOST = "auth.bupt.edu.cn"
PORTAL_HOST = "my.bupt.edu.cn"


def authentication_rejection(response):
    """Classify only explicit official errors, never echo HTML or user values."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(response.content, "html.parser")
    error = soup.select_one("#errorDiv, .alert-danger")
    message = error.get_text(" ", strip=True).lower() if error else ""
    if any(term in message for term in ("invalid credentials", "用户名或者密码", "用户名或密码", "密码错误")):
        return InsightError("invalid_credentials", "官方认证明确提示账号或密码不正确；请在官方页面核对统一认证凭据，程序不自动重试")
    if any(term in message for term in ("captcha", "验证码", "mfa", "动态口令", "二次认证")) or soup.select_one('input[name="captcha"], input[name="otp"]'):
        return InsightError("interaction_required", "官方认证要求验证码或其他人工验证，请使用官方交互入口")
    if any(term in message for term in ("locked", "锁定", "频繁", "too many")):
        return InsightError("account_restricted", "官方认证提示账号受限或请求频繁，请按官方提示处理，程序不自动重试")
    return InsightError("auth_failed", f"官方统一认证未接受本次登录（HTTP {response.status_code}）；尚不能确定原因，需核对官方提示")


def is_auth(url):
    p = urlsplit(url)
    return (p.scheme == "https" and p.hostname == AUTH_HOST and p.port in (None, 443)
            and not p.username and not p.password and p.path == "/authserver/login")


def school_url(url):
    p = urlsplit(url)
    allowed = (p.hostname == AUTH_HOST and p.scheme == "https" and p.port in (None, 443)) or (
        p.hostname == PORTAL_HOST and p.scheme in ("http", "https") and p.port in (None, 80, 443))
    if not allowed or p.username or p.password:
        raise InsightError("unsafe_redirect", "拒绝跳转到未经核验的认证或业务地址")
    return url


class SchoolHTTP:
    def __init__(self, session=None, timeout=20):
        self.session = session or requests.Session()
        self.timeout = timeout

    def request(self, method, url, **kwargs):
        callback_expected = kwargs.pop("callback_expected", None)
        for _ in range(10):
            school_url(url)
            try:
                response = self.session.request(method, url, allow_redirects=False,
                                                timeout=self.timeout, **kwargs)
            except requests.RequestException:
                raise InsightError("network_failed", "学校系统连接失败；请检查校园网/VPN、DNS和证书") from None
            if response.status_code in (301, 302, 303, 307, 308):
                target = school_url(urljoin(url, response.headers.get("Location", "")))
                if callback_expected and method.upper() == "POST":
                    from urllib.parse import parse_qs
                    actual, expected = urlsplit(target), urlsplit(callback_expected)
                    ticket = parse_qs(actual.query).get("ticket", [""])[0]
                    def origin_port(p):
                        return p.port or (443 if p.scheme == "https" else 80)
                    if ((actual.scheme, actual.hostname, origin_port(actual), actual.path) !=
                        (expected.scheme, expected.hostname, origin_port(expected), expected.path)
                        or not ticket.startswith("ST-")):
                        raise InsightError("wrong_service", "CAS 回调缺少有效 ST 或目标与门户 service 不符")
                    expected_query = parse_qs(expected.query)
                    actual_query = parse_qs(actual.query)
                    if any(actual_query.get(k) != v for k, v in expected_query.items()):
                        raise InsightError("wrong_service", "CAS 回调业务参数与门户 service 不符")
                    callback_expected = None
                if response.status_code in (307, 308) and method.upper() != "GET":
                    raise InsightError("unsafe_redirect", "拒绝自动转发包含凭据的 POST 请求")
                method, url, kwargs = "GET", target, {}
                continue
            if response.status_code in (401, 403):
                if response.status_code == 401 and method.upper() == "POST" and is_auth(url):
                    raise authentication_rejection(response)
                raise InsightError("login_expired" if response.status_code == 401 else "access_denied",
                                   "学校系统要求重新认证或拒绝当前权限")
            if response.status_code >= 400:
                raise InsightError("network_failed", f"学校系统 HTTP {response.status_code}")
            if len(response.content) > 8_000_000:
                raise InsightError("structure_changed", "页面超出大小限制")
            if response.encoding is None or response.encoding.lower() in ("iso-8859-1", "ascii"):
                from bs4 import BeautifulSoup
                response.encoding = BeautifulSoup(response.content, "html.parser").original_encoding or "utf-8"
            return response
        raise InsightError("redirect_loop", "学校系统跳转次数超限")
