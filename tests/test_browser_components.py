from pathlib import Path
import sys
from uuid import uuid4

import pytest

from core.errors import InsightError
from core.security import read_state, write_state
from core.locking import single_run

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    from core.browser import launch
    with sync_playwright() as pw:
        try:
            instance = launch(pw, {"net": {"browser": "edge"}})
        except Exception:
            pytest.skip("本机未安装测试浏览器")
        yield instance
        instance.close()


def test_original_byr_selectors_on_fictional_html(browser):
    from sources.byr import JS_ROWS, JS_BODY
    page = browser.new_page()
    page.set_content((FIXTURES / "byr_board.html").read_text(encoding="utf-8"))
    rows = page.evaluate(JS_ROWS)
    assert len(rows) == 1 and rows[0]["author"] == "demo-author"
    assert rows[0]["url"] == "https://bbs.byr.cn/article/Paper/222"
    page.set_content('<nav>导航</nav><table><tr><td class="a-content">虚构原帖全文</td></tr></table>')
    assert page.evaluate(JS_BODY) == "虚构原帖全文"
    page.set_content('<nav>导航</nav>')
    assert page.evaluate(JS_BODY) == ""
    page.close()


def test_byr_fetch_retries_and_body(browser, cfg, monkeypatch):
    from sources.byr import fetch
    from core.security import write_state
    calls = []
    context = browser.new_context()
    board = (FIXTURES / "byr_board.html").read_text(encoding="utf-8")
    def route_handler(route):
        calls.append(route.request.url)
        html = board if "/board/" in route.request.url else '<table><tr><td class="a-content">虚构科研全文</td></tr></table>'
        route.fulfill(status=200, body=html, content_type="text/html; charset=utf-8")
    context.route("**/*", route_handler)
    class Session:
        def __init__(self, *a):
            self.ctx = context
            self.state_path = Path(cfg["paths"]["session_dir"]) / "byr.bin"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def cookie(self, *a):
            return "fixture-user"
        def new_page(self):
            return context.new_page()
    monkeypatch.setattr("sources.byr.Session", Session)
    monkeypatch.setattr("core.security.write_state", lambda *a: None)
    result, _, errors = fetch(cfg, quiet=True)
    assert not errors and len(result["Paper"]) == 1
    assert result["Paper"][0].body == "虚构科研全文"
    assert len(calls) == 2
    context.close()


def test_byr_missing_login_explicit(cfg):
    from sources.byr import fetch
    with pytest.raises(InsightError) as exc:
        fetch(cfg, quiet=True)
    assert exc.value.status == "login_expired"


@pytest.mark.parametrize('second_page', ['new', 'repeated', 'failed'])
def test_byr_pagination_deduplicates_and_keeps_partial_results(browser, cfg, monkeypatch, second_page):
    from datetime import datetime, timezone, timedelta
    from sources.byr import fetch
    from playwright.sync_api import TimeoutError

    cfg['sources']['byr']['board_overrides'] = {'Paper': {'pages': 2, 'rows_per_page': 30}}
    context = browser.new_context()
    calls = []
    board = (FIXTURES / 'byr_board.html').read_text(encoding='utf-8').replace('2026-10-12 12:00', '12:34:56')

    def route_handler(route):
        url = route.request.url
        calls.append(url)
        html = board if '/board/' in url else '<table><tr><td class="a-content">虚构科研全文</td></tr></table>'
        if '?p=2' in url:
            if second_page == 'failed':
                raise AssertionError('failed page should be intercepted before navigation')
            if second_page == 'new':
                html = board.replace('/222', '/333')
        route.fulfill(status=200, body=html, content_type='text/html; charset=utf-8')

    context.route('**/*', route_handler)

    class Session:
        def __init__(self, *args):
            self.ctx = context
            self.state_path = Path(cfg['paths']['session_dir']) / 'byr.bin'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def cookie(self, *args):
            return 'fixture-user'

        def new_page(self):
            page = context.new_page()
            original = page.goto

            def goto(url, **kwargs):
                if '?p=2' in url and second_page == 'failed':
                    raise TimeoutError('fictional pagination timeout')
                return original(url, **kwargs)

            monkeypatch.setattr(page, 'goto', goto)
            return page

    monkeypatch.setattr('sources.byr.Session', Session)
    monkeypatch.setattr('core.security.write_state', lambda *args: None)
    result, _, errors = fetch(cfg, quiet=True)
    assert len(result['Paper']) == (2 if second_page == 'new' else 1)
    assert len({item.url for item in result['Paper']}) == len(result['Paper'])
    day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    assert result['Paper'][0].published == day + ' 12:34:56'
    assert all(item.body == '虚构科研全文' for item in result['Paper'])
    assert bool(errors) == (second_page == 'failed')
    assert sum('/article/' in url for url in calls) == len(result['Paper'])
    context.close()


def test_byr_legacy_configuration_prefers_encrypted_state(cfg):
    from core.browser import Session
    path = Path(cfg["paths"]["session_dir"])
    path.mkdir(parents=True, exist_ok=True)
    (path / "byr.json").write_text('{"cookies": [], "origins": []}')
    (path / "byr.bin").write_bytes(b"test-not-opened")
    cfg["sources"]["byr"]["session"] = "byr.json"
    assert Session(cfg, "byr").state_path.suffix == ".bin"


def test_os_lock_prevents_overlapping_run(tmp_path):
    path = tmp_path / "lock"
    with single_run(path):
        with pytest.raises(InsightError) as exc:
            with single_run(path):
                pass
        assert exc.value.status == "already_running"
    with single_run(path):
        pass


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI 本机组件")
def test_real_dpapi_roundtrip(tmp_path):
    path = tmp_path / "state.bin"
    state = {"cookies": [{"name": "fixture-only", "value": "synthetic-state-value"}], "origins": []}
    write_state(path, state)
    assert b"synthetic-state-value" not in path.read_bytes()
    assert read_state(path) == state
    path.write_bytes(b"damaged-fixture")
    with pytest.raises(InsightError):
        read_state(path)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Credential Manager 本机组件")
def test_real_credential_manager_roundtrip():
    from core.security import vault
    backend = vault()
    service = "BUPTInsight.AutomatedTest." + uuid4().hex
    try:
        backend.set_password(service, "fictional-user", "synthetic-value-only")
        assert backend.get_password(service, "fictional-user") == "synthetic-value-only"
    finally:
        backend.delete_password(service, "fictional-user")
    assert backend.get_password(service, "fictional-user") is None
