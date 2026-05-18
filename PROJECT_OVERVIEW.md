# 주차 서비스 CX 모니터 — 프로젝트 종합 문서

> 작성 기준: 2026-05-15  
> 담당자: 킬로 (SOCAR 거점사업운영팀 CX운영파트)  
> 프로젝트 경로: `C:\Users\jh199\projects\parking-cx-monitor`

---

## 1. 프로젝트 개요

국내 주요 주차 플랫폼 서비스의 동향을 자동으로 수집·분류하여 CX 관점에서 모니터링하는 **Windows 전용 데스크톱 앱**.

매일 한 번 크롤링을 돌려 경쟁사 앱 리뷰, 뉴스, 블로그, 홈페이지 변경을 수집하고, Electron 기반 UI에서 타임라인 형태로 조회한다.

### 주요 기능

| 기능 | 설명 |
|------|------|
| 자동 크롤링 | Google News RSS, 네이버 뉴스/블로그, 앱스토어 리뷰, 홈페이지 diff |
| 타임라인 뷰 | 수집된 변경사항을 날짜순으로 표시, 클릭 시 요약 펼침 |
| 앱 평점 현황 | 경쟁사 Android/iOS 평점·리뷰 수 카드 |
| 서비스별 필터 | 모두의주차장 포함 8개 서비스 선택 필터 |
| 유형별 필터 | 뉴스/리뷰/홈페이지/앱 유형별 필터 |
| 텍스트 검색 | 수집된 변경사항 전문 검색 |
| 원문 바로가기 | 각 카드에서 원문 링크 직접 접근 |

---

## 2. 기술 스택

### 프론트엔드 (Electron Renderer)

- **Electron 36.x** — Chromium 기반 데스크톱 앱 컨테이너
- **HTML/CSS/Vanilla JS** — CDN 라이브러리 없음 (CSP `script-src 'self'` 적용)
- **SVG 인라인 생성** — 외부 차트 라이브러리 대신 JS로 직접 그림

### 메인 프로세스 (Node.js)

- **Electron `ipcMain`** — 렌더러 ↔ 메인 프로세스 통신
- **`child_process.spawn`** — Python/exe 백엔드 실행 및 stdout JSON 수신

### 백엔드 (Python 3.11)

| 라이브러리 | 용도 |
|-----------|------|
| `requests 2.31` | HTTP 요청 |
| `beautifulsoup4 4.12` | HTML 파싱, 기사 본문 추출 |
| `feedparser 6.0` | RSS 피드 파싱 |
| `pyyaml 6.0` | `sources.yaml` 로드 |
| `google-play-scraper 1.2.4` | Play Store 평점·리뷰 수집 |
| `python-dateutil 2.9` | 날짜 파싱 |

### 데이터베이스

- **SQLite 3** (WAL 모드) — `monitor.db`
- 배포 시 `%APPDATA%\parking-cx-monitor\monitor.db`에 위치

### 배포

- **PyInstaller** — Python 백엔드를 단일 `.exe`로 컴파일
- **electron-builder NSIS** — Windows 인스톨러 생성 (arm64 + x64)

---

## 3. 파일 구조

```
parking-cx-monitor/
├── src/
│   ├── main.js              # Electron 메인 프로세스
│   ├── preload.js           # contextBridge API 노출
│   └── renderer/
│       ├── index.html       # 앱 진입점 HTML
│       ├── app.js           # UI 로직 전체 (렌더러)
│       └── style.css        # 모던 SaaS 테마 CSS
│
├── backend/
│   ├── daily_crawl.py       # 크롤러 메인 (모든 소스 처리)
│   ├── db.py                # SQLite CRUD 래퍼 + CLI
│   ├── diff_detector.py     # HTML diff 감지 유틸
│   └── requirements.txt     # Python 의존성
│
├── backend-dist/            # PyInstaller 컴파일 결과물
│   ├── daily_crawl.exe
│   └── db.exe
│
├── data/
│   ├── services.json        # 모니터링 대상 서비스 정의 (v2.1)
│   ├── sources.yaml         # 크롤링 소스 정의
│   ├── keywords.yaml        # 검색 키워드
│   ├── features.json        # 기능 검색용 데이터
│   └── monitor.db           # SQLite DB (개발 환경)
│
├── build-resources/
│   ├── icon.ico             # 앱 아이콘
│   └── installer.nsh        # NSIS 인스톨러 스크립트
│
├── scripts/
│   └── build-backend.ps1   # PyInstaller 빌드 자동화
│
├── dist-installer/          # 빌드 결과물 (인스톨러)
├── logs/                    # 크롤링 실행 로그
├── package.json
└── electron-builder.yml
```

---

## 4. 모니터링 대상 서비스 (8개)

`data/services.json` v2.1 기준

| # | ID | 서비스명 | 운영사 | Play Store ID | iOS App ID |
|---|----|---------|----|---------------|-----------|
| 1 | `moduparking` | **모두의주차장** ⭐ | 모두컴퍼니 (쏘카) | `com.parkingshare.mobile` | `780174422` |
| 2 | `kakaot_parking` | 카카오T 주차 | 카카오모빌리티 | `com.kakao.taxi` | `981110422` |
| 3 | `iparking` | 아이파킹 | 파킹클라우드(주) | `kr.co.iparking.android` | `978597106` |
| 4 | `nicepark` | 나이스파크 | 나이스파크(주) | `kr.co.nicetcm.nice_m` | `1556588504` |
| 5 | `highparking` | 하이파킹 (투루파킹) | 휴맥스모빌리티 | `kr.co.turu.parking` | `6711335059` |
| 6 | `parkingfriends` | 파킹프렌즈 | MDS Mobility | `com.misconct.parkingfriends` | `1437488741` |
| 7 | `zoomansa` | 주만사 | 주식회사 주만사 | `com.zoomansa.parking` | `1472478299` |
| 8 | `amano_korea` | 아마노코리아 | 아마노그룹 한국법인 | — | — |

> `moduparking`은 `is_internal: true` 플래그로 내부 서비스로 표시됨  
> 앱 평점 카드에서 모두의주차장이 항상 맨 왼쪽에 표시됨

---

## 5. 크롤링 소스 (`sources.yaml`)

### 소스 유형별 처리 방식

| 타입 | 설명 | 대상 서비스 |
|------|------|------------|
| `rss` | Google News RSS (`when:7d`) | 전 서비스 (키워드 기반) |
| `naver_blog` | 네이버 블로그 검색 (`search.naver.com`) | 7개 서비스 |
| `naver_news` | 네이버 뉴스 검색 | 7개 서비스 |
| `html_list` | 보도자료 페이지 HTML 파싱 | 카카오모빌리티, 휴맥스 |
| `html_diff` | 홈페이지 변경 감지 (해시 비교) | 6개 서비스 |
| `appstore` | Google Play 리뷰 수집 (★4 미만) | 7개 서비스 |
| `ios_appstore` | iTunes RSS 리뷰 수집 (★4 미만) | 7개 서비스 |
| `app_info` | 앱 평점·버전 변화 추적 | 전 서비스 |
| `youtube_rss` | YouTube 채널 RSS | 카카오모빌리티, 휴맥스 |

### 네이버 검색 주요 키워드

| 서비스 | 블로그 키워드 | 뉴스 키워드 |
|--------|-------------|-----------|
| 카카오T | 카카오T 주차, 카카오모빌리티 주차장, 케이엠파킹 | 카카오T 주차, 카카오모빌리티 주차 |
| 아이파킹 | 아이파킹 주차, 파킹클라우드 주차 | 아이파킹, 파킹클라우드 주차 |
| 나이스파크 | 나이스파크 주차, NICEPARK | 나이스파크 주차 |
| 하이파킹 | 투루파킹, 하이파킹 주차, 휴맥스모빌리티 주차 | 투루파킹, 하이파킹 |
| 파킹프렌즈 | 파킹프렌즈, MDS모빌리티 주차 | 파킹프렌즈 |
| 주만사 | 주만사 주차, 주만사 월정기권 | 주만사 주차 |
| 모두의주차장 | 모두의주차장 | 모두의주차장 |

### iOS App ID 확인 방법
```
https://itunes.apple.com/search?term=앱이름&country=kr&entity=software&limit=5
응답 JSON의 trackId 값을 app_id로 사용
```

---

## 6. 데이터베이스 스키마

DB 파일 위치:
- **개발**: `parking-cx-monitor/data/monitor.db`
- **배포**: `%APPDATA%\parking-cx-monitor\monitor.db`

### 테이블 목록

#### `services`
```sql
id        TEXT PRIMARY KEY   -- 서비스 고유 ID (예: moduparking)
name_ko   TEXT               -- 한국어 서비스명
operator  TEXT               -- 운영사명
category  TEXT               -- 카테고리
meta_json TEXT               -- services.json 원본 JSON
```

#### `changes` (핵심 테이블)
```sql
id           INTEGER PRIMARY KEY AUTOINCREMENT
service_id   TEXT NOT NULL          -- services.id 참조
published_at DATE NOT NULL          -- 발행일
source_type  TEXT                   -- news/blog/review/html_diff/app_info
change_type  TEXT                   -- 변경 유형 (뉴스/앱리뷰/기능변경 등)
title        TEXT                   -- 제목
summary      TEXT                   -- 본문 요약 (최대 700자)
url          TEXT                   -- 원문 URL
url_hash     TEXT UNIQUE            -- 중복 방지용 MD5 해시
sentiment    TEXT DEFAULT 'neutral' -- positive/negative/neutral
collected_at DATETIME               -- 수집 시각
```

> 중복 방지 전략:
> - `url_hash UNIQUE` 제약으로 동일 URL 재삽입 차단
> - `dedup_key` 파라미터로 Google News 정규화 제목 기반 중복 제거
> - `get_all_changes()`에서 `_norm_title()`로 언론사명 제거 후 추가 중복 제거

#### `html_snapshots`
```sql
service_id   TEXT
url          TEXT
content_hash TEXT               -- 이전 콘텐츠 해시 (변경 감지용)
content_text TEXT               -- 이전 콘텐츠 텍스트
snapshot_at  DATETIME
PRIMARY KEY (service_id, url)
```

#### `app_info`
```sql
service_id   TEXT
platform     TEXT               -- google_play / ios
app_id       TEXT
rating       REAL               -- 현재 평점
num_ratings  INTEGER            -- 누적 리뷰 수
version      TEXT               -- 현재 버전
update_notes TEXT               -- 업데이트 내용
checked_at   DATETIME
PRIMARY KEY (service_id, platform)
```

#### `app_info_history`
시간에 따른 평점/버전 변화 이력 보관 (삽입 시마다 기록)

#### `collection_log`
크롤링 실행 이력 (`run_at`, `status`, `items_added`, `items_removed`, `notes`)

---

## 7. IPC 통신 구조

```
렌더러 (app.js)
  └─ window.api.*(...)  [contextBridge]
        └─ ipcRenderer.invoke(...)
              └─ ipcMain.handle(...)  [main.js]
                    └─ spawn(db.exe / daily_crawl.exe)
                          └─ stdout JSON → resolve
```

### 노출된 API (`preload.js`)

| API | IPC 채널 | 설명 |
|-----|----------|------|
| `getStatus()` | `db:status` | 마지막 크롤링 시각, 오늘 수집 건수 |
| `getChanges(svcId)` | `db:changes` | 서비스별 변경사항 100건 |
| `getAllChanges(ct)` | `db:all_changes` | 전체 변경사항 (유형 필터 가능) |
| `getSummary()` | `db:summary` | 최근 24시간 요약 |
| `searchFeats(query)` | `db:search` | 기능 검색 |
| `getServices()` | `db:services` | 서비스 목록 |
| `getAppStats()` | `db:app_stats` | 앱 평점·버전 현황 |
| `runCrawl()` | `crawl:run` | 크롤러 실행 (진행 로그 스트리밍) |
| `onCrawlLog(cb)` | `crawl:log` | 크롤러 로그 수신 |

---

## 8. 렌더러 UI 구조 (`app.js` + `style.css`)

### 레이아웃

```
┌─────────────────────────────────────────────────────────┐
│  헤더: 앱 제목 + 상태 배지 + 다시 수집 버튼               │
├───────────────────────────────┬─────────────────────────┤
│  타임라인 (왼쪽)               │  오른쪽 패널 (300px)     │
│  - 날짜 구분선                 │  - 서비스 필터 (체크박스)  │
│  - 변경사항 카드 목록           │  - 유형 필터              │
│    ┌──────────────────────┐   │  - 검색창                 │
│    │ 서비스뱃지 유형뱃지 날짜 │   │  - 앱 평점 카드 섹션      │
│    │ 제목              ↗원문│   │    (모두의주차장 맨 앞)   │
│    │ [클릭 시 펼침]          │   │                         │
│    │  요약 텍스트           │   │                         │
│    │  [↗ 원문 바로가기]     │   │                         │
│    └──────────────────────┘   │                         │
└───────────────────────────────┴─────────────────────────┘
```

### 카드 클릭-펼침 동작

```javascript
// 조건: summary가 50자 이상이고 제목과 다를 때만 펼침 섹션 표시
const hasSummary = c.summary &&
                   c.summary.trim().length > 50 &&
                   c.summary.trim().slice(0, 30) !== (c.title || '').trim().slice(0, 30)

// 이벤트 위임 (링크 클릭 제외)
timeline.addEventListener('click', e => {
  if (e.target.closest('a')) return
  const card = e.target.closest('.change-card[data-expandable]')
  if (!card) return
  card.dataset.expanded = card.dataset.expanded === 'true' ? 'false' : 'true'
})
```

### 앱 평점 카드 정렬 규칙
1. `moduparking` 항상 맨 앞
2. 나머지는 누적 리뷰 수 내림차순
3. DB에 데이터 없어도 앱 ID가 있으면 빈 카드로 표시 (fallback)

---

## 9. 크롤러 상세 (`daily_crawl.py`)

### 실행 흐름

```
daily_crawl.py 실행
  ├── init_db() + import_services()   DB 초기화 및 서비스 임포트
  ├── sources.yaml 로드
  └── 소스별 처리 루프
        ├── rss          → feedparser → insert_change()
        ├── naver_blog   → requests + BS4 → _fetch_article_text() → insert_change()
        ├── naver_news   → requests + BS4 → _fetch_article_text() → insert_change()
        ├── html_list    → requests + BS4 → insert_change()
        ├── html_diff    → 해시 비교 → 변경 시 insert_change()
        ├── appstore     → google-play-scraper → insert_change()
        ├── ios_appstore → iTunes RSS → insert_change()
        ├── app_info     → 평점/버전 수집 → save_app_info()
        └── youtube_rss  → feedparser → insert_change()
```

### 기사 본문 자동 보강 (`_fetch_article_text`)

네이버 뉴스/블로그 스니펫이 200자 미만일 때 원문 URL에 직접 접속하여 본문을 추출:
```python
if len(desc) < 200 and href:
    fetched = _fetch_article_text(href)
    if len(fetched) > len(desc):
        desc = fetched
```

BeautifulSoup으로 `article`, `.article-body`, `#articleBody` 등 선택자를 시도하여 본문 추출.

### 앱 리뷰 수집 기준

- Google Play: `flag_below_rating: 4` → ★4 미만 리뷰만 수집
- iOS App Store: `flag_below_rating: 4` → ★4 미만 리뷰만 수집
- 수집 기간: `window_days: 14` (최근 14일)

---

## 10. 빌드 및 배포

### 개발 환경 실행

```powershell
cd C:\Users\jh199\projects\parking-cx-monitor

# 가상환경 생성 (최초 1회)
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt

# 개발 모드 실행
npm start
```

### 배포 빌드 (인스톨러 생성)

```powershell
# arm64 (Samsung Galaxy Book, Snapdragon)
npm run build:installer:arm64

# x64 (일반 Intel/AMD)
npm run build:installer:x64

# 둘 다
npm run build:installer
```

빌드 순서:
1. `build-backend.ps1` — PyInstaller로 `db.exe`, `daily_crawl.exe` 생성
2. `electron-builder` — Electron 앱 패키징 + NSIS 인스톨러 생성
3. 결과물: `dist-installer/` 폴더

### 배포 후 파일 위치

```
설치 폴더 (사용자 지정, 기본 %LOCALAPPDATA%)\
  └── 주차 서비스 CX 모니터.exe
      └── resources\
            ├── backend\     ← daily_crawl.exe, db.exe
            └── data\        ← services.json, sources.yaml

%APPDATA%\parking-cx-monitor\
  └── monitor.db             ← DB (여기에만 쓰기 가능)
```

### 바로가기 (데스크톱)

```
경로: C:\Users\jh199\Desktop\주차 CX 모니터.lnk
대상: C:\Users\jh199\projects\parking-cx-monitor\dist-installer\win-arm64-unpacked\주차 서비스 CX 모니터.exe
작업 디렉토리: C:\Users\jh199\projects\parking-cx-monitor\dist-installer\win-arm64-unpacked
```

> 바로가기가 깨진 경우 PowerShell로 재생성:
> ```powershell
> $ws = New-Object -ComObject WScript.Shell
> $sc = $ws.CreateShortcut("$env:USERPROFILE\Desktop\주차 CX 모니터.lnk")
> $sc.TargetPath = "C:\Users\jh199\projects\parking-cx-monitor\dist-installer\win-arm64-unpacked\주차 서비스 CX 모니터.exe"
> $sc.WorkingDirectory = "C:\Users\jh199\projects\parking-cx-monitor\dist-installer\win-arm64-unpacked"
> $sc.Save()
> ```

---

## 11. 주요 설계 결정 사항

| 결정 | 이유 |
|------|------|
| Python 백엔드 분리 (PyInstaller exe) | Node.js에서 네이버 스크래핑/구글플레이 파싱 라이브러리 부족, Python 생태계 활용 |
| SQLite WAL 모드 | 크롤러와 UI가 동시에 DB 접근 시 락 충돌 방지 |
| `url_hash UNIQUE` 중복 방지 | 동일 기사가 여러 키워드에서 걸려도 한 번만 저장 |
| Google News 정규화 중복 제거 | `– 언론사명` 접미사 제거 후 비교, 동일 기사 다중 언론 배포 시 중복 제거 |
| CDN 라이브러리 미사용 | Electron CSP `script-src 'self'` 정책 준수, 오프라인 동작 보장 |
| SVG 인라인 차트 | 차트 라이브러리 없이 JS로 직접 생성 |
| 라인 차트 제거 | 데이터 부족 시 의미없는 시각화 → 평점 카드(텍스트) 방식으로 전환 |
| 기사 본문 자동 보강 | 네이버 스니펫 200자 미만 → 원문 직접 fetch로 summary 품질 향상 |
| 카드 expand hasSummary 조건 | 쓸모없는 "기사 전문은 원문에서 확인하세요" 같은 fallback 메시지 표시 방지 |
| moduparking 항상 첫 번째 | 내부 서비스로 비교 기준점으로 항상 왼쪽/상단에 고정 |
| 배포 DB를 %APPDATA%에 저장 | 설치 폴더는 read-only일 수 있으므로 writable 경로로 분리 |

---

## 12. 알려진 이슈 및 주의사항

### `com.parkingshare.mobile` (모두의주차장 Play Store)

`google-play-scraper`가 해당 패키지 ID를 찾지 못할 수 있음. 앱 평점 카드는 프론트엔드 fallback으로 항상 표시되지만 수치가 비어있을 수 있음. 실제 Play Store에서 최신 패키지 ID 재확인 권장.

### 네이버 스크래핑 차단

네이버가 봇 감지 시 스크래핑을 차단할 수 있음. `User-Agent` 헤더와 요청 간격으로 완화하고 있으나, 반복 실패 시 네이버 검색 API 공식 키 발급 검토 필요.

### 크롤링 주기

현재 수동 실행 방식 ("다시 수집" 버튼). 자동 스케줄 (Windows 작업 스케줄러 또는 앱 내 타이머)은 미구현 상태.

### 아이파킹·나이스파크 초기 데이터

v2.1에서 신규 추가된 서비스로, 첫 크롤링 실행 전까지 앱 평점 및 뉴스 데이터가 없음. "다시 수집" 클릭 후 데이터 확인 필요.

---

## 13. 향후 개선 가능 사항

- [ ] 자동 일일 크롤링 스케줄 (Windows 작업 스케줄러 연동)
- [ ] 앱 평점 변화 트렌드 그래프 (데이터 충분히 쌓인 후)
- [ ] 리뷰 감성 분석 고도화 (현재 neutral/positive/negative 단순 분류)
- [ ] Slack 알림 연동 (특정 키워드 감지 시 자동 알림)
- [ ] 카카오T 앱 전용 ID (`com.kakao.taxi`) — 주차 기능 리뷰만 필터링 필요
- [ ] 백업/내보내기 기능 (DB 전체 CSV 내보내기)

---

*이 문서는 `C:\Users\jh199\projects\parking-cx-monitor\PROJECT_OVERVIEW.md`에 저장되어 있습니다.*
