#!/usr/bin/env python3
"""변경사항 유형 분류 + 감성 분석 유틸리티."""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

# ──────────────────────────────────────────────
# 키워드 로드 (keywords.yaml)
# ──────────────────────────────────────────────

_keywords_cache: dict | None = None


def _load_keywords() -> dict:
    global _keywords_cache
    if _keywords_cache is None:
        import yaml
        kw_path = DATA_DIR / "keywords.yaml"
        with open(kw_path, encoding="utf-8") as f:
            _keywords_cache = yaml.safe_load(f)
    return _keywords_cache


# ──────────────────────────────────────────────
# 변경 유형 분류
# ──────────────────────────────────────────────

# 기본 내장 키워드 (keywords.yaml 로드 실패 시 fallback)
_DEFAULT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "사업확장": ["런칭", "출시", "오픈", "신규", "확대", "진출", "확장", "개시", "설립"],
    "기술":     ["AI", "인공지능", "업데이트", "개선", "LPR", "IoT", "자동화", "플랫폼", "시스템"],
    "제휴":     ["제휴", "MOU", "협약", "파트너", "협력", "계약", "합작"],
    "VOC":      ["불편", "오류", "버그", "문제", "민원", "별점", "리뷰", "장애", "먹통"],
    "정책":     ["정책", "약관", "요금", "수수료", "변경", "공지", "인상", "인하", "규정"],
}


def classify_change_type(title: str, summary: str | None = None) -> str:
    """제목/요약 텍스트에서 변경 유형을 추론."""
    text = (title + " " + (summary or "")).lower()

    try:
        kw_data = _load_keywords()
        type_kws = kw_data.get("cx_signals", _DEFAULT_TYPE_KEYWORDS)
    except Exception:
        type_kws = _DEFAULT_TYPE_KEYWORDS

    # 매칭된 키워드 수가 가장 많은 유형 선택
    scores: dict[str, int] = {}
    for type_name, keywords in type_kws.items():
        scores[type_name] = sum(1 for kw in keywords if kw.lower() in text)

    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "기타"


# ──────────────────────────────────────────────
# 감성 분류
# ──────────────────────────────────────────────

_DEFAULT_SENTIMENT: dict[str, list[str]] = {
    "positive": ["출시", "확장", "제휴", "성장", "개선", "호평", "편리", "혁신", "수상", "흑자"],
    "negative": ["오류", "장애", "민원", "불편", "피해", "지연", "불만", "적자", "소송", "과태료"],
}


def classify_sentiment(title: str, summary: str | None = None) -> str:
    """긍정 / 부정 / 중립 분류."""
    text = (title + " " + (summary or "")).lower()

    try:
        kw_data    = _load_keywords()
        senti_kws  = kw_data.get("sentiment", _DEFAULT_SENTIMENT)
    except Exception:
        senti_kws = _DEFAULT_SENTIMENT

    pos = sum(1 for kw in senti_kws.get("positive", []) if kw.lower() in text)
    neg = sum(1 for kw in senti_kws.get("negative", []) if kw.lower() in text)

    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


# ──────────────────────────────────────────────
# 6개월 이내 날짜 검증
# ──────────────────────────────────────────────

def is_within_6months(date_str: str) -> bool:
    """published_at 날짜가 6개월 이내인지 확인."""
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=180)
    try:
        dt = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
        return dt >= cutoff
    except ValueError:
        return True  # 파싱 불가 시 허용


# ──────────────────────────────────────────────
# 간단 셀프 테스트
# ──────────────────────────────────────────────

if __name__ == "__main__":
    cases = [
        "카카오모빌리티, AI 기반 주차 예측 서비스 출시",
        "하이파킹, 현대카드와 MOU 체결",
        "앱 오류로 결제 장애 발생 민원 급증",
        "모두의주차장 요금 정책 변경 공지",
        "일반적인 뉴스 기사 제목",
    ]
    for c in cases:
        t = classify_change_type(c)
        s = classify_sentiment(c)
        print(f"[{t:6s}|{s:8s}] {c}")
