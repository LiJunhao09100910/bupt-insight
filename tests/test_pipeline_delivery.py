import copy
import json

import pytest
import requests

from core.database import Database, content_hash, identity
from core.errors import InsightError
from core.notifications import Result, dispatch, message, wechat, check_receipt
from core.pipeline import sync, database


def test_new_unchanged_changed_versions(tmp_path, notice):
    db = Database(tmp_path / "notices.sqlite")
    assert db.upsert(notice, ["pushplus", "desktop"]) == "new"
    assert db.upsert(notice, ["pushplus", "desktop"]) == "unchanged"
    assert len(db.pending(["pushplus", "desktop"])) == 2
    notice.body += "\n虚构更新：延期一天。"
    assert db.upsert(notice, ["pushplus", "desktop"]) == "changed"
    assert len(db.pending(["pushplus", "desktop"])) == 4
    row = db.db.execute("SELECT revision FROM notices").fetchone()
    assert row["revision"] == 2
    db.close()


def test_byr_identity_and_whitespace_hash(notice):
    notice.source, notice.url = "byr", "https://bbs.byr.cn/article/Paper/123?p=1"
    key = identity(notice)
    notice.url = "https://bbs.byr.cn/article/Paper/123?p=2"
    assert identity(notice) == key == "byr:Paper:123"
    digest = content_hash(notice)
    notice.body = "\n " + notice.body + "  \n"
    notice.replies += 3
    assert content_hash(notice) == digest


def test_failed_body_preserves_previous_version(tmp_path, notice):
    db = Database(tmp_path / "db.sqlite")
    db.upsert(notice, ["pushplus"])
    original = notice.body
    notice.body = ""
    notice.extra["body_status"] = "structure_changed"
    assert db.upsert(notice, ["pushplus"]) == "unchanged"
    assert db.db.execute("SELECT body FROM notices").fetchone()[0] == original
    assert len(db.pending(["pushplus"])) == 1
    db.close()


def test_incomplete_new_notice_persisted_without_push(tmp_path, notice):
    db = Database(tmp_path / "db.sqlite")
    notice.body = ""
    notice.extra["body_status"] = "network_failed"
    db.upsert(notice, ["pushplus"])
    assert db.status()["notices"] == 1 and not db.pending(["pushplus"])
    notice.body, notice.extra["body_status"] = "恢复的虚构正文", "ok"
    db.upsert(notice, ["pushplus"])
    assert len(db.pending(["pushplus"])) == 1
    db.close()


def test_channel_failure_independent_and_durable(cfg, tmp_path, notice):
    db = Database(tmp_path / "db.sqlite")
    db.upsert(notice, ["pushplus", "desktop"])
    sent = []
    def sender(channel, *args):
        sent.append(channel)
        return Result("accepted", "fixture") if channel == "pushplus" else Result("failed", "fixture")
    dispatch(cfg, db, sender)
    assert sorted(sent) == ["desktop", "pushplus"]
    assert [r["channel"] for r in db.pending(["pushplus", "desktop"])] == ["desktop"]
    db.close()
    db = Database(tmp_path / "db.sqlite")
    dispatch(cfg, db, lambda *args: Result("submitted", "fixture"))
    assert not db.pending(["pushplus", "desktop"])
    db.close()


def test_crash_or_unknown_not_automatically_resent(cfg, tmp_path, notice):
    db = Database(tmp_path / "db.sqlite")
    db.upsert(notice, ["pushplus"])
    row = db.pending(["pushplus"])[0]
    db.delivery(row["id"], "sending")
    db.recover()
    assert not db.pending(["pushplus"])
    assert db.db.execute("SELECT status FROM deliveries").fetchone()[0] == "unknown"
    db.close()


def test_definite_failure_retries(cfg, tmp_path, notice, monkeypatch):
    cfg["push"]["retries"] = 3
    db = Database(tmp_path / "db.sqlite")
    db.upsert(notice, ["pushplus"])
    calls = []
    monkeypatch.setattr("core.notifications.time.sleep", lambda _: None)
    def sender(*args):
        calls.append(args)
        return Result("failed" if len(calls) < 3 else "accepted", "fixture")
    dispatch(cfg, db, sender)
    assert len(calls) == 3 and not db.pending(["pushplus"])
    assert db.db.execute("SELECT attempts FROM deliveries").fetchone()[0] == 3
    db.close()


def test_baseline_not_pushed_on_next_scan(tmp_path, notice):
    db = Database(tmp_path / "db.sqlite")
    db.upsert(notice, ["pushplus"], baseline=True)
    db.upsert(notice, ["pushplus"])
    assert not db.pending(["pushplus"])
    notice.body += "更新"
    db.upsert(notice, ["pushplus"])
    assert len(db.pending(["pushplus"])) == 1
    db.close()


def test_source_isolation_and_no_new_status(cfg, notice, monkeypatch):
    monkeypatch.setattr("core.security.get_secret", lambda _: None)
    def bad(*args, **kwargs):
        raise InsightError("login_expired", "虚构认证失效")
    def good(*args, **kwargs):
        return {"Paper": [notice]}, None, []
    first = sync(cfg, fetchers={"portal": bad, "byr": good})
    assert first["sources"]["portal"]["status"] == "login_expired"
    assert first["sources"]["byr"]["new"] == 1
    second = sync(cfg, fetchers={"portal": bad, "byr": good})
    assert second["sources"]["byr"]["status"] == "no_new"
    db = database(cfg)
    assert db.status()["notices"] == 1 and len(db.status()["runs"]) == 4
    db.close()


def test_private_body_and_ticket_not_sent_to_wechat(notice):
    title, body = message(notice.to_dict())
    assert title == notice.title
    assert notice.body not in body and notice.url not in body
    assert notice.body in message(notice.to_dict(), external=False)[1]


class Response:
    def __init__(self, status, data):
        self.status_code, self.data = status, data
    def json(self):
        return self.data


@pytest.mark.parametrize("kind,code,status", [("pushplus", 200, "accepted"), ("pushplus", 500, "failed"),
    ("pushplus", 0, "failed"), ("serverchan", 0, "accepted"), ("serverchan", 40001, "failed")])
def test_business_code_not_just_http200(kind, code, status):
    result = wechat(kind, "test", "synthetic", "SCTfixtureOnly", post=lambda *a, **kw: Response(200, {"code": code, "data": "fixture-receipt"}))
    assert result.status == status


def test_read_timeout_is_ambiguous():
    def post(*args, **kwargs):
        raise requests.ReadTimeout("must not leak SCTfixture")
    result = wechat("pushplus", "test", "synthetic", "fixture", post=post)
    assert result.status == "unknown" and "SCTfixture" not in result.detail


def test_receipt_provider_delivery_distinguished():
    result = check_receipt("fixture", access_key="fixture", get=lambda *a, **kw: Response(200, {"code": 200, "data": {"status": 2}}))
    assert result.status == "provider_delivered"


def test_unknown_sender_exception_does_not_block_desktop(cfg, tmp_path, notice):
    db = Database(tmp_path / "db.sqlite")
    db.upsert(notice, ["pushplus", "desktop"])
    def sender(channel, *args):
        if channel == "pushplus":
            raise RuntimeError("secret-fixture")
        return Result("submitted", "fixture")
    results = dispatch(cfg, db, sender)
    assert {r["status"] for r in results} == {"unknown", "submitted"}
    assert "secret-fixture" not in str(results)
    db.close()


def test_account_scope_keeps_previous_outbox_separate(cfg, notice, monkeypatch):
    monkeypatch.setattr("core.security.get_secret", lambda _: json.dumps({"scope": "a" * 32}))
    first = database(cfg)
    first.upsert(notice, ["pushplus"])
    first.close()
    monkeypatch.setattr("core.security.get_secret", lambda _: json.dumps({"scope": "b" * 32}))
    second = database(cfg)
    assert second.status()["notices"] == 0 and not second.pending(["pushplus"])
    second.close()


def test_attachment_notice_is_deliverable_and_attachment_change_detected(tmp_path, notice):
    db = Database(tmp_path / "attachments.sqlite")
    notice.body = ""
    notice.extra = {"body_status": "attachment_only", "attachments": [{"name": "虚构附件.pdf", "url": "http://my.bupt.edu.cn/system/_content/download.jsp?wbfileid=1"}]}
    assert db.upsert(notice, ["desktop"]) == "new"
    assert len(db.pending(["desktop"])) == 1
    assert "附件内容尚未提取" in message(notice.to_dict(), external=False)[1]
    notice.extra["attachments"][0]["url"] = "http://my.bupt.edu.cn/system/_content/download.jsp?wbfileid=2"
    assert db.upsert(notice, ["desktop"]) == "changed"
    assert len(db.pending(["desktop"])) == 2
    db.close()


def test_image_only_notice_has_explicit_unread_content_label(tmp_path, notice):
    db = Database(tmp_path / "images.sqlite")
    notice.body = ""
    notice.extra = {"body_status": "image_only", "attachments": [{"name": "正文图片1", "url": "http://my.bupt.edu.cn/__local/fixture.png"}]}
    db.upsert(notice, ["desktop"])
    assert len(db.pending(["desktop"])) == 1
    assert "图片文字尚未识别" in message(notice.to_dict(), external=False)[1]
    assert "/__local/" not in message(notice.to_dict(), external=True)[1]
    db.close()


def test_corrupt_database_is_preserved_and_rejected(tmp_path):
    path = tmp_path / "corrupt.sqlite"
    original = b"synthetic-corrupt-database-not-a-password"
    path.write_bytes(original)
    with pytest.raises(InsightError) as exc:
        Database(path)
    assert exc.value.status == "storage_corrupt"
    assert path.read_bytes() == original
