import argparse
import getpass
import json
import shutil
import subprocess
import sys
from pathlib import Path

from core.config import ROOT, load_config, resolve
from core.errors import InsightError, safe_error
from core.pipeline import database, sync
from core.security import save_credentials, put_secret, delete_secret


def output(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def parser():
    ap = argparse.ArgumentParser(description="BUPT Insight：本地校园通知助手")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="创建无密码配置")
    web=sub.add_parser('web',help='启动只监听本机的校园信息网页')
    web.add_argument('--port',type=int,default=8765)
    web.add_argument('--open',action='store_true',help='启动后打开浏览器')
    cred = sub.add_parser("credentials", help="管理 Windows 安全凭据")
    cred.add_argument("action", choices=["save", "clear", "token"])
    cred.add_argument("--channel", choices=["pushplus", "serverchan", "pushplus_access_key"])
    login = sub.add_parser("login", help="认证并测试读取真实业务内容")
    login.add_argument("source", choices=["portal", "byr"])
    login.add_argument("--interactive", action="store_true")
    login.add_argument("--mode", choices=["browser", "http", "auto"])
    portal = sub.add_parser("portal", help="门户适配校准")
    portal.add_argument("action", choices=["inspect", "test", "probe"])
    portal.add_argument("--interactive", action="store_true")
    portal.add_argument("--mode", choices=["browser", "http", "auto"])
    scan = sub.add_parser("scan", help="独立扫描门户/BYR；新正文版本写入 SQLite")
    scan.add_argument("sources", nargs="*", metavar="SOURCE")
    scan.add_argument("--boards", help="BYR 版面代号，逗号分隔")
    scan.add_argument("--push", action="store_true")
    scan.add_argument("--baseline", action="store_true", help="建立基线，不发送已有通知")
    sub.add_parser("push", help="发送待处理队列，重试明确失败渠道")
    test = sub.add_parser("test-push", help="发送虚构测试通知；不会发送私有通知正文")
    test.add_argument("channel", choices=["pushplus", "serverchan", "desktop"])
    sub.add_parser("status", help="检查采集状态和推送队列")
    history = sub.add_parser("history", help="查看本地历史通知")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--id", help="本地查看指定通知全文")
    logout = sub.add_parser("logout", help="清除本地会话；可同时清除凭据")
    logout.add_argument("source", choices=["portal", "byr", "all"])
    logout.add_argument("--clear-credentials", action="store_true")
    delivery = sub.add_parser("delivery", help="查看/确认接收/查询回执/人工重试未知结果")
    delivery.add_argument("action", choices=["list", "confirm", "check", "retry"])
    delivery.add_argument("id", nargs="?", type=int)
    schedule = sub.add_parser("schedule", help="注册 Windows Task Scheduler 任务")
    schedule.add_argument("action", choices=["install", "remove"])
    schedule.add_argument("--times", default="07:30,12:30,19:00")
    backup = sub.add_parser('backup', help='在线备份、校验和带防覆盖确认的恢复')
    backup.add_argument('action', choices=['create', 'list', 'verify', 'restore', 'recover-copy'])
    backup.add_argument('name', nargs='?')
    backup.add_argument('--confirm', help='恢复预览提供的当前数据库SHA256指纹')
    sub.add_parser('health', help='检查各来源最近成功采集和长期无数据状态')
    profile = sub.add_parser('profile', help='初始化或校验本地个人画像')
    profile.add_argument('action', choices=['init', 'validate', 'path'])
    ai = sub.add_parser('ai', help='离线演示、分析、查看本地分析、评估或保存模型密钥')
    ai.add_argument('action', choices=['demo', 'analyze', 'show', 'evaluate', 'key'])
    ai.add_argument('--id', help='指定本地通知ID')
    ai.add_argument('--limit', type=int, default=3)
    ai.add_argument('--mode', choices=['off', 'mock', 'api'])
    ai.add_argument('--notify', action='store_true', help='demo时发送并记录一条虚构智能桌面提醒')
    feedback=sub.add_parser('feedback',help='记录本人对当前通知版本的反馈，不重发通知')
    feedback.add_argument('action',choices=['add','list'])
    feedback.add_argument('--id')
    feedback.add_argument('--label',choices=['important','relevant','irrelevant','unsure'])
    feedback.add_argument('--quality',type=int,choices=range(1,6))
    recommend=sub.add_parser('recommend',help='本地预览相关性与证据，不弹窗')
    recommend.add_argument('--id')
    recommend.add_argument('--limit',type=int,default=20)
    evaluation=sub.add_parser('evaluate',help='冻结真实历史、标注并对比规则与API；仅本地保存')
    evaluation.add_argument('action',choices=['freeze','run','label','rate','list'])
    evaluation.add_argument('batch',nargs='?')
    evaluation.add_argument('--sample')
    evaluation.add_argument('--label',choices=['important','relevant','irrelevant','unsure'])
    evaluation.add_argument('--method',choices=['all','legacy','interest','api'],default='all')
    evaluation.add_argument('--limit',type=int,default=40)
    evaluation.add_argument('--score',type=int,choices=range(0,6))
    return ap


def portal_inspect(cfg, interactive):
    from core.portal_auth import PortalAuthenticator
    from bs4 import BeautifulSoup
    if not interactive:
        raise InsightError("interaction_required", "inspect 需要 --interactive：在浏览器导航到真实通知列表")
    if cfg["sources"]["portal"].get("auth_mode") == "http":
        auth = PortalAuthenticator(cfg)
        client = auth.http_session(verify=False)
        try:
            response = auth.landing
            while True:
                soup = BeautifulSoup(response.content, "html.parser")
                output({"status": "captured_unverified", "url_without_query": response.url.split("?")[0],
                        "structure": [{"tag": t.name, "id": t.get("id"), "class": t.get("class", [])}
                                      for t in soup.select("table[id], ul[id], div[id], iframe")[:80]]})
                print("未完成身份/通知验收。可在本地输入本人门户通知/iframe列表URL继续检查；直接 Enter 保存未校准会话并结束。")
                target = input().strip()
                if not target:
                    break
                from sources.portal import clean_link
                response = client.request("GET", clean_link(target))
            auth.save_http(client)
            print("已保存未校准的加密 HTTP 会话。请配置真实选择器后运行 portal test --mode http。")
        finally:
            client.session.close()
        return
    with PortalAuthenticator(cfg).open_browser(interactive=True) as browser:
        print("已进入门户。请导航至通知列表，完成后回到此终端按 Enter。尚未宣布登录/采集验证通过。")
        input()
        print("页面结构（不输出 Cookie、动态参数或正文）：")
        for frame in browser.page.frames:
            from core.http import school_url
            try:
                school_url(frame.url)
            except InsightError:
                continue
            soup = BeautifulSoup(frame.content(), "html.parser")
            nodes = []
            for tag in soup.select("table[id], ul[id], div[id], iframe")[:80]:
                nodes.append({"tag": tag.name, "id": tag.get("id"), "class": tag.get("class", [])})
            output({"url_without_query": frame.url.split("?")[0], "structure": nodes})
        browser.save()
        print("已保存未校准的加密会话。请按 README 配置选择器，再执行 portal test；此操作不等于验证通过。")


def login_byr(cfg):
    from core.browser import login
    from core.config import load_config
    from sources.byr import JS_ROWS
    board = cfg["sources"]["byr"].get("boards", ["Paper"])[0]
    def probe(page):
        for cookie in page.context.cookies():
            if cookie["name"] in ("nforum[UTMPUSERID]", "login-user") and cookie["value"] not in ("", "guest"):
                return "logged-in-marker"
        return None
    def verify(page):
        page.goto(f"https://bbs.byr.cn/board/{board}", wait_until="domcontentloaded")
        page.wait_for_selector("table.board-list tr", timeout=20000)
        return bool(page.evaluate(JS_ROWS))
    if not login("byr", "https://bbs.byr.cn/index", probe=probe, verify=verify):
        raise InsightError("interaction_required", "BYR 登录未完成，未保存会话")



def credentials_command(args):
    if args.action == "save":
        save_credentials()
        # Credential/account change invalidates both auth implementations.
        if (ROOT / "config.yaml").exists():
            from core.portal_auth import PortalAuthenticator
            PortalAuthenticator(load_config()).logout()
        print("凭据已保存到当前 Windows 用户的 Credential Manager")
    elif args.action == "clear":
        delete_secret("portal")
        if (ROOT / "config.yaml").exists():
            from core.portal_auth import PortalAuthenticator
            PortalAuthenticator(load_config()).logout()
        print("学校凭据和门户会话已清除")
    else:
        if not args.channel:
            raise InsightError("configuration_error", "请指定 --channel")
        if not sys.stdin.isatty():
            raise InsightError("interaction_required", "请在本地交互式终端输入密钥")
        secret = getpass.getpass("推送密钥（输入不可见）：")
        if not secret:
            delete_secret(args.channel)
            print("推送密钥已清除")
        else:
            put_secret(args.channel, secret)
            print("推送密钥已保存；需在 config.yaml 启用该渠道")

def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.cmd == "init":
            dst = ROOT / "config.yaml"
            if dst.exists():
                print("config.yaml 已存在，保留现有配置")
            else:
                shutil.copyfile(ROOT / "config.example.yaml", dst)
                print(f"已创建 {dst}；未保存任何密码")
            return 0
        if args.cmd == "credentials":
            from core.locking import single_run
            if not (ROOT / "config.yaml").exists():
                raise InsightError("configuration_error", "请先运行 init 创建配置")
            credentials_cfg = load_config()
            with single_run(resolve(credentials_cfg, credentials_cfg["paths"]["data_dir"]) / "run.lock"):
                credentials_command(args)
            return 0
        cfg = load_config()
        if args.cmd=='web':
            from core.web import serve
            serve(args.port,args.open)
            return 0
        if args.cmd == 'backup':
            from core import backup
            from core.pipeline import database_path
            from core.locking import single_run
            path = database_path(cfg)
            with single_run(resolve(cfg, cfg['paths']['data_dir']) / 'run.lock'):
                if args.action == 'create':
                    output(backup.create(path))
                elif args.action == 'list':
                    output(backup.listing(path))
                else:
                    if not args.name:
                        raise InsightError('configuration_error', '请指定当前账号的备份文件名')
                    if args.action == 'verify':
                        output(backup.verify(path, args.name))
                    elif args.action == 'recover-copy':
                        output(backup.recover_copy(path, args.name))
                    else:
                        output(backup.restore(path, args.name, args.confirm))
            return 0
        if args.cmd == 'profile':
            from core import profile
            if args.action == 'init':
                output({'path': profile.initialize(cfg), 'status': 'created_blank'})
            elif args.action == 'path':
                output({'path': str(profile.path(cfg))})
            else:
                value = profile.load(cfg)
                output({'status': 'valid', 'fingerprint': value.fingerprint(), 'empty': value == profile.Profile()})
            return 0
        if args.cmd == 'ai' and args.action in ('demo', 'evaluate', 'key'):
            if args.action == 'key':
                if not sys.stdin.isatty():
                    raise InsightError('interaction_required', '请在本地交互式终端保存AI密钥')
                value = getpass.getpass('AI API Key（不回显，空输入删除）：')
                put_secret('llm_api_key', value) if value else delete_secret('llm_api_key')
                output({'status': 'saved' if value else 'cleared'})
            elif args.action == 'evaluate':
                from tools.evaluate_analysis import evaluate
                output(evaluate())
            else:
                if args.mode == 'api':
                    raise InsightError('configuration_error', 'demo仅离线演示；真实API请配置后使用ai analyze')
                from core.analysis import rules
                from core.profile import Profile
                item = {'title': '虚构研究助理招募', 'body': '虚构实验室招募科研助理。要求掌握Python。报名截止2026年11月20日。', 'source': 'test'}
                result = rules(item, Profile(skills=['Python'], goals=['科研']))
                output({'simulation': True, 'engine': 'mock-rules', 'result': result.model_dump()})
                if args.notify:
                    from core.locking import single_run
                    from core.schema import Item
                    from core.database import identity
                    from core.notifications import desktop
                    from core.smart import message
                    from uuid import uuid4
                    demo = Item(source='test', channel='BUPT Insight 虚构样例',
                                title='BUPT Insight Phase 2 智能提醒测试',
                                url='https://www.bupt.edu.cn/#phase2-demo-' + uuid4().hex,
                                body=item['body'])
                    with single_run(resolve(cfg, cfg['paths']['data_dir']) / 'run.lock'):
                        db = database(cfg)
                        try:
                            db.upsert(demo, ['desktop'])
                            delivery = db.db.execute('SELECT id FROM deliveries WHERE notice_id=?', (identity(demo),)).fetchone()[0]
                            title, body = message(demo.to_dict(), result)
                            db.delivery(delivery, 'sending', attempt=True)
                            sent = desktop(title, '[模拟分析：背景与通知均虚构]\n' + body, demo.url)
                            db.delivery(delivery, sent.status, sent.detail)
                            output({'simulation': True, 'delivery_id': delivery, **sent.__dict__})
                            return int(sent.status == 'failed')
                        finally:
                            db.close()
            return 0
        if args.cmd in ('portal','login') and getattr(args, "mode", None):
            cfg["sources"]["portal"]["auth_mode"] = args.mode
        if args.cmd == "scan":
            if any(s not in ("portal", "byr") for s in args.sources):
                raise InsightError("configuration_error", "信息源只能是 portal 或 byr")
            report = sync(cfg, args.sources, args.push, args.baseline, args.boards)
            output(report)
            return int(any(s["status"] not in ("ok", "no_new") for s in report["sources"].values()) or
                       any(d["status"] in ("failed", "unknown") for d in report["deliveries"]) or report.get('backup', {}).get('status') == 'failed')
        if args.cmd == "portal" and args.action == "probe":
            from tools.probe_network import probe
            output([probe("http://my.bupt.edu.cn"), probe("https://auth.bupt.edu.cn/authserver/login")])
            return 0
        if args.cmd == "portal" and args.action == "inspect":
            portal_inspect(cfg, args.interactive)
            return 0
        if args.cmd == "login" and args.source == "byr":
            login_byr(cfg)
            return 0
        if args.cmd in ("login", "portal"):
            from sources.portal import fetch
            fetched, _, errors = fetch(cfg, interactive=args.interactive)
            items = [i for group in fetched.values() for i in group]
            complete = [i for i in items if i.body and i.extra.get("body_status") == "ok"]
            attachment_only = [i for i in items if i.extra.get("body_status") == "attachment_only"]
            image_only = [i for i in items if i.extra.get("body_status") == "image_only"]
            output({"status": "verified_with_notice" if complete and not errors else (
                "verified_with_media" if (attachment_only or image_only) and not errors else (
                "verified_empty_list" if not items and not errors else "failed")),
                "notice_count": len(items), "complete_bodies": len(complete), "attachment_only": len(attachment_only), "image_only": len(image_only), "errors": errors,
                "sample": [{"title": i.title, "published": i.published, "origin": i.channel,
                            "url": i.url, "body_length": len(i.body)} for i in complete[:1]]})
            return int(bool(errors))
        if args.cmd == "logout":
            from core.locking import single_run
            with single_run(resolve(cfg, cfg["paths"]["data_dir"]) / "run.lock"):
                from core.portal_auth import PortalAuthenticator
                if args.source in ("all", "portal"):
                    PortalAuthenticator(cfg).logout()
                if args.source in ("all", "byr"):
                    path = resolve(cfg, f"{cfg['paths']['session_dir']}/{cfg['sources']['byr']['session']}")
                    path.unlink(missing_ok=True)
                    path.with_suffix(".json").unlink(missing_ok=True)
                    path.with_suffix(".bin").unlink(missing_ok=True)
                if args.clear_credentials:
                    delete_secret("portal")
                    for channel in ("pushplus", "serverchan", "pushplus_access_key", 'llm_api_key'):
                        delete_secret(channel)
                print("本地会话已清除；学校浏览器或其他设备的会话需在官方页面退出")
            return 0
        if args.cmd == "schedule":
            import re
            times = args.times.split(",")
            if any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t) for t in times):
                raise InsightError("configuration_error", "时间格式应为 HH:MM，以逗号分隔")
            command = ["powershell.exe", "-NoProfile", "-File", str(ROOT / "deploy" / "Install.ps1"),
                       "-PythonPath", sys.executable, "-TimesCsv", args.times]
            if args.action == "remove":
                command.append("-Uninstall")
            return subprocess.run(command).returncode
        from core.locking import single_run
        from contextlib import nullcontext
        readonly = args.cmd in ("status", "history", 'health','recommend') or (args.cmd == "delivery" and args.action == "list") or (args.cmd == 'ai' and args.action == 'show') or (args.cmd=='feedback' and args.action=='list')
        guard = nullcontext() if readonly else single_run(resolve(cfg, cfg["paths"]["data_dir"]) / "run.lock")
        with guard:
            db = database(cfg)
            try:
                if args.cmd=='feedback':
                    from core.feedback import record
                    from core.profile import load
                    if args.action=='list':
                        output([dict(r) for r in db.db.execute('SELECT id,notice_id,label,explanation_quality,created_at FROM feedback ORDER BY id DESC LIMIT 50')])
                    else:
                        row=db.db.execute('SELECT * FROM notices WHERE id=?',(args.id,)).fetchone()
                        if not row or not args.label:raise InsightError('feedback_invalid','请指定现有通知ID和反馈标签')
                        ident=record(db,row,load(cfg),args.label,explanation_quality=args.quality)
                        output({'status':'recorded','feedback_id':ident,'delivery_modified':False})
                elif args.cmd=='recommend':
                    from core.analysis import rules
                    from core.profile import load
                    from core.personalization import decide
                    from core.smart import feedback_route
                    from core.feedback import latest
                    profile=load(cfg)
                    rows=db.db.execute('SELECT * FROM notices WHERE id=?',(args.id,)).fetchall() if args.id else db.db.execute("SELECT * FROM notices WHERE source IN ('portal','byr') ORDER BY updated_at DESC LIMIT ?",(max(1,min(200,args.limit)),)).fetchall()
                    output([{'id':r['id'],'title':r['title'],'relevance':(a:=rules(json.loads(r['payload']),profile)).relevance,
                             'route':feedback_route(json.loads(r['payload']),a,'ok',profile,latest(db,r,profile)),
                             'matches':decide(json.loads(r['payload']),profile).to_dict(),
                             'qualification':'unknown'} for r in rows])
                elif args.cmd=='evaluate':
                    from core import evaluation
                    from core.profile import load
                    if args.action=='freeze':
                        output(evaluation.freeze(cfg,db,load(cfg),args.limit))
                    elif args.action=='list':
                        output([f.name for f in sorted(evaluation.root(cfg).glob('*')) if f.is_dir()])
                    else:
                        if not args.batch:raise InsightError('evaluation_invalid','请指定当前账号评估批次名')
                        if args.action=='run':output(evaluation.evaluate(cfg,args.batch,args.method))
                        elif args.action=='rate':
                            output(evaluation.rate(cfg,args.batch,args.sample,args.method,args.score))
                        else:
                            output(evaluation.label(cfg,args.batch,args.sample,args.label))
                elif args.cmd == "status":
                    from core.progress import read as read_progress
                    state = db.status()
                    state["database_path"] = db.db.execute("PRAGMA database_list").fetchone()[2]
                    state["progress"] = read_progress(cfg)
                    from core.health import inspect
                    state['health'] = inspect(cfg, db)
                    state['analysis'] = [dict(r) for r in db.db.execute('SELECT engine,status,count(*) AS count FROM analysis_cache GROUP BY engine,status')]
                    output(state)
                elif args.cmd == 'health':
                    from core.health import inspect
                    value = inspect(cfg, db)
                    output(value)
                    return int(value['status'] != 'healthy')
                elif args.cmd == 'ai':
                    from core.analysis import analyze_row, settings
                    from core.profile import load
                    options = settings(cfg)
                    if args.mode:
                        options['mode'] = args.mode
                    if args.action == 'show':
                        row = db.db.execute('SELECT engine,status,result FROM analysis_cache WHERE notice_id=? ORDER BY created_at DESC LIMIT 1', (args.id,)).fetchone()
                        output({'engine': row['engine'], 'status': row['status'], 'result': json.loads(row['result'])} if row else {'status': 'not_found'})
                    else:
                        import time
                        profile_value = load(cfg)
                        rows = db.db.execute('SELECT * FROM notices WHERE id=?', (args.id,)).fetchall() if args.id else db.db.execute('SELECT * FROM notices WHERE source!=? ORDER BY updated_at DESC LIMIT ?', ('test', max(1, min(100, args.limit)))).fetchall()
                        start = time.monotonic(); budget = max(.1, min(60, float(options.get('budget_seconds', 12))))
                        results = []
                        for row in rows:
                            remaining = budget - (time.monotonic() - start)
                            if remaining <= .1:
                                break
                            results.append(analyze_row(db, row, profile_value, options, remaining))
                        output({'processed': len(results), 'results': results, 'push_created': False})
                elif args.cmd == "history":
                    if args.id:
                        row = db.db.execute("SELECT payload FROM notices WHERE id=?", (args.id,)).fetchone()
                        output(json.loads(row[0]) if row else {"error": "未找到通知"})
                    else:
                        output(db.history(max(1, min(args.limit, 200))))
                elif args.cmd in ("push", "test-push"):
                    from core.notifications import dispatch
                    from core.schema import Item
                    db.recover()
                    if args.cmd == 'push':
                        from core.analysis import run_pending
                        run_pending(cfg, db)
                    test_notice = None
                    if args.cmd == "test-push":
                        from uuid import uuid4
                        key = uuid4().hex
                        item = Item(source="test", channel="BUPT Insight 本地测试", title="BUPT Insight 通知测试",
                                    url=f"https://www.bupt.edu.cn/#insight-test-{key}",
                                    body="这是虚构测试消息。请检查微信/Windows 通知中心；不包含学校账号信息。")
                        db.upsert(item, channels=[args.channel])
                        from core.database import identity
                        test_notice = identity(item)
                        cfg["push"]["channels"] = {args.channel: {"enabled": True}}
                    results = dispatch(cfg, db, notice_id=test_notice)
                    output(results)
                    return int(not results or any(d["status"] in ("failed", "unknown") for d in results))
                elif args.cmd == "delivery":
                    if args.action == "list":
                        output([dict(r) for r in db.db.execute("SELECT id,channel,status,attempts,detail FROM deliveries ORDER BY id DESC LIMIT 50")])
                    else:
                        row = db.db.execute("SELECT * FROM deliveries WHERE id=?", (args.id,)).fetchone()
                        if row is None:
                            raise InsightError("configuration_error", "请指定有效 delivery ID")
                        if args.action == "confirm":
                            db.delivery(args.id, "received", "用户人工确认已收到")
                        elif args.action == "retry":
                            member = db.db.execute('SELECT batch_id FROM digest_members WHERE delivery_id=?', (args.id,)).fetchone()
                            if member:
                                with db.db:
                                    db.db.execute("UPDATE digest_batches SET status='pending' WHERE id=?", (member[0],))
                                    db.db.execute("UPDATE deliveries SET status='digest_waiting' WHERE id IN (SELECT delivery_id FROM digest_members WHERE batch_id=?)", (member[0],))
                                output({'status': 'digest_retry_requested', 'message': '用户显式要求重发整组汇总，可能包含已查看的成员'})
                            else:
                                db.delivery(args.id, "pending", "用户已核对后显式要求重试")
                        elif args.action == "check":
                            if row["channel"] != "pushplus" or not row["receipt"]:
                                raise InsightError("configuration_error", "该条没有可查询的 PushPlus 流水号")
                            from core.notifications import check_receipt
                            result = check_receipt(row["receipt"])
                            db.delivery(args.id, result.status, result.detail, result.receipt)
                            output(result.__dict__)
            finally:
                db.close()
        return 0
    except (Exception, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code == 0:
            return 0
        status, message = safe_error(exc)
        output({"status": status, "message": message})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
