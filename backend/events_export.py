"""
이벤트 마스터 (Google Sheets) → docs/events.json 내보내기

환경변수:
    EVENTS_SPREADSHEET_ID  : 이벤트 마스터 Sheets ID (없으면 SPREADSHEET_ID 공유 사용)
    EVENTS_SHEET_NAME      : 시트 탭 이름 (기본: 이벤트마스터)
    EVENTS_WINDOW_DAYS     : 오늘부터 N일 이내 시작 이벤트 포함 (기본: 10)
    GOOGLE_CREDENTIALS     : 서비스 계정 JSON 문자열
"""
import os
import json
from pathlib import Path
from datetime import datetime, timedelta

ROOT_DIR = Path(__file__).parent.parent

EVENTS_SPREADSHEET_ID = (
    os.environ.get("EVENTS_SPREADSHEET_ID") or
    os.environ.get("SPREADSHEET_ID", "")
)
EVENTS_SHEET_NAME  = os.environ.get("EVENTS_SHEET_NAME", "이벤트마스터")
WINDOW_DAYS        = int(os.environ.get("EVENTS_WINDOW_DAYS", "10"))

HEADERS = [
    "event_id", "title", "category", "start_date", "end_date", "venue",
    "region_1", "region_2", "impact", "start_time", "end_time", "source",
    "verified", "notes", "memo", "region_3", "lat", "lng",
    "traffic_control", "duration_type", "demand_type", "event_history", "modu_transaction",
]


def _get_client():
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise RuntimeError("gspread 미설치: pip install gspread google-auth")

    raw = os.environ.get("GOOGLE_CREDENTIALS", "")
    if raw:
        info = json.loads(raw)
    else:
        creds_path = ROOT_DIR / "google_credentials.json"
        with open(creds_path, encoding="utf-8") as f:
            info = json.load(f)

    creds = Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    return gspread.authorize(creds)


def fetch_events() -> list[dict]:
    if not EVENTS_SPREADSHEET_ID:
        print("[WARN] EVENTS_SPREADSHEET_ID 미설정 — events.json 건너뜀")
        return []
    try:
        gc = _get_client()
        sh = gc.open_by_key(EVENTS_SPREADSHEET_ID)
        ws = sh.worksheet(EVENTS_SHEET_NAME)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[WARN] 이벤트 Sheets 읽기 실패: {e}")
        return []

    if len(rows) < 2:
        return []

    # 헤더 행으로 컬럼 위치 파악 (순서가 달라도 OK)
    raw_headers = [h.strip() for h in rows[0]]
    col_idx = {h: i for i, h in enumerate(raw_headers)}

    def get(row, key):
        idx = col_idx.get(key)
        if idx is None or idx >= len(row):
            return ""
        return (row[idx] or "").strip()

    events = []
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        ev = {h: get(row, h) for h in HEADERS}
        if not ev.get("title") or not ev.get("start_date"):
            continue
        events.append(ev)

    return events


def export_events_json():
    today_dt  = datetime.now()
    today_str = today_dt.strftime("%Y-%m-%d")
    deadline  = (today_dt + timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")

    all_events = fetch_events()

    filtered = []
    for ev in all_events:
        sd = ev.get("start_date", "")
        ed = ev.get("end_date", "") or sd
        if not sd:
            continue
        # 진행 중(시작≤오늘≤종료) 또는 D-WINDOW 이내 시작
        if ed >= today_str and sd <= deadline:
            filtered.append(ev)

    filtered.sort(key=lambda x: x.get("start_date", ""))

    out = {
        "ok": True,
        "events": filtered,
        "total": len(filtered),
        "last_updated": today_dt.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    out_path = ROOT_DIR / "docs" / "events.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[INFO] docs/events.json: {len(filtered)}건 내보내기 완료")


if __name__ == "__main__":
    export_events_json()
