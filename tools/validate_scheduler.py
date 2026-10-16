"""One real Task Scheduler run with small samples; restore production config afterward."""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.config import ROOT, load_config, resolve
from core.locking import single_run
from core.pipeline import database


def powershell(script):
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
    if result.returncode:
        raise RuntimeError("Windows Task Scheduler 操作失败，原始输出未记录")
    return result.stdout.strip()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='docs/scheduler-live-validation.json')
    args = parser.parse_args()
    output_path = (ROOT / args.output).resolve()
    if not output_path.is_relative_to(ROOT / 'docs'):
        raise RuntimeError('验收输出必须位于项目docs目录')
    cfg = load_config()
    lock = resolve(cfg, cfg["paths"]["data_dir"]) / "run.lock"
    config_path = ROOT / "config.yaml"
    backup = resolve(cfg, cfg["paths"]["data_dir"]) / "scheduler-config-backup.yaml"
    original = config_path.read_bytes()
    db = database(cfg)
    try:
        previous_run_id = db.db.execute("SELECT COALESCE(MAX(id),0) FROM sync_runs").fetchone()[0]
    finally:
        db.close()
    before = json.loads(powershell("$t=Get-ScheduledTask -TaskName BUPTInsight -ErrorAction Stop; $i=Get-ScheduledTaskInfo -TaskName BUPTInsight; @{state=[string]$t.State;last_run=$i.LastRunTime.ToString('o')} | ConvertTo-Json -Compress"))
    if before["state"] == "Running":
        raise RuntimeError("已有计划任务在运行，未修改配置")
    result = {"date": datetime.now().astimezone().date().isoformat(), "sample_run": {"portal_rows": 1, "byr_board": "Paper", "byr_rows": 1}, "production_config_restored": False}
    with single_run(lock):
        backup.write_bytes(original)
        cfg["sources"]["portal"]["rows_per_list"] = 1
        cfg["sources"]["byr"]["rows_per_board"] = 1
        cfg["sources"]["byr"]["boards"] = ["Paper"]
        config_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    try:
        powershell("Start-ScheduledTask -TaskName BUPTInsight -ErrorAction Stop")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            time.sleep(3)
            snapshot = json.loads(powershell("$t=Get-ScheduledTask -TaskName BUPTInsight; $i=Get-ScheduledTaskInfo -TaskName BUPTInsight; @{state=[string]$t.State;last_run=$i.LastRunTime.ToString('o');last_result=$i.LastTaskResult;next_run=$i.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss');trigger_count=$t.Triggers.Count;logon_type=[string]$t.Principal.LogonType} | ConvertTo-Json -Compress"))
            if snapshot["last_run"] != before["last_run"] and snapshot["state"] != "Running":
                result["scheduler"] = snapshot
                db = database(cfg)
                try:
                    runs = [dict(r) for r in db.db.execute("SELECT id,source,status,total FROM sync_runs WHERE id>? ORDER BY id", (previous_run_id,))]
                finally:
                    db.close()
                result["observed_sync_runs"] = runs
                expected = {name for name in ("portal", "byr") if cfg["sources"][name].get("enabled")}
                completed = {r["source"] for r in runs if r["status"] in ("ok", "no_new") and r["total"] > 0}
                result["passed"] = snapshot["last_result"] == 0 and expected <= completed
                break
        else:
            raise RuntimeError("计划任务样本运行超过180秒；未停止任务")
    finally:
        # A running sync keeps its loaded config. Restoring the file does not alter that run.
        config_path.write_bytes(original)
        result["production_config_restored"] = config_path.read_bytes() == original
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
