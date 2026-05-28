"""CSAT 월간 리포트 전체 오케스트레이션.

실행 흐름:
1. csat_processor.process_csat() — Google Sheets에서 데이터 처리
2. csat_report_gen.generate_all() — Claude API로 분석 + HTML 생성
3. docs/csat/csat_meta.json 업데이트
4. Slack Webhook으로 공지 발송

CLI:
    python backend/csat_main.py                    # 전월 자동
    python backend/csat_main.py --month 4 --year 2026
    python backend/csat_main.py --skip-slack       # 슬랙 발송 건너뜀
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

from csat_processor import process_csat
from csat_report_gen import generate_all
from csat_slack import post_to_slack

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_CSAT = REPO_ROOT / "docs" / "csat"
META_FILE = DOCS_CSAT / "csat_meta.json"


def _previous_month(today: date) -> tuple[int, int]:
    if today.month == 1:
        return 12, today.year - 1
    return today.month - 1, today.year


def _update_meta(month: int, year: int, slack_posted: bool) -> None:
    """월별 리포트 메타 정보 업데이트."""
    if META_FILE.exists():
        meta = json.loads(META_FILE.read_text(encoding="utf-8"))
    else:
        meta = {"reports": []}

    prefix = f"{year}-{month:02d}"
    entry = {
        "year": year,
        "month": month,
        "label": f"{year}년 {month}월",
        "page1": f"{prefix}_page1.html",
        "page2": f"{prefix}_page2.html",
        "slack_text": f"{prefix}_slack.txt",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "slack_posted": slack_posted,
    }

    # 동일 월 이전 엔트리 제거 후 삽입
    meta["reports"] = [r for r in meta["reports"]
                        if not (r["year"] == year and r["month"] == month)]
    meta["reports"].append(entry)
    meta["reports"].sort(key=lambda r: (r["year"], r["month"]), reverse=True)
    meta["latest"] = {"year": year, "month": month}
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")

    META_FILE.parent.mkdir(parents=True, exist_ok=True)
    META_FILE.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("메타 업데이트: %s", META_FILE)


def run(
    month: int,
    year: int,
    skip_slack: bool = False,
    confluence_url: str = "",
) -> int:
    log.info("=== CSAT 월간 리포트 생성 시작: %d년 %d월 ===", year, month)

    # 1. 데이터 처리
    data = process_csat(month, year)

    if data["kpi_basic"]["n"] == 0:
        log.warning("분석 대상 완료건수 0 — 리포트 생성 중단")
        return 2

    # 2. HTML + 슬랙 메시지 생성
    result = generate_all(data, DOCS_CSAT, confluence_url=confluence_url)

    # raw data도 함께 저장 (디버깅·재생성용)
    raw_file = DOCS_CSAT / f"{year}-{month:02d}_data.json"
    raw_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    log.info("raw 데이터 저장: %s", raw_file)

    # 3. Slack 발송
    slack_posted = False
    if not skip_slack:
        slack_posted = post_to_slack(result["slack_text"])

    # 4. 메타 업데이트
    _update_meta(month, year, slack_posted)

    log.info("=== 완료 ===")
    return 0


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    p = argparse.ArgumentParser()
    p.add_argument("--month", type=int)
    p.add_argument("--year", type=int)
    p.add_argument("--skip-slack", action="store_true")
    p.add_argument("--confluence", default=os.environ.get("CONFLUENCE_URL", ""))
    args = p.parse_args()

    if args.month and args.year:
        m, y = args.month, args.year
    else:
        m, y = _previous_month(date.today())

    rc = run(m, y, skip_slack=args.skip_slack, confluence_url=args.confluence)
    sys.exit(rc)


if __name__ == "__main__":
    main()
