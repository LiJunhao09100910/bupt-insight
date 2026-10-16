from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def pytest_configure(config):
    # Avoid inheriting inaccessible temp folders created by other Windows identities.
    (Path(config.rootpath) / ".test-output").mkdir(exist_ok=True)


@pytest.fixture
def cfg(tmp_path):
    return {
        "paths": {"data_dir": str(tmp_path / "data"), "session_dir": str(tmp_path / "sessions"),
                  "inbox_dir": str(tmp_path / "inbox")},
        "net": {"browser": "edge", "timeout_ms": 1000, "retries": 2, "delay_ms": 0},
        "sources": {
            "portal": {"enabled": True, "base": "http://my.bupt.edu.cn", "session": "portal.bin",
                       "identity_selector": "#identity", "business_selector": "#business", "lists": []},
            "byr": {"enabled": True, "base": "https://bbs.byr.cn", "session": "byr.bin",
                    "requires_login": True, "rows_per_board": 2, "boards": ["Paper"]}},
        "push": {"retries": 1, "channels": {"pushplus": {"enabled": True}, "desktop": {"enabled": True}}}}


@pytest.fixture
def entry():
    return {"name": "虚构通知", "url": "http://my.bupt.edu.cn/notices",
            "row_selector": ".notice", "link_selector": "a", "date_selector": ".date",
            "source_selector": ".origin", "body_selector": "#content", "empty_selector": ".empty"}


@pytest.fixture
def notice():
    from core.schema import Item
    return Item(source="portal", channel="虚构科研处", title="虚构竞赛报名通知", url="http://my.bupt.edu.cn/view?id=1",
                published="2026-10-12", body="虚构正文：报名时间以正式通知为准。", private=True,
                extra={"body_status": "ok"})
