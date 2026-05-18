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

import logging
log = logging.getLogger(__name__)


def _merge_data(sheets_rows: list, db_rows: list, limit: int = 300) -> list:
    """Sheets 데이터와 SQLite 데이터를 URL 키 기준으로 병합·중복제거."""
    seen: set = set()
    results: list = []

    def _key(row: dict) -> str:
        url = (row.get('url') or '').strip()
        if url:
            return url
        return (
            f"{row.get('service_id','')}|"
            f"{str(row.get('published_at',''))[:10]}|"
            f"{(row.get('title') or '')[:60]}"
        )

    for row in list(sheets_rows) + list(db_rows):
        k = _key(row)
        if k not in seen:
            seen.add(k)
            results.append(row)

    results.sort(key=lambda x: (x.get('published_at') or ''), reverse=True)
    return results[:limit]


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
    if _IS_CLOUD:
        # 클라우드에서는 크롤러 실행 불가 — 무조건 수집완료로 반환
        status['crawled_today'] = True
        try:
            import sheets
            sheet_data = sheets.read_all_cached()
            status['today_total'] = len(sheet_data)
        except Exception:
            status['today_total'] = 0
    return jsonify(status)

@app.route('/api/services')
def api_services():
    svcs = db.get_services()
    if _IS_CLOUD:
        # SQLite 기반 카운트 먼저 확보
        db_counts = db.get_service_counts()
        sheets_counts: dict = {}
        try:
            import sheets
            sheet_data = sheets.read_all_cached()
            for row in sheet_data:
                sid = row.get('service_id', '')
                sheets_counts[sid] = sheets_counts.get(sid, 0) + 1
        except Exception:
            pass
        for svc in svcs:
            sid = svc['id']
            # 두 소스 중 큰 값 사용 (중복 제거 후 실제 merge 개수와 근사)
            svc['count'] = max(sheets_counts.get(sid, 0), db_counts.get(sid, 0))
    return jsonify(svcs)

@app.route('/api/changes/<svc_id>')
def api_changes(svc_id):
    db_rows = db.get_changes(svc_id)
    if _IS_CLOUD:
        sheets_rows: list = []
        try:
            import sheets
            all_data = sheets.read_all_cached()
            sheets_rows = [r for r in all_data if r.get('service_id') == svc_id]
            log.info(f"[api_changes] svc={svc_id} sheets={len(sheets_rows)} sqlite={len(db_rows)}")
        except Exception as e:
            log.error(f"[api_changes] Sheets error: {e}")
        return jsonify(_merge_data(sheets_rows, db_rows, limit=200))
    return jsonify(db_rows)

@app.route('/api/all_changes')
def api_all_changes():
    change_type = request.args.get('type') or None
    db_rows = db.get_all_changes(change_type=change_type)
    if _IS_CLOUD:
        sheets_rows: list = []
        try:
            import sheets
            all_data = sheets.read_all_cached()
            if change_type:
                all_data = [r for r in all_data if r.get('change_type') == change_type]
            sheets_rows = all_data
            log.info(f"[api_all_changes] type={change_type} sheets={len(sheets_rows)} sqlite={len(db_rows)}")
        except Exception as e:
            log.error(f"[api_all_changes] Sheets error: {e}")
        return jsonify(_merge_data(sheets_rows, db_rows, limit=500))
    return jsonify(db_rows)

@app.route('/api/summary')
def api_summary():
    from datetime import datetime, timedelta
    cutoff_dt  = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    cutoff_day = cutoff_dt[:10]
    db_rows = db.get_summary()
    if _IS_CLOUD:
        sheets_rows: list = []
        try:
            import sheets
            all_data = sheets.read_all_cached()
            # collected_at 기준 우선, 없으면 published_at 날짜로 fallback
            def _is_recent(r: dict) -> bool:
                col = str(r.get('collected_at') or '')
                if col >= cutoff_dt:
                    return True
                return str(r.get('published_at', ''))[:10] >= cutoff_day
            sheets_rows = [r for r in all_data if _is_recent(r)]
        except Exception as e:
            log.error(f"[api_summary] Sheets error: {e}")
        db_recent = [r for r in db_rows if str(r.get('published_at', ''))[:10] >= cutoff_day]
        return jsonify(_merge_data(sheets_rows, db_recent, limit=200))
    return jsonify(db_rows)

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


@app.route('/api/debug')
def api_debug():
    """환경 진단 — 배포 후 확인용."""
    import sys
    info = {
        'is_cloud': _IS_CLOUD,
        'env_railway_env': bool(os.environ.get('RAILWAY_ENVIRONMENT')),
        'env_railway_svc': bool(os.environ.get('RAILWAY_SERVICE_ID')),
        'env_google_creds': bool(os.environ.get('GOOGLE_CREDENTIALS')),
        'env_spreadsheet_id': bool(os.environ.get('SPREADSHEET_ID')),
        'spreadsheet_id_value': (os.environ.get('SPREADSHEET_ID') or '')[:20],
        'creds_starts_with': '',
        'sheets_row_count': 0,
        'sheets_error': '',
        'python': sys.version,
    }
    creds = os.environ.get('GOOGLE_CREDENTIALS', '')
    info['creds_len'] = len(creds)
    info['creds_starts_with'] = repr(creds[:10]) if creds else ''
    try:
        import sheets
        data = sheets.read_all_cached()
        info['sheets_row_count'] = len(data)
        info['sheets_sample_ids'] = list({r.get('service_id') for r in data[:50]})
    except Exception as e:
        info['sheets_error'] = str(e)
    return jsonify(info)


# ── 크롤러 실행 (SSE 스트리밍) ───────────────────────────

@app.route('/api/crawl')
def api_crawl():
    """크롤러 실행 + stdout을 Server-Sent Events로 실시간 전송."""
    def generate():
        py_cmd  = sys.executable   # 현재 실행 중인 Python 인터프리터 (로컬·Railway 공통)
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
