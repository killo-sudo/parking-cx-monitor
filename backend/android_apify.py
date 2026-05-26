"""Android Google Play 리뷰 수집 — Apify actor 경유.

google-play-scraper 라이브러리가 GHA runner IP에서 일부 앱에 대해 0건을
silent return하는 케이스 발생 → Apify actor로 우회.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

# neatrat/google-play-store-reviews-scraper — $0.15/1K, 4.8★ 1.1K 사용자
_DEFAULT_ACTOR = "neatrat/google-play-store-reviews-scraper"


def fetch_android_reviews(
    package_name: str,
    recent_days: int = 14,
    max_reviews: int = 300,
) -> list[dict[str, Any]]:
    """Apify actor를 호출해 단일 앱의 Android 리뷰 fetch.

    반환값: actor가 돌려준 raw item 리스트.
    APIFY_TOKEN 미설정 / 호출 실패 시 빈 리스트.
    """
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        log.warning("APIFY_TOKEN 미설정 — Android Apify 수집 스킵")
        return []

    try:
        from apify_client import ApifyClient
    except ImportError:
        log.warning("apify-client 미설치")
        return []

    actor_id = os.environ.get("APIFY_ANDROID_ACTOR", _DEFAULT_ACTOR).strip() or _DEFAULT_ACTOR
    client = ApifyClient(token)

    # neatrat actor: package name 또는 Play Store URL 둘 다 지원
    url = (
        package_name
        if package_name.startswith("http")
        else f"https://play.google.com/store/apps/details?id={package_name}"
    )

    run_input = {
        "appIdOrUrl": url,
        "sortBy": "Newest",
        "recentDays": int(recent_days),
        "maxReviews": int(max_reviews),
        "uniqueReviewsOnly": True,
    }

    try:
        run = client.actor(actor_id).call(run_input=run_input)
    except Exception as e:
        log.error(f"Apify Android actor 호출 실패 [{actor_id}, {package_name}]: {e}")
        return []

    if not run or run.get("status") != "SUCCEEDED":
        log.warning(
            f"Apify Android run 실패 [{package_name}]: "
            f"status={run.get('status') if run else 'None'}"
        )
        return []

    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        return []

    try:
        items = list(client.dataset(dataset_id).iterate_items())
    except Exception as e:
        log.error(f"Apify Android dataset 읽기 실패 [{package_name}]: {e}")
        return []

    log.info(f"[Apify Android] pkg={package_name}: {len(items)}건 fetched")
    return items


def normalize_apify_android(
    raw: dict[str, Any],
    *,
    service_id: str,
    package_name: str,
    flag_below: int,
) -> dict[str, Any] | None:
    """Apify Android actor raw item을 우리 DB 포맷으로 변환."""
    # rating
    rating = raw.get("score") or raw.get("rating") or raw.get("stars")
    try:
        score = int(rating) if rating is not None else 5
    except (TypeError, ValueError):
        score = 5
    if score > flag_below:
        return None

    # date
    date_raw = (
        raw.get("at")
        or raw.get("date")
        or raw.get("reviewDate")
        or raw.get("updatedAt")
        or ""
    )
    if isinstance(date_raw, str) and len(date_raw) >= 10:
        pub_str = date_raw[:10]
        if pub_str[:4] < "2020":
            return None
    else:
        return None

    content = (
        raw.get("content")
        or raw.get("text")
        or raw.get("review")
        or raw.get("body")
        or ""
    ).strip()[:1000]

    if not content:
        return None

    author = (raw.get("userName") or raw.get("author") or raw.get("user") or "익명").strip()

    review_hash = hashlib.md5(
        (content + pub_str + author).encode()
    ).hexdigest()[:8]

    return {
        "service_id":   service_id,
        "published_at": pub_str,
        "source_type":  "appstore",
        "change_type":  "VOC",
        "title":        f"[Android ★{score}] {author}",
        "summary":      content,
        "url":          f"https://play.google.com/store/apps/details?id={package_name}#r{review_hash}",
        "sentiment":    "negative" if score <= 2 else "neutral",
    }
