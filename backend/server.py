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

@app.route('/api/status')
def api_status():
    return jsonify(db.get_status())

@app.route('/api/services')
def api_services():
    return jsonify(db.get_services())

@app.route('/api/changes/<svc_id>')
def api_changes(svc_id):
    return jsonify(db.get_changes(svc_id))

@app.route('/api/all_changes')
def api_all_changes():
    change_type = request.args.get('type') or None
    return jsonify(db.get_all_changes(change_type=change_type))

@app.route('/api/summary')
def api_summary():
    return jsonify(db.get_summary())

@app.route('/api/search')
def api_search():
    query = request.args.get('q', '')
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
