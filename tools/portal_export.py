"""Export portal notices into an uploadable bundle.

Run this on a machine that can reach the campus portal (manual login). The
server never authenticates to the portal; it only imports the produced file:

    python -X utf8 tools/portal_export.py --config portal.yaml
    scp portal-*.json <server>:/var/lib/bupt-insight/portal-inbox/
    # on the server
    python -X utf8 run.py portal import /var/lib/bupt-insight/portal-inbox/portal-*.json

The bundle is plain JSON (optionally .gz) and carries a sha256 of its items so
the server can detect truncation or tampering.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import yaml
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from core.browser import launch
from core.portal_import import FORMAT, VERSION, bundle_digest

DATE_PATTERNS = (
    re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})"),
    re.compile(r"(\d{1,2})[-/月.](\d{1,2})"),
)


def canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in ("ticket", "jsessionid") and not k.lower().startswith("utm_")
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), urlencode(sorted(query)), parts.fragment))


def parse_day(text: str) -> date | None:
    text = (text or "").strip()
    match = DATE_PATTERNS[0].search(text)
    if match:
        try:
            return date(*map(int, match.groups()))
        except ValueError:
            return None
    match = DATE_PATTERNS[1].search(text)
    if match:
        try:
            return date(datetime.now().year, int(match.group(1)), int(match.group(2)))
        except ValueError:
            return None
    return None


def node_text(node, selector: str) -> str:
    if not node or not selector:
        return ""
    match = node.select_one(selector)
    return match.get_text(" ", strip=True) if match else ""


def rows_from_html(html: str, base_url: str, entry: dict) -> list[dict]:
    """Parse one list page. Shared by the browser and HTTP transports."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select(entry["row_selector"])
    result = []
    for row in rows:
        link = row.select_one(entry["link_selector"])
        if not link or not link.get("href"):
            continue
        title = (link.get("title") or link.get_text(" ", strip=True)).strip()
        if not title:
            continue
        published = node_text(row, entry.get("date_selector", ""))
        if not published:
            match = re.search(r"20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2}", row.get_text(" ", strip=True))
            if match:
                published = match.group()
        department = node_text(row, entry.get("source_selector", "")) or entry["name"]
        result.append(
            {
                "title": title[:400],
                "url": canonical_url(urljoin(base_url, link["href"])),
                "published": published[:40],
                "department": department[:100],
                "list": entry["name"],
            }
        )
    return result


def body_from_html(html: str, base_url: str, selector: str) -> dict:
    """Extract body/attachments. Shared by the browser and HTTP transports."""
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one(selector)
    if node is None:
        return {"body": "", "body_status": "body_failed", "attachments": []}
    attachments = []
    for link in soup.select('a[href*="download.jsp"]'):
        name = link.get_text(" ", strip=True)
        if name and link.get("href"):
            attachments.append({"name": name[:200], "url": canonical_url(urljoin(base_url, link["href"]))})
    for tag in node.select("script, style, nav"):
        tag.decompose()
    body = node.get_text("\n", strip=True)
    if body:
        status = "ok"
    elif attachments:
        status = "attachment_only"
    elif node.select("img[src]"):
        status = "image_only"
    else:
        status = "body_failed"
    return {"body": body, "body_status": status, "attachments": attachments}


def scrape_list(page, entry: dict) -> list[dict]:
    page.goto(entry["url"], wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_selector(entry["row_selector"], timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(800)
    return rows_from_html(page.content(), page.url, entry)


def scrape_body(page, item: dict, selector: str) -> dict:
    page.goto(item["url"], wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_selector(selector, state="attached", timeout=30000)
    except Exception:
        return {**item, "body": "", "body_status": "body_failed", "attachments": []}
    return {**item, **body_from_html(page.content(), page.url, selector)}


def _identity_visible(candidate, selector: str) -> bool:
    try:
        if candidate.is_closed():
            return False
        locator = candidate.locator(selector)
        return locator.count() > 0 and locator.first.is_visible()
    except Exception:
        return False


def wait_for_login(page, context, identity_selector: str, timeout: int):
    """Wait for the human login without requiring terminal input.

    Some portal flows close the opener tab when the authenticated window opens;
    poll every live page in the context instead of sleeping on one page.
    """
    print("浏览器已打开：请在窗口中登录门户（含验证码/二次验证）。", flush=True)
    deadline = time.time() + timeout
    if not identity_selector:
        if sys.stdin and sys.stdin.isatty():
            input("登录完成后按 Enter 继续…")
            return page
        print("未配置 identity_selector，等待 20 秒后继续…", flush=True)
        time.sleep(20)
        return page
    while time.time() < deadline:
        for candidate in reversed(context.pages):
            if _identity_visible(candidate, identity_selector):
                print(f"已检测到登录身份区域，继续（{candidate.url}）。", flush=True)
                return candidate
        time.sleep(2)
        if int(time.time()) % 30 < 2:
            live = [page.url[:80] for page in context.pages if not page.is_closed()]
            print(f"等待登录… 当前页面：{live or '（无）'}", flush=True)
    raise SystemExit("等待登录超时；可调大 login_timeout 后重试")


def browser_net(cfg: dict) -> dict:
    """Edge by default; browser_path overrides the channel lookup when set."""
    return {
        "net": {
            "browser": cfg.get("browser", "edge"),
            "executable_path": cfg.get("browser_path", "") or "",
        }
    }


def build_bundle(cfg: dict, args) -> dict:
    cutoff = date.today() - timedelta(days=args.days)
    items: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    with sync_playwright() as pw:
        browser = launch(pw, browser_net(cfg), headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(cfg["base"], wait_until="domcontentloaded", timeout=60000)
        page = wait_for_login(page, context, cfg.get("identity_selector", ""), int(cfg.get("login_timeout", 300)))

        for entry in cfg["lists"]:
            print(f"读取列表：{entry['name']}（{entry.get('url') or page.url}）", flush=True)
            try:
                rows = scrape_list(page, entry)
                print(f"  解析到 {len(rows)} 行", flush=True)
            except Exception as exc:
                errors.append(f"{entry['name']}: {type(exc).__name__}")
                continue
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
                    items.append(scrape_body(page, row, entry["body_selector"]))
                except Exception as exc:
                    errors.append(f"{row['title'][:40]}: {type(exc).__name__}")
                    items.append({**row, "body": "", "body_status": "body_failed", "attachments": []})
            if len(items) >= args.max:
                break
        browser.close()

    return bundle_payload(items, cfg, args, errors)


def bundle_payload(items: list[dict], cfg: dict, args, errors: list[str] | None = None) -> dict:
    for item in items:
        item["id"] = "portal:" + hashlib.sha1(item["url"].encode("utf-8")).hexdigest()
        item["fetched_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    stats = {
        "items": len(items),
        "ok": sum(1 for i in items if i["body_status"] == "ok"),
        "attachment_only": sum(1 for i in items if i["body_status"] == "attachment_only"),
        "image_only": sum(1 for i in items if i["body_status"] == "image_only"),
        "body_failed": sum(1 for i in items if i["body_status"] == "body_failed"),
        "errors": errors or [],
    }
    return {
        "format": FORMAT,
        "version": VERSION,
        "bundle_id": bundle_digest(items),
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "client": {"tool": "portal-export/1.0", "portal": cfg["base"], "days": args.days},
        "window": {"days": args.days},
        "stats": stats,
        "items": items,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="把信息门户通知导出为可上传的 bundle")
    parser.add_argument("--config", default="portal_client.yaml")
    parser.add_argument("--out", default="")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--max", type=int, default=400)
    parser.add_argument("--gzip", action="store_true")
    parser.add_argument("--browser", default=None, help="edge（默认）/ chrome / chromium")
    parser.add_argument("--browser-path", default=None, help="浏览器可执行文件绝对路径；留空用通道查找")
    args = parser.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if args.browser:
        cfg["browser"] = args.browser
    if args.browser_path is not None:
        cfg["browser_path"] = args.browser_path
    if not cfg.get("lists"):
        print("配置里没有 lists", file=sys.stderr)
        return 2
    bundle = build_bundle(cfg, args)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out or f"portal-{stamp}.json")
    if args.gzip or out.suffix == ".gz":
        out = out.with_suffix(".json.gz") if out.suffix != ".gz" else out
        out.write_bytes(gzip.compress(json.dumps(bundle, ensure_ascii=False, indent=1).encode("utf-8")))
    else:
        out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    stats = bundle["stats"]
    print(
        f"已导出 {stats['items']} 条（正文 {stats['ok']}，附件 {stats['attachment_only']}，"
        f"图片 {stats['image_only']}，失败 {stats['body_failed']}）→ {out}"
    )
    if stats["errors"]:
        print("部分错误：", "; ".join(stats["errors"][:5]))
    print("\n上传并在服务器导入：")
    print(f"  scp {out} <server>:/var/lib/bupt-insight/portal-inbox/")
    print(f"  python -X utf8 run.py portal import /var/lib/bupt-insight/portal-inbox/{out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

