"""Slack Incoming Webhook 발송 모듈.

환경변수:
    CSAT_SLACK_WEBHOOK_URL : Slack Incoming Webhook URL
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import requests

log = logging.getLogger(__name__)


def post_to_slack(message: str, webhook_url: str | None = None) -> bool:
    """Incoming Webhook으로 텍스트 메시지 발송."""
    url = webhook_url or os.environ.get("CSAT_SLACK_WEBHOOK_URL")
    if not url:
        log.warning("CSAT_SLACK_WEBHOOK_URL 미설정 — 발송 건너뜀")
        return False

    payload = {"text": message}
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        log.info("Slack 발송 성공 (%d bytes)", len(message))
        return True
    except requests.RequestException as e:
        log.error("Slack 발송 실패: %s", e)
        return False


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True, help="발송할 텍스트 파일 경로")
    p.add_argument("--dry-run", action="store_true",
                   help="실제 발송 없이 출력만")
    args = p.parse_args()

    text = Path(args.file).read_text(encoding="utf-8")
    if args.dry_run:
        print("=== DRY RUN ===")
        print(text)
        return

    ok = post_to_slack(text)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
