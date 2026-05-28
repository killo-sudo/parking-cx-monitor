"""CSAT 누적 시트 구조 진단 — 헤더, 핵심 컬럼, 4월 데이터 분포 확인."""

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# UTF-8 출력 강제 (Windows cp949 대응)
sys.stdout.reconfigure(encoding="utf-8")

import gspread
from google.oauth2.service_account import Credentials

SS_ID = "17cDkOqnNVWgJ5F1F2-MmY-xA_8wON9Ay0O0En0yOE2U"
GID = "5177617"
TARGET_MONTH = 4
TARGET_YEAR = 2026

CREDS = Path(__file__).resolve().parent.parent / "google_credentials.json"


def col_letter(idx: int) -> str:
    s, n = "", idx + 1
    while n > 0:
        r = (n - 1) % 26
        s = chr(65 + r) + s
        n = (n - 1) // 26
    return s


def extract_date(cell):
    if cell is None or cell == "":
        return None
    s = str(cell).strip()
    for f in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S",
              "%Y/%m/%d", "%Y. %m. %d", "%Y. %m. %d.", "%m/%d/%Y", "%Y%m%d"]:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("/", "-")).date()
    except Exception:
        return None


def main():
    info = json.loads(CREDS.read_text(encoding="utf-8-sig"))
    creds = Credentials.from_service_account_info(info, scopes=[
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ])
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(SS_ID)
    ws = next(w for w in ss.worksheets() if str(w.id) == GID)
    rows = ws.get_all_values()
    print(f"전체 행 수: {len(rows)}")
    print(f"전체 열 수(첫행): {len(rows[0]) if rows else 0}")

    # 헤더 행 후보 (상위 5행)
    print("\n=== 상위 5행 첫 8열 ===")
    for i in range(min(5, len(rows))):
        sample = [f"{col_letter(j)}={rows[i][j]!r}" for j in range(min(8, len(rows[i])))]
        print(f"R{i}: {sample}")

    # 헤더 결정 (첫 비어있지 않은 행)
    hdr_row = -1
    for i in range(min(5, len(rows))):
        if any(str(c).strip() for c in rows[i]):
            hdr_row = i
            break
    if hdr_row < 0:
        print("헤더 감지 실패"); return
    hdr = [str(c).strip() for c in rows[hdr_row]]
    print(f"\n=== 헤더 (R{hdr_row}) 전체 ===")
    for i, h in enumerate(hdr):
        print(f"  {col_letter(i)}({i}) = {h!r}")

    data_rows = rows[hdr_row + 1 :]
    print(f"\n데이터 행 수: {len(data_rows)}")

    # O열(idx 14) - 응답 확인
    print(f"\n=== O열(idx=14, 헤더={hdr[14] if len(hdr) > 14 else '없음'!r}) ===")
    o_vals = [r[14].strip() if 14 < len(r) else "" for r in data_rows]
    print(f"  distinct Top10: {Counter(o_vals).most_common(10)}")
    print(f"  비어있지 않은 값 처음 10: {[v for v in o_vals if v][:10]}")

    # AE열(idx 30) - 회신일
    print(f"\n=== AE열(idx=30, 헤더={hdr[30] if len(hdr) > 30 else '없음'!r}) ===")
    ae_vals = [r[30] if 30 < len(r) else "" for r in data_rows]  # strip 안 함
    nonempty = [v for v in ae_vals if str(v).strip()]
    print(f"  비어있지 않은 셀: {len(nonempty)}건 / 전체 {len(ae_vals)}건")
    print(f"  raw repr 처음 15: {[repr(v) for v in nonempty[:15]]}")
    # 길이 분포
    len_dist = Counter(len(str(v)) for v in nonempty)
    print(f"  값 길이 분포 Top5: {len_dist.most_common(5)}")
    # 마지막 회신일 (뒤쪽 = 최근일 가능성)
    print(f"  뒤쪽 nonempty 15개: {[repr(v) for v in nonempty[-15:]]}")
    # 월별 분포
    ae_months = Counter()
    failed_samples = []
    for v in ae_vals:
        s = str(v).strip()
        if not s:
            continue
        d = extract_date(s)
        if d:
            ae_months[f"{d.year}-{d.month:02d}"] += 1
        elif len(failed_samples) < 8:
            failed_samples.append(s)
    print(f"  월별 분포 Top10: {ae_months.most_common(10)}")
    if failed_samples:
        print(f"  ⚠ 파싱 실패 샘플: {failed_samples}")

    # A열 - 발송 일자
    print(f"\n=== A열(idx=0, 헤더={hdr[0] if hdr else '없음'!r}) 월별 분포 ===")
    a_months = Counter()
    for r in data_rows:
        d = extract_date(r[0] if len(r) > 0 else "")
        if d:
            a_months[f"{d.year}-{d.month:02d}"] += 1
    print(f"  Top10: {a_months.most_common(10)}")

    # 4월 데이터 조합 (AE=4월 + O='완료')
    print(f"\n=== {TARGET_YEAR}-{TARGET_MONTH:02d} 매칭 진단 ===")
    apr_ae = sum(1 for v in ae_vals
                  if (d := extract_date(v)) and d.year == TARGET_YEAR and d.month == TARGET_MONTH)
    print(f"  AE열 = {TARGET_MONTH}월: {apr_ae}건")
    apr_ae_complete = sum(1 for r in data_rows
                          if 14 < len(r) and 30 < len(r)
                          and (d := extract_date(r[30])) and d.year == TARGET_YEAR and d.month == TARGET_MONTH
                          and str(r[14]).strip() == "완료")
    print(f"  AE열={TARGET_MONTH}월 + O열='완료': {apr_ae_complete}건")

    # 4월 회신일 + O열의 모든 값 분포
    o_vals_apr = []
    for r in data_rows:
        if 30 < len(r) and 14 < len(r):
            d = extract_date(r[30])
            if d and d.year == TARGET_YEAR and d.month == TARGET_MONTH:
                o_vals_apr.append(r[14].strip())
    print(f"\n=== {TARGET_YEAR}-{TARGET_MONTH:02d} 회신일 행의 O열 값 분포 ===")
    print(f"  {Counter(o_vals_apr).most_common(15)}")

    # 만약 AE열이 비어있다면 다른 컬럼에 회신일이 있을 수 있음 → 모든 컬럼 스캔
    if apr_ae == 0:
        print(f"\n⚠ AE열에 {TARGET_MONTH}월 데이터 없음 → 다른 컬럼에서 회신일 후보 검색")
        for ci in range(len(hdr)):
            cnt = 0
            for r in data_rows:
                if ci < len(r):
                    d = extract_date(r[ci])
                    if d and d.year == TARGET_YEAR and d.month == TARGET_MONTH:
                        cnt += 1
            if cnt > 50:  # 의미있는 양만
                print(f"  {col_letter(ci)}({ci}) [{hdr[ci]!r}]: {cnt}건")


if __name__ == "__main__":
    main()
