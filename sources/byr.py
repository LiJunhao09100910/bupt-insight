"""北邮人论坛。

版面是 hash 路由的 SPA，`networkidle` 不稳 —— 用 domcontentloaded + 等选择器 + 重试，
这套组合跑 25 个版 0 失败。置顶行常年不动，必须跳过，否则每次都当成新帖。
"""
import json
import time

from core.browser import Session
from core.config import resolve
from core.schema import Item
from core.errors import InsightError, safe_error
from core.progress import update as progress

JS_ROWS = """() => {
    const t = document.querySelector('table.board-list');
    if (!t) return [];
    const out = [];
    for (const tr of t.querySelectorAll('tr')) {
        if (tr.classList.contains('top')) continue;
        const tds = Array.from(tr.querySelectorAll('td'));
        if (tds.length < 5) continue;
        const a = tds[1].querySelector("a[href*='/article/']");
        if (!a) continue;
        const cells = tds.map(c => c.innerText.replace(/\\s+/g, ' ').trim());
        out.push({
            title: (a.innerText || '').trim(),
            url: new URL(a.getAttribute('href').replace(/^#!?/, ''), 'https://bbs.byr.cn').href,
            author: (cells[3] || '').replace(/^\\|\\s*/, ''),
            published: cells[2] || '',
            replies: parseInt(cells[4] || '0', 10) || 0,
            last_active: cells[5] || ''
        });
    }
    return out;
}"""

# nforum 正文在 class 带文章号的 td.a-content 里。
# 曾经用 document.body 兜底，结果抓回来满屏导航栏 —— 所以宁可空着也不兜底 body。
JS_BODY = """() => {
    const el = document.querySelector('td.a-content');
    return el ? el.innerText : '';
}"""


def read(cfg, url: str, max_chars: int = 1200) -> tuple[str, str]:
    """读单篇正文。降低信息成本的关键不是给链接，是告诉你要不要点开。"""
    import re

    with Session(cfg, "byr") as s:
        page = s.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=40000)
        check_login(page, s)
        page.wait_for_selector("td.a-content", timeout=40000)
        body = page.evaluate(JS_BODY) or ""
        return page.title(), re.sub(r"\n{3,}", "\n\n", body.strip())[:max_chars]


def load_watchlist(cfg, only=None):
    wl = json.loads(resolve(cfg, cfg["sources"]["byr"].get("watchlist", "watchlist.json")).read_text(encoding="utf-8"))
    wl = {k: v for k, v in wl.items() if not k.startswith("_")}
    if only:
        want = {b.strip() for b in only.split(",")}
        wl = {k: v for k, v in wl.items() if k in want}
    configured = cfg["sources"]["byr"].get("boards")
    if configured and not only:
        wl = {k: v for k, v in wl.items() if k in configured}
    if not wl:
        raise InsightError("configuration_error", "BYR 关注版面为空或版面代号不在 watchlist.json")
    return wl


def check_login(page, session):
    if not session.cookie("nforum[UTMPUSERID]", "login-user"):
        raise InsightError("login_expired", "BYR 会话失效，请重新运行 login byr")
    if page.locator('form[action="/login"] input[name="passwd"]').count():
        if page.locator('form[action="/login"] input[name="passwd"]').first.is_visible():
            raise InsightError("login_expired", "BYR 返回访客登录表单，请重新登录")


def fetch(cfg, only=None, quiet=False):
    """抓所有版面，返回 {board: [Item]}。不做过滤不打分的活。"""
    watch = load_watchlist(cfg, only)
    rows_per = cfg["sources"]["byr"]["rows_per_board"]
    timeout = cfg["net"]["timeout_ms"] + 10000
    tries = cfg["net"]["retries"]
    delay = cfg["net"]["delay_ms"] / 1000

    fetched: dict[str, list] = {}
    errors: list[str] = []

    with Session(cfg, "byr") as s:
        user = s.cookie("nforum[UTMPUSERID]", "login-user")
        if not user:
            raise InsightError("login_expired", "BYR 会话失效，请重跑 python run.py login byr")
        if not quiet:
            print(f"BYR 会话待业务验证，版面 {len(watch)} 个")

        page = s.new_page()

        def grab(board):
            last = None
            for _ in range(tries):
                try:
                    page.goto(f"https://bbs.byr.cn/board/{board}",
                              wait_until="domcontentloaded", timeout=timeout)
                    check_login(page, s)
                    page.wait_for_selector("table.board-list tr", timeout=20000)
                    page.wait_for_timeout(400)
                    rows = page.evaluate(JS_ROWS)[:rows_per]
                    if not rows:
                        raise InsightError("structure_changed", "BYR 列表没有可解析帖子；请检查版面或选择器")
                    return rows
                except Exception as e:
                    if isinstance(e, InsightError) and e.status == "login_expired":
                        raise
                    last = e
                    page.wait_for_timeout(800)
            raise last

        for board, meta in watch.items():
            progress(cfg, "byr", "board_list", board=board)
            time.sleep(delay)
            try:
                rows = grab(board)
                fetched[board] = [
                    Item(source="byr", channel=meta["name"], private=cfg["sources"]["byr"].get("private", False),
                         extra={"body_status": "pending"}, **r) for r in rows
                ]
                for item_index, item in enumerate(fetched[board], start=1):
                    progress(cfg, "byr", "post_body", board=board, current=item_index, total=len(fetched[board]))
                    for attempt in range(max(1, tries)):
                        time.sleep(delay)
                        try:
                            page.goto(item.url, wait_until="domcontentloaded", timeout=timeout)
                            check_login(page, s)
                            page.wait_for_selector("td.a-content", timeout=timeout)
                            item.body = (page.evaluate(JS_BODY) or "").strip()
                            if not item.body:
                                raise InsightError("structure_changed", "BYR 正文为空")
                            item.extra["body_status"] = "ok"
                            break
                        except Exception as exc:
                            status, message = safe_error(exc)
                            item.extra["body_status"] = status
                            if status == "login_expired" or attempt == max(1, tries) - 1:
                                errors.append(f"{status}: {board} 正文读取失败：{message}")
                                if status == "login_expired":
                                    return fetched, watch, errors
                                break
                if not quiet:
                    print(f"  {board:18} {meta['name']:16} {len(rows):>3} 条")
            except Exception as e:
                fetched[board] = []
                status, message = safe_error(e)
                errors.append(f"{status}: {board}: {message}")
                if not quiet:
                    print(f"  {board:18} {status}")

        from core.security import write_state
        # Migrate legacy BYR JSON on successful scan; retain old file until explicit logout.
        if any(fetched.values()):
            target = s.state_path.with_suffix(".bin") if s.state_path.suffix == ".json" else s.state_path
            write_state(target, s.ctx.storage_state())

    return fetched, watch, errors
