from core.config import resolve
from core.database import Database
from core.errors import safe_error
from core.locking import single_run
from core.notifications import dispatch, enabled
from core.progress import update as progress


def database_path(cfg):
    # Keep old account history/outboxes separate when credentials are replaced.
    import json
    import re
    from core.security import get_secret
    saved = get_secret("portal")
    scope = json.loads(saved).get("scope", "default") if saved else "default"
    if scope != "default" and not re.fullmatch(r"[0-9a-f]{32}", scope):
        from core.errors import InsightError
        raise InsightError("credentials_invalid", "本地凭据作用域无效，请重新保存")
    return resolve(cfg, cfg["paths"]["data_dir"]) / scope / "insight.sqlite3"


def database(cfg):
    return Database(database_path(cfg))


def sync(cfg, names=None, push=False, baseline=False, boards=None, fetchers=None):
    from sources import get
    names = names or [k for k in ("portal", "byr") if cfg["sources"][k].get("enabled")]
    report = {"sources": {}, "deliveries": []}
    with single_run(resolve(cfg, cfg["paths"]["data_dir"]) / "run.lock"):
        db = database(cfg)
        try:
            db.recover()
            for name in names:
                progress(cfg, name, "starting")
                run = db.start_run(name)
                counts = {"new": 0, "changed": 0, "unchanged": 0}
                errors = []
                try:
                    fetch = fetchers[name] if fetchers else get(name).fetch
                    fetched, _, errors = fetch(cfg, only=boards if name == "byr" else None, quiet=True)
                    for items in fetched.values():
                        for item in items:
                            change = db.upsert(item, channels=enabled(cfg), baseline=baseline)
                            counts[change] += 1
                    status = "partial_failed" if errors and sum(counts.values()) else (
                        "failed" if errors else ("no_new" if not counts["new"] and not counts["changed"] else "ok"))
                    if errors and not sum(counts.values()) and any("login_expired" in x for x in errors):
                        status = "login_expired"
                except (Exception, SystemExit) as exc:
                    status, message = safe_error(exc)
                    errors.append(message)
                db.finish_run(run, status, counts, errors)
                report["sources"][name] = {"status": status, **counts, "errors": errors}
                progress(cfg, name, "source_finished", status=status, **counts)
            if push and not baseline:
                try:
                    from core.analysis import run_pending
                    report['analysis'] = run_pending(cfg, db)
                except Exception:
                    report['analysis'] = {'status': 'failed', 'message': '分析不可用，继续基础提醒'}
                progress(cfg, "deliveries", "pushing")
                report["deliveries"] = dispatch(cfg, db)
            try:
                from core.backup import automatic
                report['backup'] = automatic(database_path(cfg), cfg.get('backup', {}))
            except Exception:
                report['backup'] = {'status': 'failed', 'message': '自动备份失败，原库保留；请检查空间和权限'}
            from core.health import inspect
            report['health'] = inspect(cfg, db)
            progress(cfg, "all", "completed")
        finally:
            db.close()
    return report
