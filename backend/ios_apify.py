"""iOS App Store 리뷰 수집 — Apify actor 경유.

Apple iTunes RSS API가 2026-05-26경 사실상 deprecated 상태가 되면서 (entries
빈 응답) 우회 수단으로 도입. amp-api 직접 호출은 서버사이드 토큰만 사용해서
브라우저로도 추출 불가능 (Playwright POC 실패 — process.env.MEDIA_API_TOKEN).
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

# thewolves/appstore-reviews-scraper — $0.10/1K reviews, 입력: appIds + country
_DEFAULT_ACTOR = "thewolves/appstore-reviews-scraper"


def _run_field(run: Any, key: str) -> Any:
    """apify-client 버전 차이 대응 — Run이 dict일 수도 Run 객체일 수도 있음."""
    if run is None:
        return None
    if isinstance(run, dict):
        return run.get(key)
    return getattr(run, key, None)


def fetch_ios_reviews(
    app_id: str,
    country: str = "KR",
    max_reviews: int = 200,
) -> list[dict[str, Any]]:
    """Apify actor를 호출해 단일 앱의 iOS 리뷰 fetch.

    반환값: actor가 돌려준 raw item 리스트 (필드 매핑은 호출자가 처리).
    APIFY_TOKEN 미설정 / 호출 실패 시 빈 리스트.
    actor가 maxReviews를 무시할 수 있으니 호출자가 필요시 후처리 잘라야 함.
    """
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        log.warning("APIFY_TOKEN 미설정 — iOS Apify 수집 스킵")
        return []

    try:
        from apify_client import ApifyClient
    except ImportError:
        log.warning("apify-client 미설치")
        return []

    actor_id = os.environ.get("APIFY_IOS_ACTOR", _DEFAULT_ACTOR).strip() or _DEFAULT_ACTOR
    client = ApifyClient(token)

    # thewolves/appstore-reviews-scraper 실제 JSON 입력 필드 (콘솔 JSON 탭 확인됨)
    run_input = {
        "appIds": [str(app_id)],
        "country": country.lower(),  # "kr"
        "maxItems": int(max_reviews),
    }

    try:
        run = client.actor(actor_id).call(run_input=run_input)
    except Exception as e:
        log.error(f"Apify actor 호출 실패 [{actor_id}, {app_id}]: {e}")
        return []

    # apify-client 버전에 따라 dict 또는 Run 객체 반환 → 둘 다 대응
    status = _run_field(run, "status")
    dataset_id = _run_field(run, "defaultDatasetId") or _run_field(run, "default_dataset_id")

    if status != "SUCCEEDED":
        log.warning(f"Apify run 실패 [{app_id}]: status={status}")
        return []

    if not dataset_id:
        return []

    try:
        items = list(client.dataset(dataset_id).iterate_items())
    except Exception as e:
        log.error(f"Apify dataset 읽기 실패 [{app_id}]: {e}")
        return []

    log.info(f"[Apify iOS] app={app_id}: {len(items)}건 fetched")
    return items


def normalize_apify_item(
    raw: dict[str, Any],
    *,
    service_id: str,
    app_id: str,
    flag_below: int,
) -> dict[str, Any] | None:
    """Apify actor의 raw item을 우리 DB 포맷으로 변환.

    actor마다 필드명이 살짝 달라서 여러 키를 fallback으로 시도.
    rating > flag_below 인 리뷰는 None 반환.
    """
    # rating
    rating = raw.get("rating") or raw.get("score") or raw.get("stars")
    try:
        score = int(rating) if rating is not None else 5
    except (TypeError, ValueError):
        score = 5
    if score > flag_below:
        return None

    # date — ISO 8601 등 다양한 포맷 대응
    date_raw = (
        raw.get("date")
        or raw.get("updatedAt")
        or raw.get("createdAt")
        or raw.get("reviewDate")
        or ""
    )
    if isinstance(date_raw, str) and len(date_raw) >= 10:
        pub_str = date_raw[:10]
        if pub_str[:4] < "2020":
            return None
    else:
        return None

    # 본문 + 제목
    rev_title = (raw.get("title") or raw.get("reviewTitle") or "").strip()
    content = (
        raw.get("review")
        or raw.get("text")
        or raw.get("content")
        or raw.get("body")
        or ""
    ).strip()
    author = (raw.get("userName") or raw.get("author") or raw.get("user") or "익명").strip()

    if rev_title and content:
        merged = f"[{rev_title}] {content}"
    elif rev_title:
        merged = rev_title
    else:
        merged = content
    merged = merged[:1200]

    if not merged:
        return None

    review_hash = hashlib.md5(
        (merged + pub_str + author).encode()
    ).hexdigest()[:8]

    return {
        "service_id":   service_id,
        "published_at": pub_str,
        "source_type":  "ios_appstore",
        "change_type":  "VOC",
        "title":        f"[iOS ★{score}] {author}",
        "summary":      merged,
        "url":          f"https://apps.apple.com/kr/app/id{app_id}#r{review_hash}",
        "sentiment":    "negative" if score <= 2 else "neutral",
    }
