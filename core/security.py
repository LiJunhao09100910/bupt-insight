"""Windows-only secrets and DPAPI state. No plaintext fallback."""
import getpass
import json
import os
import sys
from pathlib import Path

from core.errors import InsightError

SERVICE = "BUPTInsight"


def vault():
    if sys.platform != "win32":
        raise InsightError("unsupported", "凭据存储仅启用 Windows Credential Manager")
    from keyring.backends.Windows import WinVaultKeyring
    return WinVaultKeyring()


def get_secret(name):
    return vault().get_password(SERVICE, name)


def put_secret(name, value):
    vault().set_password(SERVICE, name, value)


def delete_secret(name):
    from keyring.errors import PasswordDeleteError
    try:
        vault().delete_password(SERVICE, name)
    except PasswordDeleteError:
        pass


def credentials():
    payload = get_secret("portal")
    if not payload:
        raise InsightError("credentials_missing", "请先运行 python run.py credentials save，在本地输入账号密码")
    return json.loads(payload)


def save_credentials():
    if not sys.stdin.isatty():
        raise InsightError("interaction_required", "请在本机交互式终端保存凭据")
    account = getpass.getpass("学号（输入不可见）：").strip()
    password = getpass.getpass("统一认证密码（输入不可见）：")
    if not account or not password:
        raise InsightError("credentials_missing", "账号和密码不能为空")
    from uuid import uuid4
    existing = get_secret("portal")
    old = json.loads(existing) if existing else {}
    scope = old.get("scope") if old.get("account") == account else None
    put_secret("portal", json.dumps({"account": account, "password": password,
                                    "scope": scope or uuid4().hex}))


def write_state(path, state):
    if sys.platform != "win32":
        raise InsightError("unsupported", "会话文件要求 Windows DPAPI，禁止明文降级")
    import win32crypt
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(state, ensure_ascii=False).encode("utf-8")
    encrypted = win32crypt.CryptProtectData(raw, "BUPT Insight session", None, None, None, 1)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encrypted)
    os.replace(temporary, path)


def read_state(path, allow_legacy=False):
    path = Path(path)
    if not path.exists():
        return None
    if allow_legacy and path.suffix == ".json":
        # Only the original BYR snapshot format is accepted; new writes use DPAPI.
        return json.loads(path.read_text(encoding="utf-8"))
    if sys.platform != "win32":
        raise InsightError("unsupported", "当前系统无法解密 Windows 会话")
    import win32crypt
    try:
        raw = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 1)[1]
        return json.loads(raw.decode("utf-8"))
    except Exception:
        raise InsightError("session_invalid", "会话无法解密或已损坏，请重新登录") from None
