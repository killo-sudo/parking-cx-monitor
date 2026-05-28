"""모두의주차장 월간 CSAT 데이터 처리기.

Apps Script v4.4 (분석요청.gs) 로직의 Python 포팅.
Google Sheets 누적 시트에서 특정 월 데이터를 읽어 구조화된 dict로 반환.

환경변수:
    GOOGLE_CREDENTIALS    : 서비스 계정 JSON 문자열
    CSAT_SPREADSHEET_ID   : CSAT 누적 시트 ID
                            (기본: 17cDkOqnNVWgJ5F1F2-MmY-xA_8wON9Ay0O0En0yOE2U)
    CSAT_SOURCE_GID       : 원본 데이터 탭 GID (기본: 5177617)
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

log = logging.getLogger(__name__)

# ── 설정 ─────────────────────────────────────────
DEFAULT_SPREADSHEET_ID = "17cDkOqnNVWgJ5F1F2-MmY-xA_8wON9Ay0O0En0yOE2U"
DEFAULT_SOURCE_GID = "5177617"

STATUS_COL_IDX = 14         # O열: 응답 확인
STATUS_VALUE = "완료"
SEND_DATE_COL_IDX = 0       # A열: 발송 일자
DATE_COL_IDX = 30           # AE열: 설문지 회신일
AF_FALLBACK_IDX = 32        # AG열: 불만족 여부 (폴백)
DIS_SUBJ_FALLBACK_IDX = 33  # AH열: 불만족 주체 (폴백)

SAT_WORDS = {"매우만족", "만족", "5", "4"}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


# ── 헬퍼 ─────────────────────────────────────────
def _load_credentials() -> Credentials:
    raw = os.environ.get("GOOGLE_CREDENTIALS", "")
    # GitHub Secret 값에 UTF-8 BOM이 섞여있는 경우 제거 (sheets.py와 동일 패턴)
    raw_bytes = raw.encode("utf-8")
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        raw = raw_bytes[3:].decode("utf-8")
    raw = raw.strip()
    if raw:
        info = json.loads(raw)
    else:
        local = Path(__file__).resolve().parent.parent / "google_credentials.json"
        if not local.exists():
            raise RuntimeError(
                "GOOGLE_CREDENTIALS env or google_credentials.json required"
            )
        info = json.loads(local.read_text(encoding="utf-8-sig"))
    return Credentials.from_service_account_info(info, scopes=SCOPES)


def load_sheet_rows(spreadsheet_id: str, gid: str) -> list[list[Any]]:
    """gid로 시트 탭을 찾아 전체 행을 반환."""
    creds = _load_credentials()
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(spreadsheet_id)
    target = None
    for ws in ss.worksheets():
        if str(ws.id) == str(gid):
            target = ws
            break
    if target is None:
        raise RuntimeError(f"gid {gid} 탭을 찾지 못함")
    return target.get_all_values()


def parse_header(rows: list[list[Any]]) -> tuple[int, list[str]]:
    """상위 5행 중 비어있지 않은 첫 행을 헤더로 사용."""
    for r in range(min(5, len(rows))):
        if any(str(c).strip() for c in rows[r]):
            return r, [str(c).strip() for c in rows[r]]
    return -1, []


def col_letter(idx: int) -> str:
    s, n = "", idx + 1
    while n > 0:
        r = (n - 1) % 26
        s = chr(65 + r) + s
        n = (n - 1) // 26
    return s


def find_col(hdr: list[str], kws: list[str]) -> int:
    for i, h in enumerate(hdr):
        for kw in kws:
            if h.strip() == kw:
                return i
    for i, h in enumerate(hdr):
        for kw in kws:
            if kw in h:
                return i
    return -1


def extract_date(cell: Any) -> date | None:
    if cell is None or cell == "":
        return None
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    s = str(cell).strip()
    if not s:
        return None
    fmts = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
        "%Y. %m. %d",
        "%Y. %m. %d.",
        "%m/%d/%Y",
        "%Y%m%d",
    ]
    for f in fmts:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("/", "-")).date()
    except Exception:
        return None


def is_same_month(d: date | None, month: int, year: int) -> bool:
    if not d:
        return False
    return d.year == year and d.month == month


def fmt_md(d: date | None) -> str:
    if not d:
        return ""
    return f"{d.month}/{d.day}"


def get_af(row: list[Any], af_idx: int) -> int:
    """AG열 값 → -1(불만족) / 0(중립) / 1(만족)."""
    if af_idx < 0 or af_idx >= len(row):
        return 0
    raw = str(row[af_idx] or "").strip()
    if not raw:
        return 0
    try:
        v = float(raw)
        if v > 0:
            return 1
        if v < 0:
            return -1
        return 0
    except ValueError:
        pass
    if raw in ("불만족", "Y", "예", "true"):
        return -1
    if raw in ("만족", "N", "아니오", "false"):
        return 1
    return 0


def detect_csat_cols(
    hdr: list[str], rows: list[list[Any]], excl: list[int]
) -> list[dict[str, Any]]:
    """CSAT 항목 자동 감지 — 만족척도(5/4/3/2/1 또는 매우만족~매우불만족)."""
    levels = {"매우만족", "만족", "보통", "불만족", "매우불만족",
              "5", "4", "3", "2", "1"}
    result = []
    for c in range(len(hdr)):
        if c in excl:
            continue
        name = hdr[c].strip()
        if not name:
            continue
        total, match = 0, 0
        for r in rows:
            if c >= len(r):
                continue
            raw = str(r[c] or "").strip()
            if not raw:
                continue
            total += 1
            try:
                num = float(raw)
                if 1 <= num <= 5:
                    match += 1
                    continue
            except ValueError:
                pass
            if raw in levels:
                match += 1
        if total >= 3 and match / total >= 0.5:
            result.append({"idx": c, "name": name})
    return result


def short_csat_name(full: str) -> str:
    dot = full.find(". ")
    if 0 < dot < 8:
        return full[:dot]
    return full[:20]


def sort_desc(m: dict) -> list:
    return sorted(m.keys(), key=lambda k: m[k], reverse=True)


def get_weeks_sun_start(year: int, month: int) -> list[dict]:
    """월의 주차 분할 (일요일 시작 기준)."""
    if month == 12:
        last_day = date(year, 12, 31)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    weeks = []
    wn = 0
    cur = date(year, month, 1)
    while cur <= last_day:
        wn += 1
        # cur.weekday(): Mon=0..Sun=6 → Sun=6, JS의 day(): Sun=0..Sat=6
        wday_js = (cur.weekday() + 1) % 7  # Sun=0..Sat=6
        days_to_sat = 6 if wday_js == 0 else 6 - wday_js
        w_end = cur + timedelta(days=days_to_sat)
        if w_end > last_day:
            w_end = last_day
        weeks.append({"wn": wn, "start": cur, "end": w_end})
        cur = w_end + timedelta(days=1)
    return weeks


def _split_voc_buckets(text: str) -> str:
    """긴 텍스트 100자 이내 요약."""
    s = re.sub(r"\s+", " ", text).strip()
    if len(s) <= 100:
        return s
    return s[:97] + "..."


# ── 미해결 사유 패턴 분류 ───────────────────────
_UNRESOLVED_PATTERNS = [
    ("상담 자동종료/응답지연", ["자동종료", "응답 지연", "응답지연",
                                "기다리", "대기", "끊김", "끊어"]),
    ("환불 처리 불만",       ["환불 거부", "환불 안", "환불 처리", "환불 불가"]),
    ("규정/절차 불만",       ["규정", "절차", "정책", "방침", "기준이"]),
    ("현장/업체 문제",       ["현장", "업체", "주차장에서", "관리자",
                                "제휴", "관리실"]),
    ("소통/맥락 파악 부족",   ["맥락", "이해 못", "같은 말", "반복",
                                "이해를", "공감"]),
    ("시스템/앱 문제",       ["오류", "버그", "앱이", "시스템", "결제 안",
                                "결제오류", "기능"]),
]


def classify_unresolved_reason(text: str) -> str:
    s = text.strip()
    if not s:
        return "기타"
    for label, kws in _UNRESOLVED_PATTERNS:
        for kw in kws:
            if kw in s:
                return label
    return "기타"


# ── 메인 처리 ────────────────────────────────────
def process_csat(
    month: int,
    year: int,
    spreadsheet_id: str | None = None,
    gid: str | None = None,
) -> dict[str, Any]:
    """특정 월 CSAT 데이터를 구조화 dict로 반환."""
    # env가 빈 문자열인 경우에도 DEFAULT로 fallback 되도록 명시 처리
    spreadsheet_id = (
        spreadsheet_id
        or os.environ.get("CSAT_SPREADSHEET_ID")
        or DEFAULT_SPREADSHEET_ID
    )
    gid = gid or os.environ.get("CSAT_SOURCE_GID") or DEFAULT_SOURCE_GID
    log.info("대상 시트: %s (gid=%s)", spreadsheet_id, gid)

    log.info("CSAT 처리 시작: %d년 %d월", year, month)
    all_rows = load_sheet_rows(spreadsheet_id, gid)
    if not all_rows:
        raise RuntimeError("소스 시트가 비어있음")

    hdr_row, hdr = parse_header(all_rows)
    if hdr_row < 0:
        raise RuntimeError("헤더 행 감지 실패")
    data_rows = all_rows[hdr_row + 1 :]

    # ── 디버그: 헤더 + 핵심 컬럼 샘플 ──
    log.info("[디버그] 헤더 행: %d, 전체 %d열", hdr_row, len(hdr))
    log.info("[디버그] 헤더 전체: %s",
             " | ".join(f"{col_letter(i)}={h!r}" for i, h in enumerate(hdr[:40])))
    if data_rows:
        # O열(status, idx 14), AE열(date, idx 30) 샘플
        log.info("[디버그] A열(발송일자) 샘플5: %s",
                 [r[SEND_DATE_COL_IDX] if SEND_DATE_COL_IDX < len(r) else "" for r in data_rows[:5]])
        log.info("[디버그] O열(응답확인 idx=14) 샘플10: %s",
                 [r[STATUS_COL_IDX] if STATUS_COL_IDX < len(r) else "" for r in data_rows[:10]])
        log.info("[디버그] AE열(회신일 idx=30) 샘플10: %s",
                 [r[DATE_COL_IDX] if DATE_COL_IDX < len(r) else "" for r in data_rows[:10]])
        # O열 unique 값 집계 (전체)
        status_counts: dict[str, int] = {}
        for r in data_rows:
            v = str(r[STATUS_COL_IDX]).strip() if STATUS_COL_IDX < len(r) else ""
            status_counts[v] = status_counts.get(v, 0) + 1
        top_statuses = sorted(status_counts.items(), key=lambda x: -x[1])[:10]
        log.info("[디버그] O열 distinct 값 Top10: %s", top_statuses)
        # AE열의 4월 데이터 카운트
        ae_apr_count = sum(
            1 for r in data_rows
            if DATE_COL_IDX < len(r)
            and is_same_month(extract_date(r[DATE_COL_IDX]), month, year)
        )
        log.info("[디버그] AE열 기준 %d월 데이터: %d건", month, ae_apr_count)

    # ── 컬럼 인덱스 ──
    send_idx = SEND_DATE_COL_IDX
    date_idx = DATE_COL_IDX
    status_idx = STATUS_COL_IDX

    cat_idx = find_col(hdr, ["대분류"])
    mid_idx = find_col(hdr, ["중분류"])
    sub_idx = find_col(hdr, ["소분류"])
    lot_idx = find_col(hdr, ["주차장명", "주차장"])
    agent_idx = find_col(hdr, ["상담원명", "상담원"])

    res1st_idx = find_col(
        hdr,
        [
            "한 번에 해결되었나요", "한번에 해결되었나요",
            "한 번에 해결", "한번에 해결", "해결되었나요",
            "문의 내용이 한 번", "1차해결", "해결 여부", "해결여부",
        ],
    )
    unre_idx = find_col(
        hdr,
        [
            "해결되지 않았다면", "해결되지않았다면",
            "이유는 무엇인가요", "이유는 무엇",
            "미해결사유", "미해결 사유",
        ],
    )
    sat_idx = find_col(
        hdr,
        [
            "전체 서비스 경험에 만족하십니까", "전체 서비스 경험에 만족",
            "전체 서비스 경험", "복합4", "만족하십니까",
            "전체만족도", "전체 만족도", "종합만족도",
        ],
    )
    wish_idx = find_col(
        hdr,
        [
            "바라는 점을 자유롭게", "바라는 점", "바라는점",
            "자유롭게 기재", "고객의견", "의견", "건의사항",
        ],
    )
    af_idx = find_col(hdr, ["불만족 여부", "불만족여부"])
    if af_idx < 0:
        af_idx = AF_FALLBACK_IDX
    dis_subj_idx = find_col(hdr, ["불만족 주체", "불만족주체", "불만족 대상"])
    if dis_subj_idx < 0:
        dis_subj_idx = DIS_SUBJ_FALLBACK_IDX

    # ── 필터링 ──
    sent_rows = [
        r for r in data_rows
        if is_same_month(extract_date(r[send_idx] if send_idx < len(r) else ""),
                         month, year)
    ]
    a_rows = [
        r for r in data_rows
        if is_same_month(extract_date(r[date_idx] if date_idx < len(r) else ""),
                         month, year)
        and (status_idx < len(r) and str(r[status_idx]).strip() == STATUS_VALUE)
    ]
    n = len(a_rows)
    log.info("발송: %d, 완료: %d", len(sent_rows), n)

    # ── CSAT 항목 감지 ──
    excl = [
        x for x in [send_idx, date_idx, status_idx, cat_idx, mid_idx, sub_idx,
                    lot_idx, agent_idx, res1st_idx, unre_idx, wish_idx,
                    af_idx, dis_subj_idx]
        if x >= 0
    ]
    csat_cols = detect_csat_cols(hdr, a_rows, excl)
    csat_fallback = False
    if not csat_cols and sat_idx >= 0:
        csat_cols = [{"idx": sat_idx, "name": hdr[sat_idx]}]
        csat_fallback = True

    # ── CSAT 집계 ──
    csat_res_tot, csat_sat_tot = 0, 0
    item_stats = []
    for col in csat_cols:
        pos, tot = 0, 0
        for r in a_rows:
            if col["idx"] >= len(r):
                continue
            val = str(r[col["idx"]] or "").strip()
            if not val:
                continue
            tot += 1
            try:
                num = float(val)
                if num >= 4:
                    pos += 1
                    continue
            except ValueError:
                pass
            if val in SAT_WORDS:
                pos += 1
        csat_res_tot += tot
        csat_sat_tot += pos
        item_stats.append({
            "short_name": short_csat_name(col["name"]),
            "full_name": col["name"],
            "pos": pos,
            "tot": tot,
            "rate": round(pos / n * 100, 1) if n > 0 else 0.0,
        })

    csat_denom = n * len(csat_cols)
    csat_rate = round(csat_sat_tot / csat_denom * 100, 1) if csat_denom > 0 else 0.0

    csat_respondent_count = sum(
        1 for r in a_rows
        if any(
            col["idx"] < len(r) and str(r[col["idx"]] or "").strip()
            for col in csat_cols
        )
    )

    # ── 1차 해결 ──
    res1st_ok, res1st_fail, res1st_tot = 0, 0, 0
    for r in a_rows:
        if res1st_idx < 0 or res1st_idx >= len(r):
            continue
        v = str(r[res1st_idx] or "").strip()
        if not v:
            continue
        res1st_tot += 1
        if v in ("예", "Y", "해결", "1"):
            res1st_ok += 1
        elif v in ("아니오", "N", "미해결", "0"):
            res1st_fail += 1
    res1st_rate = round(res1st_ok / n * 100, 1) if n > 0 else 0.0

    # ── AF 집계 ──
    af_pos, af_neg = 0, 0
    for r in a_rows:
        af = get_af(r, af_idx)
        if af > 0:
            af_pos += 1
        elif af < 0:
            af_neg += 1

    # ── 불만족 주체 ──
    dis_subj_map: dict[str, int] = defaultdict(int)
    for r in a_rows:
        if get_af(r, af_idx) >= 0:
            continue
        subj = str(r[dis_subj_idx] or "").strip() if dis_subj_idx < len(r) else ""
        if not subj:
            subj = "(미기재)"
        dis_subj_map[subj] += 1

    # ── 환불 비율 ──
    refund_count = 0
    if sub_idx >= 0:
        refund_count = sum(
            1 for r in a_rows
            if sub_idx < len(r)
            and ("환불" in str(r[sub_idx] or "") or "취소" in str(r[sub_idx] or ""))
        )

    # ── 주간 추이 ──
    weeks = get_weeks_sun_start(year, month)
    week_stats = []
    for w in weeks:
        w_rows = [
            r for r in a_rows
            if (d := extract_date(r[date_idx] if date_idx < len(r) else ""))
            and w["start"] <= d <= w["end"]
        ]
        wn = len(w_rows)
        w_csat_pos = 0
        for col in csat_cols:
            for r in w_rows:
                if col["idx"] >= len(r):
                    continue
                val = str(r[col["idx"]] or "").strip()
                if not val:
                    continue
                try:
                    num = float(val)
                    if num >= 4:
                        w_csat_pos += 1
                        continue
                except ValueError:
                    pass
                if val in SAT_WORDS:
                    w_csat_pos += 1
        w_csat_denom = wn * len(csat_cols)
        w_csat_rate = round(w_csat_pos / w_csat_denom * 100, 1) if w_csat_denom > 0 else 0.0

        w_res1st_ok = sum(
            1 for r in w_rows
            if res1st_idx >= 0 and res1st_idx < len(r)
            and str(r[res1st_idx] or "").strip() in ("예", "Y", "해결", "1")
        )
        w_af_pos = sum(1 for r in w_rows if get_af(r, af_idx) > 0)
        w_af_neg = sum(1 for r in w_rows if get_af(r, af_idx) < 0)
        week_stats.append({
            "wn": w["wn"],
            "start": w["start"].isoformat(),
            "end": w["end"].isoformat(),
            "start_md": fmt_md(w["start"]),
            "end_md": fmt_md(w["end"]),
            "n": wn,
            "csat_rate": w_csat_rate,
            "res1st_rate": round(w_res1st_ok / wn * 100, 1) if wn > 0 else 0.0,
            "af_pos": w_af_pos,
            "af_neg": w_af_neg,
        })

    # ── 분류 집계 ──
    cat_map: dict[str, int] = defaultdict(int)
    cat_af_map: dict[str, dict[str, int]] = defaultdict(lambda: {"pos": 0, "neg": 0})
    mid_map: dict[str, int] = defaultdict(int)
    sub_map: dict[str, int] = defaultdict(int)
    sub_af_map: dict[str, dict[str, int]] = defaultdict(lambda: {"pos": 0, "neg": 0})
    lot_map: dict[str, int] = defaultdict(int)
    lot_af_map: dict[str, dict[str, int]] = defaultdict(lambda: {"pos": 0, "neg": 0})

    def cell(r: list[Any], idx: int) -> str:
        if idx < 0 or idx >= len(r):
            return ""
        return str(r[idx] or "").strip()

    for r in a_rows:
        af = get_af(r, af_idx)
        cat = cell(r, cat_idx) or "(미상)"
        cat_map[cat] += 1
        if af > 0:
            cat_af_map[cat]["pos"] += 1
        elif af < 0:
            cat_af_map[cat]["neg"] += 1
        mid_map[cell(r, mid_idx) or "(미상)"] += 1
        sub = cell(r, sub_idx) or "(미상)"
        sub_map[sub] += 1
        if af > 0:
            sub_af_map[sub]["pos"] += 1
        elif af < 0:
            sub_af_map[sub]["neg"] += 1
        lot = cell(r, lot_idx) or "(미상)"
        lot_map[lot] += 1
        if af > 0:
            lot_af_map[lot]["pos"] += 1
        elif af < 0:
            lot_af_map[lot]["neg"] += 1

    # ── 미해결 사유 ──
    unre_rows = []
    for r in a_rows:
        v_res = cell(r, res1st_idx)
        unresolved_text = cell(r, unre_idx)
        if v_res in ("아니오", "N", "미해결", "0") or unresolved_text:
            unre_rows.append({
                "date_md": fmt_md(extract_date(r[date_idx] if date_idx < len(r) else "")),
                "lot": cell(r, lot_idx),
                "cat": cell(r, cat_idx),
                "sub": cell(r, sub_idx),
                "reason": unresolved_text,
            })

    unresolved_class_map: dict[str, int] = defaultdict(int)
    for u in unre_rows:
        unresolved_class_map[classify_unresolved_reason(u["reason"])] += 1

    # ── VOC 필터 ──
    voc_rows_raw = []
    for r in a_rows:
        af = get_af(r, af_idx)
        v_res = cell(r, res1st_idx)
        wish = cell(r, wish_idx)
        unre_text = cell(r, unre_idx)
        if not (af < 0
                or v_res in ("아니오", "N", "미해결", "0")
                or wish
                or unre_text):
            continue
        voc_rows_raw.append({
            "date": extract_date(r[date_idx] if date_idx < len(r) else ""),
            "date_md": fmt_md(extract_date(r[date_idx] if date_idx < len(r) else "")),
            "lot": cell(r, lot_idx) or "(미상)",
            "cat": cell(r, cat_idx),
            "mid": cell(r, mid_idx),
            "sub": cell(r, sub_idx),
            "agent": cell(r, agent_idx),
            "sat": cell(r, sat_idx),
            "res1st": v_res,
            "wish": wish,
            "unresolved_reason": unre_text,
            "dis_subj": cell(r, dis_subj_idx),
            "af": af,
        })

    # 정렬: 미상 우선, 다음 lot_neg desc, 다음 date asc
    lot_neg_map = {k: v["neg"] for k, v in lot_af_map.items()}

    def voc_sort_key(v):
        lot = v["lot"]
        is_unknown = 0 if lot == "(미상)" else 1
        neg = -(lot_neg_map.get(lot, 0))
        d = v["date"] or date(1900, 1, 1)
        return (is_unknown, neg, d)

    voc_rows_raw.sort(key=voc_sort_key)

    # 바라는 점
    wishes = []
    for r in a_rows:
        wish = cell(r, wish_idx)
        if not wish:
            continue
        wishes.append({
            "cat": cell(r, cat_idx),
            "sub": cell(r, sub_idx),
            "wish": wish,
        })

    # ── 최종 출력 ──
    def with_pct(m: dict[str, int]) -> list[dict]:
        return [
            {"name": k, "count": v,
             "pct": round(v / n * 100, 1) if n > 0 else 0.0}
            for k, v in sorted(m.items(), key=lambda x: x[1], reverse=True)
        ]

    def cat_with_af(m: dict[str, int], af_m: dict[str, dict]) -> list[dict]:
        out = []
        for k in sort_desc(m):
            af = af_m.get(k, {"pos": 0, "neg": 0})
            out.append({
                "name": k,
                "count": m[k],
                "pct": round(m[k] / n * 100, 1) if n > 0 else 0.0,
                "af_pos": af["pos"],
                "af_neg": af["neg"],
            })
        return out

    result = {
        "label": f"{year}년 {month}월",
        "month": month,
        "year": year,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "debug": {
            "header_row": hdr_row,
            "res1st_col": f"{col_letter(res1st_idx)}({res1st_idx})" if res1st_idx >= 0 else "미감지",
            "unre_col":   f"{col_letter(unre_idx)}({unre_idx})"   if unre_idx   >= 0 else "미감지",
            "sat_col":    f"{col_letter(sat_idx)}({sat_idx})"     if sat_idx    >= 0 else "미감지",
            "af_col":     f"{col_letter(af_idx)}({af_idx})",
            "dis_subj_col": f"{col_letter(dis_subj_idx)}({dis_subj_idx})",
            "csat_count": len(csat_cols),
            "csat_fallback": csat_fallback,
        },
        "kpi_basic": {
            "sent": len(sent_rows),
            "n": n,
            "response_rate": round(n / len(sent_rows) * 100, 1)
                              if sent_rows else 0.0,
            "csat_response_total": csat_res_tot,
            "csat_respondent_count": csat_respondent_count,
            "csat_sat_total": csat_sat_tot,
            "csat_denom": csat_denom,
            "csat_rate": csat_rate,
            "res1st_tot": res1st_tot,
            "res1st_ok": res1st_ok,
            "res1st_fail": res1st_fail,
            "res1st_rate": res1st_rate,
            "af_pos": af_pos,
            "af_neg": af_neg,
            "af_neg_pct": round(af_neg / n * 100, 1) if n > 0 else 0.0,
            "refund_count": refund_count,
            "refund_rate": round(refund_count / n * 100, 1) if n > 0 else 0.0,
            "dis_subj_breakdown": dict(dis_subj_map),
        },
        "weekly": week_stats,
        "item_sat": item_stats,
        "category_dist": cat_with_af(cat_map, cat_af_map),
        "mid_category": with_pct(mid_map)[:15],
        "sub_category": cat_with_af(sub_map, sub_af_map)[:15],
        "unresolved_classified": [
            {"name": k, "count": v,
             "pct": round(v / len(unre_rows) * 100, 1) if unre_rows else 0.0}
            for k, v in sorted(unresolved_class_map.items(),
                                key=lambda x: x[1], reverse=True)
        ],
        "unresolved_total": len(unre_rows),
        "unresolved_rows": unre_rows,
        "parking_complaints": [
            {"name": k, "neg": lot_neg_map[k], "total": lot_map[k],
             "pct": round(lot_neg_map[k] / lot_map[k] * 100, 1) if lot_map[k] else 0.0}
            for k in sort_desc(lot_neg_map)
            if lot_neg_map[k] > 0
        ][:10],
        "parking_top": [
            {"name": k, "count": lot_map[k],
             "pct": round(lot_map[k] / n * 100, 1) if n > 0 else 0.0}
            for k in sort_desc(lot_map)
            if k != "(미상)" and lot_map[k] > 0
        ][:10],
        "voc_raw": [
            {**v, "date": v["date"].isoformat() if v["date"] else None,
             "summary": _split_voc_buckets(v["wish"] or v["unresolved_reason"]
                                            or v.get("sub", ""))}
            for v in voc_rows_raw
        ],
        "voc_wishes": wishes,
    }

    return result


# ── CLI ──────────────────────────────────────────
def _previous_month(today: date) -> tuple[int, int]:
    if today.month == 1:
        return 12, today.year - 1
    return today.month - 1, today.year


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--month", type=int)
    p.add_argument("--year", type=int)
    p.add_argument("--out", type=str, default=None,
                   help="JSON 출력 경로 (미지정 시 stdout)")
    args = p.parse_args()

    if args.month and args.year:
        m, y = args.month, args.year
    else:
        m, y = _previous_month(date.today())

    data = process_csat(m, y)
    out = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        log.info("저장: %s (%d자)", args.out, len(out))
    else:
        print(out)


if __name__ == "__main__":
    main()
