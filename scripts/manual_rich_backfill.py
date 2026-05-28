"""CSAT 리포트 수동 풍부화 (Claude Code 자동화 없이 운영).

배경:
- GitHub Actions의 monthly_csat 워크플로는 ANTHROPIC_API_KEY가 시크릿에 없으면
  csat_report_gen.llm_analyze()가 _fallback_analysis() 폴백으로 빠져,
  AI 제안·핵심요약이 한 줄 스텁만 찍힌 빈약한 리포트가 발행됨.
- API 키 결제 대신, 매월 1일 GitHub Actions가 폴백으로 한 번 찍은 뒤
  Claude Code에서 사람(킬로)이 "이번 달 CSAT 리포트 풍부화해줘" 트리거하면
  Claude가 직접 llm dict를 작성·저장하고 이 스크립트로 HTML/슬랙텍스트를 재생성한다.

워크플로:
1. docs/csat/{YYYY}-{MM}_data.json     ← Actions가 이미 생성·푸시
2. docs/csat/{YYYY}-{MM}_llm.json      ← Claude(나)가 새로 작성
3. python scripts/manual_rich_backfill.py --month M --year Y
   → page1.html / page2.html / slack.txt 덮어쓰기 + data.json rate 보정

산출물 키 보정:
- kpi_basic.csat_denom    : n*항목수 → csat_response_total(실제 응답칸)
- kpi_basic.csat_rate     : sat/response_total*100
- item_sat[i].rate        : pos/n → pos/tot (해당 항목 실제 응답자 기준)

llm.json 스키마 (csat_report_gen이 요구하는 키):
{
  "voc_analyses":           [{"index":int,"guichaek":str,"policy_basis":str,
                              "use_in_page1":bool,"use_in_page2":bool,"tag_text":str}, ...],
  "service_complaints_page1":[{"icon":str,"title":str,"color":str,
                              "count_text":str,"body":str}, ... 4개],
  "response_quality_page2": [위와 동일 ... 4개],
  "ai_suggestions_page1":   [{"icon":str,"title":str,"body":str}, ... 3개],
  "ai_suggestions_page2":   [위와 동일 ... 3개],
  "summary_page1":          [{"level":str,"text":str}, ... 4~6개],
  "summary_page2":          [위와 동일 ... 4~6개]
}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from csat_report_gen import (  # noqa: E402
    build_slack_message,
    render_page1,
    render_page2,
)

DOCS_CSAT = REPO_ROOT / "docs" / "csat"


def patch_rates(data: dict) -> dict:
    """data.json의 만족률을 새 공식(실제 응답 기준)으로 재계산.

    process_csat.py 패치(f7de594)의 산술 로직을 stored data에 직접 적용.
    주간 csat_rate는 per-week 응답칸 합이 저장돼 있지 않아 보정 불가(스킵).
    """
    k = data["kpi_basic"]
    if k.get("csat_response_total"):
        k["csat_denom"] = k["csat_response_total"]
        k["csat_rate"] = round(
            k["csat_sat_total"] / k["csat_response_total"] * 100, 1
        )
    for it in data["item_sat"]:
        if it.get("tot"):
            it["rate"] = round(it["pos"] / it["tot"] * 100, 1)
    return data


def run(month: int, year: int, llm_path: Path | None = None) -> int:
    prefix = f"{year}-{month:02d}"
    data_path = DOCS_CSAT / f"{prefix}_data.json"
    llm_path = llm_path or DOCS_CSAT / f"{prefix}_llm.json"

    if not data_path.exists():
        print(f"[ERR] data.json 없음: {data_path}", file=sys.stderr)
        return 2
    if not llm_path.exists():
        print(f"[ERR] llm.json 없음: {llm_path}", file=sys.stderr)
        print("  → Claude가 먼저 llm.json을 작성해야 합니다.", file=sys.stderr)
        return 2

    data = json.loads(data_path.read_text(encoding="utf-8"))
    llm = json.loads(llm_path.read_text(encoding="utf-8"))

    # 1) data.json 만족률 보정 (옛 공식 → 새 공식)
    data = patch_rates(data)

    # 2) HTML 렌더링
    p1 = render_page1(data, llm)
    p2 = render_page2(data, llm)
    slack = build_slack_message(data, llm, confluence_url="")

    # 3) 파일 저장
    (DOCS_CSAT / f"{prefix}_page1.html").write_text(p1, encoding="utf-8")
    (DOCS_CSAT / f"{prefix}_page2.html").write_text(p2, encoding="utf-8")
    (DOCS_CSAT / f"{prefix}_slack.txt").write_text(slack, encoding="utf-8")
    data_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(f"[OK] {prefix} 풍부 리포트 생성 완료")
    print(f"  - {prefix}_page1.html")
    print(f"  - {prefix}_page2.html")
    print(f"  - {prefix}_slack.txt")
    print(f"  - {prefix}_data.json (rate 보정)")
    print(f"  - CSAT(보정후): {data['kpi_basic']['csat_rate']}%")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--month", type=int, required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--llm", type=Path, default=None,
                   help="기본: docs/csat/{YYYY}-{MM}_llm.json")
    args = p.parse_args()
    sys.exit(run(args.month, args.year, args.llm))


if __name__ == "__main__":
    main()
