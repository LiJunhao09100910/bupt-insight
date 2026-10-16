"""Outbox delivery. Accepted by API and received in WeChat are different states."""
import json
import os
import sys
import time
from dataclasses import dataclass

import requests

from core.security import get_secret


@dataclass
class Result:
    status: str
    detail: str
    receipt: str | None = None


def message(item, external=True):
    title = item["title"][:80]
    if item.get("private") and external:
        # A local summary can still contain private details; no automatic disclosure.
        body = f"来源：{item['channel']}\n发布时间：{item.get('published', '未知')}\n门户有一条新通知或正文更新，请在本地历史中心查看。"
    else:
        excerpt = item.get('body', '')[:450]
        if item.get("extra", {}).get("body_status") == "attachment_only":
            excerpt = "本通知以附件提供正文，请点击原文查看；附件内容尚未提取。"
        elif item.get("extra", {}).get("body_status") == "image_only":
            excerpt = "本通知以图片提供正文，请点击原文查看；图片文字尚未识别。"
        body = f"来源：{item['channel']}\n{item.get('published', '')}\n{excerpt}\n{item['url']}"
    return title, body[:1200]


def wechat(kind, title, body, token=None, post=None):
    token = token or get_secret(kind)
    if not token:
        return Result("failed", "缺少本地推送密钥，请运行 credentials token")
    post = post or requests.post
    if kind == "pushplus":
        url = "https://www.pushplus.plus/send"
        args = {"json": {"token": token, "title": title[:80], "content": body[:1200],
                         "template": "txt", "channel": "wechat"}}
    elif kind == "serverchan":
        if not token.startswith("SCT") or not token.isalnum():
            return Result("failed", "当前适配器仅支持 Turbo SCT SendKey；SCTP/其他版本需独立配置")
        url = f"https://sctapi.ftqq.com/{token}.send"
        args = {"data": {"title": title[:80], "desp": body[:1200]}}
    else:
        return Result("failed", "未知微信渠道")
    try:
        response = post(url, timeout=(8, 20), allow_redirects=False, **args)
        if response.status_code >= 500:
            return Result("unknown", "服务端异常，是否受理未知；请核对后再决定重试")
        if response.status_code != 200:
            return Result("failed", f"推送接口 HTTP {response.status_code}")
        data = response.json()
        code = data.get("code")
        ok = (kind == "pushplus" and code == 200) or (kind == "serverchan" and code == 0)
        if not ok:
            # Do not persist server message: it can echo token, URL or payload.
            return Result("failed", "推送服务业务拒绝（请在服务官网核对密钥、配额和订阅状态）")
        receipt = data.get("data")
        if isinstance(receipt, dict):
            receipt = receipt.get("pushid")
        if not isinstance(receipt, (str, int)):
            receipt = None
        return Result("accepted", "服务端已受理，微信接收尚未确认", str(receipt) if receipt else None)
    except requests.ConnectTimeout:
        return Result("failed", "连接超时，未发送正文，可重试")
    except (requests.RequestException, ValueError, TypeError):
        return Result("unknown", "发送结果不确定；避免自动重发，请在微信和服务后台核对")


def desktop(title, body, url=""):
    if sys.platform != "win32":
        return Result("failed", "当前不是 Windows，消息已保存在数据库")
    try:
        import ctypes
        if not ctypes.windll.user32.GetShellWindow():
            return Result("failed", "没有交互式桌面，消息已保存在数据库")
        # Encode XML as data. Never interpolate scraped text into PowerShell source.
        import subprocess
        import base64
        from urllib.parse import urlsplit
        from xml.etree.ElementTree import Element, SubElement, tostring
        attrs = {"duration": "short"}
        if urlsplit(url).scheme in ("https", "http"):
            attrs.update(activationType="protocol", launch=url)
        root = Element("toast", attrs)
        binding = SubElement(SubElement(root, "visual"), "binding", {"template": "ToastGeneric"})
        SubElement(binding, "text").text = title[:80]
        SubElement(binding, "text").text = body[:450]
        encoded = base64.b64encode(tostring(root, encoding="utf-8")).decode("ascii")
        script = """$ErrorActionPreference='Stop';
        [Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] > $null;
        [Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime] > $null;
        $xml=New-Object Windows.Data.Xml.Dom.XmlDocument;
        $xml.LoadXml([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('""" + encoded + """')));
        $toast=[Windows.UI.Notifications.ToastNotification]::new($xml);
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('BUPT Insight').Show($toast);
        """
        completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                   capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        if completed.returncode != 0 or completed.stderr:
            return Result("failed", "Windows 通知提交失败，消息已保存在数据库")
        return Result("submitted", "已提交 Windows 通知中心；是否显示取决于系统通知设置")
    except Exception:
        return Result("failed", "桌面通知不可用，消息已保存在数据库")


def check_receipt(receipt, access_key=None, get=None):
    """Official read-only PushPlus receipt API; status=2 is provider delivery, not a read receipt."""
    access_key = access_key or get_secret("pushplus_access_key")
    if not access_key:
        return Result("accepted", "缺少 PushPlus AccessKey；可在微信确认收到后执行 delivery confirm")
    try:
        response = (get or requests.get)("https://www.pushplus.plus/api/open/message/sendMessageResult",
              params={"shortCode": receipt}, headers={"access-key": access_key}, timeout=(8, 20), allow_redirects=False)
        payload = response.json()
        if response.status_code != 200 or payload.get("code") != 200:
            return Result("accepted", "回执查询失败，保留已受理状态")
        status = payload.get("data", {}).get("status")
        return Result({0: "accepted", 1: "accepted", 2: "provider_delivered", 3: "failed"}.get(status, "accepted"),
                      "官方回执已查询；provider_delivered 表示服务报告已发送，仍不代表用户阅读", receipt)
    except Exception:
        return Result("accepted", "回执查询网络失败，保留已受理状态")


def enabled(cfg):
    channels = cfg.get("push", {}).get("channels", {})
    return [name for name in ("pushplus", "serverchan", "desktop") if channels.get(name, {}).get("enabled")]


def dispatch(cfg, db, sender=None, notice_id=None):
    channels = enabled(cfg)
    results = []
    digest_members = []
    for row in db.pending(channels):
        if notice_id and row["notice_id"] != notice_id:
            continue
        item = json.loads(row["payload"])
        channel = row["channel"]
        title, body = message(item, external=channel != "desktop")
        try:
            from core.smart import enrich
            policy, enriched = enrich(cfg, db, row, item)
        except Exception:
            policy, enriched = 'immediate', None
        if policy == 'archive':
            db.delivery(row['id'], 'archived', '匹配本人不感兴趣项；已存本地历史')
            results.append({'id': row['id'], 'channel': channel, 'status': 'archived'})
            continue
        if policy == 'digest' and notice_id is None:
            digest_members.append((row, item, enriched))
            continue
        if enriched:
            title, body = enriched
        result = Result("failed", "未尝试")
        for attempt in range(max(1, cfg.get("push", {}).get("retries", 3))):
            db.delivery(row["id"], "sending", attempt=True)
            try:
                if sender:
                    result = sender(channel, title, body, item["url"])
                else:
                    result = desktop(title, body, item["url"]) if channel == "desktop" else wechat(channel, title, body)
            except Exception:
                result = Result("unknown", "发送器异常，结果未知，需人工核对")
            db.delivery(row["id"], result.status, result.detail, result.receipt)
            if result.status != "failed":
                break
            if attempt + 1 < cfg.get("push", {}).get("retries", 3):
                time.sleep(min(2 ** attempt, 8))
        results.append({"id": row["id"], "channel": channel, **result.__dict__})
    if digest_members:
        from core.smart import queue_digest
        queue_digest(db, digest_members)
    if 'desktop' in channels and notice_id is None:
        # No AI import is needed for an ordinary base notification.
        has_digests = db.db.execute("SELECT 1 FROM digest_batches WHERE status IN ('pending','failed') LIMIT 1").fetchone()
        if has_digests:
            from core.smart import dispatch_digests
            results.extend(dispatch_digests(db, sender))
    return results
