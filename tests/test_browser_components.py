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
