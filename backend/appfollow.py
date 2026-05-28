"""AppFollow REST API v2 — 앱 리뷰 완전 수집.

배경: iTunes RSS(캐시 지연)·google-play-scraper(GHA IP에서 0 반환)는 누락이
많아 data.json 앱 리뷰가 불완전했음. AppFollow는 양 스토어를 실시간 집계하는
원천(#모주_app_review 슬랙 피드의 소스)이라 누락 없이 본문까지 제공.

인증: 헤더 X-AppFollow-API-Token (Read 토큰). API Dashboard에서 발급.
엔드포인트: GET https://api.appfollow.io/api/v2/reviews
  필수 ext_id, from(YYYY-MM-DD), to(YYYY-MM-DD) / 선택 page, country
  비용 10 credits/요청 (계정 월 1000).

env: APPFOLLOW_API_TOKEN
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

API_URL = "https://api.appfollow.io/api/v2/reviews"

# AppFollow store 코드 → data.json source_type / 표시 플랫폼
_STORE_MAP = {
    "as": ("ios_appstore", "iOS"),      # App Store
    "gp": ("appstore", "Android"),      # Google Play (data.json 관례상 appstore=AOS)
}

# 모두의주차장 앱 ext_id (AppFollow = 스토어 ID)
MODU_EXT_IDS = {
    "ios": "780174422",                 # App Store numeric id
    "android": "com.parkingshare.mobile",  # Google Play package
}


def _token() -> str | None:
    return os.environ.get("APPFOLLOW_API_TOKEN", "").strip() or None


def fetch_reviews(ext_id: str, date_from: str, date_to: str,
                  token: str | None = None, country: str = "") -> list[dict]:
    """ext_id 앱의 [date_from, date_to] 리뷰 전체(페이지네이션 포함) 반환(raw)."""
    token = token or _token()
    if not token:
        raise RuntimeError("APPFOLLOW_API_TOKEN 미설정")
    headers = {"X-AppFollow-API-Token": token, "Accept": "application/json"}
    out: list[dict] = []
    page = 1
    while True:
        qs = f"ext_id={ext_id}&from={date_from}&to={date_to}&page={page}"
        if country:
            qs += f"&country={country}"
        req = urllib.request.Request(f"{API_URL}?{qs}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            log.error("AppFollow %s page=%d HTTP %s: %s",
                      ext_id, page, e.code, e.read().decode()[:200])
            raise
        rv = data.get("reviews", {})
        out.extend(rv.get("list", []))
        if not rv.get("page", {}).get("next"):
            break
        page += 1
    return out


def normalize(review: dict, service_id: str = "moduparking",
              name_ko: str = "모두의주차장") -> dict | None:
    """AppFollow 리뷰 → data.json items 스키마로 변환.

    crawl_ios_appstore/crawl_appstore 출력과 동일 형태:
    title '[iOS ★N] author', summary=본문, source_type, published_at, sentiment.
    """
    store = review.get("store", "")
    if store not in _STORE_MAP:
        return None
    source_type, plat = _STORE_MAP[store]
    rating = review.get("rating") or 0
    title = (review.get("title") or "").strip()
    content = (review.get("content") or "").strip()
    author = (review.get("author") or "익명").strip()
    summary = f"[{title}] {content}" if title and content else (title or content)
    summary = summary[:1200]
    # 감성: 별점 기반 (3점 이하 부정, 그 외 중립) — 기존 크롤 관례와 일치
    sentiment = "negative" if rating and rating <= 3 else "neutral"
    return {
        "service_id":   service_id,
        "name_ko":      name_ko,
        "published_at": review.get("date", "")[:10],
        "source_type":  source_type,
        "change_type":  "VOC",
        "title":        f"[{plat} ★{rating}] {author}",
        "summary":      summary,
        "url":          (f"https://apps.apple.com/kr/app/id{MODU_EXT_IDS['ios']}"
                         if store == "as"
                         else f"https://play.google.com/store/apps/details?id={MODU_EXT_IDS['android']}"),
        "sentiment":    sentiment,
        "full_text":    content,
        "review_id":    review.get("review_id"),
    }


def fetch_modu_reviews(date_from: str, date_to: str,
                       token: str | None = None) -> list[dict]:
    """모두의주차장 iOS+Android 리뷰를 data.json 스키마로 정규화하여 반환.
    review_id 기준 중복 제거.
    """
    token = token or _token()
    items: list[dict] = []
    for ext_id in (MODU_EXT_IDS["ios"], MODU_EXT_IDS["android"]):
        for raw in fetch_reviews(ext_id, date_from, date_to, token=token):
            norm = normalize(raw)
            if norm:
                items.append(norm)
    # review_id 중복 제거
    seen = set()
    uniq = []
    for it in items:
        rid = it.get("review_id")
        key = rid if rid is not None else (it["title"], it["published_at"], it["summary"][:30])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    return uniq
