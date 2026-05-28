"""CSAT 리포트 HTML 생성기 (page1 + page2).

csat_processor.process_csat()가 만든 구조화 dict를 받아:
1) Claude API로 VOC 귀책 분류 + AI 제안 + 핵심 요약 도출
2) page1 (서비스 불만) / page2 (응대품질) HTML 두 개 생성
3) 슬랙 공유 메시지 텍스트 생성

환경변수:
    ANTHROPIC_API_KEY : Claude API 키
    CONFLUENCE_URL    : 리포트 Confluence 링크 (옵션)
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any

# anthropic는 LLM 분석에만 필요. 렌더링·슬랙 빌드는 패키지 없이도 동작해야
# 하므로(예: scripts/manual_rich_backfill.py 환경) 임포트를 lazy로 처리.
try:
    from anthropic import Anthropic  # type: ignore
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

MODEL = os.environ.get("CSAT_MODEL", "claude-sonnet-4-6")

# ── 공통 CSS ─────────────────────────────────────
COMMON_CSS = """
body{font-family:'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif;margin:0;padding:20px;background:#f5f6fa;color:#333}
.wrap{max-width:1100px;margin:0 auto}
.title{text-align:center;font-size:26px;font-weight:800;color:#1a1a2e;margin-bottom:6px}
.subtitle{text-align:center;font-size:13px;color:#888;margin-bottom:28px}
.kpi-row{display:flex;gap:14px;margin-bottom:28px;flex-wrap:wrap}
.kpi{flex:1;min-width:180px;background:#fff;border-radius:14px;padding:22px 16px;box-shadow:0 2px 10px rgba(0,0,0,.07);text-align:center;border-top:4px solid #4a90d9}
.kpi:nth-child(1){border-top-color:#4a90d9}
.kpi:nth-child(2){border-top-color:#e74c3c}
.kpi:nth-child(3){border-top-color:#f39c12}
.kpi:nth-child(4){border-top-color:#27ae60}
.kpi .icon{font-size:26px;margin-bottom:4px}
.kpi .label{font-size:12px;color:#999;margin-bottom:6px}
.kpi .value{font-size:28px;font-weight:800;color:#1a1a2e}
.kpi .sub{font-size:11px;color:#aaa;margin-top:4px}
.sec{background:#fff;border-radius:14px;padding:24px 28px;margin-bottom:22px;box-shadow:0 2px 10px rgba(0,0,0,.05)}
.sec-title{font-size:17px;font-weight:700;color:#1a1a2e;margin-bottom:14px;padding-bottom:8px;border-bottom:2px solid #f0f0f0}
table{width:100%;border-collapse:collapse;font-size:13px}
thead th{background:#2c3e50;color:#fff;padding:10px 12px;text-align:center;font-weight:600}
thead th:first-child{border-radius:6px 0 0 0}
thead th:last-child{border-radius:0 6px 0 0}
tbody td{padding:9px 12px;border-bottom:1px solid #f0f0f0;text-align:center}
tbody tr:nth-child(even){background:#f9fafb}
tbody tr:hover{background:#eef3ff}
.td-left{text-align:left}
.voc-row{display:flex;gap:14px;flex-wrap:wrap}
.voc{flex:1;min-width:260px;background:#fffef5;border-left:4px solid #f39c12;border-radius:10px;padding:16px}
.voc .meta{font-size:11px;color:#999;margin-bottom:8px}
.voc .tag{display:inline-block;background:#fff3cd;color:#856404;padding:2px 8px;border-radius:10px;font-size:10px;margin-left:4px}
.voc .badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;margin-left:4px}
.voc .badge-user{background:#f3f4f6;color:#6b7280}
.voc .badge-platform{background:#fdecea;color:#c62828}
.voc .badge-venue{background:#fff3e0;color:#e65100}
.voc .badge-unclear{background:#f3e8ff;color:#7e22ce}
.voc .body{font-size:13px;color:#555;font-style:italic;line-height:1.7}
.voc .note{font-size:11px;color:#999;margin-top:8px;font-style:normal}
.ai-row{display:flex;gap:14px;flex-wrap:wrap}
.ai{flex:1;min-width:260px;border-radius:12px;padding:18px;border:1px solid #d0e3ff}
.ai:nth-child(1){background:#f0f7ff}
.ai:nth-child(2){background:#f0fff4;border-color:#c6f6d5}
.ai:nth-child(3){background:#fffbeb;border-color:#fde68a}
.ai .ai-title{font-size:13px;font-weight:700;color:#2c5282;margin-bottom:6px}
.ai .ai-body{font-size:13px;color:#444;line-height:1.7}
.act{display:flex;align-items:flex-start;padding:9px 0;border-bottom:1px solid #f5f5f5}
.act-icon{font-size:17px;margin-right:10px;flex-shrink:0}
.act-text{font-size:13px;color:#333;line-height:1.6}
.sev-h{background:#fdecea;color:#c0392b;font-weight:700;border-radius:4px;padding:2px 8px;font-size:12px}
.sev-m{background:#fff3e0;color:#e67e22;font-weight:700;border-radius:4px;padding:2px 8px;font-size:12px}
.sev-l{background:#e8f5e9;color:#27ae60;font-weight:700;border-radius:4px;padding:2px 8px;font-size:12px}
.sat-g{background:#e8f5e9;color:#2e7d32;font-weight:700;padding:4px 10px;border-radius:4px}
.sat-n{background:#e3f2fd;color:#1565c0;font-weight:700;padding:4px 10px;border-radius:4px}
.sat-w{background:#fff3e0;color:#e65100;font-weight:700;padding:4px 10px;border-radius:4px}
.sat-d{background:#fdecea;color:#c62828;font-weight:700;padding:4px 10px;border-radius:4px}
.comp-row{display:flex;gap:14px;flex-wrap:wrap}
.comp{flex:1;min-width:200px;background:#fff;border-radius:10px;padding:18px;border-left:4px solid #ccc}
.footer{text-align:center;padding:22px;font-size:11px;color:#aaa;border-top:1px solid #eee;margin-top:30px}
"""

# ── 내부 정책 레퍼런스 (Claude system prompt에 캐싱) ──
POLICY_REFERENCE = """\
당신은 모두의주차장 거점운영팀 CSAT 분석 전문가입니다.

## [A] 서비스 유형 분류
- 제휴: 일반권(시간권·당일권), 월정기권, 사전구매(단기권)
- 자동결제: MPASS (월정액 구독형)
- 공유: 공유주차장

## [B] 환불 정책 핵심 기준
- 일반권 미사용: 결제일로부터 7일 내 전액 환불 가능
- 일반권 사용 후: 원칙 환불 불가. 단, 입차 후 15분 이내 출차 시 환불 가능, 30분 이내 + 주차장 귀책 시 환불 가능
- 월정기권 중도환불: (결제금액 − 일최대요금 × 이용일수) × 0.8 — 잔여 기간 없으면 환불 불가
- 사전구매(단기권): 주차 시작 12시간 전 무료 취소 / 12시간 이내 취소 시 1만원 수수료
- MPASS: 이미 결제된 금액 환불 원칙 불가 (장애·시스템 오류 시 예외)
- 공유주차: 결제 후 2시간 이내, 사용 전에만 환불 가능
- 현장 이중결제: 결제일로부터 14일 내 접수. 이용자 과실 시 환불 불가, 시스템·현장 오류 시 환불 가능

## [C] 귀책 판단 기준 (VOC 분류 핵심)
- 이용자 귀책: 이용 수칙 위반, 입차 후 장시간 사용, 환불기간 초과, 과실 이중결제 → 환불 거절은 정상 처리. CS 오류 아님.
- 모두의주차장 귀책: 시스템 오류, 서비스 장애로 주차권 미적용, 차단기 오류 이중결제 → 환불 + 보상 쿠폰 필요. 미이행 시 CS 오류.
- 현장(제휴처) 귀책: 만차 미안내, 정보 오기재, 공사·폐쇄 미안내 → 환불 처리 필요. 현장 귀책으로 기록.
- 귀책 불명확: 입출차 기록 미확보, 고객 주장만 있는 경우 → 입출차 기록 확인 필요로 분류.

## [D] CS 보상 정책
- 상담사: 10,000P (즉시 지급)
- 파트장: 30,000P (파트장 승인)
- 팀장: 50,000P (팀장 승인)
- CS 보상 쿠폰: 3,000P, 유효기간 1개월, 제휴주차장 한정
- 보상 제외: 이용자 명백한 과실, 이용 수칙 미준수, 주차장 현장 이슈(도난·분실·사고)
"""


# ── Claude API: VOC 분석 + AI 제안 자동 도출 ─────
def llm_analyze(data: dict[str, Any]) -> dict[str, Any]:
    """Claude API로 VOC 귀책 분류, AI 제안, 핵심 요약 등을 한 번에 도출."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY 미설정 — 룰베이스 폴백 사용")
        return _fallback_analysis(data)
    if Anthropic is None:
        log.warning("anthropic 패키지 미설치 — 룰베이스 폴백 사용")
        return _fallback_analysis(data)

    client = Anthropic(api_key=api_key)

    voc_excerpts = []
    for i, v in enumerate(data["voc_raw"][:30]):
        voc_excerpts.append({
            "index": i,
            "date": v.get("date_md", ""),
            "lot": v.get("lot", ""),
            "category": f"{v.get('cat','')} > {v.get('mid','')} > {v.get('sub','')}",
            "agent": v.get("agent", ""),
            "res1st": v.get("res1st", ""),
            "dis_subj": v.get("dis_subj", ""),
            "wish": v.get("wish", "")[:300],
            "unresolved": v.get("unresolved_reason", "")[:300],
            "summary": v.get("summary", ""),
        })

    payload = {
        "label": data["label"],
        "kpi_basic": data["kpi_basic"],
        "item_sat": data["item_sat"],
        "category_dist": data["category_dist"],
        "sub_category": data["sub_category"][:10],
        "unresolved_classified": data["unresolved_classified"],
        "voc_excerpts": voc_excerpts,
    }

    user_prompt = f"""다음 {data['label']} CSAT 분석 데이터를 보고 아래 JSON 스키마로만 응답하세요.

## 데이터
{json.dumps(payload, ensure_ascii=False, indent=2)}

## 출력 스키마 (JSON만, 다른 텍스트 금지)
{{
  "voc_analyses": [
    {{
      "index": 0,
      "guichaek": "이용자 귀책|모두의주차장 귀책|현장 귀책|귀책 불명확",
      "policy_basis": "정책 근거 한 줄 (예: '환불 정책 [B] - 일반권 사용 후 30분 초과')",
      "use_in_page1": true,
      "use_in_page2": false,
      "tag_text": "환불|환불 요청|주차권 이용 등 짧은 태그"
    }}
  ],
  "service_complaints_page1": [
    {{
      "icon": "💰", "title": "환불 정책 경직성",
      "color": "#e74c3c",
      "count_text": "(62건 · 38.0%)",
      "body": "2~4문장. 수치(N건·X%) + VOC 실제 표현 인용(작은따옴표) + 어떤 정책·프로세스의 어떤 지점이 문제인지 구체 명시. <br>로 줄바꿈 가능."
    }}
  ],
  "response_quality_page2": [
    {{
      "icon": "💬", "title": "상담 응대 지연",
      "color": "#e74c3c",
      "count_text": "(15건)",
      "body": "2~4문장. 수치 + VOC 실제 표현(예: 'AI같은 답변', '같은 말 반복') 인용 + 어느 상담 단계의 문제인지 구체. <br> 사용 가능."
    }}
  ],
  "ai_suggestions_page1": [
    {{"icon": "💡", "title": "🤖 AI 제안 1 — <서술형 헤드라인 (예: '환불 프로세스 UX 전면 개선')>",
      "body": "3~5문장. 패턴: ① 현황 진단(N건·X%, 역대 최다/전월 대비 등 비교) ② 구체 사례·VOC 표현 인용(작은따옴표) ③ 실행 권고 — 어느 화면/프로세스/정책의 무엇을 어떻게 바꿀지 명시(예: '결제 화면 내 환불 가능 시간·절차 안내 삽입', '앱 내 야간 환불 접수 채널 마련')."}},
    {{"icon": "🎯", "title": "🤖 AI 제안 2 — <서술형 헤드라인>", "body": "위 동일 패턴, 다른 주제."}},
    {{"icon": "🔧", "title": "🤖 AI 제안 3 — <서술형 헤드라인>", "body": "위 동일 패턴, 다른 주제."}}
  ],
  "ai_suggestions_page2": [
    {{"icon": "💡", "title": "🤖 AI 제안 1 — <서술형 헤드라인>",
      "body": "응대품질 관점 3~5문장. 수치 + 실제 응대 표현 인용 + 교육/스크립트/KPI/시스템 액션 중 무엇을 어떻게(예: '케이스별 맞춤 응대 스크립트 도입', '상담원 공감 역량 KPI 신설', '10,000P 보상 권한 적극 활용')."}},
    {{"icon": "🎯", "title": "🤖 AI 제안 2 — <서술형 헤드라인>", "body": "위 동일 패턴."}},
    {{"icon": "🔧", "title": "🤖 AI 제안 3 — <서술형 헤드라인>", "body": "위 동일 패턴."}}
  ],
  "summary_page1": [
    {{"level": "🔴", "text": "<수치·항목 진단 + ' — ' + 구체 액션. 예: '환불 불만 95건(40.3%) 역대 최다 — 앱 내 야간 환불 접수 불가 프로세스 즉시 개선 필요'>"}},
    {{"level": "🟡", "text": "<단기 — 동일 형식>"}},
    {{"level": "🟢", "text": "<중기 — 동일 형식>"}},
    {{"level": "🔵", "text": "<장기 — 동일 형식>"}}
  ],
  "summary_page2": [...]
}}

## 작성 규칙
1. voc_analyses: voc_excerpts 전체에 대해 귀책 판단. [C] 귀책 판단 기준 엄격 적용. 추측 금지.
2. page1 (서비스 불만): AF<0이고 환불·주차이용·현장 관련 + 귀책이 '모두의주차장 귀책' 또는 '현장 귀책'인 3건을 use_in_page1=true
3. page2 (응대품질): AF<0이고 상담응대·해결불만족·안내오류 관련 + 개선가능성 있는 3건을 use_in_page2=true
4. 이용자 귀책으로 판단된 VOC는 use_in_page1=false, use_in_page2=false
5. service_complaints_page1: 4개 카드. 환불/주차권·이용/결제·시스템/현장업체 카테고리 기반. body는 2~4문장, 수치·VOC 표현 인용·구체 지점 포함.
6. response_quality_page2: 4개 카드. 상담응대지연/채팅자동종료/기계적응대/환불안내불일치 기반. body는 2~4문장, 수치·실제 응대 표현 인용 포함.
7. ai_suggestions_page1/page2: 정확히 3개씩. **title은 '🤖 AI 제안 N — <서술형 헤드라인>' 형식** (예: '🤖 AI 제안 1 — 환불 프로세스 UX 전면 개선'). **body는 3~5문장**, 패턴: [현황 수치 진단] + [구체 사례·VOC 표현 인용(작은따옴표)] + [실행 권고 — 어느 화면/프로세스/정책의 무엇을 어떻게]. [A][B][C][D] 정책 근거 반영. 이용자 귀책 불만이면 '정책 안내 강화' 방향.
8. summary_page1/page2: 각 4~6개. 🔴(긴급) 🟡(단기) 🟢(중기) 🔵(장기) 순서. **text는 '<수치·항목 진단> — <구체 액션>' 형식** (예: '1차 해결률 62.3%(전월 55.2% 대비 +7.1%p) — 개선 추세 유지 및 환불 분야 집중 관리'). 데이터에서 직접 도출, 모호한 일반 표현 금지.
9. 모든 수치는 데이터에서 정확히 가져와야 함. 추측 금지.
10. **구체성 우선 원칙**: '교육 강화', '프로세스 개선' 같은 일반론 단독 금지. 반드시 어떤 화면·프로세스·정책·KPI의 무엇을 어떻게 바꿀지 명시. CSAT 항목명·VOC 카테고리·정책 코드([A]/[B]/[C]/[D]) 등 고유명을 활용해 식별 가능하게.
11. JSON만 출력. 코드 블록 ```json 도 금지. 순수 JSON 텍스트만."""

    log.info("Claude API 호출 (model=%s)", MODEL)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=12000,
        system=[
            {
                "type": "text",
                "text": POLICY_REFERENCE,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = "".join(
        block.text for block in msg.content if hasattr(block, "text")
    ).strip()

    # ```json ... ``` 코드 펜스 제거 (방어용)
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        log.error("LLM JSON 파싱 실패: %s\n응답:\n%s", e, text[:1000])
        return _fallback_analysis(data)

    log.info("Claude 토큰: in=%d (cached=%d) out=%d",
             getattr(msg.usage, "input_tokens", 0),
             getattr(msg.usage, "cache_read_input_tokens", 0)
             + getattr(msg.usage, "cache_creation_input_tokens", 0),
             getattr(msg.usage, "output_tokens", 0))
    return parsed


def _fallback_analysis(data: dict[str, Any]) -> dict[str, Any]:
    """API 키 없거나 LLM 실패 시 룰베이스 폴백."""
    top_voc = data["voc_raw"][:6]
    voc_analyses = []
    for i, v in enumerate(top_voc):
        voc_analyses.append({
            "index": i,
            "guichaek": "귀책 불명확",
            "policy_basis": "(LLM 미사용 — 추가 확인 필요)",
            "use_in_page1": i < 3,
            "use_in_page2": 3 <= i < 6,
            "tag_text": v.get("sub", "") or "VOC",
        })
    n = data["kpi_basic"]["n"]
    return {
        "voc_analyses": voc_analyses,
        "service_complaints_page1": [
            {"icon": "💰", "title": "환불 정책 경직성", "color": "#e74c3c",
             "count_text": f"({data['kpi_basic']['refund_count']}건 · {data['kpi_basic']['refund_rate']}%)",
             "body": "환불 관련 불만이 가장 많이 접수되었습니다."},
            {"icon": "🎫", "title": "주차권/이용 불편", "color": "#f39c12",
             "count_text": "", "body": "주차권 이용 관련 문의가 지속 접수."},
            {"icon": "💻", "title": "결제/시스템 오류", "color": "#3498db",
             "count_text": "", "body": "결제·시스템 오류 관련 문의."},
            {"icon": "🏢", "title": "현장 업체 관리", "color": "#8e44ad",
             "count_text": "", "body": "제휴 업체 관련 민원."},
        ],
        "response_quality_page2": [
            {"icon": "💬", "title": "상담 응대 지연", "color": "#e74c3c",
             "count_text": "", "body": "응답 지연 관련 불만."},
            {"icon": "⏱️", "title": "채팅 자동종료", "color": "#f39c12",
             "count_text": "", "body": "자동종료로 인한 중단."},
            {"icon": "🤖", "title": "기계적/매뉴얼 응대", "color": "#8e44ad",
             "count_text": "", "body": "맥락 파악 부족."},
            {"icon": "💰", "title": "환불 안내 불일치", "color": "#3498db",
             "count_text": "", "body": "환불 정책 안내 차이."},
        ],
        "ai_suggestions_page1": [
            {"icon": "💡", "title": "🤖 AI 제안 1",
             "body": "최하위 항목 기반 교육 강화."},
            {"icon": "🎯", "title": "🤖 AI 제안 2",
             "body": "미해결 사유 1위 프로세스 개선."},
            {"icon": "🔧", "title": "🤖 AI 제안 3",
             "body": "환불 분야 프로세스 재검토."},
        ],
        "ai_suggestions_page2": [
            {"icon": "💡", "title": "🤖 AI 제안 1",
             "body": "응답 시간 단축 SLA 도입."},
            {"icon": "🎯", "title": "🤖 AI 제안 2",
             "body": "채팅 자동종료 시간 확대."},
            {"icon": "🔧", "title": "🤖 AI 제안 3",
             "body": "환불 정책 상담원 재교육."},
        ],
        "summary_page1": [
            {"level": "🔴", "text": f"완료 {n}건 중 불만족 {data['kpi_basic']['af_neg']}건 — 긴급 대응"},
            {"level": "🟡", "text": "1차 해결률 개선"},
            {"level": "🟢", "text": "VOC 패턴 분석"},
            {"level": "🔵", "text": "장기 모니터링 체계 구축"},
        ],
        "summary_page2": [
            {"level": "🔴", "text": "응대품질 최하위 항목 긴급 개선"},
            {"level": "🟡", "text": "상담원 교육 강화"},
            {"level": "🟢", "text": "CSAT 응답률 제고"},
            {"level": "🔵", "text": "AI 응대 시스템 검토"},
        ],
    }


# ── HTML 렌더링 ──────────────────────────────────
def _sat_grade(rate: float) -> tuple[str, str]:
    if rate >= 80:
        return "sat-g", "양호"
    if rate >= 70:
        return "sat-n", "보통"
    if rate >= 60:
        return "sat-w", "주의"
    return "sat-d", "위험"


def _badge_class(guichaek: str) -> str:
    return {
        "이용자 귀책": "badge-user",
        "모두의주차장 귀책": "badge-platform",
        "현장 귀책": "badge-venue",
        "귀책 불명확": "badge-unclear",
    }.get(guichaek, "badge-unclear")


def _voc_card_html(
    voc: dict, analysis: dict | None, page: str
) -> str:
    """단일 VOC 카드 렌더링."""
    badge_cls = _badge_class(analysis["guichaek"]) if analysis else "badge-unclear"
    badge_text = analysis["guichaek"] if analysis else "귀책 불명확"
    tag_text = analysis.get("tag_text", "") if analysis else voc.get("sub", "")
    policy_basis = analysis.get("policy_basis", "") if analysis else ""

    summary = voc.get("summary", "") or voc.get("wish", "") or voc.get("unresolved_reason", "")
    # 양 끝 따옴표가 없으면 추가
    summary = summary.strip()
    if not summary.startswith(('"', '"', "'")):
        summary = f'"{summary}"'

    # 이용자 귀책 + page2의 경우 정책상 정당 거절 주석
    extra_note = ""
    if page == "page2" and analysis and analysis["guichaek"] == "이용자 귀책":
        extra_note = '<div class="note">※ 정책상 정당한 거절 사례 — 상담사 안내 내용은 적절할 수 있음</div>'
    elif policy_basis:
        extra_note = f'<div class="note">근거: {escape(policy_basis)}</div>'

    return f"""<div class="voc">
<div class="meta">📅 {escape(voc.get('date_md',''))} <span class="tag">{escape(tag_text)}</span> <span class="badge {badge_cls}">{escape(badge_text)}</span></div>
<div class="body">{escape(summary)}</div>
{extra_note}
</div>"""


def _kpi_card_html(icon: str, label: str, value: str, sub: str = "",
                   value_size: str = "") -> str:
    sub_html = f'<div class="sub">{escape(sub)}</div>' if sub else ""
    vstyle = f' style="font-size:{value_size}"' if value_size else ""
    return f"""<div class="kpi"><div class="icon">{icon}</div><div class="label">{escape(label)}</div><div class="value"{vstyle}>{escape(value)}</div>{sub_html}</div>"""


def _kpi_row_html(cards: list) -> str:
    """KPI 카드들을 한 행으로 렌더. 행 안의 값 글씨 크기를 '가장 긴 값' 기준으로
    통일해 카드 간 균형 유지. cards = [(icon, label, value, sub), ...] (sub 생략 가능).
    """
    maxlen = max((len(str(c[2])) for c in cards), default=0)
    if maxlen >= 12:
        vsize = "18px"
    elif maxlen >= 8:
        vsize = "22px"
    else:
        vsize = "28px"
    inner = "".join(
        _kpi_card_html(c[0], c[1], c[2], c[3] if len(c) > 3 else "", vsize)
        for c in cards
    )
    return '<div class="kpi-row">' + inner + "</div>"


def _table_html(headers: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body_rows = []
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            cls = "td-left" if i == 0 else ""
            cls_attr = f' class="{cls}"' if cls else ""
            cells.append(f"<td{cls_attr}>{cell}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _comp_card_html(c: dict) -> str:
    count_html = (f'<span style="font-size:11px;font-weight:400;color:#999">{escape(c["count_text"])}</span>'
                  if c.get("count_text") else "")
    return f"""<div class="comp" style="border-left-color:{escape(c['color'])}">
<div style="font-weight:700;color:{escape(c['color'])};margin-bottom:6px">{c['icon']} {escape(c['title'])} {count_html}</div>
<div style="font-size:13px;color:#555;line-height:1.8">{c['body']}</div>
</div>"""


def _csat_question(full: str) -> str:
    """full_name('품질1. 질문...')에서 질문 본문만 추출. 접두어 없으면 원문."""
    full = (full or "").strip()
    dot = full.find(". ")
    return full[dot + 2:] if 0 < dot < 8 else full


def group_item_sat(item_sat: list[dict]) -> list[dict]:
    """동일 질문(문항 텍스트 일치)을 한 행으로 통합.

    CSAT 설문은 품질/전문성/복합 세 유형으로 분기되는데 일부 문항이
    유형만 다르게 중복 출제됨(예: '품질1'='전문성1'). 같은 질문은
    응답을 합산(pos·tot)하여 단일 행으로 표시한다. 등장 순서 유지.
    """
    from collections import OrderedDict
    groups: "OrderedDict[str, dict]" = OrderedDict()
    for it in item_sat:
        q = _csat_question(it.get("full_name", "")) or it.get("short_name", "")
        g = groups.setdefault(q, {"tags": [], "question": q, "pos": 0, "tot": 0})
        g["tags"].append(it.get("short_name", ""))
        g["pos"] += it.get("pos", 0)
        g["tot"] += it.get("tot", 0)
    out = []
    for g in groups.values():
        tot = g["tot"]
        out.append({
            "tags": "·".join(g["tags"]),
            "question": g["question"],
            "pos": g["pos"],
            "tot": tot,
            "rate": round(g["pos"] / tot * 100, 1) if tot else 0.0,
            "dup": len(g["tags"]) > 1,
        })
    return out


def _item_label_html(it: dict) -> str:
    """항목표 라벨: 실제 설문 질문만 표시(품질1·전문성2 등 약어 미표시).

    중복 출제된 동일 질문은 작은 '통합' 배지로만 표시.
    """
    question = it.get("question")
    if question is None:
        question = _csat_question(it.get("full_name", "")) or it.get("short_name", "")
    dup_badge = (
        ' <span style="font-size:9px;background:#eef2ff;color:#3b5bdb;'
        'padding:1px 6px;border-radius:8px;vertical-align:middle">통합</span>'
        if it.get("dup") else ""
    )
    return f'<span style="color:#333">{escape(question)}</span>{dup_badge}'


def _ai_card_html(a: dict) -> str:
    return f"""<div class="ai">
<div class="ai-title">{a['icon']} {escape(a['title'])}</div>
<div class="ai-body">{escape(a['body'])}</div>
</div>"""


def _act_html(level: str, text: str) -> str:
    return f"""<div class="act"><span class="act-icon">{level}</span><span class="act-text">{escape(text)}</span></div>"""


def _wrap_html(title: str, subtitle: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><title>{escape(title)}</title>
<style>{COMMON_CSS}</style>
</head><body>
<div class="wrap">
<div class="title">{title}</div>
<div class="subtitle">{escape(subtitle)}</div>
{body}
<div class="footer">Generated by 모두의주차장 CSAT 자동 리포트 시스템 🤖</div>
</div></body></html>"""


def _app_review_section_html(app: dict | None, llm: dict) -> str:
    """page1 하단 '앱 리뷰 분석' 섹션. app 데이터 없으면 빈 문자열 반환.

    app = {count, avg_rating, platform{iOS,Android}, star_dist{1..5},
           sentiment{negative,neutral}, neg_pct}
    llm = app_review_summary(str), app_review_themes(list), app_review_csat_link(str)
    """
    if not app or not app.get("count"):
        return ""
    plat = app.get("platform", {})
    plat_str = " · ".join(f"{p} {c}" for p, c in plat.items()) or "-"
    sd = app.get("star_dist", {})
    star_str = " · ".join(
        f"★{s} {sd.get(str(s), sd.get(s, 0))}건"
        for s in (5, 4, 3, 2, 1)
        if (sd.get(str(s), sd.get(s, 0)))
    ) or "-"
    neg = app.get("sentiment", {}).get("negative", 0)

    kpi = _kpi_row_html([
        ("📱", "앱 리뷰 수", f"{app['count']}건", "스토어 직접 수집"),
        ("⭐", "평균 별점", f"{app.get('avg_rating', '-')}", "5점 만점"),
        ("📲", "플랫폼", plat_str, "iOS · Android"),
        ("😞", "부정 리뷰 비율", f"{app.get('neg_pct', '-')}%", f"부정 {neg}건"),
    ])
    summary = llm.get("app_review_summary", "")
    summary_html = (
        f'<p style="font-size:13px;color:#555;line-height:1.7;margin:0 0 14px">'
        f'{escape(summary)}</p>' if summary else ""
    )
    star_html = (
        f'<p style="font-size:12px;color:#777;margin:0 0 16px">'
        f'<b>별점 분포</b> &nbsp; {escape(star_str)}</p>'
    )
    themes = llm.get("app_review_themes", [])
    themes_html = (
        '<div class="comp-row">' + "".join(_comp_card_html(c) for c in themes) + "</div>"
        if themes else ""
    )
    csat_link = llm.get("app_review_csat_link", "")
    csat_html = (
        f'<div class="ai" style="margin-top:14px;background:#f0f7ff;border:1px solid #d0e3ff">'
        f'<div class="ai-title">🔗 CSAT 교차 시사점</div>'
        f'<div class="ai-body">{escape(csat_link)}</div></div>' if csat_link else ""
    )
    return f"""<div class="sec">
<div class="sec-title">📱 앱 리뷰 분석 (App Store · Google Play 직접 수집)</div>
{summary_html}{kpi}{star_html}{themes_html}{csat_html}
</div>"""


# ── Page 1: 서비스 불만 분석 ────────────────────
def render_page1(data: dict, llm: dict) -> str:
    k = data["kpi_basic"]
    top_sub = data["sub_category"][0] if data["sub_category"] else {"name": "-", "count": 0}

    kpi_html = _kpi_row_html([
        ("📋", "총 발송 건수", f"{k['sent']}건", f"분석 대상(완료): {k['n']}건"),
        ("🔥", "최다 불만 유형", top_sub["name"], f"{top_sub['count']}건"),
        ("💰", "환불 관련 비율", f"{k['refund_rate']}%", "소분류 기준"),
        ("⏳", "미해결 건수", f"{k['res1st_fail']}건", "1차 해결 실패"),
    ])

    cat_rows = [
        [escape(c["name"]), f"{c['count']}건", f"{c['pct']}%",
         str(c["af_pos"]), str(c["af_neg"])]
        for c in data["category_dist"]
    ]
    cat_table = _table_html(
        ["분류", "건수", "비율", "AF만족", "AF불만"], cat_rows
    )

    parking_rows = []
    for i, p in enumerate(data["parking_complaints"][:5], 1):
        parking_rows.append([f"{i}", escape(p["name"]), f"{p['neg']}건"])
    if not parking_rows:
        parking_rows = [["-", "(데이터 없음)", "-"]]
    parking_table = _table_html(["순위", "주차장명", "불만 건수"], parking_rows)

    comp_html = '<div class="comp-row">' + "".join(
        _comp_card_html(c) for c in llm["service_complaints_page1"]
    ) + "</div>"

    unresolved_rows = [
        [escape(u["name"]), f"{u['count']}건", f"{u['pct']}%"]
        for u in data["unresolved_classified"]
    ]
    unresolved_rows.append(
        [
            '<span style="font-weight:700">합계</span>',
            f'<span style="font-weight:700">{data["unresolved_total"]}건</span>',
            '<span style="font-weight:700">100%</span>',
        ]
    )
    unresolved_table = _table_html(["사유 분류", "건수", "비율"], unresolved_rows)

    voc_cards = []
    voc_analyses = {a["index"]: a for a in llm["voc_analyses"]}
    page1_indices = [a["index"] for a in llm["voc_analyses"] if a.get("use_in_page1")][:3]
    for idx in page1_indices:
        if idx < len(data["voc_raw"]):
            voc_cards.append(_voc_card_html(data["voc_raw"][idx], voc_analyses[idx], "page1"))
    voc_html = '<div class="voc-row">' + "".join(voc_cards) + "</div>" if voc_cards else "<p>(VOC 없음)</p>"

    ai_html = '<div class="ai-row">' + "".join(_ai_card_html(a) for a in llm["ai_suggestions_page1"]) + "</div>"
    summary_html = "".join(_act_html(s["level"], s["text"]) for s in llm["summary_page1"])
    app_review_html = _app_review_section_html(data.get("app_reviews"), llm)

    body = f"""
{kpi_html}
<div class="sec">
<div class="sec-title">📌 문의 유형 분류 현황 (대분류)</div>
{cat_table}
</div>
<div class="sec">
<div class="sec-title">🏢 불만 접수 상위 주차장 Top 5</div>
{parking_table}
</div>
<div class="sec">
<div class="sec-title">⚠️ 주요 서비스 불만 현황</div>
{comp_html}
</div>
<div class="sec">
<div class="sec-title">🔍 미해결 사유 분석</div>
{unresolved_table}
</div>
<div class="sec">
<div class="sec-title">🗣️ 주요 불만 VOC</div>
{voc_html}
</div>
<div class="sec">
<div class="sec-title">🤖 AI 개선 제안</div>
{ai_html}
</div>
<div class="sec">
<div class="sec-title">📋 핵심 요약 및 우선순위 개선사항</div>
{summary_html}
</div>
{app_review_html}
"""
    return _wrap_html(
        "📊 서비스 불만 분석 리포트",
        f"모두의주차장 CSAT 분석 · {date.today().isoformat()}",
        body,
    )


# ── Page 2: 응대품질 분석 ────────────────────────
def render_page2(data: dict, llm: dict) -> str:
    k = data["kpi_basic"]

    kpi_html = _kpi_row_html([
        ("📋", "완료(분석대상) 건수", f"{k['n']}건"),
        ("📝", "CSAT 응답 건수", f"{k['csat_respondent_count']}건"),
        ("😊", "만족+매우만족 비율", f"{k['csat_rate']}%"),
        ("✅", "1차 해결률", f"{k['res1st_rate']}%"),
    ])

    cat_rows = [
        [escape(c["name"]), f"{c['count']}건", f"{c['pct']}%",
         str(c["af_pos"]), str(c["af_neg"])]
        for c in data["category_dist"]
    ]
    cat_table = _table_html(["분류", "건수", "비율", "AF만족", "AF불만"], cat_rows)

    unresolved_rows = [
        [escape(u["name"]), f"{u['count']}건", f"{u['pct']}%"]
        for u in data["unresolved_classified"]
    ]
    unresolved_rows.append(
        [
            '<span style="font-weight:700">합계</span>',
            f'<span style="font-weight:700">{data["unresolved_total"]}건</span>',
            '<span style="font-weight:700">100%</span>',
        ]
    )
    unresolved_table = _table_html(["사유 분류", "건수", "비율"], unresolved_rows)

    comp_html = '<div class="comp-row">' + "".join(
        _comp_card_html(c) for c in llm["response_quality_page2"]
    ) + "</div>"

    item_rows = []
    for it in group_item_sat(data["item_sat"]):
        cls, grade = _sat_grade(it["rate"])
        item_rows.append([
            _item_label_html(it),
            f'<span class="{cls}">{it["rate"]}%</span>',
            f'{it["tot"]}건',
            grade,
        ])
    item_table = _table_html(
        ["설문 항목 (실제 질문)", "만족률", "응답 수", "등급"], item_rows
    )

    voc_cards = []
    voc_analyses = {a["index"]: a for a in llm["voc_analyses"]}
    page2_indices = [a["index"] for a in llm["voc_analyses"] if a.get("use_in_page2")][:3]
    for idx in page2_indices:
        if idx < len(data["voc_raw"]):
            voc_cards.append(_voc_card_html(data["voc_raw"][idx], voc_analyses[idx], "page2"))
    voc_html = '<div class="voc-row">' + "".join(voc_cards) + "</div>" if voc_cards else "<p>(VOC 없음)</p>"

    sub_rows = []
    for s in data["sub_category"][:5]:
        sub_rows.append([
            escape(s["name"]),
            f"{s['count']}건",
            '<span class="sev-h">높음</span>' if s["count"] >= 10
            else ('<span class="sev-m">중간</span>' if s["count"] >= 5
                  else '<span class="sev-l">낮음</span>'),
            str(s["af_pos"]),
            str(s["af_neg"]),
        ])
    sub_table = _table_html(["카테고리", "건수", "심각도", "AF만족", "AF불만"], sub_rows)

    ai_html = '<div class="ai-row">' + "".join(_ai_card_html(a) for a in llm["ai_suggestions_page2"]) + "</div>"
    summary_html = "".join(_act_html(s["level"], s["text"]) for s in llm["summary_page2"])

    body = f"""
{kpi_html}
<div class="sec">
<div class="sec-title">📌 문의 유형 분류 현황 (대분류)</div>
{cat_table}
</div>
<div class="sec">
<div class="sec-title">🔍 미해결 사유 분석</div>
{unresolved_table}
</div>
<div class="sec">
<div class="sec-title">⚠️ 주요 응대품질 이슈 현황</div>
{comp_html}
</div>
<div class="sec">
<div class="sec-title">📊 항목별 만족도 분석</div>
<p style="font-size:11px;color:#777;margin-bottom:6px;line-height:1.6">
각 행은 실제 설문 질문입니다. 응답자는 문항 세트(3종) 중 하나에 답하므로 질문별 응답 수가 다릅니다.
'<b>응답 수</b>'는 해당 질문에 답한 전체 인원이며, <b>만족률</b>은 그중 만족(매우만족 포함)의 비율입니다.
같은 질문이 중복 출제된 경우 <b>통합</b> 배지와 함께 한 행으로 합산했습니다.</p>
<p style="font-size:11px;color:#999;margin-bottom:10px">🟢 80%↑ 양호 &nbsp;|&nbsp; 🔵 70%↑ 보통 &nbsp;|&nbsp; 🟠 60%↑ 주의 &nbsp;|&nbsp; 🔴 60%↓ 위험</p>
{item_table}
</div>
<div class="sec">
<div class="sec-title">🗣️ 주요 불만 VOC</div>
{voc_html}
</div>
<div class="sec">
<div class="sec-title">🚨 주요 불만 이슈 Top 5 (소분류)</div>
{sub_table}
</div>
<div class="sec">
<div class="sec-title">🤖 AI 개선 제안</div>
{ai_html}
</div>
<div class="sec">
<div class="sec-title">📋 핵심 요약 및 즉시 개선 액션</div>
{summary_html}
</div>
"""
    return _wrap_html(
        "📞 고객센터 응대품질 분석 리포트",
        f"모두의주차장 CSAT 분석 · {date.today().isoformat()}",
        body,
    )


# ── 슬랙 공유 메시지 ─────────────────────────────
def build_slack_message(data: dict, llm: dict, confluence_url: str = "") -> str:
    label = data["label"]
    month_only = f"{data['month']}월"
    k = data["kpi_basic"]
    top_sub = data["sub_category"][0] if data["sub_category"] else {"name": "-", "count": 0, "pct": 0}

    comp_lines = []
    for c in llm["service_complaints_page1"][:4]:
        body_one = re.sub(r"<br\s*/?>", " ", c["body"]).replace("\n", " ").strip()
        body_one = re.sub(r"\s+", " ", body_one)
        body_one = body_one[:80] + "..." if len(body_one) > 80 else body_one
        comp_lines.append(f"• {c['title']} {c.get('count_text','')} — {body_one}")

    confluence_line = confluence_url if confluence_url else "[Confluence 링크 입력]"

    return f"""[공유] {month_only} 고객 만족도(CSAT) 및 불만 분석 리포트

안녕하세요, 거점운영팀 킬로입니다.
우리 서비스가 현장에서 고객에게 더 친절하고 편리한 경험을 제공할 수 있도록, 만족도를 발송하여 수집한 고객의 소리에 대해 AI를 활용하여 분석 리포트를 발행하여 공유드립니다.

만족도 (CSAT: Customer Satisfaction) 분석이란?
고객이 남긴 목소리(VOC)를 AI로 심층 분석하여 우리의 서비스 정책이나 운영 방식 중 무엇이 고객을 불편하게 만드는지를 파악하는 지표입니다. 데이터 기반의 분석을 통해 더욱 고객 친화적인 서비스가 될 수 있도록 개선해 가고자 합니다.

{month_only} 주요 분석 결과
• 총 발송 건수 : {k['sent']}건
• 회신 건수 : {k['n']}건 (분석 대상)
• 최다 불만 유형 : {top_sub['name']} ({top_sub['count']}건 / {top_sub.get('pct',0)}%)

주요 서비스 불만 현황
{chr(10).join(comp_lines)}

상세 리포트 확인하기 (Confluence)
{confluence_line}

매월 업데이트 및 피드백 요청
본 리포트는 매월 정기적으로 업데이트하여 공유드릴 예정입니다. 궁금하신 점이나 "이런 데이터가 추가로 보고 싶다" 하는 의견이 있다면 언제든 스레드 또는 DM으로 말씀해 주세요! 가능한 부분은 적극 반영하여 더 나은 서비스를 함께 만들어 가겠습니다."""


# ── CLI ──────────────────────────────────────────
def generate_all(
    data: dict,
    out_dir: Path,
    confluence_url: str = "",
) -> dict[str, Path | str]:
    """data dict 받아서 page1/page2 HTML + 슬랙 메시지 생성."""
    llm = llm_analyze(data)

    page1_html = render_page1(data, llm)
    page2_html = render_page2(data, llm)
    slack_msg = build_slack_message(data, llm, confluence_url)

    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{data['year']}-{data['month']:02d}"
    p1 = out_dir / f"{prefix}_page1.html"
    p2 = out_dir / f"{prefix}_page2.html"
    slack = out_dir / f"{prefix}_slack.txt"
    p1.write_text(page1_html, encoding="utf-8")
    p2.write_text(page2_html, encoding="utf-8")
    slack.write_text(slack_msg, encoding="utf-8")
    log.info("생성 완료: %s, %s, %s", p1, p2, slack)
    return {"page1": p1, "page2": p2, "slack_file": slack, "slack_text": slack_msg, "llm": llm}


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True, help="csat_processor 결과 JSON 경로")
    p.add_argument("--out", default="docs/csat", help="출력 디렉토리")
    p.add_argument("--confluence", default="", help="Confluence URL")
    args = p.parse_args()

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    result = generate_all(data, Path(args.out), args.confluence)
    print(json.dumps({k: str(v) for k, v in result.items() if k != "llm"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
