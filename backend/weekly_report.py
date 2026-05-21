#!/usr/bin/env python3
"""
weekly_report.py — THE PARKING GAZETTE 주간 리포트 생성기
매주 화요일 11:00 KST (UTC 02:00) GitHub Actions 자동 실행
"""

import html as html_lib
import json
from collections import defaultdict
from datetime import timedelta, date
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"

SERVICE_ORDER = [
    "moduparking", "kakaot_parking", "tmap_parking", "iparking",
    "nicepark", "highparking", "parkingfriends", "zoomansa",
    "amano_korea", "kmpark", "parkingcloud", "sk_shielders",
    "urbanport", "koreanef",
]

SOURCE_LABEL = {
    "news": "뉴스", "blog": "블로그", "rss": "RSS",
    "homepage": "홈페이지", "html_list": "보도자료", "html_diff": "홈피변경",
    "appstore": "리뷰(AOS)", "ios_appstore": "리뷰(iOS)",
    "app_info": "앱정보", "youtube_rss": "유튜브",
}

REVIEW_TYPES = {"appstore", "ios_appstore"}
NEWS_TYPES   = {"news", "blog", "rss", "html_list", "html_diff", "homepage", "youtube_rss"}


# ──────────────────────────────────────────────
# IO helpers
# ──────────────────────────────────────────────

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


# ──────────────────────────────────────────────
# Meta (volume counter)
# ──────────────────────────────────────────────

def load_meta() -> dict:
    m = load_json(DOCS / "gazette_meta.json", {})
    today = date.today()
    return {
        "year":            m.get("year", today.year % 100),
        "week_num":        m.get("week_num", 0),
        "issue_total":     m.get("issue_total", 0),
        "last_report_date": m.get("last_report_date"),
    }


def save_meta(meta: dict):
    (DOCS / "gazette_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def advance_meta(meta: dict) -> tuple:
    today = date.today()
    cur_year = today.year % 100
    if meta["year"] != cur_year:
        year, week_num = cur_year, 1
    else:
        year     = meta["year"]
        week_num = meta["week_num"] + 1
    issue_total = meta["issue_total"] + 1
    return year, week_num, issue_total


def get_period(meta: dict) -> tuple:
    to_dt = date.today()
    if meta["last_report_date"]:
        from_dt = parse_date(meta["last_report_date"])
        if from_dt is None:
            from_dt = to_dt - timedelta(days=7)
    else:
        from_dt = to_dt - timedelta(days=7)
    return from_dt, to_dt


# ──────────────────────────────────────────────
# Data processing
# ──────────────────────────────────────────────

def filter_period(items: list, from_dt: date, to_dt: date) -> list:
    result = []
    for item in items:
        dt = parse_date(item.get("published_at") or item.get("collected_at", ""))
        if dt and from_dt <= dt <= to_dt:
            result.append(item)
    return result


def pick_top_story(items: list) -> dict | None:
    """뉴스·블로그 중 모두의주차장 관련 or 경쟁사 사업확장·정책 우선"""
    candidates = [i for i in items if i.get("source_type") in NEWS_TYPES
                  and i.get("title") and len(i.get("title", "")) > 10]
    if not candidates:
        return None
    def score(i):
        s = 0
        if i.get("service_id") == "moduparking":
            s += 10
        ct = i.get("change_type", "")
        if ct in ("사업확장", "정책", "제휴"):
            s += 5
        if i.get("sentiment") == "negative":
            s += 3
        if len(i.get("summary") or "") > 50:
            s += 2
        return s
    return max(candidates, key=score)


def app_league(app_info: list) -> list:
    """서비스별 Android+iOS 평균 평점 계산, 내림차순"""
    by_svc = defaultdict(list)
    for a in app_info:
        if a.get("rating"):
            by_svc[a["service_id"]].append(a)
    rows = []
    for svc_id, entries in by_svc.items():
        avg = sum(e["rating"] for e in entries) / len(entries)
        total_ratings = sum(e.get("num_ratings", 0) for e in entries)
        name = entries[0].get("name_ko", svc_id)
        rows.append({"service_id": svc_id, "name_ko": name,
                     "avg": round(avg, 2), "total_ratings": total_ratings,
                     "entries": entries})
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
        reviews = [i for i in svc_items if i["source_type"] in REVIEW_TYPES]
        news    = [i for i in svc_items if i["source_type"] in NEWS_TYPES]
        neg     = sum(1 for i in svc_items if i.get("sentiment") == "negative")
        pos     = sum(1 for i in svc_items if i.get("sentiment") == "positive")
        name    = svc_items[0].get("name_ko", svc_id)
        rows.append({
            "service_id": svc_id, "name_ko": name,
            "total": len(svc_items), "reviews": len(reviews), "news": len(news),
            "neg": neg, "pos": pos,
        })
    # services not in ORDER
    for svc_id, svc_items in by_svc.items():
        if svc_id not in SERVICE_ORDER:
            name = svc_items[0].get("name_ko", svc_id)
            reviews = [i for i in svc_items if i["source_type"] in REVIEW_TYPES]
            news    = [i for i in svc_items if i["source_type"] in NEWS_TYPES]
            neg = sum(1 for i in svc_items if i.get("sentiment") == "negative")
            pos = sum(1 for i in svc_items if i.get("sentiment") == "positive")
            rows.append({"service_id": svc_id, "name_ko": name,
                         "total": len(svc_items), "reviews": len(reviews), "news": len(news),
                         "neg": neg, "pos": pos})
    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows


def pick_notable_reviews(items: list, n=4) -> list:
    """주목할 리뷰: 부정 우선, 텍스트 있는 것"""
    candidates = [i for i in items
                  if i.get("source_type") in REVIEW_TYPES
                  and i.get("summary") and len(i.get("summary", "")) > 5]
    neg = [i for i in candidates if i.get("sentiment") == "negative"]
    pos = [i for i in candidates if i.get("sentiment") == "positive"]
    # sort by summary length (more content = more useful)
    neg.sort(key=lambda i: len(i.get("summary", "")), reverse=True)
    pos.sort(key=lambda i: len(i.get("summary", "")), reverse=True)
    return (neg[:3] + pos[:1])[:n]


def pick_news_briefs(items: list, n=5) -> list:
    """경쟁사 뉴스 브리핑: 모두의주차장 제외, 뉴스·블로그"""
    candidates = [i for i in items
                  if i.get("source_type") in NEWS_TYPES
                  and i.get("service_id") != "moduparking"
                  and i.get("title") and len(i.get("title", "")) > 5]
    candidates.sort(key=lambda i: (
        i.get("change_type", "") in ("사업확장", "정책", "제휴"),
        len(i.get("summary") or ""),
    ), reverse=True)
    return candidates[:n]


# ──────────────────────────────────────────────
# HTML helpers
# ──────────────────────────────────────────────

def esc(s) -> str:
    return html_lib.escape(str(s or ""), quote=False)


def fmt_date_ko(d: date) -> str:
    MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    DAYS   = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return f"{DAYS[d.weekday()]}, {MONTHS[d.month-1]} {d.day}, {d.year}"


def sentiment_badge(s: str) -> str:
    if s == "negative":
        return '<span class="s-neg">NEG</span>'
    if s == "positive":
        return '<span class="s-pos">POS</span>'
    return '<span class="s-neu">NEU</span>'


def type_badge(t: str) -> str:
    label = SOURCE_LABEL.get(t, t)
    css = "tb-rev" if t in REVIEW_TYPES else "tb-news"
    return f'<span class="type-badge {css}">{esc(label)}</span>'


def change_badge(ct: str) -> str:
    cls = {
        "VOC": "ct-voc", "기술": "ct-tech", "정책": "ct-policy",
        "사업확장": "ct-biz", "제휴": "ct-alliance", "기타": "ct-etc",
    }.get(ct, "ct-etc")
    return f'<span class="ct-badge {cls}">{esc(ct)}</span>'


def rating_star(r: float) -> str:
    filled = int(r)
    half   = 1 if (r - filled) >= 0.5 else 0
    empty  = 5 - filled - half
    return "★" * filled + ("½" if half else "") + "☆" * empty


# ──────────────────────────────────────────────
# Section renderers
# ──────────────────────────────────────────────

def render_masthead(year: int, week_num: int, issue_total: int,
                    from_dt: date, to_dt: date) -> str:
    vol_tag  = f"{year:02d}Y {week_num}W"
    iss_tag  = f"Vol.1 · No.{issue_total:03d}"
    date_str = fmt_date_ko(to_dt)
    period   = f"{from_dt.strftime('%Y-%m-%d')} ~ {to_dt.strftime('%Y-%m-%d')}"
    return f"""
<div class="masthead">
  <div class="masthead-top">
    <span>국내 주차 플랫폼 CX 정보 종합 모니터</span>
    <span class="right-cluster">
      <span class="vol-pill">{esc(vol_tag)}</span>
      <span class="iss-pill">AUTO</span>
    </span>
  </div>
  <h1 class="gazette-title">THE PARKING GAZETTE</h1>
  <div class="tagline">모두의주차장 사업이익팀 CX이슈파트 · Weekly Edition</div>
  <div class="masthead-bar">
    <span class="vol">{esc(iss_tag)}</span>
    <span class="date">{esc(date_str)}</span>
    <span class="sync">COVERAGE PERIOD · {esc(period)}</span>
  </div>
</div>
"""


def render_stats_row(items: list, from_dt: date, to_dt: date) -> str:
    total    = len(items)
    reviews  = sum(1 for i in items if i["source_type"] in REVIEW_TYPES)
    news     = sum(1 for i in items if i["source_type"] in NEWS_TYPES)
    svcs     = len({i["service_id"] for i in items})
    neg_pct  = round(sum(1 for i in items if i.get("sentiment") == "negative") / max(total, 1) * 100)
    days     = (to_dt - from_dt).days or 1
    per_day  = round(total / days, 1)
    return f"""
<div class="stats-row">
  <div class="stat-cell">
    <div class="stat-v">{total:,}</div>
    <div class="stat-l">TOTAL ITEMS</div>
  </div>
  <div class="stat-cell">
    <div class="stat-v">{reviews:,}</div>
    <div class="stat-l">REVIEWS</div>
  </div>
  <div class="stat-cell">
    <div class="stat-v">{news:,}</div>
    <div class="stat-l">NEWS · BLOG</div>
  </div>
  <div class="stat-cell">
    <div class="stat-v">{svcs}</div>
    <div class="stat-l">SERVICES</div>
  </div>
  <div class="stat-cell">
    <div class="stat-v">{neg_pct}%</div>
    <div class="stat-l">NEGATIVE RATE</div>
  </div>
  <div class="stat-cell">
    <div class="stat-v">{per_day}</div>
    <div class="stat-l">PER DAY AVG</div>
  </div>
</div>
"""


def render_top_story(item: dict | None) -> str:
    if not item:
        return ""
    title   = esc(item.get("title", "(제목 없음)"))
    summary = esc(item.get("summary", ""))[:300]
    svc     = esc(item.get("name_ko", item.get("service_id", "")))
    src     = type_badge(item.get("source_type", ""))
    ct      = change_badge(item.get("change_type", "기타"))
    sb      = sentiment_badge(item.get("sentiment", "neutral"))
    date_s  = esc(item.get("published_at", ""))
    url     = esc(item.get("url", "#"))
    return f"""
<div class="top-story">
  <div class="top-story-label">TOP STORY · LEAD</div>
  <div class="ts-meta">{date_s} &nbsp;·&nbsp; {svc} &nbsp;·&nbsp; {src} {ct} {sb}</div>
  <h2 class="ts-headline"><a href="{url}" target="_blank" rel="noopener">{title}</a></h2>
  <p class="ts-lede">{summary}</p>
</div>
"""


def render_league(league: list) -> str:
    if not league:
        return ""
    rows_html = ""
    modu_rank = next((i + 1 for i, r in enumerate(league)
                      if r["service_id"] == "moduparking"), None)
    for rank, row in enumerate(league, 1):
        is_us = row["service_id"] == "moduparking"
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "")
        cls   = "league-row us" if is_us else "league-row"
        us_tag = '<span class="us-tag">자사</span>' if is_us else ""
        bar_w = round(row["avg"] / 5 * 100)
        bar_cls = "bar-fill us" if is_us else "bar-fill"
        aos_r = next((e for e in row["entries"] if e["platform"] == "google_play"), None)
        ios_r = next((e for e in row["entries"] if e["platform"] == "ios"), None)
        aos_str = f"A {aos_r['rating']:.2f}" if aos_r else "—"
        ios_str = f"i {ios_r['rating']:.2f}" if ios_r else "—"
        rows_html += f"""
  <div class="{cls}">
    <div class="lr-rank">{rank}</div>
    <div class="lr-medal">{medal}</div>
    <div class="lr-info">
      <div class="lr-name">{esc(row['name_ko'])} {us_tag}</div>
      <div class="lr-platforms">{esc(aos_str)} &nbsp; {esc(ios_str)}</div>
      <div class="bar-wrap"><div class="{bar_cls}" style="width:{bar_w}%"></div></div>
    </div>
    <div class="lr-score">
      <span class="lr-avg">{'★'}{row['avg']:.2f}</span>
      <span class="lr-cnt">{row['total_ratings']:,} reviews</span>
    </div>
  </div>"""
    pos_note = f" — 현재 {modu_rank}위" if modu_rank else ""
    return f"""
<div class="card">
  <div class="card-head">
    <span class="ch-title">🏆 Parking App League</span>
    <span class="ch-sub">앱 평점 현황{esc(pos_note)}</span>
  </div>
  <div class="league-body">{rows_html}
  </div>
</div>
"""


def render_service_dispatch(svc_rows: list) -> str:
    if not svc_rows:
        return ""
    rows_html = ""
    for row in svc_rows:
        is_us = row["service_id"] == "moduparking"
        cls   = "svc-row us" if is_us else "svc-row"
        us_tag = '<span class="us-tag">자사</span>' if is_us else ""
        neg_cls = "neg-count hot" if row["neg"] > 20 else "neg-count"
        rows_html += f"""
  <div class="{cls}">
    <div class="svc-name">{esc(row['name_ko'])} {us_tag}</div>
    <div class="svc-stat">{row['total']:,}</div>
    <div class="svc-stat">{row['reviews']:,}</div>
    <div class="svc-stat">{row['news']:,}</div>
    <div class="svc-stat {neg_cls}">{row['neg']:,}</div>
    <div class="svc-stat pos-count">{row['pos']:,}</div>
  </div>"""
    return f"""
<div class="card">
  <div class="card-head">
    <span class="ch-title">📋 Service Dispatch</span>
    <span class="ch-sub">서비스별 수집 현황</span>
  </div>
  <div class="dispatch-body">
    <div class="svc-header">
      <div class="svc-name">서비스</div>
      <div class="svc-stat">전체</div>
      <div class="svc-stat">리뷰</div>
      <div class="svc-stat">뉴스</div>
      <div class="svc-stat">부정</div>
      <div class="svc-stat">긍정</div>
    </div>
    {rows_html}
  </div>
</div>
"""


def render_voc_brief(items: list) -> str:
    reviews = pick_notable_reviews(items)
    if not reviews:
        return ""
    cards = ""
    for item in reviews:
        title   = esc(item.get("title", ""))
        summary = esc(item.get("summary", ""))[:160]
        svc     = esc(item.get("name_ko", item.get("service_id", "")))
        sb      = sentiment_badge(item.get("sentiment", "neutral"))
        src     = type_badge(item.get("source_type", ""))
        date_s  = esc(item.get("published_at", ""))
        url     = esc(item.get("url", "#"))
        cls     = "voc-card neg" if item.get("sentiment") == "negative" else "voc-card pos"
        cards += f"""
  <div class="{cls}">
    <div class="voc-meta">{date_s} · {svc} · {src} {sb}</div>
    <div class="voc-title"><a href="{url}" target="_blank" rel="noopener">{title}</a></div>
    <div class="voc-body">{summary}</div>
  </div>"""
    return f"""
<div class="card">
  <div class="card-head">
    <span class="ch-title">🗣 VOC Brief</span>
    <span class="ch-sub">이번 주 주목할 고객 목소리</span>
  </div>
  <div class="voc-body-wrap">{cards}
  </div>
</div>
"""


def render_competitor_wire(items: list) -> str:
    briefs = pick_news_briefs(items)
    if not briefs:
        return ""
    rows = ""
    for item in briefs:
        title  = esc(item.get("title", ""))
        svc    = esc(item.get("name_ko", item.get("service_id", "")))
        ct     = change_badge(item.get("change_type", "기타"))
        sb     = sentiment_badge(item.get("sentiment", "neutral"))
        date_s = esc(item.get("published_at", ""))
        url    = esc(item.get("url", "#"))
        sum_s  = esc(item.get("summary", ""))[:100]
        rows += f"""
  <div class="wire-row">
    <div class="wire-meta">{date_s} · {svc} {ct} {sb}</div>
    <div class="wire-title"><a href="{url}" target="_blank" rel="noopener">{title}</a></div>
    {'<div class="wire-sum">' + sum_s + '</div>' if sum_s else ''}
  </div>"""
    return f"""
<div class="card">
  <div class="card-head">
    <span class="ch-title">📡 Competitor Wire</span>
    <span class="ch-sub">경쟁사 주간 동향</span>
  </div>
  <div class="wire-body">{rows}
  </div>
</div>
"""


def render_sources(from_dt: date, to_dt: date, total: int) -> str:
    return f"""
<div class="sources-foot">
  <strong>SOURCES &amp; METHODOLOGY</strong> &nbsp;—&nbsp;
  Coverage period: {esc(str(from_dt))} ~ {esc(str(to_dt))} · {total:,} items
  · 수집 채널: Google Play / iTunes RSS · 네이버 검색 API · Google News RSS · HTML diff
  · 본 리포트는 GitHub Actions에서 매주 화요일 KST 11:00 자동 생성됩니다.
</div>
"""


# ──────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────

CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --slate-900:#0f172a; --slate-800:#1e293b; --slate-700:#334155;
  --slate-500:#64748b; --slate-400:#94a3b8; --slate-300:#cbd5e1;
  --slate-200:#e2e8f0; --slate-100:#f1f5f9; --slate-50:#f8fafc;
  --blue-900:#1e3a8a; --blue-700:#1d4ed8; --blue-600:#2563eb;
  --blue-500:#3b82f6; --blue-400:#60a5fa; --blue-200:#bfdbfe;
  --blue-100:#dbeafe; --blue-50:#eff6ff;
  --cyan-500:#06b6d4; --cyan-400:#22d3ee; --cyan-100:#cffafe;
  --emerald-500:#10b981; --emerald-100:#d1fae5;
  --red-500:#ef4444; --red-100:#fee2e2;
  --amber-500:#f59e0b; --amber-100:#fef3c7;
  --surface:#fff; --bg:var(--slate-50); --border:var(--slate-200);
  --text:var(--slate-900); --text-2:var(--slate-700); --text-m:var(--slate-500);
  --shadow-sm:0 1px 3px rgba(15,23,42,.06);
  --shadow-md:0 4px 12px rgba(15,23,42,.08);
  --font:-apple-system,BlinkMacSystemFont,'Pretendard','Apple SD Gothic Neo',sans-serif;
  --mono:'SF Mono',Consolas,monospace;
}
html { font-size:15px; scroll-behavior:smooth; }
body { font-family:var(--font); background:var(--bg); color:var(--text); line-height:1.65; }
a { color:var(--blue-600); text-decoration:none; }
a:hover { text-decoration:underline; }

.container { max-width:1120px; margin:0 auto; padding:24px 20px 64px; }

/* MASTHEAD */
.masthead {
  background:var(--surface); border:2px solid var(--slate-900);
  border-radius:12px; padding:22px 28px 14px; margin-bottom:14px;
  box-shadow:var(--shadow-md);
}
.masthead-top {
  display:flex; justify-content:space-between; align-items:center;
  font-size:11px; color:var(--text-m); letter-spacing:1.2px; font-weight:700;
  text-transform:uppercase; padding-bottom:10px; border-bottom:1px solid var(--border);
  margin-bottom:10px;
}
.right-cluster { display:flex; gap:10px; align-items:center; }
.vol-pill {
  background:var(--blue-700); color:#fff; padding:3px 10px; border-radius:4px;
  font-size:12px; font-weight:800; letter-spacing:0.5px;
}
.iss-pill {
  background:var(--emerald-500); color:#fff; padding:3px 8px; border-radius:4px;
  font-size:10px; font-weight:800; letter-spacing:1px;
}
.gazette-title {
  font-family:var(--font); font-size:52px; font-weight:900; letter-spacing:-2.4px;
  text-align:center; color:var(--text); line-height:1; margin-bottom:4px;
}
.tagline {
  text-align:center; font-size:12px; color:var(--text-m); margin-bottom:12px; font-weight:500;
}
.masthead-bar {
  border-top:3px double var(--slate-900); border-bottom:1px solid var(--border);
  padding:8px 0; display:flex; justify-content:space-between; align-items:center;
  font-size:11.5px; color:var(--text-2); font-weight:600;
}

/* STATS ROW */
.stats-row {
  display:grid; grid-template-columns:repeat(6,1fr); margin-bottom:14px;
  background:var(--surface); border:1px solid var(--border); border-radius:12px;
  box-shadow:var(--shadow-sm); overflow:hidden;
}
.stat-cell {
  padding:18px 10px; text-align:center; border-right:1px solid var(--border);
}
.stat-cell:last-child { border-right:none; }
.stat-v { font-size:22px; font-weight:800; color:var(--text); letter-spacing:-0.5px; }
.stat-l { font-size:10.5px; color:var(--text-m); font-weight:700; letter-spacing:1px; margin-top:5px; text-transform:uppercase; }

/* SECTION TITLE */
.sec-title {
  font-size:12.5px; font-weight:800; color:var(--text); text-transform:uppercase;
  letter-spacing:1.5px; padding:7px 0; border-top:2px solid var(--slate-900);
  border-bottom:1px solid var(--slate-900); margin:18px 0 12px;
  display:flex; justify-content:space-between; align-items:center;
}
.sec-title .sec-sub { font-size:11px; font-weight:500; color:var(--text-m); text-transform:none; letter-spacing:0; }

/* TOP STORY */
.top-story {
  background:var(--surface); border:1px solid var(--border); border-radius:12px;
  padding:28px 30px; margin-bottom:14px; position:relative; box-shadow:var(--shadow-sm);
}
.top-story-label {
  position:absolute; top:-11px; left:24px;
  background:var(--slate-900); color:#fff; padding:4px 14px; border-radius:4px;
  font-size:10.5px; font-weight:800; letter-spacing:1.8px;
}
.ts-meta { font-size:11.5px; color:var(--text-m); margin-bottom:10px; }
.ts-headline { font-size:26px; font-weight:900; line-height:1.35; letter-spacing:-0.6px; margin-bottom:12px; }
.ts-headline a { color:var(--text); }
.ts-headline a:hover { color:var(--blue-700); }
.ts-lede {
  font-size:14px; color:var(--text-2); line-height:1.8;
  padding:0 0 0 14px; border-left:4px solid var(--cyan-500);
}

/* GRID */
.grid-2 { display:grid; grid-template-columns:1.4fr 1fr; gap:14px; margin-bottom:14px; }
.grid-2-equal { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:14px; }

/* CARD */
.card {
  background:var(--surface); border:1px solid var(--border); border-radius:12px;
  box-shadow:var(--shadow-sm); overflow:hidden; margin-bottom:14px;
}
.card-head {
  background:var(--slate-900); color:#fff; padding:11px 18px;
  display:flex; justify-content:space-between; align-items:center;
}
.ch-title { font-size:13.5px; font-weight:800; }
.ch-sub { font-size:10.5px; opacity:0.78; }

/* LEAGUE */
.league-body { padding:4px 0 8px; }
.league-row {
  display:grid; grid-template-columns:28px 24px 1fr 110px;
  gap:10px; align-items:center; padding:10px 18px;
  border-bottom:1px solid var(--slate-100);
}
.league-row:last-child { border-bottom:none; }
.league-row.us {
  background:linear-gradient(90deg,var(--cyan-100),transparent);
  border-left:3px solid var(--cyan-500);
}
.lr-rank { font-size:18px; font-weight:900; color:var(--text-m); font-family:var(--mono); }
.league-row.us .lr-rank { color:var(--cyan-500); }
.lr-medal { font-size:16px; }
.lr-name { font-size:13px; font-weight:700; color:var(--text); display:flex; align-items:center; gap:6px; }
.league-row.us .lr-name { color:var(--blue-900); }
.lr-platforms { font-size:11px; color:var(--text-m); margin:3px 0 4px; font-family:var(--mono); }
.bar-wrap { height:6px; background:var(--slate-100); border-radius:3px; overflow:hidden; }
.bar-fill { height:100%; background:linear-gradient(90deg,var(--slate-400),var(--slate-700)); border-radius:3px; }
.bar-fill.us { background:linear-gradient(90deg,var(--cyan-400),var(--cyan-500)); }
.lr-score { text-align:right; }
.lr-avg { display:block; font-size:16px; font-weight:800; color:var(--text); }
.league-row.us .lr-avg { color:var(--cyan-500); }
.lr-cnt { font-size:10.5px; color:var(--text-m); margin-top:2px; display:block; }

/* DISPATCH */
.dispatch-body { padding:4px 0 8px; }
.svc-header {
  display:grid; grid-template-columns:1fr repeat(5,70px);
  padding:8px 18px; font-size:10.5px; font-weight:800; color:var(--text-m);
  text-transform:uppercase; letter-spacing:0.5px; border-bottom:1px solid var(--border);
}
.svc-row {
  display:grid; grid-template-columns:1fr repeat(5,70px);
  padding:8px 18px; border-bottom:1px solid var(--slate-100); align-items:center;
}
.svc-row:last-child { border-bottom:none; }
.svc-row.us { background:linear-gradient(90deg,var(--cyan-100),transparent); border-left:3px solid var(--cyan-500); }
.svc-name { font-size:13px; font-weight:700; color:var(--text); display:flex; align-items:center; gap:6px; }
.svc-stat { font-size:13px; font-weight:600; color:var(--text-2); text-align:center; font-family:var(--mono); }
.neg-count { color:var(--red-500) !important; }
.neg-count.hot { font-weight:900; }
.pos-count { color:var(--emerald-500) !important; }

/* VOC */
.voc-body-wrap { padding:14px 18px; display:flex; flex-direction:column; gap:10px; }
.voc-card { border-radius:8px; padding:12px 14px; border-left:3px solid transparent; }
.voc-card.neg { background:var(--red-100); border-left-color:var(--red-500); }
.voc-card.pos { background:var(--emerald-100); border-left-color:var(--emerald-500); }
.voc-meta { font-size:11px; color:var(--text-m); margin-bottom:5px; }
.voc-title { font-size:13px; font-weight:700; color:var(--text); margin-bottom:5px; }
.voc-title a { color:inherit; }
.voc-body { font-size:12.5px; color:var(--text-2); line-height:1.7; }

/* COMPETITOR WIRE */
.wire-body { padding:4px 18px 14px; }
.wire-row { padding:10px 0; border-bottom:1px solid var(--slate-100); }
.wire-row:last-child { border-bottom:none; }
.wire-meta { font-size:11px; color:var(--text-m); margin-bottom:4px; }
.wire-title { font-size:13px; font-weight:700; color:var(--text); margin-bottom:3px; }
.wire-title a { color:inherit; }
.wire-sum { font-size:12px; color:var(--text-2); line-height:1.6; }

/* BADGES */
.us-tag {
  background:var(--cyan-500); color:#fff; font-size:9px; font-weight:800;
  padding:1px 6px; border-radius:3px;
}
.s-neg { background:var(--red-100); color:var(--red-500); font-size:10px; font-weight:800; padding:1px 6px; border-radius:3px; }
.s-pos { background:var(--emerald-100); color:var(--emerald-500); font-size:10px; font-weight:800; padding:1px 6px; border-radius:3px; }
.s-neu { background:var(--slate-100); color:var(--text-m); font-size:10px; font-weight:600; padding:1px 6px; border-radius:3px; }
.type-badge { font-size:10px; font-weight:700; padding:1px 6px; border-radius:3px; }
.tb-rev { background:var(--blue-100); color:var(--blue-700); }
.tb-news { background:var(--slate-100); color:var(--text-m); }
.ct-badge { font-size:10px; font-weight:700; padding:1px 6px; border-radius:3px; }
.ct-voc { background:var(--amber-100); color:var(--amber-500); }
.ct-tech { background:var(--blue-100); color:var(--blue-700); }
.ct-policy { background:#f3e8ff; color:#7c3aed; }
.ct-biz { background:var(--emerald-100); color:var(--emerald-500); }
.ct-alliance { background:var(--cyan-100); color:var(--cyan-500); }
.ct-etc { background:var(--slate-100); color:var(--text-m); }

/* SOURCES */
.sources-foot {
  margin-top:14px; padding:14px 18px; border-radius:12px;
  background:var(--surface); border:1px solid var(--border);
  font-size:12px; color:var(--text-m); line-height:1.8; box-shadow:var(--shadow-sm);
}
.news-foot {
  text-align:center; font-size:11px; color:var(--text-m);
  margin-top:16px; padding-top:14px; border-top:1px solid var(--border);
}

@media(max-width:900px) {
  .gazette-title { font-size:36px; }
  .stats-row { grid-template-columns:repeat(3,1fr); }
  .stat-cell:nth-child(3) { border-right:none; }
  .grid-2, .grid-2-equal { grid-template-columns:1fr; }
  .svc-header, .svc-row { grid-template-columns:1fr repeat(3,60px); }
  .svc-stat:nth-child(5), .svc-stat:nth-child(6),
  .svc-header div:nth-child(5), .svc-header div:nth-child(6) { display:none; }
}
"""


# ──────────────────────────────────────────────
# Full HTML
# ──────────────────────────────────────────────

def render_full_html(items, app_info_list, year, week_num, issue_total, from_dt, to_dt) -> str:
    top_story = pick_top_story(items)
    league    = app_league(app_info_list)
    svc_rows  = service_stats(items)

    masthead        = render_masthead(year, week_num, issue_total, from_dt, to_dt)
    stats_row       = render_stats_row(items, from_dt, to_dt)
    top_story_html  = render_top_story(top_story)
    league_html     = render_league(league)
    dispatch_html   = render_service_dispatch(svc_rows)
    voc_html        = render_voc_brief(items)
    wire_html       = render_competitor_wire(items)
    sources_html    = render_sources(from_dt, to_dt, len(items))

    vol_tag  = f"{year:02d}Y {week_num}W"
    date_str = fmt_date_ko(to_dt)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>THE PARKING GAZETTE · {esc(vol_tag)} · {esc(date_str)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">

{masthead}

{stats_row}

<div class="sec-title">
  This Week's Lead
  <span class="sec-sub">{esc(str(from_dt))} ~ {esc(str(to_dt))} 기간 수집 데이터 기반</span>
</div>

{top_story_html}

<div class="grid-2">
  {league_html}
  {dispatch_html}
</div>

<div class="sec-title">
  VOC &amp; Competitor Wire
  <span class="sec-sub">리뷰 하이라이트 · 경쟁사 동향</span>
</div>

<div class="grid-2-equal">
  {voc_html}
  {wire_html}
</div>

{sources_html}

<div class="news-foot">
  ─── END OF ISSUE ───<br>
  THE PARKING GAZETTE · {esc(vol_tag)} · Auto-generated by GitHub Actions · {esc(str(to_dt))}
</div>

</div>
</body>
</html>
"""


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    meta = load_meta()
    year, week_num, issue_total = advance_meta(meta)
    from_dt, to_dt = get_period(meta)

    print(f"[gazette] {year:02d}Y {week_num}W · Vol.1 No.{issue_total:03d}")
    print(f"[gazette] period: {from_dt} ~ {to_dt}")

    raw_data    = load_json(DOCS / "data.json", {})
    all_items   = raw_data.get("items", []) if isinstance(raw_data, dict) else []
    period_items = filter_period(all_items, from_dt, to_dt)
    app_info    = load_json(DOCS / "app_info.json", []) or []

    print(f"[gazette] {len(period_items)} items in period (total: {len(all_items)})")

    html = render_full_html(period_items, app_info, year, week_num, issue_total, from_dt, to_dt)

    out = DOCS / "gazette_latest.html"
    out.write_text(html, encoding="utf-8")
    print(f"[gazette] written → {out}")

    archive = DOCS / f"gazette_{to_dt.strftime('%Y_%m_%d')}.html"
    archive.write_text(html, encoding="utf-8")
    print(f"[gazette] archive → {archive}")

    new_meta = {
        "year":             year,
        "week_num":         week_num,
        "issue_total":      issue_total,
        "last_report_date": to_dt.isoformat(),
    }
    save_meta(new_meta)
    print(f"[gazette] meta saved")


if __name__ == "__main__":
    main()
