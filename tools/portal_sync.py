"""One command: log in to the portal, export a bundle, upload and import it.

Run on a machine that can reach the campus portal:

    python -X utf8 tools/portal_sync.py --save-credentials   # once, encrypted
    python -X utf8 tools/portal_sync.py

Default transport is direct HTTP/CAS (the portal iframe often renders blank in
automation). `login.mode: browser` keeps the Playwright path as a fallback.

Defaults are relative to this repository: `portal_client.yaml` for the client
config and `portal-out/` for the generated bundle.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from core.secrets import EncryptedStore, load_master_key  # noqa: E402
from tools.portal_export import build_bundle  # noqa: E402


def resolve(value, default: Path) -> Path:
    if value is None:
        return default
    path = Path(value).expanduser()
    return path if path.is_absolute() else (Path.cwd() / path)


def resolve_repo(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (ROOT / path)


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"找不到配置文件：{path}（先复制 portal_client.example.yaml）")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def credentials_store(cfg: dict) -> EncryptedStore:
    login = cfg.get("login") or {}
    return EncryptedStore(
        resolve_repo(login.get("credentials_file", "secrets/portal.enc")),
        resolve_repo(login.get("key_file", "secrets/portal.key")),
        "portal-credentials",
    )


def save_credentials(cfg: dict) -> int:
    if not sys.stdin or not sys.stdin.isatty():
        raise SystemExit("请在交互式终端运行 --save-credentials（密码不回显）")
    username = input("门户账号：").strip()
    password = getpass.getpass("门户密码（不回显）：")
    if not username or not password:
        raise SystemExit("账号或密码为空")
    store = credentials_store(cfg)
    load_master_key(store.key_path, create=True)
    store.write({"username": username, "password": password, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    print(f"已加密保存到 {store.path}（与密钥文件分开存放）")
    return 0


def load_credentials(cfg: dict, allow_prompt: bool = True) -> tuple[str, str]:
    login = cfg.get("login") or {}
    username = str(login.get("username") or "").strip()
    password = str(login.get("password") or "")
    if username and password:
        return username, password
    store = credentials_store(cfg)
    if store.exists():
        value = store.read()
        return str(value.get("username") or ""), str(value.get("password") or "")
    if allow_prompt and sys.stdin and sys.stdin.isatty():
        print("未找到已保存凭据，本次手动输入（可用 --save-credentials 加密保存）。")
        return input("门户账号：").strip(), getpass.getpass("门户密码（不回显）：")
    return "", ""


def export_bundle(cfg: dict, args) -> dict:
    mode = str((cfg.get("login") or {}).get("mode") or "http").lower()
    if mode == "browser":
        return build_bundle(cfg, args)
    from tools import portal_http

    username, password = load_credentials(cfg)
    if not username or not password:
        raise SystemExit(
            "缺少门户凭据：在 portal_client.yaml 的 login.username/password 填写，"
            "或先运行 python -X utf8 tools/portal_sync.py --save-credentials"
        )
    print(f"使用账号 {username} 通过统一认证登录…", flush=True)
    session = portal_http.login(cfg, username, password, timeout=int((cfg.get("login") or {}).get("timeout", 25)))
    print("登录成功，开始抓取。", flush=True)
    return portal_http.export(cfg, args, session)


def write_bundle(data: dict, args) -> Path:
    outdir = resolve(args.out_dir, ROOT / "portal-out")
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"portal-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    stats = data["stats"]
    print(
        f"\n已导出 {stats['items']} 条（正文 {stats['ok']}，附件 {stats['attachment_only']}，"
        f"图片 {stats['image_only']}，失败 {stats['body_failed']}）"
    )
    if stats["errors"]:
        print("部分错误：", "; ".join(stats["errors"][:5]))
    return path


def remote_script(server: dict, name: str) -> str:
    service_user = server.get("service_user", "bupt")
    app_dir = server["app_dir"]
    inbox = server["inbox"]
    python = server.get("python", "/usr/bin/python3")
    extra = " ".join(shlex.quote(item) for item in server.get("import_args") or [])
    target = f"{inbox}/{name}"
    inner = (
        f"sudo -n install -o {shlex.quote(service_user)} -g {shlex.quote(service_user)} "
        f"-m 600 {shlex.quote('/tmp/' + name)} {shlex.quote(target)} && "
        f"cd {shlex.quote(app_dir)} && "
        f"sudo -n -u {shlex.quote(service_user)} {shlex.quote(python)} -X utf8 "
        f"run.py portal import {shlex.quote(target)} {extra}; "
        f"rc=$?; sudo -n rm -f {shlex.quote('/tmp/' + name)}; exit $rc"
    )
    return inner


def upload_paramiko(server: dict, bundle: Path) -> tuple[int, str, str]:
    import paramiko

    host = server["host"]
    user = server["user"]
    port = int(server.get("port", 22))
    name = bundle.name
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    options = dict(port=port, username=user, timeout=20, banner_timeout=25, auth_timeout=25)
    password = os.environ.get("PORTAL_SSH_PASSWORD")
    try:
        if password:
            client.connect(host, password=password, look_for_keys=False, allow_agent=False, **options)
        else:
            try:
                client.connect(host, look_for_keys=True, allow_agent=True, **options)
            except paramiko.AuthenticationException:
                password = getpass.getpass(f"{user}@{host} 密码（不保存）：")
                client.connect(host, password=password, look_for_keys=False, allow_agent=False, **options)
    except Exception as exc:
        raise SystemExit(f"SSH 连接失败：{type(exc).__name__}；检查 host/user/端口或改用密钥登录") from None
    try:
        sftp = client.open_sftp()
        sftp.put(str(bundle), f"/tmp/{name}")
        sftp.close()
        stdin, stdout, stderr = client.exec_command(
            "bash -lc " + shlex.quote(remote_script(server, name)), timeout=300
        )
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err
    finally:
        client.close()


def upload_cli(server: dict, bundle: Path) -> tuple[int, str, str]:
    host = server["host"]
    user = server["user"]
    port = str(server.get("port", 22))
    name = bundle.name
    uploaded = subprocess.run(
        ["scp", "-P", port, str(bundle), f"{user}@{host}:/tmp/{name}"],
        capture_output=True,
        text=True,
    )
    if uploaded.returncode != 0:
        return uploaded.returncode, uploaded.stdout, uploaded.stderr
    remote = subprocess.run(
        ["ssh", "-p", port, f"{user}@{host}", "bash -lc " + shlex.quote(remote_script(server, name))],
        capture_output=True,
        text=True,
    )
    return remote.returncode, remote.stdout, remote.stderr


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="导出信息门户 → 上传 → 服务器导入")
    parser.add_argument("--config", default=None, help="默认 portal_client.yaml（仓库根目录）")
    parser.add_argument("--bundle", default=None, help="跳过导出，直接上传已有 bundle")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--max", type=int, default=300)
    parser.add_argument("--out-dir", default=None, help="默认 portal-out/（仓库根目录）")
    parser.add_argument("--no-upload", action="store_true", help="只导出，不上传")
    parser.add_argument("--save-credentials", action="store_true", help="交互输入门户账号并加密保存后退出")
    parser.add_argument("--host", default=None, help="覆盖 server.host")
    parser.add_argument("--user", default=None, help="覆盖 server.user")
    args = parser.parse_args(argv)

    config_path = resolve(args.config, ROOT / "portal_client.yaml")
    cfg = load_config(config_path)

    if args.save_credentials:
        return save_credentials(cfg)

    if args.bundle:
        bundle = resolve(args.bundle, ROOT / "portal-out" / "bundle.json")
        if not bundle.exists():
            raise SystemExit(f"找不到 bundle：{bundle}")
    else:
        if not cfg.get("lists"):
            raise SystemExit("配置里没有 lists，无法导出")
        data = export_bundle(cfg, args)
        if not data["items"]:
            raise SystemExit("没有抓到任何条目（检查 lists[].url 与选择器），未上传")
        bundle = write_bundle(data, args)

    print(f"本地 bundle：{bundle}")
    if args.no_upload:
        print("已跳过上传（--no-upload）。")
        return 0

    server = dict(cfg.get("server") or {})
    if args.host:
        server["host"] = args.host
    if args.user:
        server["user"] = args.user
    if not server.get("host") or not server.get("user") or not server.get("app_dir") or not server.get("inbox"):
        raise SystemExit("配置缺少 server.host/user/app_dir/inbox")

    print(f"上传到 {server['user']}@{server['host']}:{server.get('port', 22)} …")
    try:
        import paramiko  # noqa: F401

        code, out, err = upload_paramiko(server, bundle)
    except ImportError:
        print("未安装 paramiko，回退到系统 scp/ssh（可能需要输入两次密码）。")
        code, out, err = upload_cli(server, bundle)

    if out.strip():
        try:
            print(json.dumps(json.loads(out), ensure_ascii=False, indent=2))
        except ValueError:
            print(out.strip())
    if err.strip():
        print(err.strip(), file=sys.stderr)
    if code != 0:
        print(f"服务器导入失败（exit {code}）")
        return code
    print("导入完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
