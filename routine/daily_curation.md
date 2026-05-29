# THE PARKING GAZETTE — 데일리 큐레이션 루틴 스펙

> 매일 아침(크롤 이후) Claude가 `docs/data.json`을 읽어 **종합 기사**로 재작성해 `docs/curated.json`을 생성·커밋한다.
> 이 문서는 스케줄 원격 에이전트(claude.ai routine)의 프롬프트 원본이자, 수기 백필 시의 작성 기준이다.

## 파이프라인 위치
```
매일 07:15 KST   GitHub Actions(daily_crawl.py) → docs/data.json 갱신·커밋   [기존]
매주 월 09:00 KST 이 루틴 → docs/data.json 읽기 → 종합 → docs/curated.json 커밋·푸시
페이지            curated.json을 메인 기사 피드로 렌더 (web-api.js getCuratedEdition)
```
> 실행 주기: **매주 월요일 09:00 KST**(cron `0 0 * * 1` UTC). 크롤은 매일 돌지만 큐레이션은 주 1회.
> 14일 창은 주간(7일) 간격과 겹치므로 직전 주 누락분까지 포착되고, dedup으로 중복은 방지된다.

## 매일 실행 절차
1. repo clone/pull (main 최신).
2. `routine/moduparking_kb.md` 읽기 (CX 시사점 근거).
3. `docs/data.json` 읽기. **대상 = source_type이 news/blog인 항목 중 최근 14일** (published_at 기준; 없으면 collected_at). appstore/ios_appstore(리뷰)·homepage는 제외 — 리뷰는 페이지가 data.json에서 직접 처리.
4. **노이즈 제외**: 주차산업/해당 서비스와 무관한 항목 버리기 (예: 맛집·미용실·여행/축제 후기·부동산·일반 블로그 홍보글로 키워드만 우연히 걸린 것, 순수 광고·영업글). 판단 근거를 요약 카운트로 dropped.noise에 집계.
5. **클러스터링**: 같은 사안(이벤트)을 다룬 항목들을 하나로 묶기. 서비스가 달라도 같은 사안이면 한 클러스터. (제목·본문의 핵심 개체/사건 기준)
6. **중복 제외**: 같은 클러스터 내 동일 보도(다매체 배포·RSS 스텁)는 대표로 합산. dropped.duplicates에 집계.
7. 각 클러스터를 **종합 기사 1건으로 재작성**:
   - 매체별로 조금씩 다른 정보(수치·배경·코멘트)를 **읽고 비교해 취합**한다. 한 기사 베끼기 금지.
   - 사실 위주, 추측/과장 금지. 수치·주체·일자는 출처 간 교차확인.
8. **CX 시사점(cx_note)**: `moduparking_kb.md` 근거로 모두의주차장 관점 해설 (작성 가이드 §6 준수). 함의 약하면 비움.
9. **누적(아카이브) 병합**: 기존 `docs/curated.json`을 읽어, 새로 종합한 기사를 합친다. **id 기준 dedup** — 같은 id가 있으면 최신 종합본으로 교체, 없으면 추가. 과거 주차 기사는 보존(페이지가 주차별로 탐색하므로 지우지 않음). published_at 기준 ISO 주차로 자연 분류된다.
10. `docs/curated.json` 작성(아래 스키마). 중요도순 정렬. `edition_date`·`generated_at`은 이번 실행 기준으로 갱신.
11. 변경 있으면 commit(`chore: daily curated edition {date} [skip ci]`) → `git pull --rebase --autostash` → push.

> **id 규칙**: `YYYYMMDD-slug` (원 사안 보도일 + 영문 슬러그). 같은 사안의 후속 보도가 다음 날 또 잡혀도 같은 id로 묶여 중복 누적되지 않도록 슬러그를 안정적으로 정한다.
> **보관 범위**: 누적이 너무 커지면(예: 1년 초과) 오래된 주차를 `docs/curated_archive/{year}.json`으로 분리하는 것을 후속 과제로 둔다. 당분간 단일 파일 유지.

> **Slack 발송**: 없음 (페이지만 갱신). 향후 필요 시 채널을 지정해 추가한다.
> **실행 시각**: 매주 월요일 09:00 KST (cron `0 0 * * 1`). routine id `trig_01JmYY5BziU1nwfFt7Qegbjk`.

## curated.json 스키마
```json
{
  "ok": true,
  "schema_version": "1.0",
  "generated_at": "ISO8601 (KST)",
  "edition_date": "YYYY-MM-DD",
  "source_window": "YYYY-MM-DD ~ YYYY-MM-DD",
  "editor": "claude-daily-routine",
  "dropped": { "noise": <int>, "duplicates": <int> },
  "articles": [
    {
      "id": "YYYYMMDD-slug",
      "headline": "종합 헤드라인",
      "deck": "한 줄 부제(핵심 요약)",
      "category": "정책|기술|사업확장|제휴|VOC|기타",
      "importance": "high|mid|low",
      "sentiment": "positive|neutral|negative (모두의주차장 관점 함의)",
      "service_ids": ["kakaot_parking", ...],
      "published_at": "YYYY-MM-DD (원 사안 발생/보도일)",
      "body": "종합 본문. 문단 구분은 \\n\\n. 3~6문단 권장(중요도 high는 더 길고 깊게).",
      "cx_note": "🅼 모두의주차장 관점 해설 (없으면 빈 문자열)",
      "source_count": <int 클러스터 총 기사 수>,
      "sources": [ { "outlet": "매체명", "url": "원문 URL" }, ... ]
    }
  ]
}
```

## 분량·톤 기준 (킬로님 확정)
- **더 길고 깊게**: high 기사는 배경·작동방식·규모·의미 등 여러 각도로 본문 충실히. mid도 3~4문단.
- 헤드라인은 신문체(사실+핵심), deck은 부제로 보강.
- **CX 시사점은 프로세스 정확성 우선** — 모두의주차장이 못 하는 건 왜 못 하는지 구조로 설명. 단순 "우리도 하자" 금지.
- 카테고리 매핑: 정책(법·제도·정부) / 기술(시스템·장비·AI) / 사업확장(실적·확장·IPO·수상) / 제휴(MOU·협력) / VOC(이용자 불만·이슈) / 기타.

## service_id 참조
kakaot_parking 카카오T주차 · tmap_parking Tmap주차 · iparking 아이파킹 · nicepark 나이스파크 · highparking 하이파킹(투루파킹) · parkingfriends 파킹프렌즈 · zoomansa 주만사 · amano_korea 아마노코리아 · kmpark 케이엠파크 · parkingcloud 파킹클라우드 · sk_shielders SK쉴더스 · moduparking 모두의주차장(자사)

## 품질 레퍼런스
`docs/curated.json` 시드(2026-05-29, 수기 작성 5건)가 분량·톤·CX시사점 품질 기준이다. 특히 카카오 장애인 자동감면 기사의 cx_note(선불·중개 구조로 직접 도입 불가 + 검토 갈래 + 확인 필요 명시)가 표준.
