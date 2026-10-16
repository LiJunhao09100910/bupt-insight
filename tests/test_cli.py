import pytest

from core.cli import main
from core.locking import single_run
from core.pipeline import database
from core.notifications import dispatch, Result


def test_credentials_mutation_refused_during_sync(cfg, monkeypatch, capsys):
    monkeypatch.setattr("core.cli.load_config", lambda: cfg)
    from pathlib import Path
    with single_run(Path(cfg["paths"]["data_dir"]) / "run.lock"):
        assert main(["credentials", "save"]) == 1
    assert "already_running" in capsys.readouterr().out


def test_test_push_does_not_send_existing_private_outbox(cfg, notice, monkeypatch, capsys):
    monkeypatch.setattr("core.cli.load_config", lambda: cfg)
    monkeypatch.setattr("core.security.get_secret", lambda _: None)
    db = database(cfg)
    db.upsert(notice, ["desktop"])
    db.close()
    sent = []
    def desktop(title, body, url):
        sent.append(title)
        return Result("submitted", "fictional-test")
    monkeypatch.setattr("core.notifications.desktop", desktop)
    assert main(["test-push", "desktop"]) == 0
    assert sent == ["BUPT Insight 通知测试"]
    db = database(cfg)
    assert len(db.pending(["desktop"])) == 1
    db.close()


def test_disabled_desktop_leaves_notification_durable(cfg, notice, monkeypatch):
    monkeypatch.setattr("core.security.get_secret", lambda _: None)
    cfg["push"]["channels"]["desktop"]["enabled"] = False
    db = database(cfg)
    db.upsert(notice, ["desktop"])
    results = dispatch(cfg, db, sender=lambda *a: pytest.fail("关闭的桌面渠道不应调用"))
    assert results == [] and db.status()["notices"] == 1
    db.close()


def test_status_remains_readable_while_sync_locked(cfg, monkeypatch, capsys):
    from pathlib import Path
    monkeypatch.setattr("core.cli.load_config", lambda: cfg)
    monkeypatch.setattr("core.security.get_secret", lambda _: None)
    with single_run(Path(cfg["paths"]["data_dir"]) / "run.lock"):
        assert main(["status"]) == 0
    assert '"notices"' in capsys.readouterr().out


@pytest.mark.parametrize("source", ["portal", "byr", "all"])
def test_logout_clears_only_selected_local_sessions(cfg, monkeypatch, source):
    from pathlib import Path
    monkeypatch.setattr("core.cli.load_config", lambda: cfg)
    folder = Path(cfg["paths"]["session_dir"])
    folder.mkdir(parents=True)
    portal = folder / "portal.bin"
    byr = folder / "byr.bin"
    legacy = folder / "byr.json"
    for path in (portal, byr, legacy):
        path.write_bytes(b"fictional-not-opened")
    assert main(["logout", source]) == 0
    assert portal.exists() == (source == "byr")
    assert byr.exists() == (source == "portal")
    assert legacy.exists() == (source == "portal")
