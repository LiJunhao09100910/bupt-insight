"""Portal-specific CAS + browser fallback; never exchanges a UCloud token."""
import time
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit, parse_qs

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from core.browser import launch
from core.errors import InsightError
from core.http import SchoolHTTP, is_auth, school_url, PORTAL_HOST, authentication_rejection
from core.security import credentials, read_state, write_state
from core.config import resolve


def follow_portal_landing(client, response):
    """Follow the portal's observed literal landing redirect; never evaluate scripts."""
    for _ in range(5):
        if urlsplit(response.url).hostname != PORTAL_HOST:
            return response
        soup = BeautifulSoup(response.content, "html.parser")
        target = None
        for script in soup.select("script:not([src])"):
            match = re.fullmatch(r'''\s*window\.location\.href\s*=\s*["']([^"']+)["']\s*;?\s*''', script.get_text())
            if match:
                target = school_url(urljoin(response.url, match.group(1)))
                if urlsplit(target).hostname != PORTAL_HOST:
                    raise InsightError("unsafe_redirect", "门户落地脚本试图跳转到其他系统，未跟随")
                break
        if not target:
            return response
        response = client.request("GET", target)
    raise InsightError("redirect_loop", "门户落地脚本跳转次数超限")


def browser_login_controls(page):
    """Official page can render its visible login controls inside a same-origin iframe."""
    for _ in range(8):
        for frame in page.frames:
            p = urlsplit(frame.url)
            if p.scheme != "https" or p.hostname != "auth.bupt.edu.cn" or p.port not in (None, 443):
                continue
            tab = frame.get_by_text("密码登录", exact=True)
            if tab.count() and tab.first.is_visible():
                tab.first.click()
            for user_selector, password_selector, submit_selector in (
                    ('input[name="username"]', 'input[name="password"]', 'input[type="submit"]'),
                    ('#username', '#password', 'input[onclick="loginPassword()"]')):
                user, password, submit = (frame.locator(s).first for s in
                                          (user_selector, password_selector, submit_selector))
                if user.count() and password.count() and submit.count() and user.is_visible() and password.is_visible():
                    return user, password, submit
        page.wait_for_timeout(500)
    raise InsightError("browser_page_unavailable", "官方登录 iframe 未呈现可操作表单；请检查学校页面/网络策略，或尝试 --mode http。未伪装浏览器或绕过校方检查")


def login_form(html, url, allow_manual=False):
    if not is_auth(url):
        raise InsightError("unsafe_auth", "密码仅允许提交至已核验的 HTTPS 统一认证登录页")
    soup = BeautifulSoup(html, "html.parser")
    password = soup.select_one('input[name="password"]')
    form = password.find_parent("form") if password else None
    if form is None:
        raise InsightError("structure_changed", "未定位账号密码认证表单")
    if not allow_manual and (soup.select('input[name*="captcha"], input[name*="otp"]') or "captchaId" in html):
        raise InsightError("interaction_required", "官方认证要求验证码/MFA，请使用浏览器模式人工完成")
    action = urljoin(url, form.get("action") or url)
    if not is_auth(action):
        raise InsightError("unsafe_auth", "认证表单目标发生变化，未提交密码")
    fields = {i["name"]: i.get("value", "") for i in form.select("input[name]")
              if i.get("name") not in ("username", "password")}
    if not fields.get("execution"):
        raise InsightError("structure_changed", "认证页面缺少动态 execution 参数")
    return action, fields


def validate_service(auth_url):
    service = parse_qs(urlsplit(auth_url).query).get("service", [""])[0]
    school_url(service)
    if urlsplit(service).hostname != PORTAL_HOST:
        raise InsightError("wrong_service", "CAS service 不是信息门户，拒绝混用业务认证")
    return service


class PortalAuthenticator:
    def __init__(self, cfg):
        self.cfg = cfg
        self.src = cfg["sources"]["portal"]
        self.path = resolve(cfg, f"{cfg['paths']['session_dir']}/{self.src['session']}")

    def http_session(self, interactive=False, verify=True):
        state = read_state(self.path)
        client = SchoolHTTP(timeout=self.cfg["net"]["timeout_ms"] / 1000)
        for cookie in (state or {}).get("http_cookies", []):
            client.session.cookies.set_cookie(requests.cookies.create_cookie(**cookie))
        response = client.request("GET", self.src["base"])
        if is_auth(response.url):
            service = validate_service(response.url)
            action, fields = login_form(response.text, response.url)
            saved = credentials()
            # Current official loginPassword() trims both fields before parent.doLogin().
            fields.update(username=saved["account"].strip(), password=saved["password"].strip())
            # POST never follows redirects while carrying the password. Callback consumes ST.
            response = client.request("POST", action, data=fields, callback_expected=service,
                                      headers={"Referer": response.url, "Origin": "https://auth.bupt.edu.cn"})
            if is_auth(response.url):
                raise authentication_rejection(response)
            if urlsplit(response.url).hostname != PORTAL_HOST:
                raise InsightError("login_expired", "CAS 未回到信息门户业务会话")
        response = follow_portal_landing(client, response)
        if urlsplit(response.url).hostname != PORTAL_HOST:
            raise InsightError("login_expired", "尚未回到门户；未保存会话")
        from sources.portal import verify_html
        if verify:
            verify_html(response.text, response.url, self.src, expected_account=credentials()["account"])
        self.landing = response
        self.save_http(client)
        return client

    def save_http(self, client):
        cookies = [{k: getattr(c, k) for k in ("name", "value", "domain", "path", "secure", "expires")}
                   for c in client.session.cookies]
        write_state(self.path, {"http_cookies": cookies})

    def open_browser(self, interactive=False):
        return PortalBrowser(self, interactive)

    def logout(self):
        self.path.unlink(missing_ok=True)


class PortalBrowser:
    def __init__(self, auth, interactive):
        self.auth, self.interactive = auth, interactive
        self.pw = self.browser = self.ctx = None

    def __enter__(self):
        try:
            self.pw = sync_playwright().start()
            self.browser = launch(self.pw, self.auth.cfg, headless=not self.interactive)
            state = read_state(self.auth.path)
            state = state.get("browser") if state else None
            self.ctx = self.browser.new_context(storage_state=state)
            self.page = self.ctx.new_page()
            try:
                self.page.goto(self.auth.src["base"], wait_until="domcontentloaded",
                               timeout=self.auth.cfg["net"]["timeout_ms"])
            except Exception:
                raise InsightError("network_failed", "浏览器无法访问门户；请检查校园网/VPN、官方证书和学校可用性") from None
            self.page.wait_for_timeout(800)
            if is_auth(self.page.url):
                validate_service(self.page.url)
                # Validate the live form action before filling. Native JS handles dynamic fields.
                login_form(self.page.content(), self.page.url, allow_manual=True)
                controls = browser_login_controls(self.page)
                saved = credentials()
                password = saved["password"]

                def guard(route):
                    request = route.request
                    from urllib.parse import unquote_plus
                    body = unquote_plus((request.post_data or "") + request.url)
                    if password in body and not is_auth(request.url):
                        route.abort()
                    else:
                        route.continue_()
                self.ctx.route("**/*", guard)
                controls[0].fill(saved["account"])
                controls[1].fill(password)
                controls[2].click()
                deadline = time.monotonic() + (self.auth.src.get("manual_wait_seconds", 180)
                                               if self.interactive else 8)
                if self.interactive:
                    print("已提交官方认证表单。如出现验证码、扫码或 MFA，请在浏览器完成；程序不会代答。")
                while time.monotonic() < deadline:
                    if urlsplit(self.page.url).hostname == PORTAL_HOST and "clogin.jsp" not in self.page.url:
                        break
                    self.page.wait_for_timeout(1000)
                self.ctx.unroute("**/*", guard)
                if is_auth(self.page.url):
                    raise InsightError("interaction_required", "认证未完成；请运行 login portal --interactive 检查官方提示")
            school_url(self.page.url)
            if urlsplit(self.page.url).hostname != PORTAL_HOST:
                raise InsightError("login_expired", "尚未进入信息门户业务页面")
            return self
        except Exception:
            self.__exit__()
            raise

    def save(self):
        write_state(self.auth.path, {"browser": self.ctx.storage_state()})

    def __exit__(self, *args):
        if self.ctx:
            self.ctx.close()
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()
