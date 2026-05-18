#!/usr/bin/env python3
"""매일 오전 7시 슬랙 브리핑 발송.

환경변수:
    SLACK_WEBHOOK_URL  : Slack Incoming Webhook URL
    SPREADSHEET_ID     : Google Sheets ID (sheets.py 통해 읽기)
    GOOGLE_CREDENTIALS : 서비스 계정 JSON
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

import requests

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# 서비스 한글명
SERVICE_NAMES = {
    "kakaot_parking":  "카카오T 주차",
    "iparking":        "아이파킹",
    "nicepark":        "나이스파크",
    "amano_korea":     "아마노코리아",
    "highparking":     "투루파킹(하이파킹)",
    "parkingfriends":  "파킹프렌즈",
    "zoomansa":        "주만사",
    "moduparking":     "모두의주차장",
}

SOURCE_EMOJI = {
    "news":       "📰",
    "blog":       "📝",
    "cafe":       "☕",
    "html_diff":  "🌐",
    "html_list":  "📋",
    "appstore":   "⭐",
    "ios_appstore": "🍎",
    "youtube_rss": "▶️",
}

CHANGE_EMOJI = {
    "VOC":    "💬",
    "정책":   "📜",
    "기술":   "⚙️",
    "사업확장": "📈",
    "제휴":   "🤝",
    "기타":   "📌",
}


def _load_recent(hours: int = 27) -> list[dict]:
    """최근 N시간 항목 로드. Sheets 우선, 실패 시 SQLite."""
    cutoff = datetime.now() - timedelta(hours=hours)

    # Sheets에서 읽기 시도
    try:
        import sheets as sh_mod
        all_data = sh_mod.read_all_cached()
        result = []
        for row in all_data:
            try:
                pub = str(row.get("published_at", ""))[:10]
                if datetime.strptime(pub, "%Y-%m-%d") >= cutoff.replace(hour=0, minute=0):
                    result.append(row)
            except Exception:
                continue
        if result:
            log.info(f"[Briefing] Sheets에서 {len(result)}건 로드")
            return result
    except Exception as e:
        log.warning(f"[Briefing] Sheets 읽기 실패: {e}")

    # SQLite fallback
    try:
        import db
        db.init_db()
        rows = db.get_all_changes(limit=500)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        result = [r for r in rows if str(r.get("published_at", ""))[:10] >= cutoff_str]
        log.info(f"[Briefing] SQLite에서 {len(result)}건 로드")
        return result
    except Exception as e:
        log.error(f"[Briefing] SQLite 읽기 실패: {e}")
        return []


def _build_message(items: list[dict], date_str: str) -> dict:
    """Slack Block Kit 메시지 생성."""
    by_service: dict[str, list] = defaultdict(list)
    for item in items:
        svc = item.get("service_id", "unknown")
        by_service[svc].append(item)

    # 서비스별 섹션 빌드
    sections = []
    for svc_id, svc_items in sorted(by_service.items()):
        svc_name = SERVICE_NAMES.get(svc_id, svc_id)
        is_modu  = svc_id == "moduparking"
        header   = f"{'🏠 ' if is_modu else ''}*{svc_name}* — {len(svc_items)}건"

        lines = []
        for item in svc_items[:5]:  # 서비스당 최대 5건
            src_emoji    = SOURCE_EMOJI.get(item.get("source_type", ""), "•")
            change_emoji = CHANGE_EMOJI.get(item.get("change_type", ""), "")
            title        = (item.get("title") or "")[:60]
            url          = item.get("url") or ""
            text         = f"{src_emoji}{change_emoji} {f'<{url}|{title}>' if url else title}"
            lines.append(text)

        if len(svc_items) > 5:
            lines.append(f"_…외 {len(svc_items) - 5}건_")

        sections.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{header}\n" + "\n".join(lines),
            },
        })
        sections.append({"type": "divider"})

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🚗 주차 플랫폼 데일리 브리핑 — {date_str}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*총 {len(items)}건* 신규 수집 | 서비스 {len(by_service)}개",
            },
        },
        {"type": "divider"},
        *sections,
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "모두의주차장 CX운영파트 · THE PARKING GAZETTE 자동 브리핑",
                }
            ],
        },
    ]

    return {"blocks": blocks}


def send_briefing():
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        log.error("[Briefing] SLACK_WEBHOOK_URL 환경변수가 없습니다.")
        sys.exit(1)

    today = datetime.now().strftime("%Y년 %m월 %d일")
    items = _load_recent(hours=27)

    if not items:
        payload = {
            "text": f"🚗 주차 플랫폼 데일리 브리핑 — {today}\n어제 수집된 신규 항목이 없습니다."
        }
    else:
        payload = _build_message(items, today)

    resp = requests.post(webhook_url, json=payload, timeout=10)
    if resp.status_code == 200:
        log.info(f"[Briefing] 슬랙 발송 완료 — {len(items)}건")
    else:
        log.error(f"[Briefing] 슬랙 발송 실패: {resp.status_code} {resp.text}")
        sys.exit(1)


if __name__ == "__main__":
    send_briefing()
