"""Local, read-only dashboard. No third-party dependencies or provider calls."""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .config import load_settings
from .db.store import Store
from .quality.report import build_report
from .report import signal_report

ASSETS = Path(__file__).with_name('ui')


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value


def read_dashboard(database_url, signal_id=None):
    """One SQLite read transaction; never initialize/migrate a customer's database."""
    if not database_url.startswith('sqlite:///'):
        raise ValueError('only sqlite:/// URLs are supported')
    path = Path(database_url[10:]).resolve()
    if not path.is_file():
        return {'mode':'local', 'status':'NOT_INITIALIZED', 'message':'尚未初始化数据，请先运行 python3 -m ati migrate。', 'signals':[], 'report':None}
    store = Store.__new__(Store)
    store.conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)
    store.conn.row_factory = sqlite3.Row
    try:
        store.conn.execute('PRAGMA query_only=ON')
        store.conn.execute('BEGIN')
        signals = [dict(r) for r in store.conn.execute(
            'SELECT signal_id,trade_date,decision_cutoff,data_status FROM signal_snapshot ORDER BY decision_cutoff DESC LIMIT 100')]
        report = signal_report(store, signal_id or (signals[0]['signal_id'] if signals else None), rejection_limit=500, include_factor_sample=False)
        if signal_id and report.get('status') == 'MISSING':
            raise LookupError('未找到这条信号，请刷新列表。')
        quality = build_report(store)
        # The legacy coverage metric measures identity matching. Present actual
        # quote coverage separately so a one-stock snapshot cannot appear complete.
        master_time = store.conn.execute('SELECT max(valid_from) FROM security_master_snapshot').fetchone()[0]
        quote_time = store.conn.execute('SELECT max(event_time) FROM quote_snapshot').fetchone()[0]
        universe = {r[0] for r in store.conn.execute('SELECT security_id FROM security_master_snapshot WHERE valid_from=?', (master_time,))}
        quotes = {r[0] for r in store.conn.execute('SELECT security_id FROM quote_snapshot WHERE event_time=?', (quote_time,))}
        quality['quote_universe_coverage'] = len(universe & quotes)/len(universe) if universe else None
        # Keep the dashboard response bounded; the report still exposes the total count.
        return {'mode':'local', 'status':'READY', 'signals':signals, 'signal_limit':100,
                'report':report if 'signal' in report else None, 'quality':quality,
                'loaded_at':datetime.now(timezone.utc).isoformat()}
    finally:
        store.close()


def demo_dashboard():
    from .demo import run_demo
    report = run_demo(detailed=True)
    return {'mode':'demo', 'status':'READY', 'signals':[report['signal']], 'report':report,
            'quality':None, 'loaded_at':datetime.now(timezone.utc).isoformat()}


def make_handler(database_url=None, demo_payload=None):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, payload):
            self._send(status, json.dumps(_finite(payload), ensure_ascii=False, allow_nan=False).encode(), 'application/json; charset=utf-8')

        def do_GET(self):
            # Loopback binding plus an exact host check prevents DNS rebinding.
            if self.headers.get('Host') not in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}:
                self._json(403, {'message':'请使用本机地址访问。'})
                return
            parsed = urlsplit(self.path)
            assets = {'/':('index.html','text/html'), '/app.js':('app.js','text/javascript'), '/style.css':('style.css','text/css')}
            if parsed.path in assets:
                name, mime = assets[parsed.path]
                self._send(200, (ASSETS / name).read_bytes(), mime + '; charset=utf-8')
            elif parsed.path == '/api/dashboard':
                signal_id = parse_qs(parsed.query).get('signal_id', [None])[0]
                try:
                    if demo_payload is not None:
                        if signal_id and signal_id != demo_payload['report']['signal']['signal_id']:
                            raise LookupError('未找到这条演示信号。')
                        payload = demo_payload
                    else:
                        payload = read_dashboard(database_url, signal_id)
                    self._json(200, payload)
                except LookupError as exc:
                    self._json(404, {'message':str(exc)})
                except (sqlite3.Error, ValueError):
                    self._json(503, {'message':'暂时无法读取数据。请确认数据库已完成迁移，或稍后重试。'})
            else:
                self._json(404, {'message':'页面不存在。'})

        def log_message(self, *args):
            pass
    return Handler


def serve(*, demo=False, port=8765):
    if not 1 <= port <= 65535:
        raise ValueError('port must be between 1 and 65535')
    payload = demo_dashboard() if demo else None
    database_url = None if demo else load_settings().database_url
    with ThreadingHTTPServer(('127.0.0.1', port), make_handler(database_url, payload)) as server:
        print(f'ATI 客户工作台 http://127.0.0.1:{port} · {"合成演示" if demo else "本地只读"}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
