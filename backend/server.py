#!/usr/bin/env python3
"""THE PARKING GAZETTE — Flask 웹 서버 모드

실행:
    python backend/server.py
    → 브라우저: http://localhost:5000
    → 외부 공유: ngrok http 5000
"""

import sys
import os
import json
import subprocess
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import db

RENDERER_DIR = ROOT_DIR / 'src' / 'renderer'

app = Flask(__name__)


# ── 정적 파일 (HTML / JS / CSS) ────────────────────────

@app.route('/')
def index():
    return send_from_directory(str(RENDERER_DIR), 'index.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory(str(RENDERER_DIR), filename)


# ── API ─────────────────────────────────────────────────

_IS_CLOUD = bool(
    os.environ.get('RAILWAY_ENVIRONMENT') or
    os.environ.get('RAILWAY_SERVICE_ID') or
    os.environ.get('RAILWAY_ENVIRONMENT_ID') or
    os.environ.get('GOOGLE_CREDENTIALS')   # Railway에 수동 설정한 변수 → 클라우드 확실
)

@app.route('/api/status')
def api_status():
    status = db.get_status()
    # 클라우드 배포 환경에서는 크롤러 자동 실행 방지
    # Sheets 데이터 유무로 crawled_today 판단
    if _IS_CLOUD and not status['crawled_today']:
        try:
            import sheets
            sheet_data = sheets.read_all_cached()
            if sheet_data:
                status['crawled_today'] = True
                status['today_total'] = len(sheet_data)
            else:
                # 데이터 없어도 크롤 트리거 막기 (서버에서 크롤 불가)
                status['crawled_today'] = True
                status['today_total'] = 0
        except Exception:
            status['crawled_today'] = True
    return jsonify(status)

@app.route('/api/services')
def api_services():
    svcs = db.get_services()
    if _IS_CLOUD:
        try:
            import sheets
            sheet_data = sheets.read_all_cached()
            count_map = {}
            for row in sheet_data:
                sid = row.get('service_id', '')
                count_map[sid] = count_map.get(sid, 0) + 1
            for svc in svcs:
                svc['count'] = count_map.get(svc['id'], 0)
        except Exception:
            pass
    return jsonify(svcs)

@app.route('/api/changes/<svc_id>')
def api_changes(svc_id):
    if _IS_CLOUD:
        try:
            import sheets
            all_data = sheets.read_all_cached()
            filtered = [r for r in all_data if svc_id == '__all__' or r.get('service_id') == svc_id]
            filtered.sort(key=lambda x: x.get('published_at', ''), reverse=True)
            import logging; logging.getLogger(__name__).info(
                f"[api_changes] svc={svc_id} total={len(all_data)} filtered={len(filtered)}"
            )
            return jsonify(filtered[:200])
        except Exception as e:
            import logging; logging.getLogger(__name__).error(f"[api_changes] Sheets error: {e}")
    return jsonify(db.get_changes(svc_id))

@app.route('/api/all_changes')
def api_all_changes():
    change_type = request.args.get('type') or None
    if _IS_CLOUD:
        try:
            import sheets
            all_data = sheets.read_all_cached()
            if change_type:
                all_data = [r for r in all_data if r.get('change_type') == change_type]
            all_data.sort(key=lambda x: x.get('published_at', ''), reverse=True)
            return jsonify(all_data[:500])
        except Exception:
            pass
    return jsonify(db.get_all_changes(change_type=change_type))

@app.route('/api/summary')
def api_summary():
    if _IS_CLOUD:
        try:
            import sheets
            from datetime import datetime, timedelta
            cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d")
            all_data = sheets.read_all_cached()
            recent = [r for r in all_data if str(r.get('published_at', ''))[:10] >= cutoff]
            return jsonify(recent)
        except Exception:
            pass
    return jsonify(db.get_summary())

@app.route('/api/search')
def api_search():
    query = request.args.get('q', '').lower()
    if _IS_CLOUD and query:
        try:
            import sheets
            all_data = sheets.read_all_cached()
            results = [r for r in all_data if query in (r.get('title') or '').lower()
                       or query in (r.get('summary') or '').lower()]
            return jsonify(results[:100])
        except Exception:
            pass
    return jsonify(db.search_features(query))

@app.route('/api/app_stats')
def api_app_stats():
    return jsonify(db.get_app_stats())


# ── 크롤러 실행 (SSE 스트리밍) ───────────────────────────

@app.route('/api/crawl')
def api_crawl():
    """크롤러 실행 + stdout을 Server-Sent Events로 실시간 전송."""
    def generate():
        venv_py = ROOT_DIR / '.venv' / 'Scripts' / 'python.exe'
        py_cmd  = str(venv_py) if venv_py.exists() else 'python'
        crawler = ROOT_DIR / 'backend' / 'daily_crawl.py'

        proc = subprocess.Popen(
            [py_cmd, str(crawler)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(ROOT_DIR),
            env={**os.environ, 'PYTHONUTF8': '1'},
            encoding='utf-8',
            errors='replace',
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                yield f"data: {json.dumps(line)}\n\n"
        proc.wait()
        yield f"data: {json.dumps('__DONE__:' + str(proc.returncode))}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


# ── 실행 ────────────────────────────────────────────────

if __name__ == '__main__':
    print("=" * 52)
    print("   THE PARKING GAZETTE  —  웹 서버 모드")
    print("=" * 52)
    db.init_db()
    db.import_services()
    port = int(os.environ.get('PORT', 5000))
    print(f"\n  브라우저 접속  →  http://localhost:{port}")
    print("  외부 공유     →  ngrok http 5000")
    print("  종료          →  Ctrl+C\n")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
