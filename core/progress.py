"""Small local progress report for long scans. Contains no titles or credentials."""
import json
import os
from datetime import datetime, timezone

from core.config import resolve


def update(cfg, source, stage, **details):
    path = resolve(cfg, cfg["paths"]["data_dir"]) / "progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "source": source, "stage": stage, **details}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def read(cfg):
    path = resolve(cfg, cfg["paths"]["data_dir"]) / "progress.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
