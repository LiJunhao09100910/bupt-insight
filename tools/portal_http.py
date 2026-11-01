"""Direct HTTP/CAS login and portal export (no browser).

The portal's visible login form is rendered inside an iframe that often stays
blank under automation (and occasionally under manual Firefox/Edge too). The
HTTP path posts the same official CAS form directly, which is the method the
original project validated against the real portal.

Only this client-side tool uses the credentials; the server never sees them.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from tools.portal_export import body_from_html, bundle_payload, parse_day, rows_from_html

AUTH_HOST = "auth.bupt.edu.cn"
PORTAL_HOST = "my.bupt.edu.cn"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36 Edg/156.0.0.0"
)


class PortalError(Exception):
    pass


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


def _identity(html: str, selector: str) -> bool:
    if not selector:
        return True
    node = BeautifulSoup(html, "html.parser").select_one(selector)
    return bool(node and node.get_text(strip=True))


def _auth_error(html: str) -> str:
    node = BeautifulSoup(html, "html.parser").select_one("#errorDiv, .alert-danger, #msg, .auth_error")
    text = " ".join(node.get_text(" ", strip=True).split()) if node else ""
    if any(word in text for word in ("密码", "错误", "锁定", "验证码", "频繁")):
        return f"统一认证未通过：{text[:120]}"
    return "统一认证未通过（账号密码错误、需要验证码或账号受限）"


def _landing_target(html: str, base: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.select("script:not([src])"):
        match = re.fullmatch(
            r"\s*window\.location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]\s*;?\s*", script.get_text()
        )
        if match:
            return urljoin(base, match.group(1))
    meta = soup.select_one('meta[http-equiv="refresh" i]')
    if meta and "url=" in (meta.get("content") or "").lower():
        return urljoin(base, re.split(r"url=", meta["content"], flags=re.I)[-1].strip("'\""))
    return ""


def _follow_landing(session, response, timeout: int):
    for _ in range(6):
        if _host(response.url) != PORTAL_HOST:
            return response
        target = _landing_target(response.text, response.url)
        if not target:
            return response
        if _host(target) != PORTAL_HOST:
            raise PortalError("门户落地脚本试图跳转到其他系统，已停止")
        response = session.get(target, timeout=timeout, allow_redirects=True)
    raise PortalError("门户跳转次数过多")


def login(cfg: dict, username: str, password: str, timeout: int = 25):
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"})
    response = session.get(cfg["base"], timeout=timeout, allow_redirects=True)
    identity_selector = cfg.get("identity_selector", "")
    if _host(response.url) == PORTAL_HOST and _identity(response.text, identity_selector):
        return session
    if _host(response.url) != AUTH_HOST:
        raise PortalError(f"门户跳转到了意外地址：{_host(response.url) or '未知'}")

    soup = BeautifulSoup(response.text, "html.parser")
    form = soup.select_one("form#loginForm")
    if form is None:
        for candidate in soup.select("form"):
            if candidate.select_one('input[name="password"]'):
                form = candidate
                break
    if form is None:
        raise PortalError("统一认证页面没有登录表单（页面结构可能已改版）")

    data = {
        element["name"]: element.get("value") or ""
        for element in form.select("input[name]")
        if element["name"] not in ("username", "password")
    }
    data["username"] = username
    data["password"] = password
    action = urljoin(response.url, form.get("action") or response.url)
    if _host(action) != AUTH_HOST:
        raise PortalError("登录表单目标不是统一认证，已停止提交")
    posted = session.post(
        action,
        data=data,
        timeout=timeout,
        allow_redirects=True,
        headers={"Referer": response.url, "Origin": f"https://{AUTH_HOST}"},
    )
    if _host(posted.url) == AUTH_HOST:
        raise PortalError(_auth_error(posted.text))
    posted = _follow_landing(session, posted, timeout)
    if _host(posted.url) != PORTAL_HOST:
        raise PortalError("认证后未回到信息门户")
    if not _identity(posted.text, identity_selector):
        # Some landing pages only set cookies; revisit the portal root once.
        posted = _follow_landing(session, session.get(cfg["base"], timeout=timeout, allow_redirects=True), timeout)
        if not _identity(posted.text, identity_selector):
            raise PortalError("已回到门户但未找到身份区域；identity_selector 可能已过期")
    return session


def fetch(session, url: str, referer: str = "", timeout: int = 25) -> str:
    response = session.get(
        url,
        timeout=timeout,
        allow_redirects=True,
        headers={"Referer": referer} if referer else None,
    )
    # The portal root answers with a tiny page that jumps via
    # window.location.href="xs_index.jsp?..."; follow it like a browser.
    response = _follow_landing(session, response, timeout)
    if _host(response.url) != PORTAL_HOST:
        raise PortalError("会话失效或门户跳转异常")
    return response.text


def next_page_url(html: str, current_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.select("a[href]"):
        if " ".join(link.get_text(" ", strip=True).split()) in ("下页", "下一页"):
            return urljoin(current_url, link["href"])
    return ""


def export(cfg: dict, args, session) -> dict:
    cutoff = date.today() - timedelta(days=args.days)
    items: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for entry in cfg["lists"]:
        url = entry.get("url") or cfg["base"]
        pages = max(1, min(10, int(entry.get("pages", 1))))
        print(f"读取列表：{entry['name']}（{url}，最多 {pages} 页）", flush=True)
        for page_no in range(pages):
            try:
                html = fetch(session, url, cfg["base"])
                rows = rows_from_html(html, url, entry)
            except Exception as exc:
                errors.append(f"{entry['name']}: {type(exc).__name__}: {exc}")
                break
            print(f"  第 {page_no + 1} 页解析到 {len(rows)} 行", flush=True)
            if not rows:
                break
            dated = [day for day in (parse_day(row["published"]) for row in rows) if day]
            for row in rows:
                if len(items) >= args.max:
                    break
                if row["url"] in seen:
                    continue
                day = parse_day(row["published"])
                if day is not None and day < cutoff:
                    continue
                seen.add(row["url"])
                try:
                    parsed = body_from_html(fetch(session, row["url"], url), row["url"], entry["body_selector"])
                except Exception as exc:
                    errors.append(f"{row['title'][:40]}: {type(exc).__name__}")
                    parsed = {"body": "", "body_status": "body_failed", "attachments": []}
                items.append({**row, **parsed})
            if len(items) >= args.max:
                break
            # Stop paging once a whole page is older than the window (page 1 can
            # contain pinned items, so only trust this from page 2 onwards).
            if page_no > 0 and dated and max(dated) < cutoff:
                break
            next_url = next_page_url(html, url)
            if not next_url:
                break
            url = next_url
        if len(items) >= args.max:
            break
    return bundle_payload(items, cfg, args, errors)
