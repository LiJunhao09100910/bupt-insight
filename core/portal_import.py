"""Import manually exported portal bundles.

The server never authenticates to the portal. A machine inside the campus
network exports a signed-by-hash JSON bundle; this module validates it and
feeds the same notices/versions pipeline as BYR.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from core.database import now
from core.errors import InsightError
from core.schema import Item

FORMAT = "bupt-portal-bundle"
VERSION = 1
BODY_STATUS = {"ok", "attachment_only", "image_only", "body_failed"}
MAX_ITEMS = 2000


def _canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in ("ticket", "jsessionid") and not k.lower().startswith("utm_")
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), urlencode(sorted(query)), parts.fragment))


def bundle_digest(items: list) -> str:
    """Stable hash of the payload; the upload carries it so tampering is visible."""
    payload = {"format": FORMAT, "version": VERSION, "items": items}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_bundle(path) -> tuple[dict, str]:
    source = Path(path)
    if not source.exists():
        raise InsightError("bundle_missing", f"找不到 bundle：{source}")
    raw = source.read_bytes()
    if source.suffix == ".gz":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            raise InsightError("bundle_invalid", "gzip 解压失败") from None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise InsightError("bundle_invalid", "bundle 不是合法的 UTF-8 JSON") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise InsightError("bundle_invalid", f"不是 {FORMAT} 文件")
    if data.get("version") != VERSION:
        raise InsightError("bundle_invalid", f"不支持的 bundle 版本：{data.get('version')}")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise InsightError("bundle_invalid", "bundle 里没有 items")
    if len(items) > MAX_ITEMS:
        raise InsightError("bundle_invalid", f"items 超过上限 {MAX_ITEMS}")
    digest = bundle_digest(items)
    declared = str(data.get("bundle_id") or "")
    if declared and declared != digest:
        raise InsightError("bundle_tampered", "bundle_id 与内容不一致，文件可能被修改")
    return data, digest


def _entry_to_item(entry: dict, digest: str) -> Item:
    if not isinstance(entry, dict):
        raise InsightError("bundle_invalid", "items 中存在非对象条目")
    title = str(entry.get("title") or "").strip()
    url = str(entry.get("url") or "").strip()
    if not title or not url:
        raise InsightError("bundle_invalid", "条目缺少 title 或 url")
    status = str(entry.get("body_status") or "ok")
    if status not in BODY_STATUS:
        raise InsightError("bundle_invalid", f"未知 body_status：{status}")
    attachments = []
    for attachment in entry.get("attachments") or []:
        name = str(attachment.get("name") or "").strip()
        link = str(attachment.get("url") or "").strip()
        if name and link:
            attachments.append({"name": name[:200], "url": _canonical_url(link)})
    return Item(
        source="portal",
        channel=str(entry.get("department") or entry.get("list") or "信息门户")[:100],
        title=title[:400],
        url=_canonical_url(url),
        published=str(entry.get("published") or "")[:40],
        body=str(entry.get("body") or ""),
        private=True,
        extra={
            "body_status": status,
            "attachments": attachments,
            "portal_list": str(entry.get("list") or "")[:100],
            "bundle_id": digest,
            "fetched_at": str(entry.get("fetched_at") or ""),
        },
    )


def import_bundle(cfg, db, path, force: bool = False, channels=()) -> dict:
    data, digest = load_bundle(path)
    if not force and db.bundle_imported(digest):
        return {
            "status": "already_imported",
            "bundle_id": digest,
            "generated_at": data.get("generated_at", ""),
            "message": "该 bundle 已导入过；内容未变时重复上传不会产生新版本",
        }

    counts = {"new": 0, "changed": 0, "unchanged": 0}
    errors = []
    items = []
    for index, entry in enumerate(data["items"], start=1):
        try:
            item = _entry_to_item(entry, digest)
        except InsightError as exc:
            errors.append(f"item {index}: {exc.status}")
            continue
        items.append(item)
        change = db.upsert(item, channels=channels)
        counts[change] += 1

    run = db.start_run("portal")
    status = "ok" if not errors else ("partial_failed" if items else "failed")
    db.finish_run(run, status, counts, errors)
    db.record_bundle(digest, str(path), len(items), counts, errors)
    return {
        "status": status,
        "bundle_id": digest,
        "generated_at": data.get("generated_at", ""),
        "items": len(items),
        **counts,
        "errors": errors,
        "imported_at": now(),
    }
