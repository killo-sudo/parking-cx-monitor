#!/usr/bin/env python3
"""메인 크롤러 — 앱 실행 시 또는 수동 새로고침 시 호출."""

import sys
import os
import json
import logging
import hashlib
import re
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import quote

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

if getattr(sys, 'frozen', False):
    ROOT_DIR     = Path(sys.executable).parent.parent
    WRITABLE_DIR = Path(os.environ.get('APPDATA', str(Path.home()))) / 'parking-cx-monitor'
else:
    ROOT_DIR     = Path(__file__).parent.parent
    WRITABLE_DIR = ROOT_DIR
sys.path.insert(0, str(ROOT_DIR / "backend"))

import yaml
import requests
from bs4 import BeautifulSoup
import feedparser

import db
from diff_detector import classify_change_type, classify_sentiment

# ──────────────────────────────────────────────
# 로그 설정
# ──────────────────────────────────────────────

LOG_DIR = WRITABLE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_log_file = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def _get(url, **kwargs):
    """requests.get with SSL fallback: try verify=True first, then verify=False."""
    try:
        return requests.get(url, headers=HEADERS, timeout=15, verify=True, **kwargs)
    except requests.exceptions.SSLError:
        return requests.get(url, headers=HEADERS, timeout=15, verify=False, **kwargs)

DATA_DIR = ROOT_DIR / "data"


def load_sources() -> list[dict]:
    with open(DATA_DIR / "sources.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("sources", [])


def load_services() -> list[dict]:
    with open(DATA_DIR / "services.json", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("services", [])


# ──────────────────────────────────────────────
# RSS 크롤러 (Google News + Naver News RSS)
# ──────────────────────────────────────────────

def crawl_rss(source: dict, services: list[dict]) -> list[dict]:
    url_template = source.get("url_template", "")
    cutoff = datetime.now() - timedelta(days=source.get("days_back", 1))
    items: list[dict] = []

    for svc in services:
        sid      = svc["id"]
        keywords = svc.get("monitor_keywords", [])

        for kw in keywords:
            url = url_template.replace("{KEYWORD}", quote(kw))
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    if getattr(entry, "published_parsed", None):
                        pub_dt = datetime(*entry.published_parsed[:6])
                    else:
                        pub_dt = datetime.now()

                    if pub_dt < cutoff:
                        continue

                    raw_title = entry.get("title", "")
                    title     = _normalize_news_title(raw_title)
                    summary   = _strip_html(entry.get("summary", ""))[:1500]
                    link      = entry.get("link", "")
                    # RSS 요약이 짧으면 기사 본문 추출 — 단, 브랜드 키워드 포함 확인
                    if len(summary) < 200 and link:
                        fetched = _fetch_article_text(link)
                        brand_kws = _BRAND_REQUIRED.get(sid, [])
                        fetched_has_brand = any(b in fetched.lower() for b in brand_kws) if brand_kws else True
                        if len(fetched) > len(summary) and fetched_has_brand:
                            summary = fetched

                    # 주차·브랜드 관련성 삼중 검증 (브랜드 + 관련성 + 주차 강화 게이트)
                    if not _is_relevant(title, summary, svc):
                        continue
                    if not _brand_validate(sid, title, summary):
                        continue
                    if not _is_strong_parking_match(title, summary):
                        continue  # 제목에 주차키워드 없고 본문에 1회만 있는 비유적 언급 차단

                    # 뉴스 전문 추출 (요약과 별도)
                    full_text = _fetch_article_text(link, max_chars=3000) if link else ""

                    dedup_key = f"{sid}|{pub_dt.strftime('%Y-%m-%d')}|{title}"

                    items.append({
                        "service_id":   sid,
                        "published_at": pub_dt.strftime("%Y-%m-%d"),
                        "source_type":  "news",
                        "change_type":  classify_change_type(title, summary),
                        "title":        title,
                        "summary":      summary,
                        "full_text":    full_text,
                        "url":          link,
                        "sentiment":    classify_sentiment(title, summary),
                        "dedup_key":    dedup_key,
                    })
            except Exception as e:
                log.warning(f"RSS 실패 [{sid}|{kw}]: {e}")
                continue

    return items


_GENERIC_WORDS = {
    "주차", "파킹", "parking", "주차장", "서비스", "이용", "요금", "예약",
    "차량", "입차", "출차", "정기", "할인", "모두의", "the", "and", "of",
}

# 서비스별 필수 브랜드 키워드 — 본문에 없으면 수집 제외
_BRAND_REQUIRED: dict[str, list[str]] = {
    'moduparking':    ['모두의주차장', '모두의 주차장'],
    'iparking':       ['아이파킹'],
    'nicepark':       ['나이스파크', 'nicepark'],
    'sk_shielders':   ['sk쉴더스', 'sk 쉴더스', 'sk쉴더'],
    'kmpark':         ['케이엠파크', '케이엠파킹'],
    'parkingcloud':   ['파킹클라우드'],
    'parkingfriends': ['파킹프렌즈', 'mds모빌리티'],
    'amano_korea':    ['아마노코리아', '아마노 주차'],
    'highparking':    ['하이파킹', '투루파킹', '휴맥스모빌리티'],
    'zoomansa':       ['주만사'],
    'kakaot_parking': ['카카오t', '카카오모빌리티', '케이엠파킹'],
    'tmap_parking':   ['티맵 주차', 'tmap 주차', '티맵모빌리티 주차'],
}

_PARKING_KW = [
    '주차', '파킹', 'parking', '입차', '출차', '정기권', '월정기',
    '주차요금', '주차비', '무료주차', '유료주차', '주차면', '발렛', '주차권', '주차장',
]

# 뉴스/블로그 수집 시 제외할 키워드 (카셰어링·대리운전·택시·EV충전·물류 관련 혼입 방지)
_NEWS_EXCLUDE_KW = {
    # 카셰어링/대리/택시
    "그린카", "쏘카", "피플카", "대리", "택시",
    # 전기차 충전 사업 (별개 산업, 주차와 본질 다름)
    "볼트업", "전기차 충전", "충전사업", "충전 사업",
    "충전인프라", "충전 인프라", "충전기 설치",
    # 자율주행·로지스틱스·피지컬 AI (모빌리티 인접이나 주차 무관)
    "피지컬 AI", "피지컬AI", "물류 AX", "물류AX",
    "무인 물류", "자율주행 물류",
}

# 모빌리티 통합 앱(카카오T/Tmap) 리뷰 — 주차 키워드 없으면 제외
_PARKING_FILTERED_REVIEW_SVCS = {"kakaot_parking", "tmap_parking"}


def _review_cutoff_date():
    """리뷰 수집 시 작성일이 이 날짜 이전이면 제외.
    환경변수 CRAWL_FROM_DATE (예: '2026-01-01') 또는 None 반환.
    """
    raw = os.environ.get("CRAWL_FROM_DATE", "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        log.warning(f"CRAWL_FROM_DATE 형식 오류 (YYYY-MM-DD 필요): {raw}")
        return None


def _has_parking_kw(text: str) -> bool:
    """본문에 주차 관련 키워드 1개 이상 포함 여부 (리뷰용)."""
    if not text:
        return False
    t = text.lower()
    return any(kw in t for kw in _PARKING_KW)


def _is_strong_parking_match(title: str, body: str) -> bool:
    """뉴스/블로그용 강화 게이트.
    조건: 제목에 주차 키워드 있거나, 본문에 2회 이상 등장해야 통과.
    1회짜리 비유적 언급(예: "장시간 주차 환경") 차단.
    """
    title_l = (title or "").lower()
    body_l  = (body or "").lower()
    if any(kw in title_l for kw in _PARKING_KW):
        return True
    # 본문 등장 횟수 합산 (같은 키워드 여러 번도 1로 카운트해서 보수적)
    distinct_hits = sum(1 for kw in _PARKING_KW if kw in body_l)
    if distinct_hits >= 2:
        return True
    # 단일 키워드가 본문에 여러 번 나오는 경우도 통과
    total_hits = sum(body_l.count(kw) for kw in _PARKING_KW)
    return total_hits >= 2


def _brand_validate(service_id: str, title: str, desc: str) -> bool:
    """서비스 브랜드명이 본문에 실제로 포함되어 있는지 검증.
    _BRAND_REQUIRED에 등록되지 않은 서비스는 기본 차단 (deny-by-default).
    """
    brands = _BRAND_REQUIRED.get(service_id)
    if not brands:
        return False  # 브랜드 규칙 미등록 서비스는 수집 제외
    chk = (title + " " + desc).lower()
    return any(b in chk for b in brands)


def _parking_summary(text: str, max_chars: int = 500) -> str:
    """텍스트에서 주차 관련 문장만 추출해 요약 생성.
    '어떤 주차 내용이 담긴 글인지'를 보여주기 위한 필터.
    """
    if not text:
        return ""
    sents = re.split(r'[.!?\n]+', text)
    rel = [s.strip() for s in sents
           if len(s.strip()) >= 10 and any(kw in s.lower() for kw in _PARKING_KW)]
    if rel:
        return ' '.join(rel[:4])[:max_chars]
    return text[:max_chars]

def _normalize_news_title(title: str) -> str:
    """Google News 제목에서 ' – 언론사명' 접미사 제거."""
    return re.sub(r'\s*[\-–—]\s*[^\-–—]{1,35}$', '', title or '').strip()

def _is_relevant(title: str, summary: str, svc: dict) -> bool:
    """수집된 뉴스가 해당 서비스와 명확히 관련 있는지 엄격하게 검증."""
    text = (title + " " + summary).lower()
    keywords = svc.get("monitor_keywords", [])

    # 1순위: 전체 키워드 구문 완전 매칭
    for kw in keywords:
        if kw.lower() in text:
            return True

    # 2순위: 키워드 내 브랜드성 단어만 (제네릭 단어 제외, 3자 이상)
    for kw in keywords:
        for word in kw.split():
            wl = word.lower()
            if len(wl) >= 3 and wl not in _GENERIC_WORDS and wl in text:
                return True

    return False


# ──────────────────────────────────────────────
# Google Play 리뷰 크롤러
# ──────────────────────────────────────────────

def crawl_appstore(source: dict) -> list[dict]:
    if source.get("platform") != "google_play":
        return []

    app_id      = source.get("app_id", "")
    sid         = source.get("service_id", "")
    flag_below  = source.get("flag_below_rating", 3)

    review_count = source.get("review_count", 200)
    try:
        from google_play_scraper import reviews, Sort
        result, _ = reviews(
            app_id, lang="ko", country="kr",
            sort=Sort.NEWEST, count=review_count,
        )
    except ImportError:
        log.warning("google-play-scraper 미설치")
        return []
    except Exception as e:
        log.error(f"Google Play 조회 실패 [{app_id}]: {e}")
        return []

    cutoff = _review_cutoff_date()
    items: list[dict] = []
    for r in result:
        score  = r.get("score", 5)
        if score > flag_below:
            continue

        pub_raw = r.get("at")
        if not isinstance(pub_raw, datetime) or pub_raw.year < 2020:
            continue  # 날짜 불명 → 제외
        if cutoff and pub_raw.date() < cutoff:
            continue  # 컷오프 이전 작성 → 제외
        pub_date_str = pub_raw.strftime("%Y-%m-%d")

        content = (r.get("content") or "")[:1000]

        # 모빌리티 통합 앱(카카오T/Tmap) — 본문에 주차 키워드 없으면 제외
        if sid in _PARKING_FILTERED_REVIEW_SVCS and not _has_parking_kw(content):
            continue

        review_hash = hashlib.md5((content + pub_date_str + r.get('userName', '')).encode()).hexdigest()[:8]
        items.append({
            "service_id":   sid,
            "published_at": pub_date_str,
            "source_type":  "appstore",
            "change_type":  "VOC",
            "title":        f"[Android ★{score}] {r.get('userName', '익명')}",
            "summary":      content,
            "url":          f"https://play.google.com/store/apps/details?id={app_id}#r{review_hash}",
            "sentiment":    "negative" if score <= 2 else "neutral",
        })

    return items


# ──────────────────────────────────────────────
# iOS App Store 리뷰 크롤러 (iTunes RSS API)
# ──────────────────────────────────────────────

def crawl_ios_appstore(source: dict) -> list[dict]:
    """Apple App Store 리뷰 수집 (iTunes RSS — 인증 불필요).

    Apple iTunes RSS API의 알려진 버그: sortBy=mostRecent가 실제로 최신 리뷰를
    안 돌려주는 경우가 잦음 (앱별로 수주~수개월 stale 상태로 캐싱됨).
    → mostRecent와 mostHelpful 두 sort를 모두 호출해서 합집합으로 보강.
      이렇게 하면 highparking 같은 케이스에서 누락 6개월 → 10일로 감소.
    """
    app_id     = source.get("app_id", "")
    sid        = source.get("service_id", "")
    flag_below = source.get("flag_below_rating", 3)

    if not app_id:
        return []

    max_pages = source.get("max_pages", 1)
    entries: list = []
    # 첫 page의 첫 entry는 앱 정보 — sort별로 한 번씩만 제외
    for sort_by in ("mostRecent", "mostHelpful"):
        for page in range(1, max_pages + 1):
            url = (
                f"https://itunes.apple.com/kr/rss/customerreviews/"
                f"page={page}/id={app_id}/sortBy={sort_by}/json"
            )
            try:
                resp = _get(url)
                if resp.status_code != 200:
                    break
                data = resp.json()
                page_entries = data.get("feed", {}).get("entry", [])
                if not page_entries:
                    break
                # 각 sort의 page=1 첫 entry는 앱 정보 → 스킵
                if page == 1 and page_entries:
                    page_entries = page_entries[1:]
                if not page_entries:
                    break
                entries.extend(page_entries)
            except Exception as e:
                log.warning(f"iOS 앱스토어 요청 실패 [{app_id}] sort={sort_by} page={page}: {e}")
                break
    if not entries:
        return []

    # review_hash로 자연 dedup — 같은 리뷰가 sort별로 중복돼도 hash 동일하면 1개로
    cutoff = _review_cutoff_date()
    seen_hashes: set[str] = set()
    items: list[dict] = []
    for entry in entries:
        try:
            rating_raw = entry.get("im:rating", {})
            if isinstance(rating_raw, dict):
                score = int(rating_raw.get("label", "5"))
            else:
                score = 5

            if score > flag_below:
                continue

            rev_title = entry.get("title", {}).get("label", "").strip()
            content   = entry.get("content", {}).get("label", "").strip()
            author    = entry.get("author", {}).get("name", {}).get("label", "익명")

            # iOS 리뷰는 날짜 정보가 'updated' 필드에 있음
            updated = entry.get("updated", {}).get("label", "")
            if not updated or updated[:4] < "2020":
                continue  # 날짜 불명 → 제외
            pub_str = updated[:10]
            if cutoff:
                try:
                    if datetime.strptime(pub_str, "%Y-%m-%d").date() < cutoff:
                        continue
                except ValueError:
                    pass

            # iOS는 제목·본문이 별도 필드. 본문이 짧으면 제목이 실제 의미일 때가 많음
            # → "요약" 컬럼에 둘을 합쳐 사용자가 한 컬럼에서 전체 리뷰를 본다
            if rev_title and content:
                merged_summary = f"[{rev_title}] {content}"
            elif rev_title:
                merged_summary = rev_title
            else:
                merged_summary = content
            merged_summary = merged_summary[:1200]

            # 모빌리티 통합 앱(카카오T/Tmap) — 합쳐진 본문에 주차 키워드 없으면 제외
            if sid in _PARKING_FILTERED_REVIEW_SVCS and not _has_parking_kw(merged_summary):
                continue

            review_hash = hashlib.md5((merged_summary + pub_str + author).encode()).hexdigest()[:8]
            if review_hash in seen_hashes:
                continue   # 다른 sort에서 이미 본 리뷰
            seen_hashes.add(review_hash)
            items.append({
                "service_id":   sid,
                "published_at": pub_str,
                "source_type":  "ios_appstore",
                "change_type":  "VOC",
                "title":        f"[iOS ★{score}] {author}",
                "summary":      merged_summary,
                "url":          f"https://apps.apple.com/kr/app/id{app_id}#r{review_hash}",
                "sentiment":    "negative" if score <= 2 else "neutral",
            })
        except Exception as e:
            log.debug(f"iOS 리뷰 항목 파싱 오류: {e}")
            continue

    return items


# ──────────────────────────────────────────────
# 앱 평점 / 버전 변경 추적
# ──────────────────────────────────────────────

def crawl_app_info(source: dict) -> list[dict]:
    """앱 평점·버전 변화 감지. 변경 시만 change 기록."""
    platform = source.get("platform", "google_play")
    app_id   = source.get("app_id", "")
    sid      = source.get("service_id", "")

    if not app_id:
        return []

    if platform == "google_play":
        rating, num_ratings, version, update_notes = _fetch_gplay_info(app_id)
    elif platform == "ios":
        rating, num_ratings, version, update_notes = _fetch_ios_info(app_id)
    else:
        return []

    if rating is None:
        return []

    prev = db.get_app_info(sid, platform)
    db.save_app_info(sid, platform, app_id, rating, num_ratings, version, update_notes)

    items: list[dict] = []
    store_label = "Google Play" if platform == "google_play" else "App Store"
    store_url   = (f"https://play.google.com/store/apps/details?id={app_id}"
                   if platform == "google_play"
                   else f"https://apps.apple.com/kr/app/id{app_id}")

    if prev:
        # 평점 0.05 이상 변화
        prev_rating = prev.get("rating") or 0
        if abs(prev_rating - rating) >= 0.05 and prev_rating > 0:
            direction = "▲ 상승" if rating > prev_rating else "▼ 하락"
            items.append({
                "service_id":   sid,
                "published_at": datetime.now().strftime("%Y-%m-%d"),
                "source_type":  "appstore",
                "change_type":  "VOC",
                "title":        f"[{store_label}] 평점 {direction} {prev_rating:.2f} → {rating:.2f} (리뷰 {num_ratings:,}개)",
                "summary":      f"평점 변화: {prev_rating:.2f} → {rating:.2f}\n총 리뷰 수: {num_ratings:,}개",
                "url":          store_url,
                "sentiment":    "positive" if rating > prev_rating else "negative",
            })

        # 버전 업데이트
        prev_version = prev.get("version") or ""
        if prev_version and version and prev_version != version and update_notes:
            items.append({
                "service_id":   sid,
                "published_at": datetime.now().strftime("%Y-%m-%d"),
                "source_type":  "appstore",
                "change_type":  classify_change_type(update_notes),
                "title":        f"[{store_label}] 버전 업데이트 {prev_version} → {version}",
                "summary":      update_notes[:500],
                "url":          store_url,
                "sentiment":    classify_sentiment(update_notes),
            })

    return items


def _fetch_gplay_info(app_id: str) -> tuple:
    try:
        from google_play_scraper import app as gplay_app
        info = gplay_app(app_id, lang="ko", country="kr")
        return (
            round(info.get("score") or 0, 2),
            info.get("ratings") or 0,
            info.get("version") or "",
            (info.get("recentChanges") or "")[:500],
        )
    except Exception as e:
        log.warning(f"Google Play 앱 정보 실패 [{app_id}]: {e}")
        return None, None, None, None


def _fetch_ios_info(app_id: str) -> tuple:
    try:
        url  = f"https://itunes.apple.com/lookup?id={app_id}&country=kr"
        resp = _get(url)
        data = resp.json()
        if data.get("resultCount", 0) == 0:
            return None, None, None, None
        r = data["results"][0]
        return (
            round(r.get("averageUserRating") or 0, 2),
            r.get("userRatingCount") or 0,
            r.get("version") or "",
            (r.get("releaseNotes") or "")[:500],
        )
    except Exception as e:
        log.warning(f"iOS 앱 정보 실패 [{app_id}]: {e}")
        return None, None, None, None


# ──────────────────────────────────────────────
# 네이버 블로그 / 뉴스 검색 크롤러
# ──────────────────────────────────────────────

def crawl_naver_search(source: dict) -> list[dict]:
    """네이버 블로그·뉴스 공식 검색 API 수집."""
    search_type = source.get("search_type", "blog")
    service_id  = source.get("service_id", "")
    keywords    = source.get("keywords", [])
    days_back   = source.get("days_back", 14)
    cutoff      = datetime.now() - timedelta(days=days_back)

    client_id     = os.environ.get("NAVER_CLIENT_ID", "").lstrip("﻿").strip()
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "").lstrip("﻿").strip()
    if not client_id or not client_secret:
        log.warning("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 미설정 — naver_search 건너뜀")
        return []

    endpoint = "news" if search_type == "news" else "blog"
    src_type  = search_type  # "news" | "blog"
    results: list[dict] = []
    seen: set[str] = set()

    for kw in keywords:
        try:
            api_url = (
                f"https://openapi.naver.com/v1/search/{endpoint}.json"
                f"?query={quote(kw)}&sort=date&display=20"
            )
            resp = requests.get(
                api_url,
                headers={
                    "X-Naver-Client-Id":     client_id,
                    "X-Naver-Client-Secret": client_secret,
                    "User-Agent":            "parking-cx-monitor/1.0",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("items", []):
                # HTML 태그 제거
                title = re.sub(r"<[^>]+>", "", item.get("title", "")).strip()
                desc  = re.sub(r"<[^>]+>", "", item.get("description", "")).strip()
                href  = item.get("link") or item.get("originallink", "")

                if not title or not href or href in seen:
                    continue
                seen.add(href)

                # 날짜 파싱 (pubDate: "Mon, 19 May 2026 10:30:00 +0900")
                pub_str = datetime.now().strftime("%Y-%m-%d")
                raw_date = item.get("pubDate", "")
                if raw_date:
                    try:
                        from email.utils import parsedate_to_datetime
                        dt = parsedate_to_datetime(raw_date)
                        pub_str = dt.strftime("%Y-%m-%d")
                        if dt.replace(tzinfo=None) < cutoff:
                            continue
                    except Exception:
                        pass

                if not _brand_validate(service_id, title, desc):
                    continue

                # 주차 강화 게이트 — 제목 또는 본문 2회+ 필수
                if not _is_strong_parking_match(title, desc):
                    continue

                ct = classify_change_type(title, desc)
                if ct == "기타":
                    continue

                # 원문 기사 본문 가져오기
                # 네이버 뉴스 뷰어(n.news.naver.com)가 가장 잘 파싱되므로 우선 시도
                naver_link    = href if "n.news.naver.com" in href else ""
                original_link = item.get("originallink") or ""
                full_body = ""
                for try_url in filter(None, [naver_link, original_link, href]):
                    full_body = _fetch_article_text(try_url, max_chars=3000)
                    if len(full_body) > max(len(desc), 100):
                        break
                # full_body가 브랜드 키워드를 포함하지 않으면 보일러플레이트 가능성 높음
                brand_kws = _BRAND_REQUIRED.get(service_id, [])
                body_has_brand = any(b in full_body.lower() for b in brand_kws) if brand_kws else True
                summary = full_body if (len(full_body) > len(desc) and body_has_brand) else desc

                results.append({
                    "service_id":   service_id,
                    "published_at": pub_str,
                    "source_type":  src_type,
                    "change_type":  ct,
                    "title":        title,
                    "summary":      summary or None,
                    "url":          href,
                    "sentiment":    classify_sentiment(title, summary),
                })

        except Exception as e:
            log.warning(f"Naver search API 실패 [{service_id}|{kw}]: {e}")
            continue

    return results


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────

def _clean_article_lines(text: str) -> str:
    """기사 본문에서 보일러플레이트 라인 제거.
    날씨 데이터, GNB 카테고리, 단어 나열형 탐색 메뉴 등을 걸러냄.
    """
    cleaned = []
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) < 15:
            continue
        # 날씨 온도 데이터 (예: "흐림 동두천 23.1℃")
        if re.search(r'\d+\.?\d*\s*[℃°]', line):
            continue
        # 네이버 GNB 카테고리 패턴 (예: "Y-정치 정부 국회 지자체")
        if re.match(r'^[A-Z]-', line):
            continue
        # 짧은 단어 나열형 네비게이션 (한글 비율이 극단적으로 낮은 줄)
        korean_chars = len(re.findall(r'[가-힣]', line))
        if len(line) > 10 and korean_chars / len(line) < 0.15:
            continue
        cleaned.append(line)
    return '\n\n'.join(cleaned)


def _fetch_article_text(url: str, max_chars: int = 1500) -> str:
    """기사 URL에서 본문 텍스트 추출. 실패 시 빈 문자열 반환."""
    try:
        headers = dict(HEADERS)
        headers["Accept-Language"] = "ko-KR,ko;q=0.9,en;q=0.8"
        headers["Referer"] = "https://search.naver.com/"
        try:
            resp = requests.get(url, headers=headers, timeout=10, verify=True, allow_redirects=True)
        except requests.exceptions.SSLError:
            resp = requests.get(url, headers=headers, timeout=10, verify=False, allow_redirects=True)
        if resp.status_code != 200:
            return ""
        ct = resp.headers.get("content-type", "").lower()
        if "html" not in ct:
            return ""
        # 한국 뉴스 사이트는 사실상 전부 UTF-8
        # apparent_encoding(chardet)은 한글 콘텐츠를 오감지해 모지바케 유발 가능
        if "euc-kr" in ct or "ks_c_5601" in ct or "euc_kr" in ct:
            resp.encoding = "euc-kr"
        else:
            resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer",
                         "aside", "iframe", "noscript", "form", "figure"]):
            tag.decompose()
        # 네이버 뉴스 뷰어 / 언론사별 주요 selector 우선순위
        SELECTORS = [
            "#dic_area",                          # 네이버 뉴스 본문
            "#newsEndContents",                   # 네이버 뉴스 (구형)
            ".newsct_article",                    # 네이버 뉴스 (구형)
            "#articleBodyContents",               # 네이버 뉴스 (구형)
            "article",                            # 표준 시맨틱
            ".article-content", ".article_body",  # 언론사 공통
            ".news_body", ".content-body",
            ".article__body", ".articleBody",
            ".article_view", ".article-view",
            "#article-view-content-div",          # 뉴시스·이데일리 등
            ".view_con", ".view-content",         # 블로터·IT조선 등
            ".read_body", ".read-body",
            ".cont_article", ".news_article",
            "[class*='article'][class*='body']",
            "[class*='article'][class*='content']",
            # "main" / "body" 제거: 날씨 위젯·GNB 네비게이션 등 페이지 보일러플레이트 유입 방지
        ]
        body_el = None
        for sel in SELECTORS:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator=" ", strip=True)
                if len(text) > 100:   # 너무 짧으면 다음 selector 시도
                    body_el = el
                    break
        if body_el is None:
            return ""
        # 문단 단위로 추출 — p/li/h2~h4 태그를 줄바꿈으로 분리
        paras = []
        for el in body_el.find_all(['p', 'li', 'h2', 'h3', 'h4', 'blockquote']):
            t = el.get_text(separator=' ', strip=True)
            t = ' '.join(t.split())
            if len(t) > 10:
                paras.append(t)
        if paras:
            text = '\n\n'.join(paras)
        else:
            # 태그 구분이 없는 경우 fallback: 문장 단위 줄바꿈
            raw = body_el.get_text(separator=' ', strip=True)
            raw = ' '.join(raw.split())
            import re as _re
            text = _re.sub(r'(?<=[.!?])\s+', '\n\n', raw)
        text = _clean_article_lines(text)
        if len(text) < 50:
            return ""
        return text[:max_chars]
    except Exception:
        return ""


def _strip_html(text: str) -> str:
    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)


def _parse_date_str(raw: str) -> str | None:
    import re
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", raw)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        return f"{y}-{mo}-{d}"
    return None


def _dedup_by_title(items: list[dict], threshold: float = 0.2) -> list[dict]:
    """유사 제목 중복 제거 (2단계).
    1단계: 같은 서비스+날짜 내 자카드 유사도 >= 0.2
    2단계: 크로스 서비스 자카드 유사도 >= 0.5 (사용자 명세 "50% 단어 일치")
    중복 그룹 내에서 네이버 뉴스 뷰어(n.news.naver.com) URL을 우선 보존.
    """
    from collections import defaultdict

    _JOSA = re.compile(r'(에서|으로|이라|이며|이고|하고|부터|까지|에게|보다|처럼|만큼|과|와|의|에|도|만|로|서|고|며|나)$')

    def tokenize(t: str) -> set:
        tokens = set()
        for tok in re.findall(r'[가-힣a-z0-9]{2,}', (t or '').lower()):
            stripped = _JOSA.sub('', tok)
            tok = stripped if len(stripped) >= 2 else tok
            if len(tok) >= 7:
                tok = tok[:5]
            tokens.add(tok)
        return tokens

    def jaccard(s1: set, s2: set) -> float:
        if not s1 or not s2:
            return 0.0
        return len(s1 & s2) / len(s1 | s2)

    def _priority(item: dict) -> int:
        """낮을수록 우선. 네이버 뷰어 > 본문 있는 기사 > 나머지."""
        url = item.get('url', '')
        summary_len = len(item.get('summary') or '')
        if 'n.news.naver.com' in url:
            return 0
        if summary_len > 200:
            return 1
        return 2

    # 중복 제거 전 그룹 내 우선순위 정렬 (네이버 뷰어 URL 먼저)
    sorted_items = sorted(items, key=_priority)

    # 1단계: 같은 서비스+날짜 내 dedup (threshold 0.6)
    groups: dict[str, list] = defaultdict(list)
    for item in sorted_items:
        key = f"{item.get('service_id', '')}|{item.get('published_at', '')}"
        groups[key].append(item)

    stage1 = []
    for group_items in groups.values():
        kept: list[tuple[set, dict]] = []
        for item in group_items:
            tokens = tokenize(item.get('title', ''))
            dup_idx = next((i for i, (kt, _) in enumerate(kept)
                            if jaccard(tokens, kt) >= threshold), None)
            if dup_idx is not None:
                # 이미 보존된 것보다 현재 아이템이 더 좋으면 교체
                if _priority(item) < _priority(kept[dup_idx][1]):
                    kept[dup_idx] = (tokens, item)
            else:
                kept.append((tokens, item))
        stage1.extend(it for _, it in kept)

    # 2단계: 크로스 서비스 dedup (날짜 기준, threshold 0.5 - 사용자 명세 "50% 단어 일치")
    date_groups: dict[str, list] = defaultdict(list)
    for item in stage1:
        date_groups[item.get('published_at', '')].append(item)

    result = []
    for group_items in date_groups.values():
        kept: list[tuple[set, dict]] = []
        for item in group_items:
            # 제목 + 요약 토큰으로 더 넓게 비교 (제목만으로는 변형 못 잡음)
            text = (item.get('title', '') or '') + ' ' + (item.get('summary', '') or '')
            tokens = tokenize(text)
            dup_idx = next((i for i, (kt, _) in enumerate(kept)
                            if jaccard(tokens, kt) >= 0.5), None)
            if dup_idx is not None:
                if _priority(item) < _priority(kept[dup_idx][1]):
                    kept[dup_idx] = (tokens, item)
            else:
                kept.append((tokens, item))
        result.extend(it for _, it in kept)

    return result


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def crawl_naver_cafe(source: dict) -> list[dict]:
    """네이버 카페 검색 크롤링 — 커뮤니티 VOC 수집.
    NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 있으면 공식 API 사용.
    없으면 HTML 스크래핑 fallback.
    """
    service_id = source.get('service_id', '')
    keywords   = source.get('keywords', [])
    days_back  = source.get('days_back', 14)
    cutoff     = datetime.now() - timedelta(days=days_back)
    results: list[dict] = []
    seen: set[str] = set()

    client_id     = os.environ.get('NAVER_CLIENT_ID', '').lstrip('﻿').strip()
    client_secret = os.environ.get('NAVER_CLIENT_SECRET', '').lstrip('﻿').strip()
    use_api       = bool(client_id and client_secret)

    for kw in keywords:
        try:
            if use_api:
                # ── 공식 Naver 검색 API (카페) ────────────────────
                api_url = 'https://openapi.naver.com/v1/search/cafearticle.json'
                resp = requests.get(
                    api_url,
                    params={'query': kw, 'display': 30, 'sort': 'date'},
                    headers={
                        'X-Naver-Client-Id': client_id,
                        'X-Naver-Client-Secret': client_secret,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                items_raw = resp.json().get('items', [])
                for it in items_raw:
                    title = BeautifulSoup(it.get('title', ''), 'html.parser').get_text()
                    href  = it.get('link', '')
                    desc  = BeautifulSoup(it.get('description', ''), 'html.parser').get_text()[:500]
                    cafe  = it.get('cafename', '')
                    pub_raw = it.get('postdate', '')
                    try:
                        pub_str = datetime.strptime(pub_raw, '%Y%m%d').strftime('%Y-%m-%d')
                        if datetime.strptime(pub_str, '%Y-%m-%d') < cutoff:
                            continue
                    except Exception:
                        pub_str = datetime.now().strftime('%Y-%m-%d')

                    if not title or href in seen:
                        continue
                    seen.add(href)
                    if not _brand_validate(service_id, title, desc):
                        continue
                    _ct = classify_change_type(title, desc)
                    if _ct == '기타':
                        continue
                    disp = f"[카페:{cafe}] {title}" if cafe else title
                    results.append({
                        'service_id':   service_id,
                        'published_at': pub_str,
                        'source_type':  'cafe',
                        'change_type':  _ct,
                        'title':        disp,
                        'summary':      _parking_summary(desc) or None,
                        'url':          href,
                        'sentiment':    classify_sentiment(title, desc),
                    })

            else:
                # ── HTML 스크래핑 fallback ─────────────────────────
                url = (
                    f"https://search.naver.com/search.naver?where=article"
                    f"&query={quote(kw)}&sm=tab_opt&sort=1"
                )
                resp = _get(url)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, 'html.parser')

                els = soup.select('ul.lst_total > li, .total_area, .cafe_area li')
                for el in els[:20]:
                    a = el.select_one('a.title_link, a.api_txt_lines, a.tit')
                    if not a:
                        continue
                    title = a.get_text(strip=True)
                    href  = a.get('href', '')
                    if not title or not href or href in seen:
                        continue
                    seen.add(href)

                    dsc_el = el.select_one('.dsc_txt, .dsc_txt_inner, .api_txt_lines')
                    desc   = dsc_el.get_text(strip=True)[:500] if dsc_el else ''
                    cafe_el = el.select_one('.cafe_name, .source_box .source')
                    cafe   = cafe_el.get_text(strip=True) if cafe_el else ''

                    date_el = el.select_one('.sub_time, .date, .info_date')
                    pub_str = datetime.now().strftime('%Y-%m-%d')
                    if date_el:
                        parsed = _parse_date_str(date_el.get_text(strip=True))
                        if parsed:
                            pub_str = parsed
                            try:
                                if datetime.strptime(pub_str, '%Y-%m-%d') < cutoff:
                                    continue
                            except ValueError:
                                pass

                    if not _brand_validate(service_id, title, desc):
                        continue
                    _ct = classify_change_type(title, desc)
                    if _ct == '기타':
                        continue
                    disp = f"[카페:{cafe}] {title}" if cafe else title
                    results.append({
                        'service_id':   service_id,
                        'published_at': pub_str,
                        'source_type':  'cafe',
                        'change_type':  _ct,
                        'title':        disp,
                        'summary':      _parking_summary(desc) or None,
                        'url':          href,
                        'sentiment':    classify_sentiment(title, desc),
                    })

        except Exception as e:
            log.warning(f"naver_cafe 실패 [{service_id}|{kw}]: {e}")
            continue

    return results


CRAWLER_MAP = {
    "appstore":     crawl_appstore,
    "ios_appstore": crawl_ios_appstore,
    "app_info":     crawl_app_info,
    "naver_blog":   crawl_naver_search,
    "naver_news":   crawl_naver_search,
    "naver_cafe":   crawl_naver_cafe,
}


_REVIEW_TYPES = {"appstore", "ios_appstore"}


def _export_data_json(services: list[dict]) -> None:
    """SQLite + Google Sheets 전체 데이터를 docs/data.json으로 내보냅니다."""
    svc_map = {s["id"]: s for s in services}

    # ── 1. SQLite에서 전건 읽기
    with db.get_conn() as conn:
        rows = conn.execute("""
            SELECT c.service_id, c.published_at, c.source_type, c.change_type,
                   c.title, c.summary, c.url, c.sentiment, c.collected_at,
                   s.name_ko, s.operator
            FROM changes c
            LEFT JOIN services s ON c.service_id = s.id
            WHERE c.url IS NOT NULL AND c.url != ''
            ORDER BY c.published_at DESC, c.collected_at DESC
        """).fetchall()

    seen_url: set[str] = set()
    items: list[dict] = []
    for row in rows:
        d   = dict(row)
        url = (d.get("url") or "").strip()
        if not url or url in seen_url:
            continue
        pub = str(d.get("published_at") or "")[:10]
        # 리뷰인데 날짜 불명이면 제외
        if d.get("source_type") in _REVIEW_TYPES and not pub:
            continue
        seen_url.add(url)
        col = str(d.get("collected_at") or "")[:16]
        items.append({
            "published_at": pub,
            "service_id":   d.get("service_id", ""),
            "name_ko":      d.get("name_ko") or svc_map.get(d.get("service_id", ""), {}).get("name_ko", ""),
            "source_type":  d.get("source_type", ""),
            "change_type":  d.get("change_type", ""),
            "title":        d.get("title", ""),
            "summary":      d.get("summary", ""),
            "url":          url,
            "sentiment":    d.get("sentiment") or "neutral",
            "collected_at": col,
            "full_text":    "",
        })

    # ── 2. Google Sheets에서 전체 보충 (SQLite에 없는 과거 데이터 포함)
    try:
        import sheets as sh_mod
        sheet_rows = sh_mod.read_all_cached()
        added_from_sheet = 0
        for row in sheet_rows:
            src = row.get("source_type", "")
            pub = str(row.get("published_at") or "")[:10]
            # 리뷰인데 날짜 불명이면 제외
            if src in _REVIEW_TYPES and not pub:
                continue
            url = (row.get("url") or "").strip()
            if url and url in seen_url:
                continue  # SQLite에서 이미 포함됨
            if url:
                seen_url.add(url)
            col = str(row.get("collected_at") or "")[:16]
            sid = row.get("service_id", "")
            items.append({
                "published_at": pub,
                "service_id":   sid,
                "name_ko":      row.get("name_ko") or svc_map.get(sid, {}).get("name_ko", ""),
                "source_type":  src,
                "change_type":  row.get("change_type", "VOC"),
                "title":        row.get("title", ""),
                "summary":      row.get("summary", ""),
                "url":          url,
                "sentiment":    row.get("sentiment") or "neutral",
                "collected_at": col,
                "full_text":    "",
            })
            added_from_sheet += 1
        if added_from_sheet:
            print(f"[INFO] Google Sheets {added_from_sheet}건 추가 병합")
    except Exception as e:
        print(f"[WARN] Sheets 리뷰 병합 실패 (무시): {e}")

    # 최신순 정렬
    items.sort(key=lambda x: (x.get("published_at") or "", x.get("collected_at") or ""), reverse=True)

    out = {
        "ok": True, "auth": True,
        "items": items, "total": len(items),
        "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    docs_path = ROOT_DIR / "docs" / "data.json"
    with open(docs_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    print(f"[INFO] docs/data.json: {len(items)}건 내보내기 완료")


def run() -> dict:
    db.init_db()
    db.import_services()

    # 최초 실행 여부 판단
    run_status   = db.get_status()
    total_items  = db.get_total_count()
    is_first_run = (run_status.get('last_run') is None) or (total_items < 30)

    # FORCE_FULL_CRAWL=1 이면 강제로 전체 수집 (1년치)
    if os.environ.get('FORCE_FULL_CRAWL') == '1':
        is_first_run = True
        print("[INFO] FORCE_FULL_CRAWL — 전체 1년치 수집 모드")
    # Sheets에 이미 데이터가 충분하면 최초 실행이 아님
    # (GitHub Actions처럼 SQLite가 항상 초기화되는 환경 대응)
    elif is_first_run:
        try:
            import sheets as _sh
            sheet_count = len(_sh.read_all_cached())
            if sheet_count >= 50:
                is_first_run = False
                print(f"[INFO] Sheets {sheet_count}건 확인 — 증분 수집 모드")
        except Exception:
            pass

    sources  = load_sources()
    services = load_services()

    if is_first_run:
        print("[INFO] 최초 실행 — 최근 1년 데이터 수집 모드")
        extended = []
        for src in sources:
            src = dict(src)
            if 'days_back'    in src: src['days_back']    = 365
            if 'window_days'  in src: src['window_days']  = 365
            if src.get('type') == 'appstore':     src['review_count'] = 2000
            if src.get('type') == 'ios_appstore': src['max_pages']    = 10
            if 'url_template' in src:
                src['url_template'] = src['url_template'].replace('when:7d', 'when:1y')
            extended.append(src)
        sources = extended
    else:
        # 증분 모드 — 전날~당일 2일치만 수집 (daily cron 기준)
        print("[INFO] 증분 수집 모드 — 최근 2일치")
        extended = []
        for src in sources:
            src = dict(src)
            if 'days_back'   in src: src['days_back']   = 2
            if 'window_days' in src: src['window_days'] = 2
            if 'url_template' in src:
                src['url_template'] = src['url_template'].replace('when:7d', 'when:2d')
            extended.append(src)
        sources = extended

    added     = 0
    errors    = 0
    new_items = []  # Sheets 동기화용 신규 항목 수집

    print(f"[INFO] 수집 시작 — 소스 {len(sources)}개")

    for src in sources:
        src_id   = src.get("id", "?")
        src_type = src.get("type", "")

        try:
            if src_type == "rss":
                items = crawl_rss(src, services)
            elif src_type in CRAWLER_MAP:
                items = CRAWLER_MAP[src_type](src)
            else:
                log.warning(f"알 수 없는 소스 타입: {src_type}")
                continue

            _DB_FIELDS = {
                'service_id','published_at','source_type','change_type',
                'title','summary','url','sentiment','dedup_key'
            }
            _REVIEW_TYPES = {"appstore", "ios_appstore"}
            for item in items:
                if src_type not in _REVIEW_TYPES:
                    _chk = (item.get('title', '') + ' ' + (item.get('summary') or '')).lower()
                    if any(kw in _chk for kw in _NEWS_EXCLUDE_KW):
                        continue
                db_item = {k: v for k, v in item.items() if k in _DB_FIELDS}
                if db.insert_change(**db_item):
                    added += 1
                    new_items.append({
                        **item,
                        "collected_at": (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S"),
                    })

            print(f"[INFO] {src_id}: {len(items)}건 수집")

        except Exception as e:
            log.error(f"[오류] {src_id}: {e}")
            errors += 1

    removed = db.purge_old(days=365)
    if removed:
        print(f"[INFO] 오래된 데이터 {removed}건 삭제")

    status = "success" if errors == 0 else ("partial" if added > 0 else "failed")
    db.log_run(status, added, removed, notes=f"errors={errors}")

    # ── Google Sheets 동기화 ───────────────────────────────
    if new_items:
        try:
            import sheets as sh_mod
            svc_map = {s["id"]: s for s in services}
            # 리뷰(appstore/ios_appstore)는 제목 기반 dedup 제외 — 익명 리뷰 등 유사 제목이 많아 오탈락 방지
            _review_types = {'appstore', 'ios_appstore'}
            reviews_only  = [i for i in new_items if i.get('source_type') in _review_types]
            non_reviews   = [i for i in new_items if i.get('source_type') not in _review_types]
            deduped = _dedup_by_title(non_reviews) + reviews_only
            synced = sh_mod.append_items(deduped, service_map=svc_map)
            sh_mod.invalidate_cache()
            print(f"[INFO] Google Sheets {synced}건 동기화 완료")
        except Exception as e:
            print(f"[WARN] Sheets 동기화 실패 (수집 결과는 정상 저장됨): {e}")

    # ── docs/data.json 생성 (GitHub Pages 직접 서빙용, GAS 불필요) ──
    try:
        _export_data_json(services)
    except Exception as e:
        print(f"[WARN] docs/data.json 생성 실패: {e}")

    # ── app_info.json 스냅샷 갱신 (Railway 클라우드 폴백용) ──
    try:
        import json as _json
        from pathlib import Path as _Path
        app_stats = db.get_app_stats()
        if app_stats:
            snap_path = _Path(__file__).parent.parent / "data" / "app_info.json"
            with open(snap_path, "w", encoding="utf-8") as _f:
                _json.dump(app_stats, _f, ensure_ascii=False, indent=2, default=str)
            print(f"[INFO] app_info.json 갱신 완료 ({len(app_stats)}건)")
    except Exception as e:
        print(f"[WARN] app_info.json 갱신 실패: {e}")

    print(f"[DONE] 총 {added}건 신규 수집 완료 (오류 {errors}건)")
    return {"added": added, "removed": removed, "errors": errors, "status": status}


if __name__ == "__main__":
    result = run()
    sys.exit(0 if result["status"] != "failed" else 1)
