"""Loopback-only reader. Collection data is read-only; UI state is account scoped."""
import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request, session, abort

from core.config import ROOT, load_config
from core.errors import InsightError
from core.pipeline import database_path
from core.profile import load as load_profile
from core.reader import Reader, get_rows, run_status, source, feedbacks

CATEGORIES = {'research': '科研机会', 'competition': '竞赛', 'internship': '实习就业',
              'event': '校园活动', 'mandatory_academic': '教务通知', 'general': '校园资讯', 'electronics': '电子科创', 'administration': '校务人事'}


def safe_url(value):
    try:
        p = urlsplit(value)
        return value if p.scheme in ('http', 'https') and p.hostname and not p.username and not p.password else ''
    except ValueError:
        return ''


def create_app(config_provider=load_config, port=8765):
    app = Flask(__name__, template_folder=str(ROOT / 'web/templates'), static_folder=str(ROOT / 'web/static'))
    app.config.update(SECRET_KEY=secrets.token_hex(32), MAX_CONTENT_LENGTH=8192,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
    app.logger.disabled = True
    readers = {}; reader_lock = threading.RLock(); cache = {}; cache_lock = threading.RLock()
    allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}

    def context():
        cfg = config_provider(); path = database_path(cfg)
        with reader_lock:
            if str(path) not in readers:
                readers[str(path)] = Reader(path.parent / 'reader.sqlite3')
            reader = readers[str(path)]
        return cfg, path, reader

    @app.before_request
    def protect():
        # Host validation blocks DNS rebinding; no CORS, remote assets or public bind.
        if request.host not in allowed:
            abort(403)
        if request.headers.get('Sec-Fetch-Site') == 'cross-site':
            abort(403)
        origin = request.headers.get('Origin')
        if origin and origin not in {f'http://{host}' for host in allowed}:
            abort(403)
        if request.method == 'POST':
            token = request.headers.get('X-CSRF-Token', '')
            if not token or not secrets.compare_digest(token, session.get('csrf', '')):
                abort(403)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    @app.errorhandler(InsightError)
    def insight(exc):
        return jsonify(error=exc.status, message=str(exc)), 503

    @app.errorhandler(sqlite3.Error)
    def storage(exc):
        return jsonify(error='storage_unavailable', message='本地数据暂时不可用，请稍后重试；原文件已保留。'), 503

    @app.errorhandler(403)
    def forbidden(exc):
        return jsonify(error='forbidden', message='请从本机页面操作或刷新页面后重试。'), 403

    @app.errorhandler(Exception)
    def safe_failure(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return jsonify(error='request_failed', message='请求无效或内容不存在。'), exc.code
        return jsonify(error='unavailable', message='页面暂时无法读取数据，请检查本地配置和运行状态。'), 503

    @app.get('/')
    def home():
        session['csrf'] = secrets.token_hex(24)
        return render_template('index.html', csrf=session['csrf'])

    def decorate(row, profile, states, events):
        from core.analysis import rules
        item = json.loads(row['payload']); key = (row['id'], row['hash'], profile.fingerprint())
        with cache_lock:
            if key not in cache:
                if len(cache) > 2000: cache.clear()
                try:
                    cache[key] = rules(item, profile).model_dump()
                except Exception:
                    cache[key] = None
            analysis = cache[key]
        state = states.get(row['id'], {}); feedback = events.get(key)
        category = analysis['category'] if analysis else 'general'
        from core.curation import assess, today
        from core.research import opportunity
        category, protected, relevance, reasons = assess(item, profile, analysis)
        research = opportunity(item, today())
        hidden = state.get('hidden_hash') == row['hash'] or bool(feedback and feedback['label'] == 'irrelevant')
        if protected:
            hidden = False  # Safety-protected academic items remain visible.
        try:
            published=datetime.fromisoformat(row['published'][:10]).date()
            historical=(datetime.now(timezone(timedelta(hours=8))).date()-published).days>180
        except (ValueError,TypeError):
            historical=False
        return {'id': row['id'], 'hash': row['hash'], 'title': row['title'], 'source': row['source'],
                'origin': row['origin'], 'published': row['published'], 'first_seen': row['first_seen'],
                'updated_at': row.get('content_seen',row['updated_at']) if row['revision']>1 else row['first_seen'], 'revision': row['revision'], 'url': safe_url(row['url']),
                'summary': ((row['body'].split('\n\n',1)[1] if row['source']=='byr' and row['body'].startswith('发信人:') and '\n\n' in row['body'] else row['body']) or '正文暂不可用，请打开原文查看。')[:240],
                'category': category, 'category_label': CATEGORIES[category],
                'relevance': relevance,
                'research': research,
                'importance': 'high' if protected else 'normal', 'historical':historical,
                'deadline': analysis['deadline'] if analysis else {'value': None, 'basis': 'unknown', 'evidence': ''},
                'reasons': reasons[:3],
                'body_status': item.get('extra', {}).get('body_status', 'ok'),
                'unread': state.get('read_hash') != row['hash'], 'favorite': bool(state.get('favorite')),
                'hidden': hidden, 'feedback': feedback['label'] if feedback else None,
                'feedback_pending': bool(feedback and not feedback['synced'])}

    def all_feedback(path,reader,profile):
        merged=feedbacks(path,profile.fingerprint())
        for key,event in reader.events().items():
            if key not in merged or event['created_at']>=merged[key]['created_at']:
                merged[key]=event
        return merged

    @app.get('/api/feed')
    def feed():
        cfg, path, reader = context(); profile = load_profile(cfg)
        states = reader.states(); events = all_feedback(path,reader,profile)
        rows = get_rows(path)
        items = [decorate(r, profile, states, events) for r in rows]
        counts = {'all': len(items), 'unread': sum(i['unread'] for i in items),
                  'favorites': sum(i['favorite'] for i in items), 'hidden': sum(i['hidden'] for i in items)}
        view = request.args.get('view', 'recommended'); query = request.args.get('q', '').strip().casefold()[:200]
        category = request.args.get('category', ''); source_filter = request.args.get('source', '')
        filtered = []
        for item, raw in zip(items, rows):
            if view == 'hidden' and not item['hidden']: continue
            if view not in ('hidden', 'all', 'favorites') and item['hidden']: continue
            if view == 'favorites' and not item['favorite']: continue
            if view == 'unread' and not item['unread']: continue
            if view == 'research':
                from core.curation import today
                try:
                    age = (today() - datetime.fromisoformat(item['published'][:10]).date()).days
                except (ValueError, TypeError):
                    continue
                if not 0 <= age <= 90 or not item['research']['candidate']: continue
            from core.curation import eligible
            if view == 'recommended' and not eligible(item): continue
            if category and item['category'] != category: continue
            if source_filter and item['source'] != source_filter: continue
            if query and query not in (item['title'] + '\n' + item['origin'] + '\n' + raw['body']).casefold(): continue
            filtered.append(item)
        sort = request.args.get('sort', 'recommended' if view == 'recommended' else 'published')
        def rank(i):
            priority = 2 if i['importance'] == 'high' or i['feedback'] == 'important' else (1 if i['relevance'] == 'high' else 0)
            return (int(not i['historical']), int(i['unread']), priority, i['research']['priority'], i['published'], i['updated_at'])
        if sort == 'recommended': filtered.sort(key=rank, reverse=True)
        elif sort == 'collected': filtered.sort(key=lambda i: i['updated_at'], reverse=True)
        else: filtered.sort(key=lambda i: (i['published'], i['updated_at']), reverse=True)
        try:
            page = max(1, int(request.args.get('page', 1)))
        except ValueError:
            abort(400)
        eligible_total = len(filtered)
        if view == 'recommended':
            # Cap ordinary recommendations, not compulsory academic matters.
            from core.curation import shortlist
            filtered = shortlist(filtered)
            page = 1
        size = max(8, len(filtered)) if view == 'recommended' else 20
        start = (page-1)*size
        return jsonify(items=filtered[start:start+size], total=len(filtered), page=page, page_size=size,
                       counts=counts, categories=CATEGORIES, eligible_total=eligible_total,
                       version=hashlib.sha256(json.dumps([(i['id'],i['hash']) for i in items],sort_keys=True).encode()).hexdigest())

    @app.get('/api/detail')
    def detail():
        cfg, path, reader = context()
        with source(path) as db:
            raw = db.execute('SELECT * FROM notices WHERE id=?', (request.args.get('id'),)).fetchone()
            row = dict(raw) if raw else None
        if not row: abort(404)
        item = json.loads(row['payload'])
        profile=load_profile(cfg)
        result = decorate(row, profile, reader.states(), all_feedback(path,reader,profile))
        result['body'] = row['body'] or '正文暂不可用，请打开原文查看。'
        result['attachments'] = [{'name': a.get('name','附件'), 'url': safe_url(a.get('url',''))} for a in item.get('extra',{}).get('attachments',[])]
        return jsonify(result)

    @app.post('/api/state')
    def state():
        body = request.get_json(silent=True) or {}
        if body.get('action') not in ('read','favorite','hidden','feedback'): abort(400)
        if body['action'] == 'feedback':
            if body.get('value') not in ('important','relevant','irrelevant','unsure'): abort(400)
        elif type(body.get('value')) is not bool: abort(400)
        cfg, path, reader = context()
        with source(path) as db:
            raw = db.execute('SELECT * FROM notices WHERE id=?', (body.get('id'),)).fetchone()
            row = dict(raw) if raw else None
        if not row: abort(404)
        if body.get('hash') != row['hash']:
            return jsonify(error='content_changed', message='正文已有更新，请刷新后操作，避免对旧版本误标记。'), 409
        reader.mutate(row, body['action'], body['value'], load_profile(cfg))
        reader.flush(cfg, path)
        return jsonify(ok=True)

    @app.get('/api/status')
    def status():
        cfg, path, reader = context(); reader.flush(cfg, path)
        return jsonify(sources=run_status(cfg,path), privacy='local', model='off_in_reader',
                       feedback_pending=sum(not e['synced'] for e in reader.events().values()))

    @app.get('/api/identity')
    def identity():
        return jsonify(app='BUPTInsightReader', protocol=1)

    return app


def serve(port=8765, open_browser=False):
    if not 1024 <= port <= 65535:
        raise InsightError('configuration_error','本地端口应在1024至65535之间')
    app = create_app(port=port)
    from waitress import serve as waitress_serve
    if open_browser:
        import webbrowser
        threading.Timer(1, lambda: webbrowser.open(f'http://127.0.0.1:{port}')).start()
    print(f'BUPT Insight：http://127.0.0.1:{port} 关闭服务请按Ctrl+C', flush=True)
    waitress_serve(app, host='127.0.0.1', port=port, threads=4, channel_timeout=20)
