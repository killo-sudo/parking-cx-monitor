#!/usr/bin/env python3
"""
weekly_report.py — THE PARKING GAZETTE 주간 리포트 생성기
매주 월요일 11:15 KST (UTC 02:15) GitHub Actions 자동 실행
"""

import html as html_lib
import json
import re
from collections import defaultdict, Counter
from datetime import timedelta, date
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"

SERVICE_ORDER = [
    "moduparking", "kakaot_parking", "tmap_parking", "iparking",
    "nicepark", "highparking", "parkingfriends", "zoomansa",
    "amano_korea", "kmpark", "parkingcloud", "sk_shielders",
]

REVIEW_TYPES = {"appstore", "ios_appstore"}
NEWS_TYPES   = {"news", "blog", "rss"}      # 통계·수집현황용 (블로그 포함)
NEWS_ONLY    = {"news", "rss"}              # TOP STORY/WIRE 인용용 (블로그 절대 제외)

PLATFORM_LABEL = {"google_play": "Google Play", "ios": "App Store"}

# ─────────────────────────────────────────────
# Korean stop-words (common particles, conjunctions, auxiliary verbs)
# ─────────────────────────────────────────────
KO_STOPWORDS = {
    "이", "가", "을", "를", "은", "는", "의", "에", "에서", "로", "으로", "와", "과",
    "도", "만", "까지", "부터", "에게", "한테", "께", "이다", "있다", "없다", "하다",
    "되다", "않다", "못하다", "같다", "그", "저", "이", "이런", "저런", "그런", "어떤",
    "한", "한번", "좀", "더", "또", "다시", "아직", "이미", "너무", "정말", "진짜",
    "앱", "이용", "사용", "주차", "주차장", "그냥", "제발", "부탁", "감사", "고맙",
    "합니다", "입니다", "습니다", "에요", "이에요", "네요", "군요", "거든요", "인데요",
    "해요", "해서", "하고", "하면", "하지", "하는", "하여", "해서", "합니다",
    "있어요", "없어요", "같아요", "같네요", "같은데", "것", "거", "게", "걸", "건",
    "때", "때문", "수", "듯", "점", "편", "번", "개", "등", "및", "또는",
}


# ─────────────────────────────────────────────
# IO helpers
# ─────────────────────────────────────────────

def load_json(path, default=None):
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def parse_date(s: str):
    if not s:
        return None
    s = str(s).strip()[:10]
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


# ─────────────────────────────────────────────
# Meta (volume/archive counter)
# ─────────────────────────────────────────────

def load_meta() -> dict:
    m = load_json(DOCS / "gazette_meta.json", {})
    today = date.today()
    return {
        "year":             m.get("year", today.year % 100),
        "week_num":         m.get("week_num", 0),
        "issue_total":      m.get("issue_total", 0),
        "last_report_date": m.get("last_report_date"),
        "issues":           m.get("issues", []),
    }


def save_meta(meta: dict):
    (DOCS / "gazette_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def advance_meta(meta: dict, to_dt: date) -> tuple:
    """ISO 캘린더 주차 기준. issue_total은 누적 발행 호수."""
    iso_year, iso_week, _ = to_dt.isocalendar()
    year     = iso_year % 100
    week_num = iso_week
    # 같은 주차 재실행 시 issue_total은 증가시키지 않음
    last_y = meta.get("year")
    last_w = meta.get("week_num")
    if last_y == year and last_w == week_num:
        issue_total = meta.get("issue_total", 1)
    else:
        issue_total = meta.get("issue_total", 0) + 1
    return year, week_num, issue_total


def get_period() -> tuple:
    """항상 가장 최근 완료된 전주 (Mon~Sun).
    실행 요일과 무관하게 동일한 윈도우 — 월요일 자동 / 다른 요일 수동 테스트 결과 일치.
    예) 오늘 목 05-21 → 전주 05-11(월)~05-17(일)
        오늘 월 05-25 → 전주 05-18(월)~05-24(일)
    """
    today = date.today()
    days_back = today.weekday() + 1   # Mon=1, Tue=2, ..., Sun=7
    to_dt   = today - timedelta(days=days_back)
    from_dt = to_dt - timedelta(days=6)
    return from_dt, to_dt


# ─────────────────────────────────────────────
# Data processing
# ─────────────────────────────────────────────

def filter_period(items: list, from_dt: date, to_dt: date) -> list:
    """기간 필터 — 모든 항목 게시일/작성일(published_at) 기준.
    리뷰는 리뷰 작성일, 뉴스·블로그는 기사 게시일이 from_dt~to_dt 범위 안에 있어야 포함.
    수집일(collected_at)은 사용하지 않는다 (실제 사건 발생 주차 기준 집계).
    """
    result = []
    for item in items:
        dt = parse_date(item.get("published_at", ""))
        if dt and from_dt <= dt <= to_dt:
            result.append(item)
    return result


def pick_top_story(items: list) -> dict | None:
    """TOP STORY 픽: 블로그 절대 제외 → 타사 뉴스 우선 → 없으면 자사 뉴스."""
    news = [i for i in items if i.get("source_type") in NEWS_ONLY
            and i.get("title") and len(i.get("title", "")) > 10]
    if not news:
        return None

    def score(i):
        s = 0
        ct = i.get("change_type", "")
        if ct in ("사업확장", "정책"):
            s += 5
        if i.get("sentiment") == "negative":
            s += 3
        if len(i.get("summary") or "") > 50:
            s += 2
        return s

    competitors = [i for i in news if i.get("service_id") != "moduparking"]
    if competitors:
        return max(competitors, key=score)
    return max(news, key=score)


def period_app_league(items: list) -> list:
    """해당 기간 수집된 리뷰 기준 평균 평점 계산."""
    by_svc = defaultdict(list)
    for item in items:
        if item.get("source_type") not in REVIEW_TYPES:
            continue
        rating = item.get("rating") or item.get("score")
        if rating is None:
            continue
        try:
            r = float(rating)
        except (TypeError, ValueError):
            continue
        by_svc[item.get("service_id", "unknown")].append((r, item))

    rows = []
    for svc_id, pairs in by_svc.items():
        avg = sum(r for r, _ in pairs) / len(pairs)
        name = pairs[0][1].get("name_ko", svc_id)
        aos_cnt = sum(1 for _, i in pairs if i.get("source_type") == "appstore")
        ios_cnt = sum(1 for _, i in pairs if i.get("source_type") == "ios_appstore")
        rows.append({
            "service_id": svc_id, "name_ko": name,
            "avg": round(avg, 2), "review_count": len(pairs),
            "aos_cnt": aos_cnt, "ios_cnt": ios_cnt,
        })
    rows.sort(key=lambda r: r["avg"], reverse=True)
    return rows


def service_stats(items: list) -> list:
    by_svc = defaultdict(list)
    for item in items:
        by_svc[item.get("service_id", "unknown")].append(item)
    rows = []
    for svc_id in SERVICE_ORDER:
        svc_items = by_svc.get(svc_id, [])
        if not svc_items:
            continue
        reviews = [i for i in svc_items if i.get("source_type") in REVIEW_TYPES]
        news    = [i for i in svc_items if i.get("source_type") in NEWS_TYPES]
        neg     = sum(1 for i in svc_items if i.get("sentiment") == "negative")
        pos     = sum(1 for i in svc_items if i.get("sentiment") == "positive")
        neu     = len(svc_items) - neg - pos
        name    = svc_items[0].get("name_ko", svc_id)
        rows.append({
            "service_id": svc_id, "name_ko": name,
            "total": len(svc_items), "reviews": len(reviews), "news": len(news),
            "neg": neg, "pos": pos, "neu": neu,
        })
    for svc_id, svc_items in by_svc.items():
        if svc_id not in SERVICE_ORDER:
            name = svc_items[0].get("name_ko", svc_id)
            reviews = [i for i in svc_items if i.get("source_type") in REVIEW_TYPES]
            news    = [i for i in svc_items if i.get("source_type") in NEWS_TYPES]
            neg = sum(1 for i in svc_items if i.get("sentiment") == "negative")
            pos = sum(1 for i in svc_items if i.get("sentiment") == "positive")
            neu = len(svc_items) - neg - pos
            rows.append({"service_id": svc_id, "name_ko": name,
                         "total": len(svc_items), "reviews": len(reviews), "news": len(news),
                         "neg": neg, "pos": pos, "neu": neu})
    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows


def pick_notable_reviews(items: list, n=5) -> list:
    candidates = [i for i in items
                  if i.get("source_type") in REVIEW_TYPES
                  and i.get("summary") and len(i.get("summary") or "") > 5]
    neg = [i for i in candidates if i.get("sentiment") == "negative"]
    pos = [i for i in candidates if i.get("sentiment") == "positive"]
    neg.sort(key=lambda i: len(i.get("summary") or ""), reverse=True)
    pos.sort(key=lambda i: len(i.get("summary") or ""), reverse=True)
    return (neg[:4] + pos[:1])[:n]


def pick_news_briefs(items: list, n=5) -> list:
    """Competitor Wire 픽: 블로그 제외, 자사 제외 (타사 뉴스만)."""
    candidates = [i for i in items
                  if i.get("source_type") in NEWS_ONLY
                  and i.get("service_id") != "moduparking"
                  and i.get("title") and len(i.get("title") or "") > 5]
    candidates.sort(key=lambda i: (
        i.get("change_type", "") in ("사업확장", "정책"),
        len(i.get("summary") or ""),
    ), reverse=True)
    return candidates[:n]


# ─────────────────────────────────────────────
# 한국어 명사 추출 (kiwipiepy 형태소 분석기)
# ─────────────────────────────────────────────

# 명사로 분석되지만 키워드로 의미 없는 단어 (브랜드명·일반어 등)
_NOUN_EXTRA_STOPWORDS = {
    # 일반 단어
    "앱", "어플", "이용", "사용", "정말", "진짜", "너무", "그냥", "제발",
    "부탁", "감사", "고맙", "현장", "실제", "이후", "이전", "지금",
    "오늘", "어제", "내일", "올해", "작년",
    "때문", "경우", "이번", "다음", "지난",
    "전혀", "조금", "많이", "자꾸", "계속", "다시", "또한",
    "사실", "확실", "정확", "분명", "그것", "이것",
    # 비주차 도메인 — 카카오T 택시·내비, Tmap 내비 등에서 새어 나오는 단어
    "바이크", "택시", "내비", "네비", "길찾기", "경로", "지도",
    # 의미 약한 메타 단어
    "관리", "정보", "설명", "이내", "당일", "기분", "여부",
    "사례", "개선", "반려", "생각", "처리", "구매", "리뷰",
    "생각", "이내", "내역",
}

# 한국 성씨 (인명 NNP 필터링용) — 단일성씨 위주, 복합성씨 일부
_KOREAN_SURNAMES = {
    "김", "이", "박", "최", "정", "강", "조", "윤", "장", "임",
    "한", "오", "서", "신", "권", "황", "안", "송", "류", "전",
    "홍", "고", "문", "양", "손", "배", "백", "허", "유", "남",
    "심", "노", "하", "곽", "성", "차", "주", "우", "구", "민",
    "원", "공", "방", "변", "함", "표", "현", "마", "기", "라",
    "지", "추", "도", "탁", "선", "설", "여", "맹", "사", "위",
    "단", "왕", "옥", "동", "어", "복", "은", "편", "용",
}

# 브랜드 화이트리스트 — 인명 휴리스틱이 잘못 차단하지 않도록 보호
_BRAND_WHITELIST_NORMALIZED = {
    "카카오", "카카오t", "카카오모빌리티", "케이엠파킹", "케이엠파크",
    "티맵", "tmap", "tmap주차", "티맵모빌리티",
    "모두의주차장", "모두의", "모두컴퍼니",
    "아이파킹", "iparking", "파킹클라우드", "parkingcloud",
    "나이스파크", "nicepark",
    "하이파킹", "투루파킹", "휴맥스모빌리티", "휴맥스",
    "파킹프렌즈", "mds", "주만사", "아마노", "아마노코리아",
    "쉴더스", "에스케이쉴더스", "sk쉴더스",
}


def _is_likely_person_name(word: str) -> bool:
    """2~4자 단어가 한국 성씨로 시작하고 브랜드 화이트리스트에 없으면 인명 후보로 간주."""
    if not word or len(word) < 2 or len(word) > 4:
        return False
    if word.lower() in _BRAND_WHITELIST_NORMALIZED:
        return False
    # 단일성씨 + 1~3자 이름 패턴
    first = word[0]
    if first in _KOREAN_SURNAMES:
        return True
    return False


def _get_kiwi():
    """kiwipiepy 인스턴스 lazy 초기화. 설치 안 됐으면 None."""
    if not hasattr(_get_kiwi, "_inst"):
        try:
            from kiwipiepy import Kiwi
            _get_kiwi._inst = Kiwi()
        except Exception:
            _get_kiwi._inst = None
    return _get_kiwi._inst


def _extract_nouns(text: str) -> list:
    """본문에서 명사(NNG)만 추출. 고유명사(NNP)는 브랜드 화이트리스트만 통과 + 인명 제외.
    공통 stopword·조사 제거 + 2글자 이상.
    """
    if not text:
        return []

    def _is_keep(form: str, tag: str) -> bool:
        if len(form) < 2:
            return False
        if form in KO_STOPWORDS or form in _NOUN_EXTRA_STOPWORDS:
            return False
        # NNG (일반명사) — 인명 휴리스틱으로 한 번 더 거름
        if tag == "NNG":
            return not _is_likely_person_name(form)
        # NNP (고유명사) — 브랜드 화이트리스트만 통과 (인명 신재혁 등 차단)
        if tag == "NNP":
            return form.lower() in _BRAND_WHITELIST_NORMALIZED
        return False

    kiwi = _get_kiwi()
    if kiwi is not None:
        try:
            tokens = kiwi.tokenize(text)
            return [t.form for t in tokens if _is_keep(t.form, t.tag)]
        except Exception:
            pass
    # Fallback: regex
    pat = re.compile(r"[가-힣]{2,7}")
    return [w for w in pat.findall(text)
            if w not in KO_STOPWORDS
            and w not in _NOUN_EXTRA_STOPWORDS
            and not _is_likely_person_name(w)]


def _extract_nouns_ordered(text: str) -> list:
    """단순히 명사 추출 — _extract_nouns와 동일하지만 명시적 이름.
    bigram 결합용으로 순서 보존이 필요해서 별도 함수로 둠 (지금은 동일하나 향후 분기 가능).
    """
    return _extract_nouns(text)


def _bigram_candidate(a: str, b: str) -> str | None:
    """두 명사를 붙여서 의미있는 복합어 후보 생성. 4~8자만 유효."""
    if not a or not b:
        return None
    merged = a + b
    if 4 <= len(merged) <= 8:
        return merged
    return None


def extract_keywords(items: list, top_n=22) -> list:
    """한국어 명사 빈출 + 인접 bigram 복합어. 빈출 bigram은 단일 명사보다 우선.
    예: "결제" + "오류"가 자주 인접 → "결제오류" 키워드로 표시.
    """
    uni_sentiment: dict[str, list[str]] = defaultdict(list)
    bi_sentiment:  dict[str, list[str]] = defaultdict(list)

    for item in items:
        text = " ".join(filter(None, [
            item.get("title", ""), item.get("summary", "")
        ]))
        sent = item.get("sentiment", "neutral")
        nouns = _extract_nouns_ordered(text)

        for n in nouns:
            uni_sentiment[n].append(sent)

        for i in range(len(nouns) - 1):
            bg = _bigram_candidate(nouns[i], nouns[i + 1])
            if bg and bg not in KO_STOPWORDS and bg not in _NOUN_EXTRA_STOPWORDS:
                bi_sentiment[bg].append(sent)

    # 자주 등장하는 bigram (cnt ≥ 2)만 유효
    common_bigrams = {bg: sents for bg, sents in bi_sentiment.items() if len(sents) >= 2}

    # bigram 구성 unigram 일부 차감 (이중 노출 방지) — 휴리스틱
    for bg, sents in common_bigrams.items():
        n = len(sents)
        # bigram을 구성한다고 추정되는 unigram 후보 — 정확한 split 모르나 빈도 동일하면 차감
        # 보수적으로: bigram 빈도만큼 unigram에서 cnt 차감 (음수 방지)
        for uni in list(uni_sentiment.keys()):
            if uni in bg and len(uni_sentiment[uni]) >= n:
                # bigram 빈도만큼 차감
                uni_sentiment[uni] = uni_sentiment[uni][n:]

    # 최종 통합 — bigram 먼저, 그 다음 unigram (cnt 내림차순)
    combined: list[tuple[str, list[str], str]] = []
    for word, sents in common_bigrams.items():
        combined.append((word, sents, "bigram"))
    for word, sents in uni_sentiment.items():
        if len(sents) >= 1:
            combined.append((word, sents, "unigram"))

    # 정렬: bigram에 +0.5 가중 (동률시 우선), 그 다음 빈도 내림차순
    def _key(t):
        word, sents, kind = t
        boost = 0.5 if kind == "bigram" else 0.0
        return -(len(sents) + boost)
    combined.sort(key=_key)
    top = combined[:top_n]

    results = []
    for word, sents, kind in top:
        cnt = len(sents)
        if cnt == 0:
            continue
        neg_ratio = sents.count("negative") / cnt
        pos_ratio = sents.count("positive") / cnt
        if neg_ratio >= 0.6:
            sev = "sev-1" if neg_ratio >= 0.8 else "sev-2"
        elif pos_ratio >= 0.5:
            sev = "sev-4"
        else:
            sev = "sev-3"
        results.append({"word": word, "cnt": cnt, "sev": sev})
    return results


def build_sparkline(items: list, from_dt: date, to_dt: date, width=110, height=36) -> str:
    """일별 항목 수로 SVG 폴리라인 생성."""
    days = (to_dt - from_dt).days or 1
    daily = Counter()
    for item in items:
        dt = parse_date(item.get("published_at") or item.get("collected_at", ""))
        if dt:
            daily[dt] += 1

    vals = []
    for i in range(days + 1):
        d = from_dt + timedelta(days=i)
        vals.append(daily.get(d, 0))

    if max(vals, default=0) == 0:
        return f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}"></svg>'

    mx = max(vals)
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = round(i / max(n - 1, 1) * width, 1)
        y = round((1 - v / mx) * (height - 4) + 2, 1)
        pts.append(f"{x},{y}")
    pts_str = " ".join(pts)
    return (f'<svg class="spark" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">'
            f'<polyline points="{pts_str}" fill="none" stroke="#1d4ed8" stroke-width="1.6"/>'
            f'</svg>')


# ─────────────────────────────────────────────
# HTML helpers
# ─────────────────────────────────────────────

def esc(s) -> str:
    return html_lib.escape(str(s or ""), quote=False)


def fmt_date_ko(d: date) -> str:
    MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    DAYS   = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return f"{DAYS[d.weekday()]}, {MONTHS[d.month-1]} {d.day}, {d.year}"


def kw_size_class(cnt: int, max_cnt: int) -> str:
    if max_cnt <= 0:
        return "s-xs"
    ratio = cnt / max_cnt
    if ratio >= 0.8:
        return "s-xl"
    if ratio >= 0.55:
        return "s-lg"
    if ratio >= 0.35:
        return "s-md"
    if ratio >= 0.18:
        return "s-sm"
    return "s-xs"


def neg_rate_class(pct: float) -> str:
    if pct >= 35:
        return "high"
    if pct >= 22:
        return "mid"
    return "low"


def badge_html(label: str, cls: str) -> str:
    return f'<span class="badge {esc(cls)}">{esc(label)}</span>'


def change_badge(ct: str) -> str:
    # 카테고리: VOC / 기술 / 정책 / 사업확장 / 기타 (5개)
    MAP = {
        "VOC": "voc", "기술": "tech", "정책": "policy",
        "사업확장": "biz", "기타": "",
    }
    cls = MAP.get(ct, "")
    if not cls:
        return ""
    return badge_html(ct, cls)


def stars_html(rating: float | None) -> str:
    if rating is None:
        return ""
    filled = min(5, max(0, round(rating)))
    empty  = 5 - filled
    on  = "★" * filled
    off = "★" * empty
    if off:
        return f'<span class="voc-stars">{on}<span class="off">{off}</span></span>'
    return f'<span class="voc-stars">{on}</span>'


# ─────────────────────────────────────────────
# Archive nav
# ─────────────────────────────────────────────

MIN_WEEK_DISPLAYED = 20  # 19주차 이하는 표시 안 함 (사용자 요청)


def render_archive_nav(meta: dict, year: int, week_num: int) -> str:
    issues = [i for i in meta.get("issues", [])
              if i.get("week_num", 0) >= MIN_WEEK_DISPLAYED]
    cur_year_str = f"{year:02d}"

    # Past issues by year
    by_year = defaultdict(list)
    for iss in issues:
        by_year[iss.get("year", year)].append(iss)
    all_years = sorted(set(list(by_year.keys()) + [year]))

    # Year switcher
    yr_pills = ""
    for y in sorted(all_years):
        active = " active" if y == year else ""
        yr_pills += f'<span class="yr{active}">{y + 2000}Y</span>'

    # Breadcrumb
    breadcrumb = (
        f'<span>Index</span>'
        f'<span class="sep">/</span>'
        f'<span>20{year}</span>'
        f'<span class="sep">/</span>'
        f'<span class="now">WEEK {cur_year_str}Y · {week_num}W</span>'
    )

    # Week pills — 이미 발행된 호 + 현재 호만 표시 (미래 placeholder 제거)
    past_set = {(iss.get("year"), iss.get("week_num")): iss.get("file", "#")
                for iss in issues}
    # 현재 주차까지만 (week_num 이하), 미래는 안 보여줌
    pills_html = ""
    for w in range(MIN_WEEK_DISPLAYED, week_num + 1):
        key = (year, w)
        if w == week_num:
            pills_html += (
                f'<a class="week-pill live" role="tab" aria-selected="true">'
                f'<span class="lbl">WEEK {cur_year_str}Y · {w}W</span></a>'
            )
        elif key in past_set:
            href = esc(past_set[key])
            pills_html += (
                f'<a class="week-pill" href="{href}" role="tab">'
                f'<span class="lbl">{cur_year_str}Y · {w}W</span></a>'
            )
        # 미래 주차(week_num+1 이상)는 표시 안 함

    return f"""
<nav class="archive-nav" aria-label="Issue archive">
  <div class="archive-top">
    <span class="arch-label">▤ Archive Index</span>
    <div class="breadcrumb">{breadcrumb}</div>
    <div class="meta">{yr_pills}</div>
  </div>
  <div class="archive-bottom">
    <div class="tree-label">
      <span class="glyph">20{year} └─</span>
      <span>WEEKLY ISSUES</span>
    </div>
    <div class="week-tabs" role="tablist">{pills_html}</div>
  </div>
</nav>"""


# ─────────────────────────────────────────────
# Section renderers
# ─────────────────────────────────────────────

def render_masthead(year: int, week_num: int, issue_total: int,
                    from_dt: date, to_dt: date) -> str:
    vol_tag  = f"{year:02d}Y · {week_num}W"
    date_str = fmt_date_ko(to_dt).upper()
    period   = f"{from_dt.strftime('%Y.%m.%d')} — {to_dt.strftime('%Y.%m.%d')}"
    return f"""
<header class="masthead">
  <div class="masthead-top">
    <div class="left">
      <span><span class="dot"></span>LIVE EDITION</span>
      <span>VOL. I · NO. {issue_total:02d}</span>
    </div>
    <div class="right">
      <span>{esc(date_str)}</span>
      <span>SEOUL · KRW 0</span>
      <span>MODU CX NEWSROOM</span>
    </div>
  </div>
  <div class="masthead-title">
    <h1><span class="the">The</span>PARKING&nbsp;GAZETTE</h1>
    <div class="masthead-tag">A Weekly Dispatch on Parking, Mobility &amp; Customer Voice — Published Every Monday by the Modu Newsroom</div>
  </div>
  <div class="masthead-meta">
    <div class="left">
      <span class="coverage">Coverage Period : {esc(period)} (전주 Mon~Sun)</span>
    </div>
    <div class="center">
      <span class="week-badge"><span>WEEK</span><span class="num">{esc(vol_tag)}</span></span>
    </div>
    <div class="right">
      <span>ISSUE #{issue_total:03d} · CUMULATIVE</span>
    </div>
  </div>
</header>"""


# 리뷰 서브카테고리 — 자사 부정 리뷰의 액션 분류
_REV_SUBCATS = {
    "결제오류":  ["결제", "카드", "카카오페이", "페이먼트", "정산", "영수증", "환불", "PG", "인증실패"],
    "예약":      ["예약", "취소", "당일예약", "변경", "일정", "사전결제"],
    "지도·검색": ["지도", "빈자리", "위치", "주소", "길찾기", "GPS", "검색", "표시"],
    "쿠폰":      ["쿠폰", "할인", "적립", "포인트", "프로모션"],
    "고객센터":  ["고객센터", "상담", "답변", "문의", "콜센터", "대기", "응답"],
}

_GAP_PEER_SVCS = ("kakaot_parking", "tmap_parking", "iparking")


def _parse_star(title: str) -> int | None:
    """리뷰 제목의 [Android ★4] / [iOS ★1] 형식에서 별점 추출."""
    if not title:
        return None
    m = re.search(r"★\s*(\d+)", title)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _classify_subcat(text: str) -> str | None:
    """리뷰 본문 → 결제/예약/지도/쿠폰/CS 5분류. 매칭 없으면 None."""
    if not text:
        return None
    t = text.lower()
    best = None
    best_score = 0
    for cat, kws in _REV_SUBCATS.items():
        score = sum(1 for k in kws if k.lower() in t)
        if score > best_score:
            best_score = score
            best = cat
    return best if best_score > 0 else None


def compute_self_review_stats(items: list) -> dict:
    """자사(모두의주차장) 리뷰만 분석 — 부정률·부정군 별점·톱 부정 카테고리."""
    self_reviews = [i for i in items
                    if i.get("service_id") == "moduparking"
                    and i.get("source_type") in REVIEW_TYPES]
    n = len(self_reviews)
    if n == 0:
        return {"n": 0, "neg_pct": 0, "neg_n": 0, "top_cat": None,
                "top_cat_n": 0, "top_cat_pct": 0, "neg_avg_star": None}

    neg_reviews = [i for i in self_reviews if i.get("sentiment") == "negative"]
    neg_n = len(neg_reviews)
    neg_pct = round(neg_n / n * 100, 1)

    stars = [s for s in (_parse_star(i.get("title", "")) for i in neg_reviews) if s is not None]
    neg_avg_star = round(sum(stars) / len(stars), 1) if stars else None

    cat_counts: dict[str, int] = {}
    for r in neg_reviews:
        cat = _classify_subcat((r.get("title", "") + " " + (r.get("summary") or "")))
        if cat:
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
    if cat_counts:
        top_cat = max(cat_counts, key=cat_counts.get)
        top_cat_n = cat_counts[top_cat]
        top_cat_pct = round(top_cat_n / neg_n * 100, 1) if neg_n else 0
    else:
        top_cat, top_cat_n, top_cat_pct = None, 0, 0

    return {
        "n": n, "neg_pct": neg_pct, "neg_n": neg_n,
        "top_cat": top_cat, "top_cat_n": top_cat_n, "top_cat_pct": top_cat_pct,
        "neg_avg_star": neg_avg_star,
    }


def compute_competitor_gap(items: list) -> dict:
    """자사 평균 별점 vs 카카오T·Tmap·아이파킹 가중평균 Gap."""
    def avg_for(sid):
        scs = [s for s in (_parse_star(i.get("title", "")) for i in items
                           if i.get("service_id") == sid
                           and i.get("source_type") in REVIEW_TYPES) if s is not None]
        return (sum(scs) / len(scs), len(scs)) if scs else (None, 0)

    self_avg, _ = avg_for("moduparking")
    weighted_sum, weighted_n = 0.0, 0
    for sid in _GAP_PEER_SVCS:
        avg, n = avg_for(sid)
        if avg is not None:
            weighted_sum += avg * n
            weighted_n   += n
    peer_avg = (weighted_sum / weighted_n) if weighted_n else None

    if self_avg is None or peer_avg is None:
        return {"self_avg": self_avg, "peer_avg": peer_avg, "gap": None}
    return {
        "self_avg": round(self_avg, 2),
        "peer_avg": round(peer_avg, 2),
        "gap":      round(self_avg - peer_avg, 2),
    }


def count_competitor_events(items: list) -> dict:
    """경쟁사 뉴스 중 정책+사업확장 카운트. 상위 3사."""
    events = [i for i in items
              if i.get("source_type") in NEWS_ONLY
              and i.get("service_id") != "moduparking"
              and i.get("change_type") in ("사업확장", "정책")]
    by_svc: dict[str, int] = {}
    name_map: dict[str, str] = {}
    for e in events:
        sid = e.get("service_id", "")
        by_svc[sid] = by_svc.get(sid, 0) + 1
        if sid not in name_map:
            name_map[sid] = e.get("name_ko", sid)
    top3 = [(name_map.get(sid, sid), n)
            for sid, n in sorted(by_svc.items(), key=lambda x: -x[1])[:3]]
    return {"total": len(events), "top3": top3}


def extract_neg_keywords(items: list, top_n: int = 30) -> list:
    """자사 부정 리뷰의 빈출 명사 키워드 (신규 키워드 비교용, kiwipiepy)."""
    neg = [i for i in items
           if i.get("service_id") == "moduparking"
           and i.get("source_type") in REVIEW_TYPES
           and i.get("sentiment") == "negative"]
    counts: dict[str, int] = {}
    for r in neg:
        text = (r.get("title", "") + " " + (r.get("summary") or ""))
        for tok in _extract_nouns(text):
            counts[tok] = counts.get(tok, 0) + 1
    return [k for k, _ in sorted(counts.items(), key=lambda x: -x[1])[:top_n]]


def compute_new_voc_ratio(cur_kws: list, history_kws: set | None) -> dict:
    """이번주 부정 키워드 중 과거에 없던 신규 키워드 비율."""
    cur_set = set(cur_kws or [])
    if not history_kws:
        return {"new_n": None, "total": len(cur_set), "new_pct": None, "new_kws": []}
    new = cur_set - history_kws
    total = len(cur_set) or 1
    return {
        "new_n":   len(new),
        "total":   len(cur_set),
        "new_pct": round(len(new) / total * 100, 1),
        "new_kws": list(new)[:3],
    }


def compute_stats(items: list, from_dt: date, to_dt: date) -> dict:
    """기간 통계 — CX팀장 권고 KPI + 시스템 운영 보조 값."""
    self_stats = compute_self_review_stats(items)
    gap_stats  = compute_competitor_gap(items)
    comp_evt   = count_competitor_events(items)

    total   = len(items)
    reviews = sum(1 for i in items if i.get("source_type") in REVIEW_TYPES)
    news    = sum(1 for i in items if i.get("source_type") in NEWS_TYPES)
    days    = (to_dt - from_dt).days or 1

    return {
        # CX팀장 권고 KPI
        "self_neg_pct":     self_stats["neg_pct"],
        "self_neg_n":       self_stats["neg_n"],
        "self_review_n":    self_stats["n"],
        "self_top_cat":     self_stats["top_cat"],
        "self_top_cat_pct": self_stats["top_cat_pct"],
        "self_top_cat_n":   self_stats["top_cat_n"],
        "self_neg_avg_star": self_stats["neg_avg_star"],
        "gap":              gap_stats["gap"],
        "self_avg":         gap_stats["self_avg"],
        "peer_avg":         gap_stats["peer_avg"],
        "comp_events":      comp_evt["total"],
        "comp_top3":        comp_evt["top3"],
        # 신규 VOC 키워드 비율은 history 필요 → main()에서 채움
        "neg_keywords":     extract_neg_keywords(items),
        # 시스템 운영 보조값 (호환)
        "total":    total,
        "reviews":  reviews,
        "news":     news,
        "per_day":  round(total / days, 1),
    }


def find_prev_stats(meta: dict, year: int, week_num: int) -> tuple:
    """가장 최근 과거 issue의 stats와 라벨(예: '25Y 52W') 반환. 없으면 (None, None)."""
    issues = sorted(
        [i for i in meta.get("issues", []) if isinstance(i.get("stats"), dict)],
        key=lambda i: (i.get("year", 0), i.get("week_num", 0)),
        reverse=True,
    )
    for iss in issues:
        if iss["year"] < year or (iss["year"] == year and iss["week_num"] < week_num):
            label = f"{iss['year']:02d}Y {iss['week_num']}W"
            return iss["stats"], label
    return None, None


def _delta_block(cur, prev, unit: str = "%", show_vs: str = "") -> str:
    """WoW 델타 표시 HTML. unit='%' for percentage change, 'pt' for raw pt diff."""
    if prev is None or prev == 0:
        if cur is None:
            return ""
        return '<div class="delta">— 기준 주차</div>'
    try:
        if unit == "pt":
            d = round(cur - prev, 1)
        else:
            d = round((cur - prev) / prev * 100, 1)
    except Exception:
        return ""
    if d > 0:
        cls, arr, sign = "up", "▲", "+"
    elif d < 0:
        cls, arr, sign = "down", "▼", "−"
        d = abs(d)
    else:
        return f'<div class="delta">— 변동 없음{(" vs " + show_vs) if show_vs else ""}</div>'
    vs = f' vs {show_vs}' if show_vs else ''
    return f'<div class="delta {cls}"><span class="arrow">{arr}</span> {sign}{d}{unit}{vs}</div>'


def render_stats(items: list, from_dt: date, to_dt: date,
                 cur: dict, prev: dict | None, prev_label: str | None,
                 new_voc: dict | None = None) -> str:
    """CX팀장 권고 KPI 6칸 — 자사 부정률 / Gap / 톱 카테고리 / 경쟁사 이벤트 / 신규 VOC / 보조."""

    def d(key, unit="%"):
        return _delta_block(cur.get(key), prev.get(key) if prev else None,
                            unit=unit, show_vs=prev_label or "")

    # ① 자사 부정 리뷰율
    cell1_label = "자사 부정 리뷰율"
    cell1_val   = f'{cur.get("self_neg_pct", 0)}'
    cell1_unit  = "%"
    cell1_sub   = (f'<div class="sub">n={cur.get("self_neg_n", 0)} / {cur.get("self_review_n", 0)}건</div>'
                   if cur.get("self_review_n") else '<div class="sub">자사 리뷰 없음</div>')
    cell1_delta = d("self_neg_pct", unit="pt")

    # ② 자사 ★ vs 경쟁사 Gap
    gap = cur.get("gap")
    if gap is None:
        cell2_val = "—"
        cell2_unit = ""
        cell2_sub = '<div class="sub">자사/경쟁사 별점 데이터 부족</div>'
    else:
        sign = "+" if gap > 0 else ("−" if gap < 0 else "±")
        cell2_val  = f'{sign}{abs(gap):.2f}'
        cell2_unit = "pt"
        cell2_sub  = (f'<div class="sub">자사 ★{cur.get("self_avg")} vs 경쟁평균 ★{cur.get("peer_avg")}</div>')
    cell2_delta = d("gap", unit="pt")

    # ③ 부정 톱 카테고리
    top_cat = cur.get("self_top_cat")
    if top_cat:
        cell3_val  = top_cat
        cell3_unit = ""
        cell3_sub  = f'<div class="sub">{cur.get("self_top_cat_n", 0)}건 ({cur.get("self_top_cat_pct", 0)}%)</div>'
    else:
        cell3_val, cell3_unit = "—", ""
        cell3_sub = '<div class="sub">자사 부정 리뷰 없음</div>'
    cell3_delta = ""  # 카테고리는 델타 비교 X

    # ④ 경쟁사 정책·사업 이벤트
    cell4_val  = f'{cur.get("comp_events", 0)}'
    cell4_unit = "건"
    top3 = cur.get("comp_top3") or []
    if top3:
        top_str = " · ".join(f"{name} {n}" for name, n in top3)
        cell4_sub = f'<div class="sub">{esc(top_str)}</div>'
    else:
        cell4_sub = '<div class="sub">정책·사업확장 분류 뉴스 없음</div>'
    cell4_delta = d("comp_events", unit="pt")

    # ⑤ 신규 VOC 키워드 비율
    if new_voc and new_voc.get("new_pct") is not None:
        cell5_val  = f'{new_voc["new_pct"]}'
        cell5_unit = "%"
        kws = new_voc.get("new_kws", [])
        kw_str = " · ".join(kws[:3]) if kws else "—"
        cell5_sub = f'<div class="sub">신규 {new_voc["new_n"]}/{new_voc["total"]}개 — {esc(kw_str)}</div>'
    else:
        cell5_val, cell5_unit = "—", ""
        cell5_sub = '<div class="sub">기준 주차 (4주 히스토리 누적 중)</div>'
    cell5_delta = ""

    # ⑥ 보조 — 자사 부정군 평균 별점 (PDF의 '부정군 ★2.1' 자리)
    nas = cur.get("self_neg_avg_star")
    if nas is not None:
        cell6_val  = f'{nas:.1f}'
        cell6_unit = "★"
        cell6_sub  = '<div class="sub">자사 부정 리뷰 평균 별점</div>'
    else:
        cell6_val, cell6_unit = "—", ""
        cell6_sub = '<div class="sub">부정 리뷰 없음</div>'
    cell6_delta = d("self_neg_avg_star", unit="pt")

    cells = [
        ("자사 부정 리뷰율",     cell1_val, cell1_unit, cell1_sub, cell1_delta),
        ("자사 ★ vs 경쟁사 Gap", cell2_val, cell2_unit, cell2_sub, cell2_delta),
        ("부정 톱 카테고리",      cell3_val, cell3_unit, cell3_sub, cell3_delta),
        ("경쟁사 정책·사업 이벤트", cell4_val, cell4_unit, cell4_sub, cell4_delta),
        ("신규 VOC 키워드",      cell5_val, cell5_unit, cell5_sub, cell5_delta),
        ("자사 부정군 평균 ★",    cell6_val, cell6_unit, cell6_sub, cell6_delta),
    ]

    cells_html = ""
    for label, val, unit, sub, delta in cells:
        cells_html += f"""
  <div class="stat">
    <div class="label">{esc(label)}</div>
    <div class="value">{esc(val)}<span class="unit">{esc(unit)}</span></div>
    {sub}
    {delta}
  </div>"""

    return f'<section class="stats" aria-label="Weekly KPIs">{cells_html}\n</section>'


def _pick_representative_review(items: list, top_cat: str | None) -> dict | None:
    """톱 부정 카테고리 + ★1~2 + 본문 30~80자 룰로 자사 대표 부정 리뷰 선정."""
    candidates = []
    for r in items:
        if r.get("service_id") != "moduparking":
            continue
        if r.get("source_type") not in REVIEW_TYPES:
            continue
        if r.get("sentiment") != "negative":
            continue
        star = _parse_star(r.get("title", ""))
        if star is None or star > 2:
            continue
        summary = (r.get("summary") or "").strip()
        if not (30 <= len(summary) <= 200):
            # 너무 짧거나 길면 후순위 (완전 배제는 아님)
            pass
        cat_match = top_cat is None or _classify_subcat(r.get("title", "") + " " + summary) == top_cat
        score = 0
        if cat_match:
            score += 5
        if 30 <= len(summary) <= 200:
            score += 3
        if star == 1:
            score += 2
        candidates.append((score, r))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


def _render_top_story(item: dict | None, items: list, cur_stats: dict) -> str:
    if not item:
        return ""
    title   = esc(item.get("title", "(제목 없음)"))
    svc     = esc(item.get("name_ko", item.get("service_id", "")))
    ct_badge = change_badge(item.get("change_type", ""))
    sent    = item.get("sentiment", "neutral")
    sent_b  = badge_html("NEG", "neg") if sent == "negative" else (badge_html("POS", "pos") if sent == "positive" else "")
    date_s  = esc(item.get("published_at", ""))
    url     = esc(item.get("url", "#"))
    src_type = item.get("source_type", "")
    src_label = "Google Play" if src_type == "appstore" else ("App Store" if src_type == "ios_appstore" else "뉴스")

    # 본문 2단 분할
    words = (item.get("summary") or "").split()
    mid   = max(1, len(words) // 2)
    para1 = esc(" ".join(words[:mid]))
    para2 = esc(" ".join(words[mid:])) if len(words) > mid else ""

    # ── 사이드: 자사 부정 리뷰 분석 (CX팀장 권고) ──
    self_neg_pct  = cur_stats.get("self_neg_pct", 0)
    self_neg_n    = cur_stats.get("self_neg_n", 0)
    self_review_n = cur_stats.get("self_review_n", 0)
    top_cat       = cur_stats.get("self_top_cat")
    top_cat_n     = cur_stats.get("self_top_cat_n", 0)
    top_cat_pct   = cur_stats.get("self_top_cat_pct", 0)
    neg_avg_star  = cur_stats.get("self_neg_avg_star")

    rep = _pick_representative_review(items, top_cat)

    if self_review_n == 0:
        # 자사 리뷰 자체가 없는 주
        side_html = """
    <h4>By the Numbers</h4>
    <div class="kf-empty">이번 주 자사 리뷰 데이터 없음<br><span class="kf-empty-sub">증분 수집 모드로 신규 리뷰만 반영</span></div>"""
    else:
        rep_html = ""
        if rep:
            rep_star = _parse_star(rep.get("title", "")) or 0
            rep_summary = esc((rep.get("summary") or "")[:180])
            rep_date    = esc(rep.get("published_at", ""))
            rep_src     = "Google Play" if rep.get("source_type") == "appstore" else "App Store"
            rep_stars_html = stars_html(float(rep_star)) if rep_star else ""
            rep_html = f"""
    <blockquote class="pullquote">{rep_summary}</blockquote>
    <div class="pullquote-cite">— {esc(rep_src)} {rep_stars_html} · {rep_date}</div>"""
        else:
            rep_html = ""

        cat_block = ""
        if top_cat:
            cat_block = f"""
    <div class="kf-sub">
      <div class="kf-num">{top_cat_n}<span class="kf-unit">건</span> <span class="kf-pct">({top_cat_pct}%)</span></div>
      <div class="kf-sub-cap">부정 톱 카테고리 — <strong>{esc(top_cat)}</strong></div>
    </div>"""

        star_block = ""
        if neg_avg_star is not None:
            star_block = f"""
    <div class="kf-sub">
      <div class="kf-num">★ {neg_avg_star:.1f}</div>
      <div class="kf-sub-cap">부정군 평균 별점 (낮을수록 신랄)</div>
    </div>"""

        side_html = f"""
    <h4>By the Numbers</h4>
    <div class="keyfact">{self_neg_pct}<span class="kf-pct-mark">%</span></div>
    <div class="keyfact-cap">자사 부정 리뷰율 <strong>(n={self_neg_n} / {self_review_n})</strong></div>
    {cat_block}
    {star_block}
    {rep_html}"""

    return f"""
<section class="top-story">
  <article>
    <div class="ts-badges">
      {badge_html("LEAD", "lead")}
      {badge_html("TOP STORY", "top")}
      {ct_badge}
      {sent_b}
    </div>
    <div class="ts-meta">
      <span>{esc(svc)}</span>
      <span class="sep">·</span>
      <span>{esc(src_label)}</span>
      <span class="sep">·</span>
      <span>{date_s}</span>
    </div>
    <h2 class="ts-headline"><a href="{url}" target="_blank" rel="noopener">{title}</a></h2>
    <p class="ts-sub">이번 주 가장 주목받은 경쟁사 뉴스. 우측 사이드는 자사 리뷰 분석입니다.</p>
    <div class="ts-body">
      <p>{para1}</p>
      {'<p>' + para2 + '</p>' if para2 else ''}
    </div>
  </article>
  <aside class="ts-side">{side_html}
  </aside>
</section>"""


def render_league(league: list, year: int, week_num: int) -> str:
    if not league:
        return "<p style='color:var(--muted);font-size:13px;'>이번 주 리뷰 데이터 없음</p>"

    modu = next((r for r in league if r["service_id"] == "moduparking"), None)
    modu_rank = next((i + 1 for i, r in enumerate(league) if r["service_id"] == "moduparking"), None)
    modu_pos_str = f"업계 {modu_rank}위 유지" if modu_rank else ""

    rows_html = ""
    for rank, row in enumerate(league, 1):
        is_self = row["service_id"] == "moduparking"
        rank_cls = "self" if is_self else (f"rank-{rank}" if rank == 1 else "")
        row_cls  = f"league-row {rank_cls}".strip()
        bar_w    = round(row["avg"] / 5 * 100)
        name_badge = '<span class="badge" style="font-size:9px;padding:1px 6px;margin-left:6px;border-color:var(--cyan-500);color:var(--cyan-600);background:#fff;">OUR APP</span>' if is_self else ""
        meta = f'리뷰 {row["review_count"]:,}건 (기간 내)'
        delta_cls = ""
        delta_str = ""
        rows_html += f"""
<div class="{esc(row_cls)}">
  <div class="rank">{rank}</div>
  <div>
    <div class="name">{esc(row['name_ko'])} {name_badge}</div>
    <div class="meta-line"><span>{meta}</span></div>
    <div class="bar-wrap"><div class="bar" style="width:{bar_w}%"></div></div>
  </div>
  <div>
    <div class="score"><span class="star">★</span> {row['avg']:.2f}</div>
    <div class="delta-mini {delta_cls}">{esc(delta_str)}</div>
  </div>
</div>"""

    callout = ""
    if modu:
        gap_str = ""
        if len(league) > 1:
            others = [r for r in league if r["service_id"] != "moduparking"]
            if others:
                nearest = min(others, key=lambda r: abs(r["avg"] - modu["avg"]))
                diff = modu["avg"] - nearest["avg"]
                gap_str = f'격차 {diff:+.2f}pt (vs. {esc(nearest["name_ko"])})'
        callout = f"""
<div class="self-callout">
  <span><span class="you">모두의주차장</span> {esc(modu_pos_str)}</span>
  <span>{esc(gap_str)}</span>
</div>"""

    return f"""
<h3>주차 앱 평점 리그</h3>
<div class="byline-inline" style="margin:6px 0 10px;">
  <span class="av">C</span>
  <span class="by" style="font-family:'Noto Serif KR',serif;font-style:italic;text-transform:none;letter-spacing:.04em;color:var(--muted);">집계 ·</span>
  <span class="nm">카니 기자</span>
  <span>· DATA DESK</span>
</div>
<div class="col-deck">기간 내 수집된 리뷰 기준 평균 평점 · ★ 5점 만점</div>
<div class="league-list">{rows_html}</div>
{callout}"""


def render_dispatch(svc_rows: list) -> str:
    if not svc_rows:
        return "<p style='color:var(--muted);font-size:13px;'>데이터 없음</p>"
    rows_html = ""
    for row in svc_rows:
        is_self = row["service_id"] == "moduparking"
        tr_cls  = "self" if is_self else ""
        total   = row["total"]
        neg_pct = round(row["neg"] / max(total, 1) * 100, 1)
        pos_pct = round(row["pos"] / max(total, 1) * 100, 1)
        neu_pct = max(0, 100 - neg_pct - pos_pct)
        rate_cls = neg_rate_class(neg_pct)
        svc_name_cls = "svc self" if is_self else "svc"
        rows_html += f"""
<tr class="{esc(tr_cls)}">
  <td class="{esc(svc_name_cls)}">{esc(row['name_ko'])}</td>
  <td class="num">{total:,}</td>
  <td class="num">{row['reviews']:,}</td>
  <td class="num">{row['news']:,}</td>
  <td><span class="mix">
    <span class="pos" style="width:{pos_pct}%"></span>
    <span class="neu" style="width:{neu_pct}%"></span>
    <span class="neg" style="width:{neg_pct}%"></span>
  </span></td>
  <td class="num"><span class="neg-rate {esc(rate_cls)}">{neg_pct}%</span></td>
</tr>"""

    return f"""
<h3>서비스 디스패치</h3>
<div class="byline-inline" style="margin:6px 0 10px;">
  <span class="av">C</span>
  <span style="font-family:'Noto Serif KR',serif;font-style:italic;text-transform:none;letter-spacing:.04em;color:var(--muted);">집계 ·</span>
  <span class="nm">카니 기자</span>
  <span>· DATA DESK</span>
</div>
<div class="col-deck">이번 주 모니터링 대상 서비스별 데이터 수집 및 감성 분포</div>
<table>
  <thead>
    <tr>
      <th>서비스</th>
      <th class="num">수집</th>
      <th class="num">리뷰</th>
      <th class="num">뉴스</th>
      <th>감성 분포</th>
      <th class="num">부정률</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>"""


def render_keyword_cloud(kws: list, label: str, sample_n: int, vol_tag: str) -> str:
    if not kws:
        return "<p style='color:var(--muted);font-size:13px;padding:20px 0;'>키워드 없음</p>"
    max_cnt = max(k["cnt"] for k in kws) if kws else 1
    cloud_html = ""
    for kw in kws:
        sz  = kw_size_class(kw["cnt"], max_cnt)
        sev = kw["sev"]
        cnt = kw["cnt"]
        cloud_html += (
            f'<span class="kw {esc(sev)} {esc(sz)}">{esc(kw["word"])}'
            f'<span class="cnt">{cnt}</span></span>\n'
        )

    # Summary
    total_sents = sum(kw["cnt"] for kw in kws)
    neg_kws = sum(kw["cnt"] for kw in kws if kw["sev"] in ("sev-1", "sev-2"))
    pos_kws = sum(kw["cnt"] for kw in kws if kw["sev"] == "sev-4")
    neu_kws = total_sents - neg_kws - pos_kws
    neg_pct = round(neg_kws / max(total_sents, 1) * 100)
    pos_pct = round(pos_kws / max(total_sents, 1) * 100)
    neu_pct = 100 - neg_pct - pos_pct

    return f"""
<div class="kwmap-head">
  <h3>{esc(label)}</h3>
  <span class="sample">표본 {sample_n:,}건 · {esc(vol_tag)}</span>
</div>
<div class="col-deck">한국어 형태소 분석으로 명사·인접 복합어 추출. 글자 크기 = 빈출 횟수.</div>
<div class="cloud" aria-label="{esc(label)} 키워드 클라우드">
{cloud_html}</div>
<div class="kw-summary">
  <span><strong>NEG {neg_pct}%</strong></span>
  <span><strong>NEU {neu_pct}%</strong></span>
  <span><strong>POS {pos_pct}%</strong></span>
</div>"""


def render_voc_brief(items: list) -> str:
    reviews = pick_notable_reviews(items)
    if not reviews:
        return "<p style='color:var(--muted);font-size:13px;'>이번 주 리뷰 없음</p>"

    cards = ""
    for item in reviews:
        is_self = item.get("service_id") == "moduparking"
        svc_name = esc(item.get("name_ko", item.get("service_id", "")))
        svc_cls  = "voc-svc self" if is_self else "voc-svc"
        sent     = item.get("sentiment", "neutral")
        card_cls = "voc-card neg" if sent == "negative" else "voc-card pos"
        sent_b   = badge_html("NEG", "neg") if sent == "negative" else badge_html("POS", "pos")
        summary  = esc((item.get("summary") or "")[:200])
        date_s   = esc(item.get("published_at", ""))
        src_type = item.get("source_type", "")
        platform = "Google Play" if src_type == "appstore" else ("App Store" if src_type == "ios_appstore" else "")
        url      = esc(item.get("url", "#"))

        rating_val = item.get("rating") or item.get("score")
        star_html  = stars_html(float(rating_val) if rating_val else None)

        # Extract hashtags from keywords in text
        text = item.get("title", "") + " " + (item.get("summary") or "")
        pattern = re.compile(r"[가-힣]{2,6}")
        raw_words = pattern.findall(text)
        tags = [w for w in raw_words[:6] if w not in KO_STOPWORDS][:3]
        tags_html = "".join(f'<span class="tag">#{esc(t)}</span>' for t in tags)

        cards += f"""
<div class="{card_cls}">
  <div class="voc-head">
    <div class="left">
      <span class="{svc_cls}">{svc_name}</span>
      {star_html}
      {sent_b}
    </div>
    <span class="voc-date">{date_s}{' · ' + platform if platform else ''}</span>
  </div>
  <p class="voc-quote">{summary}</p>
  <div class="voc-foot">{tags_html}</div>
</div>"""

    return f"""
<h3>VOC 브리프</h3>
<div class="col-deck">자사 및 경쟁사 리뷰 — 부정·긍정 시그널 큐레이션</div>
<div class="voc-list">{cards}</div>"""


def _wire_importance(rank: int) -> tuple:
    """Wire 순위 기반 중요도 — (label, css_cls) 반환. 상위 2건=★HOT, 3~5건=주목, 나머지=—."""
    if rank <= 2:
        return "★ HOT", "hot"
    if rank <= 5:
        return "주목", "watch"
    return "—", "none"


def render_wire(items: list) -> str:
    briefs = pick_news_briefs(items, n=8)
    if not briefs:
        return "<p style='color:var(--muted);font-size:13px;'>이번 주 경쟁사 뉴스 없음</p>"

    items_html = ""
    for idx, item in enumerate(briefs, 1):
        title  = esc(item.get("title", ""))
        url    = esc(item.get("url", "#"))
        svc    = esc(item.get("name_ko", item.get("service_id", "")))
        ct_b   = change_badge(item.get("change_type", ""))
        date_s = esc(item.get("published_at", ""))
        src_type = item.get("source_type", "")
        src_label = "뉴스" if src_type in ("news", "rss") else "블로그"
        imp_label, imp_cls = _wire_importance(idx)
        items_html += f"""
<div class="wire-item">
  <div class="wire-num">{idx:02d}</div>
  <div>
    <h4 class="wire-headline"><a href="{url}" target="_blank" rel="noopener">{title}</a></h4>
    <div class="wire-meta">
      <span class="src">{esc(svc)}</span>
      {ct_b}
      <span>{esc(src_label)}</span>
    </div>
  </div>
  <div class="wire-side">
    <span class="date">{date_s}</span>
    <span class="imp imp-{imp_cls}">{esc(imp_label)}</span>
  </div>
</div>"""

    return f"""
<h3>컴페티터 와이어</h3>
<div class="byline-inline" style="margin:6px 0 10px;">
  <span class="av">M</span>
  <span style="font-family:'Noto Serif KR',serif;font-style:italic;text-transform:none;letter-spacing:.04em;color:var(--muted);">취재 ·</span>
  <span class="nm">모카 기자</span>
  <span>· NEWS DESK</span>
</div>
<div class="col-deck">이번 주 업계 보도 — 사업확장 · 정책 · 기술</div>
<div class="wire-list">{items_html}</div>"""


def render_sources(from_dt: date, to_dt: date, total: int, year: int, week_num: int) -> str:
    """Sources / Coverage / Newsroom — PDF 디자인 일치."""
    next_week = week_num + 1
    next_yr   = year
    if next_week > 52:
        next_yr, next_week = year + 1, 1
    return f"""
<div class="sources">
  <div class="src-block">
    <h5>Sources &amp; Methodology</h5>
    <p>리뷰 데이터는 Google Play / App Store 공개 리뷰를 자체 크롤러가 수집하며, 뉴스는 네이버 뉴스·블로그 검색 API와 Google News RSS를 통해 집계됩니다. 변경 유형·감성 분류는 키워드 기반 자동 분류기를 사용하며, 부정·중립·긍정 3분류로 라벨링됩니다.</p>
  </div>
  <div class="src-block">
    <h5>Coverage</h5>
    <ul class="src-list">
      <li><span class="kw-label">자사</span> 모두의주차장</li>
      <li><span class="kw-label">경쟁사</span> 카카오T 주차 · Tmap 주차 · 아이파킹 · 나이스파크 · 하이파킹(투루파킹) · 파킹프렌즈 · 주만사</li>
      <li><span class="kw-label">B2B</span> 아마노코리아 · 케이엠파크 · 파킹클라우드 · SK쉴더스</li>
    </ul>
  </div>
  <div class="src-block">
    <h5>Newsroom</h5>
    <ul class="src-list">
      <li><span class="kw-label">Newsroom</span> <strong>모두컴퍼니 CX팀</strong></li>
      <li><span class="kw-label">Data Desk</span> 카니 기자 · <span class="kw-label">News Desk</span> 모카 기자</li>
      <li><span class="kw-label">Next Issue</span> {next_yr:02d}Y {next_week}W (자동 발행)</li>
      <li><span class="kw-label">Contact</span> cx-newsroom@moducompany.com</li>
    </ul>
  </div>
  <div class="colophon">
    <span class="logo"><span class="the">The</span> Parking <span>Gazette</span></span>
    <span>© {to_dt.year} Modu Company · Weekly Edition · Auto-Published Every Monday 11:15 KST</span>
    <span class="signoff">— 30 —</span>
  </div>
</div>"""


# ─────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────

CSS = """
:root {
  /* 브라운 페이퍼 베이스 + 좋은=파랑, 안좋은=빨강 시맨틱 */
  --ink: #0b0b0c;
  --ink-2: #1f2024;
  --muted: #6b6055;        /* 브라운 톤 muted */
  --rule: #0b0b0c;
  --paper: #ebe1cf;        /* 브라운 페이퍼 (warmer) */
  --paper-2: #ddd0b9;      /* 더 진한 브라운 (footer) */
  --card: #faf6ed;         /* 카드 배경 — 살짝 따뜻 */
  --slate-50: #f3eee4;     /* 슬레이트 변형 — 브라운 톤 */
  --slate-100: #ebe5d8;
  --slate-200: #d8cfbe;
  --slate-300: #b9ad97;
  --slate-500: #6c6555;
  --slate-700: #38322a;
  --slate-900: #14110d;
  --blue-700: #1d4ed8;     /* 좋은 신호 (POS / 자사 강점) */
  --blue-800: #1e3a8a;
  --blue-50:  #dbeafe;
  --cyan-500: #06b6d4;
  --cyan-600: #0891b2;
  --cyan-50:  #ecfeff;
  --red-600:  #dc2626;     /* 안좋은 신호 (NEG / VOC 부정) */
  --red-50:   #fef2f2;
  /* 좋은 신호도 파란색으로 통일 (사용자 요청) */
  --emerald-600: #1d4ed8;
  --emerald-50:  #dbeafe;
  --amber-500: #c08840;    /* 브라운 톤 앰버 */
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: "IBM Plex Sans KR", system-ui, sans-serif;
  background: var(--paper);
  color: var(--ink);
  font-feature-settings: "ss01","tnum";
  -webkit-font-smoothing: antialiased;
  line-height: 1.45;
  padding: 28px 28px 80px;
}
body::before {
  content: "";
  position: fixed; inset: 0;
  background:
    radial-gradient(circle at 20% 30%, rgba(0,0,0,.025), transparent 60%),
    radial-gradient(circle at 80% 70%, rgba(0,0,0,.02), transparent 60%);
  pointer-events: none; z-index: 0;
}
.paper {
  position: relative; z-index: 1;
  max-width: 1280px;
  margin: 0 auto;
  background: var(--card);
  border: 2px solid var(--ink);
  box-shadow: 0 1px 0 var(--ink), 0 24px 60px -28px rgba(0,0,0,.35);
}
a { color: var(--blue-700); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ARCHIVE NAV */
.archive-nav {
  background: var(--ink);
  color: #d8dbe0;
  border-bottom: 2px solid var(--ink);
  font-family: "IBM Plex Mono", monospace;
  font-size: 11px;
  letter-spacing: .1em;
  text-transform: uppercase;
}
.archive-top {
  display: flex; align-items: center; gap: 14px;
  padding: 8px 18px;
  border-bottom: 1px solid #2a2c33;
  flex-wrap: wrap;
}
.archive-top .arch-label { color: #fff; font-weight: 600; letter-spacing: .2em; padding-right: 14px; border-right: 1px solid #2a2c33; white-space: nowrap; }
.archive-top .breadcrumb { color: #9aa0aa; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; min-width: 0; }
.archive-top .breadcrumb .now { color: #fff; background: var(--red-600); padding: 2px 8px; letter-spacing: .14em; font-weight: 600; white-space: nowrap; }
.archive-top .breadcrumb .sep { color: #4a4d55; }
.archive-top .meta { margin-left: auto; color: #9aa0aa; display: flex; gap: 14px; white-space: nowrap; flex-shrink: 0; }
.archive-top .meta .yr { cursor: pointer; padding: 2px 6px; }
.archive-top .meta .yr:hover { color: #fff; }
.archive-top .meta .yr.active { color: #fff; border: 1px solid #fff; }
.archive-bottom { display: grid; grid-template-columns: auto 1fr; align-items: stretch; padding: 8px 18px 10px; }
.tree-label { display: flex; align-items: center; gap: 6px; color: #9aa0aa; padding-right: 14px; border-right: 1px solid #2a2c33; margin-right: 14px; }
.tree-label .glyph { color: #6a6d75; font-family: "IBM Plex Mono", monospace; }
.week-tabs { display: flex; gap: 5px; overflow-x: auto; align-items: center; scrollbar-width: thin; }
.week-tabs::-webkit-scrollbar { height: 4px; }
.week-tabs::-webkit-scrollbar-thumb { background: #2a2c33; }
.week-pill { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; background: #15171c; border: 1px solid #2a2c33; color: #888c95; text-decoration: none; white-space: nowrap; font-size: 11px; font-weight: 500; letter-spacing: .08em; cursor: pointer; transition: all .12s ease; }
.week-pill:hover { color: #fff; border-color: #4a4d55; background: #1f2127; }
.week-pill.live { background: var(--card); color: var(--ink); border-color: #fff; font-weight: 700; }
.week-pill.live::before { content: ""; width: 6px; height: 6px; background: var(--red-600); border-radius: 50%; animation: pulse 1.4s ease-in-out infinite; }
.week-pill.scheduled { border-style: dashed; border-color: #2a2c33; color: #5a5d65; }
.week-pill .lbl { font-family: "IBM Plex Mono", monospace; }
@keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: .55; transform: scale(.85); } }

/* BYLINE */
.byline { display: inline-flex; align-items: center; gap: 8px; padding: 5px 10px 5px 5px; background: var(--paper); border: 1px solid var(--ink); font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: .12em; text-transform: uppercase; color: var(--ink); }
.byline .avatar { width: 22px; height: 22px; background: var(--ink); color: #fff; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-family: "Playfair Display", serif; font-style: italic; font-weight: 900; font-size: 12px; }
.byline .name { font-weight: 700; }
.byline .role { color: var(--muted); }
.byline-inline { display: inline-flex; align-items: center; gap: 6px; font-family: "IBM Plex Mono", monospace; font-size: 10px; color: var(--muted); letter-spacing: .12em; text-transform: uppercase; }
.byline-inline .av { width: 14px; height: 14px; background: var(--ink); color: #fff; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-family: "Playfair Display", serif; font-style: italic; font-weight: 900; font-size: 9px; }
.byline-inline .nm { color: var(--ink); font-weight: 700; }
.byline-inline .by { color: var(--muted); font-style: italic; text-transform: none; letter-spacing: .04em; }

/* MASTHEAD */
.masthead { border-bottom: 2px solid var(--ink); padding: 18px 32px 22px; background: var(--card); }
.masthead-top { display: flex; justify-content: space-between; align-items: center; font-family: "IBM Plex Mono", monospace; font-size: 11px; letter-spacing: .14em; text-transform: uppercase; color: var(--ink-2); padding-bottom: 10px; border-bottom: 1px solid var(--ink); }
.masthead-top .left, .masthead-top .right { display: flex; gap: 18px; align-items: center; }
.dot { width: 6px; height: 6px; background: var(--red-600); border-radius: 50%; display: inline-block; margin-right: 6px; vertical-align: middle; }
.masthead-title { text-align: center; padding: 14px 0 6px; }
.masthead-title h1 { font-family: "Playfair Display", "Noto Serif KR", serif; font-weight: 900; font-size: clamp(48px, 8vw, 104px); line-height: .92; letter-spacing: -.01em; margin: 0; }
.masthead-title h1 .the { font-family: "Playfair Display", serif; font-style: italic; font-weight: 400; font-size: .42em; vertical-align: top; margin-right: 14px; letter-spacing: .04em; }
.masthead-tag { font-family: "Noto Serif KR", serif; font-weight: 400; font-style: italic; color: var(--muted); margin-top: 8px; font-size: 14px; letter-spacing: .02em; }
.masthead-meta { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--ink); border-bottom: 4px double var(--ink); padding-bottom: 12px; display: grid; grid-template-columns: 1fr auto 1fr; gap: 18px; align-items: center; font-family: "IBM Plex Mono", monospace; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--ink-2); }
.masthead-meta .center { text-align: center; }
.masthead-meta .right { text-align: right; }
.week-badge { display: inline-flex; align-items: baseline; gap: 6px; background: var(--ink); color: #fff; padding: 4px 10px; font-family: "IBM Plex Mono", monospace; font-weight: 600; font-size: 12px; letter-spacing: .12em; white-space: nowrap; }
.week-badge .num { font-size: 14px; white-space: nowrap; }
.coverage { font-family: "Noto Serif KR", serif; font-style: italic; font-weight: 500; font-size: 13px; letter-spacing: .04em; text-transform: none; }

/* STATS — 2×3 그리드 + 한 줄 강제 + 폰트 축소 */
.stats { display: grid; grid-template-columns: repeat(2, 1fr); border-bottom: 2px solid var(--ink); background: var(--card); }
.stat { padding: 18px 22px 16px; border-right: 1px solid var(--ink); border-bottom: 1px solid var(--ink); background: var(--card); position: relative; min-height: 92px; overflow: hidden; }
.stat:nth-child(2n) { border-right: none; }
.stat:nth-last-child(-n+2) { border-bottom: none; }
.stat .label { font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: .18em; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; white-space: nowrap; }
.stat .value { font-family: "Playfair Display", serif; font-weight: 900; font-size: 34px; line-height: 1.1; letter-spacing: -.02em; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stat .value .unit { font-family: "IBM Plex Sans KR", sans-serif; font-weight: 500; font-size: 13px; margin-left: 4px; color: var(--muted); }
.stat .sub { margin-top: 6px; font-family: "IBM Plex Sans KR", sans-serif; font-size: 11.5px; color: var(--ink-2); line-height: 1.35; letter-spacing: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stat .delta { margin-top: 6px; font-family: "IBM Plex Mono", monospace; font-size: 10.5px; color: var(--muted); display: flex; align-items: center; gap: 5px; letter-spacing: .04em; white-space: nowrap; }
.delta.up { color: var(--emerald-600); }
.delta.down { color: var(--red-600); }
.delta .arrow { font-weight: 700; font-size: 12px; }
.spark { position: absolute; right: 22px; top: 22px; opacity: .8; width: 110px; height: 36px; }

/* TOP STORY */
.top-story { padding: 28px 32px 32px; border-bottom: 2px solid var(--ink); display: grid; grid-template-columns: 1.5fr 1fr; gap: 36px; background: var(--card); }
.ts-badges { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
.badge { display: inline-flex; align-items: center; padding: 3px 9px; font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: .14em; text-transform: uppercase; font-weight: 600; border-radius: 999px; border: 1px solid var(--ink); background: var(--card); color: var(--ink); }
.badge.lead { background: var(--ink); color: #fff; }
.badge.top  { background: var(--red-600); color: #fff; border-color: var(--red-600); }
.badge.voc  { background: var(--cyan-50); color: var(--cyan-600); border-color: var(--cyan-500); }
.badge.tech { background: #f5f3ff; color: #6d28d9; border-color: #6d28d9; }
.badge.policy { background: #fef9c3; color: #854d0e; border-color: #854d0e; }
.badge.biz  { background: #fff1f2; color: #be123c; border-color: #be123c; }
.badge.partner { background: #ecfeff; color: var(--blue-700); border-color: var(--blue-700); }
.badge.neg  { background: var(--red-50); color: var(--red-600); border-color: var(--red-600); }
.badge.pos  { background: var(--emerald-50); color: var(--emerald-600); border-color: var(--emerald-600); }
.ts-meta { font-family: "IBM Plex Mono", monospace; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); margin-bottom: 12px; display: flex; gap: 14px; align-items: center; }
.ts-meta .sep { color: var(--slate-300); }
.ts-headline { font-family: "Noto Serif KR", "Playfair Display", serif; font-weight: 900; font-size: 38px; line-height: 1.08; letter-spacing: -.02em; margin: 0 0 14px; color: var(--ink); }
.ts-headline a { color: inherit; text-decoration: none; }
.ts-headline a:hover { color: var(--blue-700); }
.ts-sub { font-family: "Noto Serif KR", serif; font-style: italic; font-weight: 400; font-size: 16px; color: var(--slate-700); margin: 0 0 18px; line-height: 1.5; }
.ts-body { font-family: "Noto Serif KR", serif; font-size: 15px; line-height: 1.7; color: var(--ink-2); column-count: 2; column-gap: 24px; column-rule: 1px solid var(--slate-200); }
.ts-body p { margin: 0 0 12px; }
.ts-body p:first-child::first-letter { font-family: "Playfair Display", serif; font-weight: 900; font-size: 56px; float: left; line-height: .9; padding: 4px 8px 0 0; color: var(--blue-700); }
.ts-side { border-left: 1px solid var(--ink); padding-left: 28px; }
.ts-side h4 { font-family: "IBM Plex Mono", monospace; font-size: 11px; letter-spacing: .16em; text-transform: uppercase; margin: 0 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--ink); }
.keyfact { font-family: "Playfair Display", serif; font-weight: 900; font-size: 64px; line-height: 1; margin: 0 0 4px; color: var(--red-600); }
.keyfact .kf-pct-mark { font-family: "IBM Plex Sans KR", sans-serif; font-weight: 500; font-size: 28px; margin-left: 4px; color: var(--red-600); }
.keyfact-cap { font-family: "Noto Serif KR", serif; font-size: 13px; color: var(--muted); margin-bottom: 16px; }
.keyfact-cap strong { color: var(--ink); font-weight: 700; }
.kf-sub { margin: 12px 0; padding: 8px 0; border-top: 1px dashed var(--slate-200); }
.kf-sub:first-of-type { border-top: 1px solid var(--ink); padding-top: 12px; margin-top: 14px; }
.kf-num { font-family: "Playfair Display", serif; font-weight: 900; font-size: 26px; line-height: 1; color: var(--ink); }
.kf-num .kf-unit { font-family: "IBM Plex Sans KR", sans-serif; font-weight: 500; font-size: 13px; margin-left: 3px; color: var(--muted); }
.kf-num .kf-pct { font-family: "IBM Plex Mono", monospace; font-weight: 500; font-size: 13px; color: var(--muted); margin-left: 4px; }
.kf-sub-cap { font-family: "Noto Serif KR", serif; font-size: 12px; color: var(--muted); margin-top: 4px; }
.kf-sub-cap strong { color: var(--ink); font-weight: 700; }
.kf-empty { font-family: "Noto Serif KR", serif; font-size: 14px; color: var(--muted); padding: 24px 0; text-align: center; line-height: 1.6; }
.kf-empty-sub { font-size: 11px; color: var(--slate-300); }
.pullquote { font-family: "Noto Serif KR", serif; font-style: italic; font-weight: 500; font-size: 17px; line-height: 1.45; color: var(--ink); padding: 14px 0 12px; border-top: 4px double var(--ink); border-bottom: 1px solid var(--ink); margin: 18px 0 10px; position: relative; }
.pullquote::before { content: "“"; font-family: "Playfair Display", serif; font-size: 56px; line-height: .6; color: var(--blue-700); margin-right: 4px; vertical-align: -10px; }
.pullquote-cite { font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); }

/* SECTION ROW */
.section-row { display: grid; grid-template-columns: 1fr 1fr; border-bottom: 2px solid var(--ink); }
.section-row > .col { border-right: 1px solid var(--ink); background: var(--card); }
.section-row > .col:last-child { border-right: none; }
.col-head { background: var(--ink); color: #fff; padding: 10px 16px; display: flex; justify-content: space-between; align-items: center; font-family: "IBM Plex Mono", monospace; font-size: 11px; letter-spacing: .18em; text-transform: uppercase; }
.col-head .name { font-weight: 600; }
.col-head .kicker { font-family: "Noto Serif KR", serif; font-style: italic; font-weight: 400; letter-spacing: .02em; text-transform: none; font-size: 12px; color: #cfd3da; }
.col-body { padding: 18px 20px 22px; }

/* APP LEAGUE */
.league h3, .dispatch h3, .voc h3, .wire h3 { font-family: "Playfair Display", "Noto Serif KR", serif; font-weight: 900; font-size: 22px; margin: 0 0 4px; letter-spacing: -.01em; }
.col-deck { font-family: "Noto Serif KR", serif; font-style: italic; color: var(--muted); font-size: 13px; margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px solid var(--slate-200); }
.league-list { display: flex; flex-direction: column; gap: 10px; }
.league-row { display: grid; grid-template-columns: 28px 1fr auto; align-items: center; gap: 12px; padding: 10px 12px; border: 1px solid var(--slate-200); background: var(--card); position: relative; }
.league-row.self { border: 2px solid var(--cyan-500); background: var(--cyan-50); }
.league-row .rank { font-family: "Playfair Display", serif; font-weight: 900; font-size: 22px; color: var(--ink); text-align: center; }
.league-row.self .rank { color: var(--cyan-600); }
.league-row.rank-1 .rank { color: var(--amber-500); }
.league-row .name { font-family: "IBM Plex Sans KR", sans-serif; font-weight: 600; font-size: 14px; }
.league-row .bar-wrap { margin-top: 5px; height: 6px; background: var(--slate-100); border-radius: 999px; overflow: hidden; }
.league-row .bar { height: 100%; background: var(--ink); border-radius: 999px; }
.league-row.self .bar { background: var(--cyan-500); }
.league-row.rank-1 .bar { background: var(--amber-500); }
.league-row .meta-line { display: flex; gap: 8px; align-items: baseline; font-family: "IBM Plex Mono", monospace; font-size: 11px; color: var(--muted); margin-top: 4px; }
.league-row .score { font-family: "Playfair Display", serif; font-weight: 900; font-size: 20px; line-height: 1; color: var(--ink); text-align: right; }
.league-row.self .score { color: var(--cyan-600); }
.league-row .star { color: var(--amber-500); }
.league-row .delta-mini { font-family: "IBM Plex Mono", monospace; font-size: 10px; margin-top: 4px; text-align: right; color: var(--muted); }
.delta-mini.up { color: var(--emerald-600); }
.delta-mini.down { color: var(--red-600); }
.self-callout { margin-top: 14px; padding: 10px 12px; background: var(--ink); color: #fff; display: flex; justify-content: space-between; align-items: center; font-family: "IBM Plex Mono", monospace; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; }
.self-callout .you { color: var(--cyan-500); font-weight: 600; }

/* DISPATCH */
.dispatch table { width: 100%; border-collapse: collapse; font-family: "IBM Plex Sans KR", sans-serif; font-size: 13px; }
.dispatch th { text-align: left; font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); padding: 8px 6px; border-bottom: 1px solid var(--ink); font-weight: 500; }
.dispatch th.num, .dispatch td.num { text-align: right; font-variant-numeric: tabular-nums; }
.dispatch td { padding: 11px 6px; border-bottom: 1px solid var(--slate-100); vertical-align: middle; }
.dispatch tr.self td { background: var(--cyan-50); }
.dispatch tr.self td:first-child { border-left: 3px solid var(--cyan-500); padding-left: 9px; }
.dispatch .svc { font-weight: 600; }
.dispatch tr.self .svc { color: var(--cyan-600); }
.dispatch .mix { display: inline-flex; height: 6px; width: 80px; background: var(--slate-100); border-radius: 99px; overflow: hidden; }
.mix .pos { background: var(--emerald-600); }
.mix .neu { background: var(--slate-300); }
.mix .neg { background: var(--red-600); }
.neg-rate { font-family: "IBM Plex Mono", monospace; font-weight: 600; }
.neg-rate.high { color: var(--red-600); }
.neg-rate.mid  { color: var(--amber-500); }
.neg-rate.low  { color: var(--emerald-600); }

/* KEYWORD MAP */
.kwmap-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }
.kwmap-head h3 { margin: 0; }
.kwmap-head .sample { font-family: "IBM Plex Mono", monospace; font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.cloud { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: center; gap: 14px 22px; padding: 28px 8px 32px; min-height: 240px; background: var(--card); border-top: 1px dashed var(--slate-200); border-bottom: 1px dashed var(--slate-200); margin-bottom: 14px; position: relative; }
.cloud::before { content: ""; position: absolute; inset: 0; background-image: radial-gradient(circle at 15% 25%, rgba(29,78,216,.04), transparent 40%), radial-gradient(circle at 85% 75%, rgba(220,38,38,.035), transparent 40%); pointer-events: none; }
.kw { font-family: "IBM Plex Sans KR", sans-serif; font-weight: 700; line-height: 1; letter-spacing: -.01em; display: inline-flex; align-items: center; transition: transform .15s ease; cursor: default; }
.kw:hover { transform: translateY(-1px) scale(1.04); }
.kw .cnt { font-family: "IBM Plex Mono", monospace; font-size: 10px; font-weight: 500; color: var(--muted); margin-left: 4px; align-self: flex-start; margin-top: 2px; letter-spacing: .04em; }
.kw.sev-1 { background: #fde2e2; color: #991b1b; padding: 6px 14px; border-radius: 6px; font-weight: 800; }
.kw.sev-1 .cnt { color: #b91c1c; }
.kw.sev-2 { color: var(--red-600); }
.kw.sev-3 { color: var(--slate-500); font-weight: 600; }
.kw.sev-4 { background: #dbeafe; color: #1e40af; padding: 6px 14px; border-radius: 6px; font-weight: 800; }
.kw.sev-4 .cnt { color: #1d4ed8; }
.kw.s-xl { font-size: 46px; }
.kw.s-lg { font-size: 34px; }
.kw.s-md { font-size: 24px; }
.kw.s-sm { font-size: 17px; }
.kw.s-xs { font-size: 13px; }
.kw-legend { display: flex; flex-wrap: wrap; gap: 14px; padding: 10px 12px; background: var(--slate-50); border: 1px solid var(--slate-200); font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--slate-700); justify-content: center; }
.kw-legend .item { display: inline-flex; align-items: center; gap: 6px; }
.kw-legend .swatch { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
.sw-1 { background: #fde2e2; border: 1px solid #fca5a5; }
.sw-2 { background: var(--red-600); }
.sw-3 { background: var(--slate-500); }
.sw-4 { background: #dbeafe; border: 1px solid #93c5fd; }
.kw-summary { display: flex; gap: 14px; margin-top: 12px; font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); justify-content: center; }
.kw-summary strong { color: var(--ink); font-weight: 600; }

/* VOC */
.voc-list { display: flex; flex-direction: column; gap: 12px; }
.voc-card { padding: 14px 16px; background: var(--card); border: 1px solid var(--slate-200); border-left-width: 4px; }
.voc-card.neg { border-left-color: var(--red-600); }
.voc-card.pos { border-left-color: var(--emerald-600); }
.voc-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; gap: 8px; }
.voc-head .left { display: flex; gap: 8px; align-items: center; }
.voc-svc { font-family: "IBM Plex Mono", monospace; font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: var(--ink-2); font-weight: 600; }
.voc-svc.self { color: var(--cyan-600); }
.voc-stars { color: var(--amber-500); font-size: 12px; letter-spacing: 1px; }
.voc-stars .off { color: var(--slate-300); }
.voc-date { font-family: "IBM Plex Mono", monospace; font-size: 10px; color: var(--muted); letter-spacing: .08em; }
.voc-quote { font-family: "Noto Serif KR", serif; font-size: 14px; line-height: 1.55; color: var(--ink); margin: 0; }
.voc-foot { margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap; }
.tag { font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: .1em; text-transform: uppercase; padding: 2px 7px; background: var(--slate-100); color: var(--slate-700); border-radius: 2px; }

/* WIRE */
.wire-list { display: flex; flex-direction: column; }
.wire-item { display: grid; grid-template-columns: 56px 1fr auto; gap: 14px; padding: 12px 0; border-bottom: 1px dashed var(--slate-200); align-items: start; }
.wire-item:last-child { border-bottom: none; }
.wire-num { font-family: "Playfair Display", serif; font-weight: 900; font-size: 28px; line-height: 1; color: var(--slate-300); }
.wire-headline { font-family: "Noto Serif KR", serif; font-weight: 700; font-size: 15px; line-height: 1.35; margin: 0 0 6px; color: var(--ink); }
.wire-headline a { color: inherit; text-decoration: none; border-bottom: 1px solid transparent; }
.wire-headline a:hover { border-bottom-color: var(--ink); }
.wire-meta { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.wire-meta .src { color: var(--blue-700); font-weight: 600; }
.wire-side { text-align: right; font-family: "IBM Plex Mono", monospace; font-size: 10px; color: var(--muted); display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
.wire-side .date { display: block; }
.wire-side .imp { font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: .1em; font-weight: 600; }
.wire-side .imp-hot   { color: var(--red-600); }
.wire-side .imp-watch { color: var(--blue-700); }
.wire-side .imp-none  { color: var(--slate-300); }

/* SOURCES / FOOTER — PDF 디자인 일치 */
.sources { padding: 22px 32px 24px; background: var(--paper-2); color: var(--ink-2); display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 32px; border-top: 4px double var(--ink); }
.src-block h5 { font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: .2em; text-transform: uppercase; margin: 0 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--slate-300); color: var(--ink); }
.src-block p { font-family: "Noto Serif KR", serif; font-size: 12px; line-height: 1.65; margin: 0; color: var(--ink-2); }
.src-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.src-list li { font-family: "Noto Serif KR", serif; font-size: 12px; line-height: 1.5; color: var(--ink-2); }
.src-list .kw-label { font-family: "IBM Plex Mono", monospace; font-size: 9px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); margin-right: 6px; }
.colophon { grid-column: 1 / -1; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--slate-300); display: flex; justify-content: space-between; align-items: center; font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); gap: 14px; flex-wrap: wrap; }
.colophon .logo { font-family: "Playfair Display", serif; font-weight: 900; font-style: italic; text-transform: none; color: var(--ink); letter-spacing: -.01em; font-size: 15px; }
.colophon .logo .the { font-style: italic; font-weight: 400; font-size: .75em; margin-right: 4px; }
.colophon .signoff { font-family: "Playfair Display", serif; font-style: italic; font-weight: 700; font-size: 13px; color: var(--ink); letter-spacing: .04em; }

/* RESPONSIVE */
@media (max-width: 960px) {
  body { padding: 16px; }
  .stats { grid-template-columns: repeat(2, 1fr); }
  .stat { border-right: 1px solid var(--ink); border-bottom: 1px solid var(--ink); }
  .stat:nth-child(2n) { border-right: none; }
  .top-story { grid-template-columns: 1fr; gap: 24px; padding: 22px; }
  .ts-side { border-left: none; padding-left: 0; padding-top: 18px; border-top: 1px solid var(--ink); }
  .ts-body { column-count: 1; }
  .ts-headline { font-size: 28px; }
  .section-row { grid-template-columns: 1fr; }
  .section-row > .col { border-right: none; border-bottom: 1px solid var(--ink); }
  .section-row > .col:last-child { border-bottom: none; }
  .sources { grid-template-columns: 1fr; }
  .masthead-meta { grid-template-columns: 1fr; text-align: center; gap: 8px; }
  .masthead-meta .right { text-align: center; }
  .archive-bottom { grid-template-columns: 1fr; padding: 8px 12px 10px; }
  .tree-label { border-right: none; padding-right: 0; margin-right: 0; margin-bottom: 6px; }
  .kw.s-xl { font-size: 32px; }
  .kw.s-lg { font-size: 24px; }
  .kw.s-md { font-size: 18px; }
  .kw.s-sm { font-size: 14px; }
}
"""

# ─────────────────────────────────────────────
# Full HTML
# ─────────────────────────────────────────────

GOOGLE_FONTS = (
    "https://fonts.googleapis.com/css2?"
    "family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400"
    "&family=Noto+Serif+KR:wght@400;500;700;900"
    "&family=IBM+Plex+Sans+KR:wght@300;400;500;600;700"
    "&family=IBM+Plex+Mono:wght@400;500;600"
    "&display=swap"
)


# ─────────────────────────────────────────────
# 인증 게이트 (@socar.kr Google Identity Services)
# main 사이트(docs/web-api.js)와 동일 CLIENT_ID·JWT 키 사용
# ─────────────────────────────────────────────

AUTH_CLIENT_ID    = "495055817211-o0m1u8d2aglluhng1kr6fvua95u8emqp.apps.googleusercontent.com"
AUTH_ALLOWED_DOM  = "socar.kr"
AUTH_JWT_KEY      = "pg_jwt"   # main 사이트와 공유 → 한 번 로그인 시 양쪽 모두 통과
AUTH_JWT_TTL_HRS  = 6

AUTH_CSS = """
#auth-overlay { display: flex; position: fixed; inset: 0; z-index: 9999; background: #0F172A; align-items: center; justify-content: center; }
#auth-card { background: #1E293B; border: 1px solid #334155; border-radius: 12px; padding: 40px 36px; width: 360px; text-align: center; display: flex; flex-direction: column; gap: 12px; align-items: center; }
#auth-logo { font-family: 'Playfair Display','Georgia',serif; font-size: 22px; font-weight: 900; letter-spacing: 0.04em; color: #F1F5F9; }
#auth-logo .the { font-style: italic; font-weight: 400; font-size: 0.6em; margin-right: 4px; }
#auth-tagline { font-size: 11px; color: #64748B; letter-spacing: 0.04em; }
#auth-gsi-btn { margin: 8px 0; }
#auth-msg { font-size: 12px; min-height: 18px; }
#auth-hint { font-size: 10px; color: #475569; }
"""

AUTH_OVERLAY_HTML = """
<div id="auth-overlay">
  <div id="auth-card">
    <div id="auth-logo"><span class="the">The</span> PARKING GAZETTE</div>
    <div id="auth-tagline">모두의주차장 CX운영파트 · 주간 리포트</div>
    <div id="auth-gsi-btn"></div>
    <div id="auth-msg"></div>
    <div id="auth-hint">@socar.kr 계정으로만 접근 가능합니다</div>
  </div>
</div>
"""

AUTH_JS = f"""
(function () {{
  var CLIENT_ID = "{AUTH_CLIENT_ID}";
  var ALLOWED   = "{AUTH_ALLOWED_DOM}";
  var JWT_KEY   = "{AUTH_JWT_KEY}";
  var JWT_TTL   = {AUTH_JWT_TTL_HRS} * 60 * 60 * 1000;

  function decodeJwt(t) {{ try {{ return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); }} catch(_) {{ return null; }} }}
  function getStored() {{
    try {{ var i = JSON.parse(localStorage.getItem(JWT_KEY)||'null');
      if (!i) return null;
      if (Date.now() > i.exp) {{ localStorage.removeItem(JWT_KEY); return null; }}
      return i.token; }} catch(_) {{ return null; }}
  }}
  function store(t) {{ localStorage.setItem(JWT_KEY, JSON.stringify({{token:t, exp:Date.now()+JWT_TTL}})); }}
  function hide()   {{ var el = document.getElementById('auth-overlay'); if (el) el.style.display='none'; }}
  function err(m)   {{ var el = document.getElementById('auth-msg'); if (el) {{ el.textContent=m; el.style.color='#ef4444'; }} }}

  var stored = getStored();
  if (stored) {{ hide(); return; }}

  function init() {{
    if (typeof google === 'undefined' || !google.accounts) {{ setTimeout(init, 200); return; }}
    google.accounts.id.initialize({{ client_id: CLIENT_ID, callback: cb, auto_select: false }});
    var btn = document.getElementById('auth-gsi-btn');
    if (btn) google.accounts.id.renderButton(btn, {{ type:'standard', theme:'outline', size:'large', text:'signin_with', logo_alignment:'left', locale:'ko' }});
  }}
  function cb(resp) {{
    var t = resp.credential, p = decodeJwt(t);
    if (!p || !p.email) {{ err('인증 정보를 읽을 수 없습니다.'); return; }}
    var dom = p.email.split('@')[1];
    if (dom !== ALLOWED) {{ err('@socar.kr 계정만 접근 가능합니다. (' + p.email + ')'); google.accounts.id.revoke(p.email, function(){{}}); return; }}
    store(t); hide();
  }}
  init();
}})();
"""


def render_full_html(items, year, week_num, issue_total,
                     from_dt, to_dt, meta, cur_stats, prev_stats, prev_label,
                     new_voc=None) -> str:
    top_story  = pick_top_story(items)
    league     = period_app_league(items)
    svc_rows   = service_stats(items)

    modu_items  = [i for i in items if i.get("service_id") == "moduparking"]
    other_items = [i for i in items if i.get("service_id") != "moduparking"
                   and i.get("source_type") in REVIEW_TYPES]

    modu_kws  = extract_keywords(modu_items)
    other_kws = extract_keywords(other_items)

    vol_tag    = f"{year:02d}Y · {week_num}W"
    date_str   = fmt_date_ko(to_dt)

    archive_nav = render_archive_nav(meta, year, week_num)
    masthead    = render_masthead(year, week_num, issue_total, from_dt, to_dt)
    stats       = render_stats(items, from_dt, to_dt, cur_stats, prev_stats, prev_label, new_voc)
    top_s       = _render_top_story(top_story, items, cur_stats)
    league_html = render_league(league, year, week_num)
    dispatch_html = render_dispatch(svc_rows)
    modu_cloud  = render_keyword_cloud(modu_kws, "자사 키워드 맵", len(modu_items), vol_tag)
    other_cloud = render_keyword_cloud(other_kws, "타사 키워드 맵", len(other_items), vol_tag)
    voc_html    = render_voc_brief(items)
    wire_html   = render_wire(items)
    sources_html = render_sources(from_dt, to_dt, len(items), year, week_num)

    kw_legend = """
<div class="col" style="grid-column:1/-1;border-right:none;border-top:1px solid var(--ink);">
  <div class="kw-legend">
    <span class="item"><span class="swatch sw-1"></span>강한 부정 (Bg 강조)</span>
    <span class="item"><span class="swatch sw-2"></span>부정</span>
    <span class="item"><span class="swatch sw-3"></span>중립</span>
    <span class="item"><span class="swatch sw-4"></span>긍정 (Bg 강조)</span>
    <span class="item" style="margin-left:18px;">크기 = 주간 빈출 횟수</span>
  </div>
</div>"""

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>THE PARKING GAZETTE — {esc(vol_tag)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{GOOGLE_FONTS}" rel="stylesheet">
<script src="https://accounts.google.com/gsi/client" async></script>
<style>{CSS}
{AUTH_CSS}</style>
</head>
<body>
{AUTH_OVERLAY_HTML}
<script>{AUTH_JS}</script>
<main class="paper">

{archive_nav}

{masthead}

{stats}

{top_s}

<!-- SECTION A+B: LEAGUE + DISPATCH -->
<section class="section-row">
  <div class="col">
    <div class="col-head">
      <span class="name">SECTION A · APP LEAGUE</span>
      <span class="kicker">주차 앱 평점 순위 — {esc(vol_tag)}</span>
    </div>
    <div class="col-body league">
      {league_html}
    </div>
  </div>
  <div class="col">
    <div class="col-head">
      <span class="name">SECTION B · SERVICE DISPATCH</span>
      <span class="kicker">서비스별 수집 현황</span>
    </div>
    <div class="col-body dispatch">
      {dispatch_html}
    </div>
  </div>
</section>

<!-- SECTION C+D: KEYWORD MAPS -->
<section class="section-row">
  <div class="col">
    <div class="col-head">
      <span class="name">SECTION C · VOICE OF CUSTOMER · 자사</span>
      <span class="kicker">모두의주차장 — 키워드 빈출 맵</span>
    </div>
    <div class="col-body kwmap">
      {modu_cloud}
    </div>
  </div>
  <div class="col">
    <div class="col-head">
      <span class="name">SECTION D · VOICE OF CUSTOMER · 타사</span>
      <span class="kicker">경쟁사 합산 — 키워드 빈출 맵</span>
    </div>
    <div class="col-body kwmap">
      {other_cloud}
    </div>
  </div>
  {kw_legend}
</section>

<!-- SECTION E+F: VOC + WIRE -->
<section class="section-row">
  <div class="col">
    <div class="col-head">
      <span class="name">SECTION E · VOC BRIEF</span>
      <span class="kicker">이번 주 고객의 목소리</span>
    </div>
    <div class="col-body voc">
      {voc_html}
    </div>
  </div>
  <div class="col">
    <div class="col-head">
      <span class="name">SECTION F · COMPETITOR WIRE</span>
      <span class="kicker">경쟁사 뉴스 일지</span>
    </div>
    <div class="col-body wire">
      {wire_html}
    </div>
  </div>
</section>

{sources_html}

</main>
</body>
</html>"""


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    meta = load_meta()
    from_dt, to_dt = get_period()
    year, week_num, issue_total = advance_meta(meta, to_dt)

    print(f"[gazette] {year:02d}Y {week_num}W · Issue #{issue_total:03d}")
    print(f"[gazette] period: {from_dt} ~ {to_dt}")

    raw_data     = load_json(DOCS / "data.json", {})
    all_items    = raw_data.get("items", []) if isinstance(raw_data, dict) else []
    period_items = filter_period(all_items, from_dt, to_dt)

    print(f"[gazette] {len(period_items)} items in period (total: {len(all_items)})")

    cur_stats             = compute_stats(period_items, from_dt, to_dt)
    prev_stats, prev_label = find_prev_stats(meta, year, week_num)

    # 신규 VOC 키워드 비율 — 과거 4주치 자사 부정 키워드 합집합과 비교
    hist_kws: set = set()
    for iss in sorted(meta.get("issues", []),
                      key=lambda x: (x.get("year", 0), x.get("week_num", 0)),
                      reverse=True)[:4]:
        st = iss.get("stats", {})
        for kw in (st.get("neg_keywords") or []):
            hist_kws.add(kw)
    new_voc = compute_new_voc_ratio(cur_stats.get("neg_keywords", []), hist_kws if hist_kws else None)

    html = render_full_html(period_items, year, week_num, issue_total,
                            from_dt, to_dt, meta, cur_stats, prev_stats, prev_label, new_voc)

    archive_filename = f"gazette_{to_dt.strftime('%Y_%m_%d')}.html"

    out = DOCS / "gazette_latest.html"
    out.write_text(html, encoding="utf-8")
    print(f"[gazette] written → {out}")

    archive = DOCS / archive_filename
    archive.write_text(html, encoding="utf-8")
    print(f"[gazette] archive → {archive}")

    # Update meta with issue history (cur_stats 포함 → 다음 주차 WoW 델타 비교용)
    issues = meta.get("issues", [])
    # 같은 주차 재실행 시 stats만 갱신 (issue_total 유지)
    existing = next((iss for iss in issues
                     if iss.get("year") == year and iss.get("week_num") == week_num), None)
    if existing:
        existing["stats"] = cur_stats
        existing["date"]  = to_dt.isoformat()
        existing["file"]  = archive_filename
    else:
        issues.append({
            "year":     year,
            "week_num": week_num,
            "date":     to_dt.isoformat(),
            "file":     archive_filename,
            "stats":    cur_stats,
        })

    new_meta = {
        "year":             year,
        "week_num":         week_num,
        "issue_total":      issue_total,
        "last_report_date": to_dt.isoformat(),
        "issues":           issues,
    }
    save_meta(new_meta)
    print("[gazette] meta saved")


if __name__ == "__main__":
    main()
