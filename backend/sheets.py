"""Google Sheets 연동 헬퍼.

환경변수:
    GOOGLE_CREDENTIALS  : 서비스 계정 JSON 파일 내용 (문자열 전체)
    SPREADSHEET_ID      : 구글 스프레드시트 ID
로컬에서는 프로젝트 루트의 google_credentials.json 파일도 사용 가능.

시트 구조:
    리뷰        — source_type in {appstore, ios_appstore}
    뉴스·블로그  — 그 외 모든 소스 (news, blog, homepage, youtube, rss 등)
"""

import os
import re
import json
import time
import logging
from collections import defaultdict
from pathlib import Path

log = logging.getLogger(__name__)

# ── 콘텐츠 dedup용 토큰화 (daily_crawl._dedup_by_title과 동일 규칙) ──
_JOSA_RE = re.compile(r'(에서|으로|이라|이며|이고|하고|부터|까지|에게|보다|처럼|만큼|과|와|의|에|도|만|로|서|고|며|나)$')


def _tokenize(text: str) -> set:
    tokens = set()
    for tok in re.findall(r'[가-힣a-z0-9]{2,}', (text or '').lower()):
        stripped = _JOSA_RE.sub('', tok)
        tok = stripped if len(stripped) >= 2 else tok
        if len(tok) >= 7:
            tok = tok[:5]
        tokens.add(tok)
    return tokens


def _jaccard(s1: set, s2: set) -> float:
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)

SHEET_REVIEWS = "리뷰"
SHEET_NEWS    = "뉴스·블로그"

HEADERS = ["날짜", "서비스ID", "서비스명", "소스유형", "변경유형", "제목", "요약", "URL", "감성", "수집일시", "전문"]

_REVIEW_SRC_TYPES = {"appstore", "ios_appstore"}

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


def _get_worksheet(sheet_name: str):
    spreadsheet_id = os.environ.get("SPREADSHEET_ID", "")
    if not spreadsheet_id:
        return None
    client = _get_client()
    if not client:
        return None
    try:
        sh = client.open_by_key(spreadsheet_id)
        try:
            ws = sh.worksheet(sheet_name)
        except Exception:
            ws = sh.add_worksheet(sheet_name, rows=100000, cols=len(HEADERS))
            ws.append_row(HEADERS)
            return ws
        # 기존 워크시트의 첫 행이 헤더가 아니면 헤더 행 삽입 (사용자가 전체 행 삭제했을 때 대비)
        try:
            first = ws.row_values(1)
        except Exception:
            first = []
        if first != HEADERS:
            try:
                ws.insert_row(HEADERS, 1, value_input_option="RAW")
                log.info(f"[Sheets:{sheet_name}] 헤더 행이 없어 자동 삽입")
            except Exception as e:
                log.warning(f"[Sheets:{sheet_name}] 헤더 자동 삽입 실패: {e}")
        return ws
    except Exception as e:
        log.error(f"[Sheets] 워크시트 접근 실패 ({sheet_name}): {e}")
        return None


def _append_to_sheet(items: list[dict], sheet_name: str, service_map: dict | None = None) -> int:
    """지정 시트에 신규 항목 추가.

    Dedup 2중:
      ① URL 정확 일치 (기존 동작)
      ② 제목+요약 토큰 자카드 ≥ 0.5 + 같은 날짜 (사용자 명세 "50% 단어 일치")
         - 리뷰 탭은 ②를 적용하지 않음 (작성자별 유사 리뷰가 정상이라 오탈락 방지)
    """
    if not items:
        return 0
    ws = _get_worksheet(sheet_name)
    if not ws:
        return 0

    existing_urls: set = set()
    existing_by_date: dict[str, list[set]] = defaultdict(list)
    is_news_sheet = (sheet_name == SHEET_NEWS)

    try:
        url_col_idx = HEADERS.index("URL")
        existing = ws.col_values(url_col_idx + 1)
        existing_urls = {v.strip() for v in existing if v.strip()}
    except Exception as e:
        log.warning(f"[Sheets] 기존 URL 조회 실패 ({sheet_name}, dedup 스킵): {e}")

    # ② 뉴스·블로그 시트: 기존 행의 (날짜, 제목+요약 토큰) 인덱싱
    if is_news_sheet:
        try:
            all_rows = ws.get_all_values()
            # 헤더 인덱스
            date_i  = HEADERS.index("날짜")
            title_i = HEADERS.index("제목")
            summ_i  = HEADERS.index("요약")
            for row in all_rows[1:]:
                if len(row) <= max(date_i, title_i, summ_i):
                    continue
                d = (row[date_i] or "").strip()[:10]
                t = (row[title_i] or "")
                s = (row[summ_i] or "")
                if d and t:
                    existing_by_date[d].append(_tokenize(t + " " + s))
        except Exception as e:
            log.warning(f"[Sheets] 콘텐츠 dedup 인덱싱 실패 ({sheet_name}): {e}")

    rows = []
    skipped_url = 0
    skipped_content = 0
    for item in items:
        url = (item.get("url") or "").strip()
        if url and url in existing_urls:
            skipped_url += 1
            continue

        # ② 콘텐츠 dedup (뉴스·블로그 시트만)
        if is_news_sheet:
            item_date = (item.get("published_at", "") or "")[:10]
            item_text = (item.get("title", "") or "") + " " + (item.get("summary", "") or "")
            item_tokens = _tokenize(item_text)
            if item_date and item_tokens:
                if any(_jaccard(item_tokens, et) >= 0.5
                       for et in existing_by_date.get(item_date, [])):
                    skipped_content += 1
                    continue
                # 같은 배치 내 후속 중복도 잡기 위해 추가
                existing_by_date[item_date].append(item_tokens)

        if url:
            existing_urls.add(url)

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

    if skipped_url or skipped_content:
        parts = []
        if skipped_url:     parts.append(f"URL중복 {skipped_url}")
        if skipped_content: parts.append(f"콘텐츠중복 {skipped_content}")
        log.info(f"[Sheets:{sheet_name}] 제외 " + " · ".join(parts))
    if not rows:
        return 0

    try:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        log.info(f"[Sheets:{sheet_name}] {len(rows)}건 저장 완료")
        return len(rows)
    except Exception as e:
        log.error(f"[Sheets:{sheet_name}] 저장 실패: {e}")
        return 0


def append_items(items: list[dict], service_map: dict | None = None) -> int:
    """신규 항목을 소스 유형에 따라 '리뷰' 또는 '뉴스·블로그' 시트에 분리 적재. 추가된 총 행 수 반환."""
    if not items:
        return 0

    reviews     = [i for i in items if i.get("source_type") in _REVIEW_SRC_TYPES]
    non_reviews = [i for i in items if i.get("source_type") not in _REVIEW_SRC_TYPES]

    total = 0
    if reviews:
        total += _append_to_sheet(reviews, SHEET_REVIEWS, service_map)
    if non_reviews:
        total += _append_to_sheet(non_reviews, SHEET_NEWS, service_map)
    return total


# ── 캐시 ───────────────────────────────────────
_cache: dict = {"reviews": None, "news": None, "ts": 0.0}
CACHE_TTL = 300  # 5분


def _read_sheet(sheet_name: str) -> list[dict]:
    ws = _get_worksheet(sheet_name)
    if not ws:
        return []
    try:
        raw = ws.get_all_records()
        data = []
        for row in raw:
            mapped = {}
            for sheet_col, internal_key in _COL_MAP.items():
                mapped[internal_key] = row.get(sheet_col, "")
            data.append(mapped)
        return data
    except Exception as e:
        log.error(f"[Sheets:{sheet_name}] 읽기 실패: {e}")
        return []


def read_all_cached() -> list[dict]:
    """리뷰 + 뉴스·블로그 시트 전체를 캐시(5분)와 함께 반환. 필드명은 내부 키로 변환."""
    now = time.time()
    if (
        _cache["reviews"] is not None
        and _cache["news"] is not None
        and now - _cache["ts"] < CACHE_TTL
    ):
        return _cache["reviews"] + _cache["news"]

    reviews = _read_sheet(SHEET_REVIEWS)
    news    = _read_sheet(SHEET_NEWS)

    _cache["reviews"] = reviews
    _cache["news"]    = news
    _cache["ts"]      = now
    log.info(f"[Sheets] 캐시 갱신 — 리뷰 {len(reviews)}건, 뉴스·블로그 {len(news)}건")
    return reviews + news


def invalidate_cache():
    """캐시 강제 초기화 (크롤 완료 후 호출)."""
    _cache["reviews"] = None
    _cache["news"]    = None
    _cache["ts"]      = 0.0
