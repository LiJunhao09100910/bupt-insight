"""Authenticated my.bupt.edu.cn adapter, calibrated against real list and body HTML."""
import time
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

from bs4 import BeautifulSoup

from core.errors import InsightError, safe_error
from core.http import school_url, is_auth, PORTAL_HOST
from core.schema import Item
from core.progress import update as progress


def clean_link(url):
    p = urlsplit(school_url(url))
    if p.hostname != PORTAL_HOST:
        raise InsightError("structure_changed", "通知链接不是信息门户业务地址")
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if k.lower() not in ("ticket", "jsessionid")]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), p.fragment))


def verify_html(html, url, src, expected_account=None):
    soup = BeautifulSoup(html, "html.parser")
    if is_auth(url) or soup.select_one('input[type="password"]'):
        raise InsightError("login_expired", "门户跳回认证页面，需要重新登录")
    if urlsplit(url).hostname != PORTAL_HOST:
        raise InsightError("login_expired", "未进入已授权的信息门户")
    for key in ("identity_selector", "business_selector"):
        selector = src.get(key)
        if not selector:
            raise InsightError("adapter_unverified", "需在已登录门户校准身份和业务区域选择器，详见 README")
        node = soup.select_one(selector)
        if node is None or not node.get_text(strip=True):
            raise InsightError("structure_changed", f"门户验证区域缺失：{key}")
    expected = src.get("identity_expected_text") or expected_account
    if expected and expected not in soup.select_one(src["identity_selector"]).get_text():
        raise InsightError("wrong_account", "门户身份与配置的账号标记不符")
    return soup


def text(node, selector):
    match = node.select_one(selector) if selector else None
    return match.get_text(" ", strip=True) if match else ""


def parse_list(html, url, entry):
    soup = BeautifulSoup(html, "html.parser")
    for key in ("row_selector", "link_selector", "date_selector", "source_selector"):
        if not entry.get(key):
            raise InsightError("adapter_unverified", f"通知列表尚未校准：{key}")
    rows = soup.select(entry["row_selector"])
    if not rows:
        if entry.get("empty_selector") and soup.select_one(entry["empty_selector"]):
            return []
        raise InsightError("structure_changed", "未找到通知列表或明确空列表标记")
    result = []
    for row in rows:
        link = row.select_one(entry["link_selector"])
        title = (link.get("title") or link.get_text(" ", strip=True)) if link else ""
        published = text(row, entry["date_selector"])
        origin = text(row, entry["source_selector"])
        if not link or not link.get("href") or not title or not published or not origin:
            raise InsightError("structure_changed", "通知缺少标题、发布时间、来源或链接")
        result.append(Item(source="portal", channel=origin, title=title, published=published,
                           url=clean_link(urljoin(url, link["href"])), private=True))
    return result


def parse_body(html, selector):
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one('input[type="password"]'):
        raise InsightError("login_expired", "通知正文要求重新登录")
    if not selector:
        raise InsightError("adapter_unverified", "尚未校准正文选择器")
    node = soup.select_one(selector)
    if node is None:
        raise InsightError("structure_changed", "通知正文区域缺失")
    for tag in node.select("script, style, nav"):
        tag.decompose()
    body = node.get_text("\n", strip=True)
    if not body:
        raise InsightError("structure_changed", "通知正文为空，未使用整页文本兜底")
    return body


def parse_notice_body(html, selector, url):
    """Attachment-only announcements are legitimate notices, not empty-page success."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one('input[type="password"]'):
        raise InsightError("login_expired", "通知正文要求重新登录")
    if not selector or soup.select_one(selector) is None:
        raise InsightError("structure_changed", "通知正文区域缺失")
    attachments = []
    for link in soup.select('a[href*="/system/_content/download.jsp"]'):
        name = link.get_text(" ", strip=True)
        if name:
            attachments.append({"name": name, "url": clean_link(urljoin(url, link["href"]))})
    node = soup.select_one(selector)
    for tag in node.select("script, style, nav"):
        tag.decompose()
    body = node.get_text("\n", strip=True)
    if body:
        return body, "ok", attachments
    if attachments:
        return "", "attachment_only", attachments
    images = []
    for image in node.select("img[src]"):
        images.append({"name": f"正文图片{len(images) + 1}", "url": clean_link(urljoin(url, image["src"]))})
    if images:
        return "", "image_only", images
    raise InsightError("structure_changed", "正文为空且未找到实际附件，未使用整页文本兜底")


def fetch(cfg, only=None, quiet=False, interactive=False):
    from core.portal_auth import PortalAuthenticator
    src = cfg["sources"]["portal"]
    if not src.get("lists"):
        raise InsightError("adapter_unverified", "真实门户通知列表尚未校准；请先执行 portal inspect --interactive")
    auth = PortalAuthenticator(cfg)
    mode = src.get("auth_mode", "browser")
    if mode == "auto":
        try:
            return _fetch(cfg, auth, "http", quiet, interactive)
        except InsightError as exc:
            if exc.status not in ("interaction_required", "structure_changed", "auth_failed"):
                raise
    return _fetch(cfg, auth, "browser" if mode == "auto" else mode, quiet, interactive)


def _fetch(cfg, auth, mode, quiet, interactive):
    src = cfg["sources"]["portal"]
    fetched, errors = {}, []
    browser = None
    try:
        if mode == "http":
            client = auth.http_session()
            def get(url, selector=None):
                r = client.request("GET", url)
                if is_auth(r.url):
                    raise InsightError("login_expired", "门户会话在采集时失效")
                return r.text, r.url
        else:
            browser = auth.open_browser(interactive).__enter__()
            from core.security import credentials
            verify_html(browser.page.content(), browser.page.url, src, expected_account=credentials()["account"])
            def get(url, selector=None):
                school_url(url)
                try:
                    browser.page.goto(url, wait_until="domcontentloaded", timeout=cfg["net"]["timeout_ms"])
                except Exception:
                    raise InsightError("network_failed", "浏览器无法读取门户业务页面，请检查校园网/VPN") from None
                if is_auth(browser.page.url):
                    raise InsightError("login_expired", "门户会话在采集时失效")
                school_url(browser.page.url)
                frame = browser.page
                if src.get("frame_selector"):
                    element = browser.page.query_selector(src["frame_selector"])
                    frame = element.content_frame() if element else None
                    if frame is None:
                        raise InsightError("structure_changed", "通知 iframe 缺失")
                    school_url(frame.url)
                if selector:
                    try:
                        frame.wait_for_selector(selector, state="attached", timeout=cfg["net"]["timeout_ms"])
                    except Exception:
                        raise InsightError("structure_changed", "门户预期的列表/正文区域未出现") from None
                return frame.content(), frame.url

        for entry in src["lists"]:
            progress(cfg, "portal", "notice_list", channel=entry["name"])
            try:
                last = None
                for attempt in range(max(1, cfg["net"]["retries"])):
                    try:
                        time.sleep(cfg["net"]["delay_ms"] / 1000)
                        wait_selector = ",".join(s for s in (entry.get("row_selector"), entry.get("empty_selector")) if s)
                        html, url = get(clean_link(entry["url"]), wait_selector)
                        items = parse_list(html, url, entry)
                        # Real list starts with older pinned items; scan newest dates first.
                        if entry.get("sort_latest_first", False):
                            items.sort(key=lambda item: item.published, reverse=True)
                        items = items[:src.get("rows_per_list", 30)]
                        last = None
                        break
                    except Exception as exc:
                        last = exc
                        if isinstance(exc, InsightError) and exc.status == "login_expired":
                            raise
                if last:
                    raise last
                for item_index, item in enumerate(items, start=1):
                    progress(cfg, "portal", "notice_body", current=item_index, total=len(items))
                    time.sleep(cfg["net"]["delay_ms"] / 1000)
                    try:
                        body_html, _ = get(item.url, entry.get("body_selector"))
                        item.body, body_status, attachments = parse_notice_body(body_html, entry.get("body_selector"), item.url)
                        item.extra["body_status"] = body_status
                        if attachments:
                            item.extra["attachments"] = attachments
                    except Exception as exc:
                        status, message = safe_error(exc)
                        item.extra["body_status"] = status
                        errors.append(f"{status}: 正文读取失败：{message}")
                fetched[entry["name"]] = items
            except Exception as exc:
                status, message = safe_error(exc)
                errors.append(f"{status}: {message}")
        if browser:
            browser.save()
        else:
            auth.save_http(client)
    finally:
        if browser:
            browser.__exit__()
        elif "client" in locals():
            client.session.close()
    return fetched, None, errors
