"""docs/data.json의 모두의주차장 앱 리뷰를 AppFollow 완전판으로 갱신.

배경: 자체 스토어 크롤(iTunes RSS·google-play-scraper)은 누락이 많아
CSAT 리포트 앱 리뷰 섹션이 불완전했음. AppFollow API(원천)로 해당 기간
리뷰를 완전 수집해 data.json의 modu 앱 리뷰를 교체한다.

- 자체 크롤 파이프라인(db/sheets)은 건드리지 않고 docs/data.json만 후처리.
- monthly_csat 워크플로에서 리포트 생성 전에 실행(월 1회, ~20 credits).
- env APPFOLLOW_API_TOKEN 없으면 아무것도 하지 않고 종료(기존 데이터 유지).

사용:
    python scripts/refresh_app_reviews.py            # 최근 2개월 갱신
    python scripts/refresh_app_reviews.py --months 4 # 최근 4개월
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

DATA_JSON = REPO_ROOT / "docs" / "data.json"


def _load_env():
    """로컬 실행 편의: .env의 APPFOLLOW_API_TOKEN 로드(Actions에선 env로 주입)."""
    if os.environ.get("APPFOLLOW_API_TOKEN"):
        return
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("APPFOLLOW_API_TOKEN") and "=" in line:
                os.environ["APPFOLLOW_API_TOKEN"] = line.split("=", 1)[1].strip()


def _month_start(today: date, months_back: int) -> date:
    y, m = today.year, today.month - months_back
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def run(months: int = 2) -> int:
    _load_env()
    if not os.environ.get("APPFOLLOW_API_TOKEN"):
        print("[SKIP] APPFOLLOW_API_TOKEN 미설정 — data.json 유지")
        return 0

    import appfollow  # noqa: E402

    today = date.today()
    date_from = _month_start(today, months - 1).strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")
    print(f"[INFO] AppFollow 리뷰 수집: {date_from} ~ {date_to}")

    try:
        af_items = appfollow.fetch_modu_reviews(date_from, date_to)
    except Exception as e:
        print(f"[ERR] AppFollow 수집 실패: {e} — data.json 유지", file=sys.stderr)
        return 1
    if not af_items:
        print("[WARN] 수집된 리뷰 0건 — data.json 유지")
        return 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for it in af_items:
        it.setdefault("collected_at", now)

    d = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    items = d["items"]
    before = len(items)

    def is_modu_in_window(i: dict) -> bool:
        return (i.get("name_ko") == "모두의주차장"
                and i.get("source_type") in ("appstore", "ios_appstore")
                and (i.get("published_at") or "") >= date_from)

    kept = [i for i in items if not is_modu_in_window(i)]
    removed = before - len(kept)
    new_items = kept + af_items
    new_items.sort(key=lambda x: (x.get("published_at") or ""), reverse=True)
    d["items"] = new_items
    d["total"] = len(new_items)
    DATA_JSON.write_text(
        json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[OK] modu 앱 리뷰 갱신: 제거 {removed} / 추가 {len(af_items)} "
          f"/ 총 {before}→{len(new_items)}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--months", type=int, default=2,
                   help="최근 N개월 갱신 (기본 2)")
    args = p.parse_args()
    sys.exit(run(args.months))


if __name__ == "__main__":
    main()
