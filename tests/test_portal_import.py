import gzip
import json

import pytest

from core import portal_import
from core.errors import InsightError
from core.pipeline import database


def entry(number=1, body="虚构正文，欢迎报名。", status="ok"):
    return {
        "id": f"portal:{number}",
        "title": f"虚构通知 {number}",
        "url": f"http://my.bupt.edu.cn/view?id={number}",
        "published": "2026-10-30 09:00",
        "department": "科学技术研究院",
        "list": "通知公告",
        "body": body,
        "body_status": status,
        "attachments": [],
        "fetched_at": "2026-11-01T10:00:00+08:00",
    }


def write_bundle(tmp_path, items, *, tamper=False, compress=False, name=None):
    data = {
        "format": portal_import.FORMAT,
        "version": portal_import.VERSION,
        "generated_at": "2026-11-01T10:00:00+08:00",
        "bundle_id": portal_import.bundle_digest(items),
        "items": items,
    }
    if tamper:
        data["bundle_id"] = "0" * 64
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    path = tmp_path / (name or ("bundle.json.gz" if compress else "bundle.json"))
    path.write_bytes(gzip.compress(raw) if compress else raw)
    return path


def test_import_creates_private_portal_notices(cfg, tmp_path):
    path = write_bundle(tmp_path, [entry()])
    db = database(cfg)
    try:
        report = portal_import.import_bundle(cfg, db, path)
        assert report["status"] == "ok"
        assert report["new"] == 1
        row = db.db.execute("SELECT * FROM notices WHERE source='portal'").fetchone()
        assert row["title"] == "虚构通知 1"
        assert row["private"] == 1
        assert json.loads(row["payload"])["extra"]["body_status"] == "ok"
        assert db.db.execute("SELECT count(*) FROM portal_bundles").fetchone()[0] == 1
    finally:
        db.close()


def test_reupload_is_idempotent(cfg, tmp_path):
    path = write_bundle(tmp_path, [entry()])
    db = database(cfg)
    try:
        portal_import.import_bundle(cfg, db, path)
        again = portal_import.import_bundle(cfg, db, path)
        assert again["status"] == "already_imported"
        assert again["bundle_id"]
        assert db.db.execute("SELECT count(*) FROM notices").fetchone()[0] == 1
        assert db.db.execute("SELECT count(*) FROM portal_bundles").fetchone()[0] == 1
    finally:
        db.close()


def test_changed_body_creates_a_new_revision(cfg, tmp_path):
    first = write_bundle(tmp_path, [entry(body="第一版")], name="v1.json")
    second = write_bundle(tmp_path, [entry(body="第二版，补充了截止时间")], name="v2.json")
    db = database(cfg)
    try:
        portal_import.import_bundle(cfg, db, first)
        report = portal_import.import_bundle(cfg, db, second)
        assert report["changed"] == 1
        row = db.db.execute("SELECT revision, body FROM notices WHERE source='portal'").fetchone()
        assert row["revision"] == 2
        assert "第二版" in row["body"]
    finally:
        db.close()


def test_tampered_bundle_is_rejected(cfg, tmp_path):
    path = write_bundle(tmp_path, [entry()], tamper=True)
    db = database(cfg)
    try:
        with pytest.raises(InsightError) as excinfo:
            portal_import.import_bundle(cfg, db, path)
        assert excinfo.value.status == "bundle_tampered"
        assert db.db.execute("SELECT count(*) FROM notices").fetchone()[0] == 0
    finally:
        db.close()


def test_unknown_format_is_rejected(cfg, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"format": "something-else", "items": []}), encoding="utf-8")
    db = database(cfg)
    try:
        with pytest.raises(InsightError) as excinfo:
            portal_import.import_bundle(cfg, db, path)
        assert excinfo.value.status == "bundle_invalid"
    finally:
        db.close()


def test_gzip_bundle_is_supported(cfg, tmp_path):
    path = write_bundle(tmp_path, [entry(), entry(2)], compress=True)
    db = database(cfg)
    try:
        report = portal_import.import_bundle(cfg, db, path)
        assert report["items"] == 2
        assert db.db.execute("SELECT count(*) FROM notices").fetchone()[0] == 2
    finally:
        db.close()


def test_url_credentials_are_stripped(cfg, tmp_path):
    item = entry()
    item["url"] = "http://my.bupt.edu.cn/view?id=1&ticket=ST-123&utm_source=x"
    path = write_bundle(tmp_path, [item])
    db = database(cfg)
    try:
        portal_import.import_bundle(cfg, db, path)
        row = db.db.execute("SELECT url FROM notices").fetchone()
        assert "ticket" not in row["url"] and "utm" not in row["url"]
    finally:
        db.close()


def test_feed_includes_portal_items(cfg, tmp_path):
    from core.web import create_app

    path = write_bundle(tmp_path, [entry()])
    db = database(cfg)
    try:
        portal_import.import_bundle(cfg, db, path)
    finally:
        db.close()
    app = create_app(cfg, 8765)
    app.config["TESTING"] = True
    client = app.test_client()
    payload = client.get("/api/feed?view=all&source=portal", headers={"Host": "localhost"}).get_json()
    assert payload["total"] == 1
    assert payload["items"][0]["source"] == "portal"
    status = client.get("/api/status", headers={"Host": "localhost"}).get_json()
    assert status["sources"]["portal"]["status"] == "ok"


def test_cli_portal_import(cfg, tmp_path, monkeypatch, capsys):
    import yaml

    from core import cli

    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "paths": {
                    "data_dir": str(tmp_path / "data"),
                    "session_dir": str(tmp_path / "sessions"),
                    "inbox_dir": str(tmp_path / "inbox"),
                    "secrets_dir": str(tmp_path / "secrets"),
                },
                "sources": {"byr": {"enabled": True}},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BUPT_INSIGHT_CONFIG", str(config))
    bundle = write_bundle(tmp_path, [entry()])
    assert cli.main(["portal", "import", str(bundle), "--keep"]) == 0
    import json as _json

    report = _json.loads(capsys.readouterr().out)
    assert report["new"] == 1
