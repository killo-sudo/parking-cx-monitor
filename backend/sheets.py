"""Google Sheets 연동 헬퍼.

환경변수:
    GOOGLE_CREDENTIALS  : 서비스 계정 JSON 파일 내용 (문자열 전체)
    SPREADSHEET_ID      : 구글 스프레드시트 ID
로컬에서는 프로젝트 루트의 google_credentials.json 파일도 사용 가능.
"""

import os
import json
import time
import logging
from pathlib import Path

log = logging.getLogger(__name__)

SHEET_NAME = "수집데이터"
HEADERS    = ["날짜", "서비스ID", "서비스명", "소스유형", "변경유형", "제목", "요약", "URL", "감성", "수집일시", "전문"]

# Sheets 컬럼명 → 내부 필드명
_COL_MAP = {
    "날짜":    "published_at",
    "서비스ID": "service_id",
    "서비스명": "name_ko",
    "소스유형": "source_type",
    "변경유형": "change_type",
    "제목":    "title",
    "요약":    "summary",
    "URL":    "url",
    "감성":    "sentiment",
    "수집일시": "collected_at",
    "전문":    "full_text",
}


def _get_client():
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        log.warning("[Sheets] gspread 미설치 — pip install gspread google-auth")
        return None

    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]

    creds_json = os.environ.get("GOOGLE_CREDENTIALS", "")
    # Strip UTF-8 BOM (﻿) that Railway sometimes prepends to env vars
    creds_bytes = creds_json.encode('utf-8')
    if creds_bytes.startswith(b'\xef\xbb\xbf'):
        creds_json = creds_bytes[3:].decode('utf-8')
    creds_json = creds_json.strip()
    if creds_json:
        try:
            creds_dict = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        except Exception as e:
            log.error(f"[Sheets] GOOGLE_CREDENTIALS 파싱 실패: {e}")
            return None
    else:
        creds_path = Path(__file__).parent.parent / "google_credentials.json"
        if not creds_path.exists():
            return None
        from google.oauth2.service_account import Credentials as Cred
        creds = Cred.from_service_account_file(str(creds_path), scopes=scopes)

    try:
        return gspread.authorize(creds)
    except Exception as e:
        log.error(f"[Sheets] 인증 실패: {e}")
        return None


def _get_worksheet():
    spreadsheet_id = os.environ.get("SPREADSHEET_ID", "")
    if not spreadsheet_id:
        return None
    client = _get_client()
    if not client:
        return None
    try:
        sh = client.open_by_key(spreadsheet_id)
        try:
            return sh.worksheet(SHEET_NAME)
        except Exception:
            ws = sh.add_worksheet(SHEET_NAME, rows=100000, cols=len(HEADERS))
            ws.append_row(HEADERS)
            return ws
    except Exception as e:
        log.error(f"[Sheets] 워크시트 접근 실패: {e}")
        return None


def append_items(items: list[dict], service_map: dict | None = None) -> int:
    """신규 항목을 Google Sheets에 일괄 추가 (URL 기반 dedup). 추가된 행 수 반환."""
    if not items:
        return 0
    ws = _get_worksheet()
    if not ws:
        return 0

    # 기존 URL 목록 수집 — Sheets 중복 방지 (GitHub Actions 등 SQLite 없는 환경 대응)
    existing_urls: set = set()
    try:
        url_col_idx = HEADERS.index("URL")  # 7번 컬럼 (0-based)
        existing = ws.col_values(url_col_idx + 1)  # gspread는 1-based
        existing_urls = {v.strip() for v in existing if v.strip()}
    except Exception as e:
        log.warning(f"[Sheets] 기존 URL 조회 실패 (dedup 스킵): {e}")

    rows = []
    skipped = 0
    for item in items:
        url = (item.get("url") or "").strip()
        if url and url in existing_urls:
            skipped += 1
            continue
        if url:
            existing_urls.add(url)  # 이번 배치 내 중복도 방지

        svc_id      = item.get("service_id", "")
        svc_name    = (service_map or {}).get(svc_id, {}).get("name_ko", svc_id)
        source_type = item.get("source_type", "")
        full_text   = item.get("full_text", "") if source_type == "news" else ""
        rows.append([
            item.get("published_at", ""),
            svc_id,
            svc_name,
            source_type,
            item.get("change_type", ""),
            item.get("title", ""),
            item.get("summary") or "",
            url,
            item.get("sentiment", "neutral"),
            item.get("collected_at") or "",
            full_text,
        ])

    if skipped:
        log.info(f"[Sheets] 중복 {skipped}건 제외")
    if not rows:
        return 0

    try:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        log.info(f"[Sheets] {len(rows)}건 저장 완료")
        return len(rows)
    except Exception as e:
        log.error(f"[Sheets] 저장 실패: {e}")
        return 0


# ── 웹서버용 캐시 ──────────────────────────────────
_cache: dict = {"data": None, "ts": 0.0}
CACHE_TTL = 300  # 5분


def read_all_cached() -> list[dict]:
    """Sheets 전체 데이터를 캐시(5분)와 함께 반환. 필드명은 내부 키로 변환."""
    now = time.time()
    if _cache["data"] is not None and now - _cache["ts"] < CACHE_TTL:
        return _cache["data"]

    ws = _get_worksheet()
    if not ws:
        return _cache["data"] or []

    try:
        raw = ws.get_all_records()
        data = []
        for row in raw:
            mapped = {}
            for sheet_col, internal_key in _COL_MAP.items():
                mapped[internal_key] = row.get(sheet_col, "")
            data.append(mapped)
        _cache["data"] = data
        _cache["ts"]   = now
        log.info(f"[Sheets] 캐시 갱신 — {len(data)}건")
        return data
    except Exception as e:
        log.error(f"[Sheets] 읽기 실패: {e}")
        return _cache["data"] or []


def invalidate_cache():
    """캐시 강제 초기화 (크롤 완료 후 호출)."""
    _cache["data"] = None
    _cache["ts"]   = 0.0
