#!/usr/bin/env python3
"""메인 크롤러 — 앱 실행 시 또는 수동 새로고침 시 호출."""

import sys
import os
import json
import logging
import hashlib
import difflib
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
                    # RSS 요약이 제목 수준으로 짧으면 기사 본문 직접 추출
                    if len(summary) < 200 and link:
                        fetched = _fetch_article_text(link)
                        if len(fetched) > len(summary):
                            summary = fetched

                    # 주차·브랜드 관련성 이중 검증
                    if not _is_relevant(title, summary, svc):
                        continue
                    if not _brand_validate(sid, title, summary):
                        continue

                    dedup_key = f"{sid}|{pub_dt.strftime('%Y-%m-%d')}|{title}"

                    items.append({
                        "service_id":   sid,
                        "published_at": pub_dt.strftime("%Y-%m-%d"),
                        "source_type":  "news",
                        "change_type":  classify_change_type(title, summary),
                        "title":        title,
                        "summary":      summary,
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
    'urbanport':      ['어반포트', 'urbanport'],
    'koreanef':       ['한국전자금융'],
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
# HTML 리스트 크롤러 (보도자료 페이지)
# ──────────────────────────────────────────────

def crawl_html_list(source: dict) -> list[dict]:
    url            = source.get("url", "")
    sid            = source.get("service_id", "")
    item_sel       = source.get("item_selector", "article, li")
    title_sel      = source.get("title_selector", "h2 a, h3 a, a")
    date_sel       = source.get("date_selector")
    link_sel       = source.get("link_selector", "h2 a, h3 a, a")
    base_url       = source.get("base_url", "").rstrip("/")
    keyword_filter = [k.lower() for k in source.get("keyword_filter", [])]

    resp = _get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    items: list[dict] = []
    for el in soup.select(item_sel)[:30]:
        title_el = el.select_one(title_sel)
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue

        # keyword_filter가 있으면 제목에 관련 키워드가 있을 때만 수집
        if keyword_filter and not any(kw in title.lower() for kw in keyword_filter):
            continue

        link_el = el.select_one(link_sel) if link_sel else title_el
        href    = (link_el.get("href") or "") if link_el else ""
        if href and not href.startswith("http"):
            href = base_url + "/" + href.lstrip("/")

        pub_str = datetime.now().strftime("%Y-%m-%d")
        if date_sel:
            date_el = el.select_one(date_sel)
            if date_el:
                pub_str = _parse_date_str(date_el.get_text(strip=True)) or pub_str

        items.append({
            "service_id":   sid,
            "published_at": pub_str,
            "source_type":  "blog",
            "change_type":  classify_change_type(title),
            "title":        title,
            "summary":      None,
            "url":          href or url,
            "sentiment":    classify_sentiment(title),
        })

    return items


# ──────────────────────────────────────────────
# HTML diff 크롤러 — 실제 변경 내용 추출
# ──────────────────────────────────────────────

def crawl_html_diff(source: dict) -> list[dict]:
    """이전 스냅샷과 비교 후 실제 어떤 텍스트가 바뀌었는지 요약 포함."""
    url      = source.get("url", "")
    sid      = source.get("service_id", "")
    selector = source.get("selector")

    resp = _get(url)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    if selector:
        section = soup.select_one(selector)
        if section:
            new_text = section.get_text(separator="\n", strip=True)
        else:
            body = soup.find("body")
            new_text = body.get_text(separator="\n", strip=True) if body else ""
    else:
        body = soup.find("body")
        new_text = body.get_text(separator="\n", strip=True) if body else resp.text

    # 의미없는 공백줄 제거 후 10000자 제한
    new_text = "\n".join(l for l in new_text.splitlines() if l.strip())[:10000]

    new_hash   = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
    old_hash, old_text = db.get_snapshot(sid, url)
    db.save_snapshot(sid, url, new_hash, new_text)

    if old_hash is None:
        return []  # 최초 실행: 기준 스냅샷 저장만
    if old_hash == new_hash:
        return []  # 변경 없음

    diff_summary = _build_diff_summary(old_text or "", new_text)
    change_type  = classify_change_type(diff_summary)
    sentiment    = classify_sentiment(diff_summary)

    return [{
        "service_id":   sid,
        "published_at": datetime.now().strftime("%Y-%m-%d"),
        "source_type":  "homepage",
        "change_type":  change_type,
        "title":        f"홈페이지 업데이트 감지 — {url}",
        "summary":      diff_summary,
        "url":          url,
        "sentiment":    sentiment,
    }]


def _build_diff_summary(old_text: str, new_text: str) -> str:
    """두 텍스트 diff에서 의미있는 변경 줄만 추출해 요약."""
    old_lines = [l.strip() for l in old_text.splitlines() if len(l.strip()) > 8]
    new_lines = [l.strip() for l in new_text.splitlines() if len(l.strip()) > 8]

    diff = list(difflib.ndiff(old_lines, new_lines))

    removed = [l[2:] for l in diff if l.startswith("- ")][:15]
    added   = [l[2:] for l in diff if l.startswith("+ ")][:15]

    if not removed and not added:
        return "홈페이지 구조/레이아웃이 변경되었습니다."

    parts = []
    if removed:
        parts.append("▼ 사라진 내용:\n" + "\n".join(f"  · {r}" for r in removed))
    if added:
        parts.append("▲ 새로 추가된 내용:\n" + "\n".join(f"  · {a}" for a in added))

    return "\n".join(parts)[:2000]


# ──────────────────────────────────────────────
# Google Play 리뷰 크롤러
# ──────────────────────────────────────────────

def crawl_appstore(source: dict) -> list[dict]:
    if source.get("platform") != "google_play":
        return []

    app_id      = source.get("app_id", "")
    sid         = source.get("service_id", "")
    window_days = source.get("window_days", 7)
    flag_below  = source.get("flag_below_rating", 3)
    cutoff      = datetime.now() - timedelta(days=window_days)

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

    items: list[dict] = []
    for r in result:
        score  = r.get("score", 5)
        pub_dt = r.get("at", datetime.now())
        if not isinstance(pub_dt, datetime):
            pub_dt = datetime.now()
        if pub_dt < cutoff:
            break
        if score > flag_below:
            continue

        content = (r.get("content") or "")[:1000]
        items.append({
            "service_id":   sid,
            "published_at": pub_dt.strftime("%Y-%m-%d"),
            "source_type":  "appstore",
            "change_type":  "VOC",
            "title":        f"[Android ★{score}] {r.get('userName', '익명')}",
            "summary":      content,
            "url":          f"https://play.google.com/store/apps/details?id={app_id}",
            "sentiment":    "negative" if score <= 2 else "neutral",
        })

    return items


# ──────────────────────────────────────────────
# iOS App Store 리뷰 크롤러 (iTunes RSS API)
# ──────────────────────────────────────────────

def crawl_ios_appstore(source: dict) -> list[dict]:
    """Apple App Store 리뷰 수집 (iTunes RSS — 인증 불필요)."""
    app_id     = source.get("app_id", "")
    sid        = source.get("service_id", "")
    flag_below = source.get("flag_below_rating", 3)

    if not app_id:
        return []

    max_pages = source.get("max_pages", 1)
    entries: list = []
    for page in range(1, max_pages + 1):
        url = f"https://itunes.apple.com/kr/rss/customerreviews/page={page}/id={app_id}/sortBy=mostRecent/json"
        try:
            resp = _get(url)
            if resp.status_code != 200:
                break
            data = resp.json()
            page_entries = data.get("feed", {}).get("entry", [])
            if not page_entries:
                break
            entries.extend(page_entries)
        except Exception as e:
            log.warning(f"iOS 앱스토어 요청 실패 [{app_id}] page={page}: {e}")
            break
    if not entries:
        return []

    # 첫 번째 항목은 앱 정보, 나머지가 리뷰
    items: list[dict] = []
    for entry in entries[1:]:
        try:
            rating_raw = entry.get("im:rating", {})
            if isinstance(rating_raw, dict):
                score = int(rating_raw.get("label", "5"))
            else:
                score = 5

            if score > flag_below:
                continue

            title   = entry.get("title", {}).get("label", "제목없음")
            content = entry.get("content", {}).get("label", "")[:1000]
            author  = entry.get("author", {}).get("name", {}).get("label", "익명")

            # iOS 리뷰는 날짜 정보가 'updated' 필드에 있음
            updated = entry.get("updated", {}).get("label", "")
            pub_str = updated[:10] if updated else datetime.now().strftime("%Y-%m-%d")

            items.append({
                "service_id":   sid,
                "published_at": pub_str,
                "source_type":  "appstore",
                "change_type":  "VOC",
                "title":        f"[iOS ★{score}] {author}: {title[:40]}",
                "summary":      content,
                "url":          f"https://apps.apple.com/kr/app/id{app_id}",
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
# YouTube RSS 크롤러
# ──────────────────────────────────────────────

def crawl_youtube_rss(source: dict) -> list[dict]:
    """YouTube 채널 최신 영상 수집 (공개 RSS — 인증 불필요)."""
    channel_id     = source.get("channel_id", "")
    sid            = source.get("service_id", "")
    days_back      = source.get("days_back", 7)
    keyword_filter = [k.lower() for k in source.get("keyword_filter", [])]

    if not channel_id:
        return []

    url    = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    cutoff = datetime.now() - timedelta(days=days_back)

    try:
        feed = feedparser.parse(url)
    except Exception as e:
        log.warning(f"YouTube RSS 실패 [{channel_id}]: {e}")
        return []

    items: list[dict] = []
    for entry in feed.entries[:20]:
        try:
            if getattr(entry, "published_parsed", None):
                pub_dt = datetime(*entry.published_parsed[:6])
            else:
                pub_dt = datetime.now()

            if pub_dt < cutoff:
                continue

            title   = entry.get("title", "")
            summary = (entry.get("summary") or "")[:300]
            link    = entry.get("link", "")

            # keyword_filter가 있으면 제목/요약에 관련 키워드가 있을 때만 수집
            if keyword_filter:
                combined = (title + " " + summary).lower()
                if not any(kw in combined for kw in keyword_filter):
                    continue

            items.append({
                "service_id":   sid,
                "published_at": pub_dt.strftime("%Y-%m-%d"),
                "source_type":  "youtube",
                "change_type":  classify_change_type(title, summary),
                "title":        f"[YouTube] {title}",
                "summary":      summary,
                "url":          link,
                "sentiment":    classify_sentiment(title, summary),
            })
        except Exception:
            continue

    return items


# ──────────────────────────────────────────────
# 네이버 블로그 / 뉴스 검색 크롤러
# ──────────────────────────────────────────────

def crawl_naver_search(source: dict) -> list[dict]:
    """네이버 블로그 또는 뉴스 검색 결과 HTML 스크래핑 (API 키 불필요)."""
    search_type = source.get("search_type", "blog")
    service_id  = source.get("service_id", "")
    keywords    = source.get("keywords", [])
    days_back   = source.get("days_back", 14)
    cutoff      = datetime.now() - timedelta(days=days_back)
    results: list[dict] = []
    seen: set[str] = set()

    for kw in keywords:
        try:
            if search_type == "news":
                url = (
                    f"https://search.naver.com/search.naver?where=news"
                    f"&query={quote(kw)}&sm=tab_opt&sort=1&nso=so:dd,p:1y"
                )
                src_type = "news"
            else:
                url = (
                    f"https://search.naver.com/search.naver?where=blog"
                    f"&query={quote(kw)}&sm=tab_opt&sort=1&nso=so:dd,p:1y"
                )
                src_type = "blog"

            resp = _get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            if search_type == "news":
                els = soup.select(".list_news .news_area, .type01 li")
                for el in els[:25]:
                    a = el.select_one("a.news_tit, .news_tit a, a")
                    if not a:
                        continue
                    title = a.get_text(strip=True)
                    href  = a.get("href", "")
                    if not title or not href or href in seen:
                        continue
                    seen.add(href)
                    dsc  = el.select_one(".dsc_txt, .dsc_txt_wrap")
                    desc = dsc.get_text(strip=True)[:700] if dsc else ""
                    # 스니펫이 짧으면 기사 본문 직접 추출
                    if len(desc) < 200 and href:
                        fetched = _fetch_article_text(href)
                        if len(fetched) > len(desc):
                            desc = fetched
                    date_el = el.select_one(".info_group .info, .sub_txt_item")
                    pub_str = datetime.now().strftime("%Y-%m-%d")
                    if date_el:
                        parsed = _parse_date_str(date_el.get_text(strip=True))
                        if parsed:
                            pub_str = parsed
                            try:
                                if datetime.strptime(pub_str, "%Y-%m-%d") < cutoff:
                                    continue
                            except ValueError:
                                pass
                    if not _brand_validate(service_id, title, desc):
                        continue
                    results.append({
                        "service_id":   service_id,
                        "published_at": pub_str,
                        "source_type":  src_type,
                        "change_type":  classify_change_type(title, desc),
                        "title":        title,
                        "summary":      _parking_summary(desc) or None,
                        "url":          href,
                        "sentiment":    classify_sentiment(title, desc),
                    })
            else:
                els = soup.select("ul.lst_total > li, .total_wrap li")
                for el in els[:25]:
                    a = el.select_one("a.title_link, a.api_txt_lines, a.tit")
                    if not a:
                        continue
                    title = a.get_text(strip=True)
                    href  = a.get("href", "")
                    if not title or not href or href in seen:
                        continue
                    seen.add(href)
                    dsc  = el.select_one(".dsc_txt_inner, .dsc_txt, .api_txt_lines")
                    desc = dsc.get_text(strip=True)[:700] if dsc else ""
                    # 스니펫이 짧으면 블로그 본문 직접 추출
                    if len(desc) < 200 and href:
                        fetched = _fetch_article_text(href)
                        if len(fetched) > len(desc):
                            desc = fetched
                    date_el = el.select_one(".sub_txt .detail, .sub_time, .date")
                    pub_str = datetime.now().strftime("%Y-%m-%d")
                    if date_el:
                        parsed = _parse_date_str(date_el.get_text(strip=True))
                        if parsed:
                            pub_str = parsed
                            try:
                                if datetime.strptime(pub_str, "%Y-%m-%d") < cutoff:
                                    continue
                            except ValueError:
                                pass
                    if not _brand_validate(service_id, title, desc):
                        continue
                    results.append({
                        "service_id":   service_id,
                        "published_at": pub_str,
                        "source_type":  src_type,
                        "change_type":  classify_change_type(title, desc),
                        "title":        title,
                        "summary":      _parking_summary(desc) or None,
                        "url":          href,
                        "sentiment":    classify_sentiment(title, desc),
                    })
        except Exception as e:
            log.warning(f"Naver search 실패 [{service_id}|{kw}]: {e}")
            continue

    return results


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────

def _fetch_article_text(url: str, max_chars: int = 1500) -> str:
    """기사 URL에서 본문 텍스트 추출. 실패 시 빈 문자열 반환."""
    try:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=8, verify=True, allow_redirects=True)
        except requests.exceptions.SSLError:
            resp = requests.get(url, headers=HEADERS, timeout=8, verify=False, allow_redirects=True)
        if resp.status_code != 200:
            return ""
        if "html" not in resp.headers.get("content-type", ""):
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer",
                         "aside", "iframe", "noscript", "form"]):
            tag.decompose()
        body_el = (
            soup.select_one("article")
            or soup.select_one(
                ".article-content, .article_body, .news_body, "
                ".content-body, .article__body, .articleBody"
            )
            or soup.select_one(
                ".newsct_article, #articleBodyContents, "
                "#article-view-content-div, .article_view"
            )
            or soup.select_one("main")
            or soup.find("body")
        )
        if body_el is None:
            return ""
        text = body_el.get_text(separator=" ", strip=True)
        return " ".join(text.split())[:max_chars]
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


def _dedup_by_title(items: list[dict], threshold: float = 0.6) -> list[dict]:
    """같은 서비스+날짜 내 제목 유사도 기반 중복 제거.
    자카드 유사도 >= threshold 인 제목은 먼저 수집된 것만 유지.
    """
    from collections import defaultdict

    def tokenize(t: str) -> set:
        return set(re.findall(r'[가-힣a-z0-9]{2,}', (t or '').lower()))

    def jaccard(s1: set, s2: set) -> float:
        if not s1 or not s2:
            return 0.0
        return len(s1 & s2) / len(s1 | s2)

    groups: dict[str, list] = defaultdict(list)
    for item in items:
        key = f"{item.get('service_id', '')}|{item.get('published_at', '')}"
        groups[key].append(item)

    result = []
    for group_items in groups.values():
        kept_tokens: list[set] = []
        for item in group_items:
            tokens = tokenize(item.get('title', ''))
            if any(jaccard(tokens, kt) >= threshold for kt in kept_tokens):
                continue  # 유사한 제목 이미 있으면 건너뜀
            kept_tokens.append(tokens)
            result.append(item)

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

    client_id     = os.environ.get('NAVER_CLIENT_ID', '')
    client_secret = os.environ.get('NAVER_CLIENT_SECRET', '')
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
                    disp = f"[카페:{cafe}] {title}" if cafe else title
                    results.append({
                        'service_id':   service_id,
                        'published_at': pub_str,
                        'source_type':  'cafe',
                        'change_type':  classify_change_type(title, desc),
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
                    disp = f"[카페:{cafe}] {title}" if cafe else title
                    results.append({
                        'service_id':   service_id,
                        'published_at': pub_str,
                        'source_type':  'cafe',
                        'change_type':  classify_change_type(title, desc),
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
    "html_list":    crawl_html_list,
    "html_diff":    crawl_html_diff,
    "appstore":     crawl_appstore,
    "ios_appstore": crawl_ios_appstore,
    "app_info":     crawl_app_info,
    "youtube_rss":  crawl_youtube_rss,
    "naver_blog":   crawl_naver_search,
    "naver_news":   crawl_naver_search,
    "naver_cafe":   crawl_naver_cafe,
}


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

            for item in items:
                if db.insert_change(**item):
                    added += 1
                    new_items.append({
                        **item,
                        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
            deduped = _dedup_by_title(new_items)
            synced = sh_mod.append_items(deduped, service_map=svc_map)
            sh_mod.invalidate_cache()
            print(f"[INFO] Google Sheets {synced}건 동기화 완료")
        except Exception as e:
            print(f"[WARN] Sheets 동기화 실패 (수집 결과는 정상 저장됨): {e}")

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
