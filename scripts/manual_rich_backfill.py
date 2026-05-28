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
import re
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
GAZETTE_DATA = REPO_ROOT / "docs" / "data.json"  # 앱 리뷰 크롤 데이터
_REVIEW_TITLE_RE = re.compile(r"\[(iOS|Android)\s*★\s*(\d)\]")


def load_app_reviews(year: int, month: int) -> dict | None:
    """docs/data.json(GAZETTE 크롤)에서 해당 월 모두의주차장 앱 리뷰 통계 산출.

    title 형식 '[iOS ★1] 작성자' / '[Android ★5] 작성자'에서 플랫폼·별점 파싱,
    본문은 summary, 월 필터는 published_at(YYYY-MM). 리뷰 없으면 None.
    page1 하단 섹션의 통계 카드·별점 분포에 사용(테마/인용은 llm.json).
    """
    if not GAZETTE_DATA.exists():
        return None
    try:
        items = json.loads(GAZETTE_DATA.read_text(encoding="utf-8")).get("items", [])
    except Exception:
        return None
    ym = f"{year}-{month:02d}"
    revs = [
        it for it in items
        if it.get("name_ko") == "모두의주차장"
        and it.get("source_type") in ("appstore", "ios_appstore")
        and (it.get("published_at") or "").startswith(ym)
    ]
    if not revs:
        return None

    platform: dict[str, int] = {}
    star_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    stars: list[int] = []
    senti = {"negative": 0, "neutral": 0, "positive": 0}
    for it in revs:
        m = _REVIEW_TITLE_RE.search(it.get("title", "") or "")
        if m:
            platform[m.group(1)] = platform.get(m.group(1), 0) + 1
            s = int(m.group(2))
            star_dist[s] = star_dist.get(s, 0) + 1
            stars.append(s)
        sv = it.get("sentiment")
        if sv in senti:
            senti[sv] += 1
    count = len(revs)
    return {
        "count": count,
        "avg_rating": round(sum(stars) / len(stars), 2) if stars else None,
        "platform": platform,
        "star_dist": star_dist,
        "sentiment": senti,
        "neg_pct": round(senti["negative"] / count * 100, 1) if count else 0.0,
    }


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

    # 1-2) 앱 리뷰 통계 주입 (page1 하단 섹션용, 테마/인용은 llm.json)
    data["app_reviews"] = load_app_reviews(year, month)

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
    ar = data.get("app_reviews")
    if ar:
        themes = len(llm.get("app_review_themes", []))
        print(f"  - 앱 리뷰: {ar['count']}건, 평균 ★{ar['avg_rating']}, "
              f"부정 {ar['neg_pct']}% / 테마 {themes}개"
              + ("" if themes else "  ⚠ llm.json에 app_review_themes 없음"))
    else:
        print("  - 앱 리뷰: 해당 월 데이터 없음(섹션 생략)")
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
