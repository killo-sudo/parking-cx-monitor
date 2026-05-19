/**
 * 대시보드 렌더러 로직
 * 흐름: 스플래시 → 상태 확인 → 대시보드 표시
 * 데이터 수집은 GitHub Actions 크론(매일 KST 04:00)이 담당.
 */

// ──────────────────────────────────────────────
// 서비스 색상 테이블
// ──────────────────────────────────────────────
const SVC_COLORS = {
  moduparking:     '#3A3020',
  kakaot_parking:  '#7A1818',
  tmap_parking:    '#1A3A50',
  iparking:        '#1A4060',
  nicepark:        '#2A1A60',
  highparking:     '#1A3D20',
  parkingfriends:  '#3A1860',
  zoomansa:        '#1A4228',
  amano_korea:     '#1A2D5A',
  kmpark:          '#1A3A3A',
  parkingcloud:    '#2A3A1A',
  sk_shielders:    '#3A2A10',
  urbanport:       '#3A1A2A',
  koreanef:        '#2A1A1A',
}

// 서비스 카테고리 그룹 (sidebar 분류용)
const SVC_GROUPS = [
  {
    label: '내부',
    ids: ['moduparking'],
  },
  {
    label: '경쟁사',
    ids: ['kakaot_parking', 'tmap_parking', 'iparking', 'nicepark', 'highparking', 'parkingfriends', 'zoomansa', 'amano_korea', 'kmpark', 'parkingcloud', 'sk_shielders', 'urbanport', 'koreanef'],
  },
]

// ──────────────────────────────────────────────
// 상태
// ──────────────────────────────────────────────
let SERVICES      = []
let STATUS        = {}
let ACTIVE_SVC    = null
let ACTIVE_FILTER = null
let FILTER_DATE_FROM = ''
let FILTER_DATE_TO   = ''
let FILTER_KW        = ''
// CRAWLING 플래그 제거 — 수동 수집 기능 없음

let _allReviews    = []
let REVIEW_PLATFORM = ''
let REVIEW_BRAND    = ''

// ──────────────────────────────────────────────
// DOM 참조
// ──────────────────────────────────────────────
const $ = id => document.getElementById(id)

const splash        = $('splash')
const splashMsg     = $('splash-msg')
const splashLog     = $('splash-log')
const svcList       = $('service-list')
const timeline      = $('timeline')
const contentTitle  = $('content-title-text')
const colorBar      = $('svc-color-bar')
const subtitle      = $('content-subtitle')
const lastUpdated   = $('last-updated')
const reviewsBody   = $('reviews-body')
const appstatsList  = $('appstats-list')
const appstatsChart = $('appstats-chart')
const filterChips   = document.querySelectorAll('.filter-chip')

// ──────────────────────────────────────────────
// 스플래시
// ──────────────────────────────────────────────

function showSplash (msg) {
  splashMsg.textContent = msg
  splash.classList.remove('hidden')
}

function appendSplashLog (line) {
  splashLog.textContent += line
  splashLog.scrollTop = splashLog.scrollHeight
}

function hideSplash () {
  splash.classList.add('hidden')
}

// ──────────────────────────────────────────────
// 초기화 흐름
// ──────────────────────────────────────────────

async function init () {
  showSplash('데이터 확인 중...')
  setupFilterChips()

  try {
    STATUS = await window.api.getStatus()

    const svcData = await window.api.getServices()
    SERVICES = svcData

    renderServiceList()
    setupReviewFilters()
    await renderReviews()
    await renderAppStats()
    await renderIntelBar()
    updateLastUpdated()

    hideSplash()

    // 기본: 전체 타임라인 표시
    await selectService('__all__')

  } catch (err) {
    appendSplashLog(`\n[경고] ${err.message}`)
    splashMsg.textContent = '오프라인 모드 — 캐시 데이터로 표시'
    await sleep(1500)
    hideSplash()
    try {
      const svcData = await window.api.getServices()
      SERVICES = svcData
      renderServiceList()
      await renderReviews()
      await selectService('__all__')
    } catch (_) {}
  }
}

// ──────────────────────────────────────────────
// 서비스 사이드바 렌더링
// ──────────────────────────────────────────────

function renderServiceList () {
  svcList.innerHTML = ''
  const newMap    = STATUS.per_service_new || {}
  const svcById   = Object.fromEntries(SERVICES.map(s => [s.id, s]))

  // 전체 보기
  const allItem = document.createElement('div')
  allItem.className = 'svc-item'
  allItem.dataset.id = '__all__'
  allItem.innerHTML = `
    <div class="svc-dot"></div>
    <div class="svc-name">전체 보기</div>
    <div class="svc-badge"></div>
  `
  allItem.addEventListener('click', () => selectService('__all__'))
  svcList.appendChild(allItem)

  // 카테고리 그룹 — 순서: SVC_GROUPS 우선, 나머지는 기타로
  const assignedIds = new Set(SVC_GROUPS.flatMap(g => g.ids))
  const extraIds    = SERVICES.map(s => s.id).filter(id => !assignedIds.has(id))
  const groups      = extraIds.length > 0
    ? [...SVC_GROUPS, { label: '기타', ids: extraIds }]
    : SVC_GROUPS

  groups.forEach(group => {
    const groupSvcs = group.ids.map(id => svcById[id]).filter(Boolean)
    if (groupSvcs.length === 0) return

    // 그룹 헤더
    const header = document.createElement('div')
    header.className = 'svc-group-header'
    header.textContent = group.label
    svcList.appendChild(header)

    groupSvcs.forEach(svc => {
      // Sheets 기반 카운트 우선, 없으면 SQLite per_service_new
      const newCnt = (svc.count != null ? svc.count : 0) || newMap[svc.id] || 0

      const entry = document.createElement('div')
      entry.className = 'svc-entry'

      const item = document.createElement('div')
      item.className = 'svc-item'
      item.dataset.id = svc.id
      item.innerHTML = `
        <div class="svc-dot ${newCnt > 0 ? 'has-new' : ''}"></div>
        <div class="svc-name">${svc.name_ko}</div>
        <div class="svc-badge ${newCnt > 0 ? 'visible' : ''}">${newCnt}</div>
      `
      item.addEventListener('click', () => selectService(svc.id))
      entry.appendChild(item)

      const op = document.createElement('div')
      op.className = 'svc-operator'
      op.textContent = svc.operator
      entry.appendChild(op)

      svcList.appendChild(entry)
    })
  })
}

// ──────────────────────────────────────────────
// 서비스 선택 → 타임라인 로드
// ──────────────────────────────────────────────

// ──────────────────────────────────────────────
// 카테고리 필터 칩 세팅
// ──────────────────────────────────────────────

function setupFilterChips () {
  filterChips.forEach(chip => {
    chip.addEventListener('click', async () => {
      filterChips.forEach(c => c.classList.remove('active'))
      chip.classList.add('active')
      ACTIVE_FILTER = chip.dataset.type || null
      await reloadTimeline()
    })
  })

  // 날짜 필터
  const dateFrom  = $('filter-date-from')
  const dateTo    = $('filter-date-to')
  const dateClear = $('filter-date-clear')
  const kwInput   = $('filter-kw-input')
  const kwClear   = $('filter-kw-clear')

  if (dateFrom) dateFrom.addEventListener('change', async () => {
    FILTER_DATE_FROM = dateFrom.value
    await reloadTimeline()
  })
  if (dateTo) dateTo.addEventListener('change', async () => {
    FILTER_DATE_TO = dateTo.value
    await reloadTimeline()
  })
  if (dateClear) dateClear.addEventListener('click', async () => {
    FILTER_DATE_FROM = ''; FILTER_DATE_TO = ''
    if (dateFrom) dateFrom.value = ''
    if (dateTo)   dateTo.value   = ''
    await reloadTimeline()
  })

  // 키워드 검색 (300ms 디바운스)
  let _kwTimer = null
  if (kwInput) kwInput.addEventListener('input', () => {
    clearTimeout(_kwTimer)
    _kwTimer = setTimeout(async () => {
      FILTER_KW = kwInput.value.trim()
      await reloadTimeline()
    }, 300)
  })
  if (kwClear) kwClear.addEventListener('click', async () => {
    FILTER_KW = ''
    if (kwInput) kwInput.value = ''
    await reloadTimeline()
  })
}

async function reloadTimeline () {
  if (!ACTIVE_SVC) return
  await selectService(ACTIVE_SVC)
}

async function selectService (svcId) {
  ACTIVE_SVC = svcId

  document.querySelectorAll('.svc-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === svcId)
  })

  if (svcId === '__all__') {
    contentTitle.textContent = '전체 서비스 타임라인'
    colorBar.style.background = 'var(--ink)'
    const filterNote = ACTIVE_FILTER ? ` · 필터: ${ACTIVE_FILTER}` : ''
    subtitle.textContent = `${SERVICES.length}개 주차 플랫폼 VOC · 뉴스 · 앱 업데이트 · 홈페이지 변경 종합${filterNote}`
    timeline.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>'
    try {
      const changes = await window.api.getAllChanges(ACTIVE_FILTER || null)
      renderTimeline(changes, null)
    } catch (err) {
      timeline.innerHTML = `<div class="empty-state"><p>${err.message}</p></div>`
    }
    return
  }

  const svc   = SERVICES.find(s => s.id === svcId)
  const color = SVC_COLORS[svcId] || 'var(--ink)'

  contentTitle.textContent = svc ? svc.name_ko : svcId
  colorBar.style.background = color
  const filterNote = ACTIVE_FILTER ? ` · 필터: ${ACTIVE_FILTER}` : ''
  subtitle.textContent = svc ? `${svc.operator} — 최근 6개월 변경사항 · VOC · 앱 동향${filterNote}` : ''

  timeline.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>'
  try {
    let changes = await window.api.getChanges(svcId)
    if (ACTIVE_FILTER) {
      changes = changes.filter(c => c.change_type === ACTIVE_FILTER)
    }
    renderTimeline(changes, svc)
  } catch (err) {
    timeline.innerHTML = `<div class="empty-state"><p>${err.message}</p></div>`
  }
}

// ──────────────────────────────────────────────
// 타임라인 카드 렌더링
// ──────────────────────────────────────────────

function renderTimeline (changes, svc) {
  // ── 날짜 범위 필터 ──
  if (FILTER_DATE_FROM) {
    changes = changes.filter(c => (c.published_at || '') >= FILTER_DATE_FROM)
  }
  if (FILTER_DATE_TO) {
    changes = changes.filter(c => (c.published_at || '') <= FILTER_DATE_TO)
  }

  // ── 키워드 검색 필터 ──
  if (FILTER_KW) {
    const kws = FILTER_KW.toLowerCase().split(/\s+/).filter(Boolean)
    changes = changes.filter(c => {
      const hay = ((c.title || '') + ' ' + (c.summary || '')).toLowerCase()
      return kws.every(k => hay.includes(k))
    })
  }

  if (!changes || changes.length === 0) {
    const msg = (FILTER_DATE_FROM || FILTER_DATE_TO || FILTER_KW)
      ? '검색 조건에 맞는 결과가 없습니다.'
      : '수집된 변경사항이 없습니다.'
    timeline.innerHTML = `
      <div class="empty-state">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <p>${msg}</p>
      </div>`
    return
  }

  const cutoff24h = new Date(Date.now() - 24 * 60 * 60 * 1000)

  // 같은 날 제목 단어 30% 이상 겹치면 대표 1건만 표시 (접속사·조사 제외)
  // 중복 그룹 내 우선순위: 네이버 뷰어 URL > 본문 긴 것 > 나머지
  const _STOP = new Set(['이','가','을','를','의','에','에서','으로','로','과','와','도','은','는','그','이','저','것','수','등','및','또','더','각','한','된','할','될','하는','있는','없는','위한','통한','대한','관련','함께','모든','이번','해당','국내','서울','지난'])
  function _words (title) {
    return new Set((title || '').split(/[\s\-·,·…]+/).filter(w => w.length > 1 && !_STOP.has(w)))
  }
  function _similar (wa, wb) {
    if (wa.size === 0 || wb.size === 0) return false
    let inter = 0
    wa.forEach(w => { if (wb.has(w)) inter++ })
    return inter / (wa.size + wb.size - inter) >= 0.3
  }
  function _dedupPriority (c) {
    const url = c.url || ''
    const bodyLen = (c.summary || '').length
    if (url.includes('n.news.naver.com')) return 0
    if (bodyLen > 200) return 1
    return 2
  }
  // 네이버 뷰어 URL 우선으로 정렬 후 중복 제거
  changes.sort((a, b) => _dedupPriority(a) - _dedupPriority(b))
  const _seenItems = []
  changes = changes.filter(c => {
    const day = (c.published_at || '').slice(0, 10)
    const ws  = _words(c.title)
    const dupIdx = _seenItems.findIndex(s => s.day === day && _similar(ws, s.ws))
    if (dupIdx !== -1) {
      // 현재 아이템이 더 좋은 소스면 교체
      if (_dedupPriority(c) < _dedupPriority(_seenItems[dupIdx].c)) {
        _seenItems[dupIdx] = { day, ws, c }
      }
      return false
    }
    _seenItems.push({ day, ws, c })
    return true
  })
  // 교체된 대표 아이템으로 재구성
  changes = _seenItems.map(s => s.c)

  timeline.innerHTML = changes.map(c => {
    const isNew   = new Date(c.collected_at) > cutoff24h
    const typeKl  = `type-${c.change_type || '기타'}`
    const srcLbl  = srcLabel(c.source_type, c.title || '')

    const svcBadge = (!svc && c.name_ko)
      ? `<span class="card-svc-badge">${esc(c.name_ko)}</span>`
      : ''

    const starsEl = renderStars(c.title || '')

    const urlLink = c.url
      ? `<a class="card-url-link" href="${esc(c.url)}" target="_blank">↗ 원문</a>`
      : ''

    const hasSummary = c.summary &&
                       c.summary.trim().length > 30 &&
                       c.summary.trim().slice(0, 30) !== (c.title || '').trim().slice(0, 30)

    const expandBody = hasSummary
      ? `<div class="card-summary">${esc(c.summary)}</div>`
      : `<div class="card-summary-empty">크롤링된 본문이 없습니다.</div>`

    const expandSection = `
      <div class="card-expand">
        ${expandBody}
        ${c.url ? `<a class="card-goto-btn" href="${esc(c.url)}" target="_blank">↗ 원문 바로가기</a>` : ''}
      </div>`

    return `
      <div class="change-card ${isNew ? 'is-new' : ''}"
           data-type="${esc(c.change_type || '기타')}"
           data-expandable="true">
        <div class="card-meta">
          <span class="card-date">${c.published_at || ''}</span>
          ${svcBadge}
          <span class="type-badge ${typeKl}">${c.change_type || '기타'}</span>
          <span class="source-badge">${srcLbl}</span>
          ${starsEl}
          ${urlLink}
        </div>
        <div class="card-title">
          ${esc(c.title || '')}
          <span class="card-expand-icon">▾</span>
        </div>
        ${expandSection}
      </div>`
  }).join('')
}

// 카드 클릭 → 본문 펼치기/접기
timeline.addEventListener('click', e => {
  if (e.target.closest('a')) return
  const card = e.target.closest('.change-card[data-expandable]')
  if (!card) return
  card.dataset.expanded = card.dataset.expanded === 'true' ? 'false' : 'true'
})

// ──────────────────────────────────────────────
// 앱 리뷰 패널 — 플랫폼·브랜드 필터 + 시간순 스트림
// ──────────────────────────────────────────────

function setupReviewFilters () {
  const platRow  = $('review-filter-platform')
  const brandRow = $('review-filter-brand')

  if (platRow) {
    platRow.addEventListener('click', e => {
      const chip = e.target.closest('.review-filter-chip[data-platform]')
      if (!chip) return
      platRow.querySelectorAll('.review-filter-chip').forEach(c => c.classList.remove('active'))
      chip.classList.add('active')
      REVIEW_PLATFORM = chip.dataset.platform || ''
      _renderReviewCards()
    })
  }

  if (brandRow) {
    brandRow.addEventListener('click', e => {
      const chip = e.target.closest('.review-filter-chip[data-brand]')
      if (!chip) return
      brandRow.querySelectorAll('.review-filter-chip').forEach(c => c.classList.remove('active'))
      chip.classList.add('active')
      REVIEW_BRAND = chip.dataset.brand || ''
      _renderReviewCards()
    })
  }
}

function _renderReviewBrandChips (brandIds) {
  const brandRow = $('review-filter-brand')
  if (!brandRow) return
  const svcById = Object.fromEntries(SERVICES.map(s => [s.id, s]))
  const chips = brandIds.map(sid => {
    const name  = (svcById[sid] && svcById[sid].name_ko) || sid
    const short = name.length > 5 ? name.slice(0, 5) + '…' : name
    return `<button class="review-filter-chip" data-brand="${esc(sid)}">${esc(short)}</button>`
  }).join('')
  brandRow.innerHTML = `<button class="review-filter-chip active" data-brand="">전체</button>${chips}`
}

function _renderReviewCards () {
  if (!reviewsBody) return

  let filtered = _allReviews

  if (REVIEW_PLATFORM === 'ios') {
    filtered = filtered.filter(r =>
      r.source_type === 'ios_appstore' || (r.title || '').startsWith('[iOS'))
  } else if (REVIEW_PLATFORM === 'android') {
    filtered = filtered.filter(r =>
      r.source_type === 'appstore' && !(r.title || '').startsWith('[iOS'))
  }

  if (REVIEW_BRAND) {
    filtered = filtered.filter(r => r.service_id === REVIEW_BRAND)
  }

  const countEl = $('reviews-count')
  if (countEl) countEl.textContent = filtered.length > 0 ? `${filtered.length}건` : ''

  if (filtered.length === 0) {
    reviewsBody.innerHTML = `
      <div class="empty-state" style="padding:20px">
        <p style="font-size:11px">수집된 리뷰가 없습니다.</p>
      </div>`
    return
  }

  const svcById = Object.fromEntries(SERVICES.map(s => [s.id, s]))

  reviewsBody.innerHTML = filtered.map(r => {
    const title  = r.title || ''
    const isIos  = r.source_type === 'ios_appstore' || title.startsWith('[iOS')
    const platLabel = isIos ? 'iOS' : 'Android'
    const platCls   = isIos ? 'review-card-platform--ios' : 'review-card-platform--android'

    const svc       = svcById[r.service_id]
    const brandName = svc ? svc.name_ko : (r.service_id || '')

    const m     = title.match(/★(\d)/)
    const score = m ? parseInt(m[1]) : 0
    const stars = score > 0 ? '★'.repeat(score) + '☆'.repeat(5 - score) : ''

    const dateStr = (r.published_at || '').slice(0, 10)
    const content = (r.summary || '').replace(/\n+/g, ' ')

    return `<div class="review-card">
      <div class="review-card-date">${esc(dateStr)}</div>
      <div class="review-card-source">
        <span class="review-card-platform ${platCls}">${platLabel}</span>
        <span class="review-card-brand">${esc(brandName)}</span>
      </div>
      ${stars ? `<div class="review-card-stars">${stars}</div>` : ''}
      <hr class="review-card-divider">
      <div class="review-card-body">${esc(content)}</div>
    </div>`
  }).join('')
}

async function renderReviews () {
  if (!reviewsBody) return
  try {
    const reviews = await window.api.getRecentReviews()
    _allReviews = reviews

    const svcOrder = SVC_GROUPS.flatMap(g => g.ids)
    const brandSet = new Set(reviews.map(r => r.service_id).filter(Boolean))
    const brandIds = [...brandSet].sort((a, b) => {
      const ia = svcOrder.indexOf(a), ib = svcOrder.indexOf(b)
      if (ia === -1 && ib === -1) return 0
      if (ia === -1) return 1
      if (ib === -1) return -1
      return ia - ib
    })

    _renderReviewBrandChips(brandIds)
    _renderReviewCards()
  } catch (_) {
    if (reviewsBody) reviewsBody.innerHTML = ''
  }
}

// ──────────────────────────────────────────────
// 앱 지표 패널 — 운영사별 사용자 규모 비교
// ──────────────────────────────────────────────

function buildRatingChart (sorted) {
  const W = 400, H = 88
  const PT = 8, PB = 20, PL = 24, PR = 8
  const iW = W - PL - PR  // 368
  const iH = H - PT - PB  // 60
  const Y_MIN = 2.0, Y_MAX = 5.0

  const N = sorted.length
  function xOf (i) { return PL + (N > 1 ? i * (iW / (N - 1)) : iW / 2) }
  function yOf (r) { return PT + iH * (1 - (Math.min(Math.max(r, Y_MIN), Y_MAX) - Y_MIN) / (Y_MAX - Y_MIN)) }

  const aPts = [], iPts = []
  sorted.forEach(([, { platforms }], i) => {
    const x  = xOf(i)
    const gp = platforms.find(p => p.platform === 'google_play')
    const io = platforms.find(p => p.platform === 'ios')
    if (gp && gp.rating != null) aPts.push({ x, y: yOf(gp.rating), v: gp.rating })
    if (io && io.rating != null) iPts.push({ x, y: yOf(io.rating),  v: io.rating  })
  })

  if (aPts.length === 0 && iPts.length === 0) {
    return '<div class="chart-no-data">평점 데이터 수집 후 표시됩니다</div>'
  }

  function smoothPath (pts) {
    if (pts.length === 0) return ''
    if (pts.length === 1) return `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`
    let d = `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`
    for (let i = 1; i < pts.length; i++) {
      const prev = pts[i - 1], curr = pts[i]
      const cpX  = ((prev.x + curr.x) / 2).toFixed(1)
      d += ` C ${cpX} ${prev.y.toFixed(1)}, ${cpX} ${curr.y.toFixed(1)}, ${curr.x.toFixed(1)} ${curr.y.toFixed(1)}`
    }
    return d
  }

  const grids = [2, 3, 4, 5].map(v => {
    const y = yOf(v).toFixed(1)
    return `<line x1="${PL}" y1="${y}" x2="${W - PR}" y2="${y}" stroke="#E2E8F0" stroke-width="0.5"/>`
  }).join('')

  const yLabels = [2, 3, 4, 5].map(v => {
    const y = yOf(v)
    return `<text x="${PL - 3}" y="${y.toFixed(1)}" text-anchor="end" dominant-baseline="middle" class="chart-tick">${v}</text>`
  }).join('')

  const xLabels = sorted.map(([sid, { name }], i) => {
    const x   = xOf(i).toFixed(1)
    const raw = name || sid
    const lbl = raw.length > 5 ? raw.slice(0, 4) + '…' : raw
    return `<text x="${x}" y="${H - 3}" text-anchor="middle" class="chart-tick">${esc(lbl)}</text>`
  }).join('')

  const aLine = aPts.length > 1 ? `<path d="${smoothPath(aPts)}" class="chart-line-a"/>` : ''
  const iLine = iPts.length > 1 ? `<path d="${smoothPath(iPts)}" class="chart-line-i"/>` : ''

  const aDots = aPts.map(p => {
    const ly = p.y < PT + 11 ? (p.y + 10).toFixed(1) : (p.y - 4).toFixed(1)
    return `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="2.5" class="chart-dot-a"/>
<text x="${p.x.toFixed(1)}" y="${ly}" text-anchor="middle" class="chart-val-a">${Number(p.v).toFixed(1)}</text>`
  }).join('')

  const iDots = iPts.map(p => {
    const ly = p.y + 12 < H - PB ? (p.y + 10).toFixed(1) : (p.y - 4).toFixed(1)
    return `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="2.5" class="chart-dot-i"/>
<text x="${p.x.toFixed(1)}" y="${ly}" text-anchor="middle" class="chart-val-i">${Number(p.v).toFixed(1)}</text>`
  }).join('')

  const lgX = W - PR
  const legend = `
    <line x1="${lgX - 88}" y1="${PT + 4}" x2="${lgX - 78}" y2="${PT + 4}" class="chart-line-a"/>
    <circle cx="${lgX - 83}" cy="${PT + 4}" r="2" class="chart-dot-a"/>
    <text x="${lgX - 75}" y="${PT + 7}" class="chart-legend">Android</text>
    <line x1="${lgX - 42}" y1="${PT + 4}" x2="${lgX - 32}" y2="${PT + 4}" class="chart-line-i"/>
    <circle cx="${lgX - 37}" cy="${PT + 4}" r="2" class="chart-dot-i"/>
    <text x="${lgX - 29}" y="${PT + 7}" class="chart-legend">iOS</text>`

  return `<svg viewBox="0 0 ${W} ${H}" class="rating-chart" xmlns="http://www.w3.org/2000/svg">
    ${grids}${yLabels}${aLine}${iLine}${aDots}${iDots}${xLabels}${legend}
  </svg>`
}

async function renderAppStats () {
  try {
    const stats = await window.api.getAppStats()
    if (!stats || stats.length === 0) {
      appstatsChart.innerHTML = ''
      appstatsList.innerHTML  = '<div class="appstats-empty">수집 후 표시됩니다</div>'
      return
    }

    // service_id 기준으로 그루핑
    const byService = {}
    for (const r of stats) {
      if (!byService[r.service_id]) byService[r.service_id] = { name: r.name_ko, platforms: [] }
      byService[r.service_id].platforms.push(r)
    }

    // 앱 ID가 있지만 app_info 데이터 없는 서비스도 빈 카드로 표시
    for (const svc of SERVICES) {
      if (!byService[svc.id]) {
        const meta = svc.meta || {}
        if (meta.appstore_id_google || meta.appstore_id_ios) {
          byService[svc.id] = { name: svc.name_ko, platforms: [] }
        }
      }
    }

    // 모두의주차장을 가장 왼쪽(첫 번째)으로, 나머지는 리뷰 수 합산 내림차순
    const sorted = Object.entries(byService).sort((a, b) => {
      if (a[0] === 'moduparking') return -1
      if (b[0] === 'moduparking') return  1
      const sumA = a[1].platforms.reduce((s, p) => s + (p.num_ratings || 0), 0)
      const sumB = b[1].platforms.reduce((s, p) => s + (p.num_ratings || 0), 0)
      return sumB - sumA
    })

    // 꺾은선 차트 (제거됨)
    appstatsChart.innerHTML = ''

    // 카드 리스트
    appstatsList.innerHTML = sorted.map(([sid, { name, platforms }]) => {
      const totalReviews = platforms.reduce((s, p) => s + (p.num_ratings || 0), 0)
      const totalLabel   = totalReviews > 0 ? `총 ${fmtCount(totalReviews).trim()}리뷰` : ''
      const rows = platforms.map(p => {
        const plat   = p.platform === 'google_play' ? 'Android' : 'iOS'
        const star   = p.rating != null ? `★${Number(p.rating).toFixed(1)}` : '—'
        const cnt    = p.num_ratings != null ? `${fmtCount(p.num_ratings).trim()}리뷰` : '—'
        const barPct = p.rating != null ? Math.round((p.rating / 5) * 100) : 0
        return `<div class="appstats-row">
          <span class="appstats-plat">${plat}</span>
          <span class="appstats-star">${star}</span>
          <div class="appstats-bar-track">
            <div class="appstats-bar-fill" style="width:${barPct}%"></div>
          </div>
          <span class="appstats-cnt">${cnt}</span>
        </div>`
      }).join('')

      const noData = platforms.length === 0
        ? `<div class="appstats-empty" style="font-size:10px;padding:6px 0">수집 중</div>` : ''

      return `<div class="appstats-item">
        <div class="appstats-name">${esc(name || sid)}</div>
        ${totalLabel ? `<div class="appstats-total">${totalLabel}</div>` : ''}
        ${rows}${noData}
      </div>`
    }).join('')
  } catch (_) {
    appstatsChart.innerHTML = ''
    appstatsList.innerHTML  = ''
  }
}

function fmtCount (n) {
  if (n >= 10000) return `${Math.round(n / 10000)}만 `
  if (n >= 1000)  return `${(n / 1000).toFixed(1)}천 `
  return `${n} `
}

// ──────────────────────────────────────────────
// 인텔리전스 바
// ──────────────────────────────────────────────

/* 인텔바 패널 자동 롤링 헬퍼 */
function _intelRoll (el, chips, window_size, interval_ms) {
  if (!el) return
  if (!chips || chips.length === 0) return
  if (chips.length <= window_size) { el.innerHTML = chips.join(''); return }

  let idx = 0
  function show () {
    const slice = []
    for (let i = 0; i < window_size; i++) slice.push(chips[(idx + i) % chips.length])
    el.style.opacity = '0'
    el.style.transition = 'opacity 0.25s'
    setTimeout(() => {
      el.innerHTML = slice.join('')
      el.style.opacity = '1'
    }, 250)
    idx = (idx + 1) % chips.length
  }
  show()
  setInterval(show, interval_ms)
}

/* 인텔바 클릭 이벤트 위임 */
function _setupIntelClicks () {
  // 차주 예보 → 원문 URL 또는 Naver 검색
  const evEl = $('events-list')
  if (evEl) {
    evEl.addEventListener('click', e => {
      const chip = e.target.closest('[data-url]')
      if (chip && chip.dataset.url) window.open(chip.dataset.url, '_blank')
    })
  }
  // 급상승 키워드 → Naver 뉴스 검색
  const tEl = $('trending-list')
  if (tEl) {
    tEl.addEventListener('click', e => {
      const chip = e.target.closest('[data-kw]')
      if (chip && chip.dataset.kw) {
        window.open('https://search.naver.com/search.naver?where=news&query=' + encodeURIComponent(chip.dataset.kw + ' 주차'), '_blank')
      }
    })
  }
  // 경쟁사 동향 → 해당 서비스 타임라인
  const rEl = $('rival-list')
  if (rEl) {
    rEl.addEventListener('click', e => {
      const chip = e.target.closest('[data-svc]')
      if (chip && chip.dataset.svc) selectService(chip.dataset.svc)
    })
  }
}

async function renderIntelBar () {
  try {
    const [keywords, rivals, events] = await Promise.all([
      window.api.getTrendingKeywords(),
      window.api.getCompetitorActivity(),
      window.api.getUpcomingEvents(),
    ])

    // ── 급상승 키워드 (최대 8개, 5초마다 롤링, 창크기 5)
    const tl = $('trending-list')
    if (tl) {
      if (!keywords || keywords.length === 0) {
        tl.innerHTML = '<span class="intel-loading">데이터 부족</span>'
      } else {
        const chips = keywords.map((k, i) => {
          const arrow = k.prev === 0 ? '<span class="trend-arrow-up">NEW</span>'
                      : k.curr > k.prev ? '<span class="trend-arrow-up">▲</span>'
                      : k.curr < k.prev ? '<span class="trend-arrow-down">▼</span>'
                      : '<span class="trend-arrow-same">—</span>'
          return `<span class="trend-chip" data-kw="${esc(k.word)}">
            <span class="trend-rank">${i+1}</span>
            <span class="trend-word">${esc(k.word)}</span>
            ${arrow}
            <span class="trend-cnt">${k.curr}</span>
          </span>`
        })
        _intelRoll(tl, chips, 5, 5000)
      }
    }

    // ── 경쟁사 동향 (최대 6개, 5초마다 롤링, 창크기 4)
    const rl = $('rival-list')
    if (rl) {
      if (!rivals || rivals.length === 0) {
        rl.innerHTML = '<span class="intel-loading">데이터 부족</span>'
      } else {
        const svcById = Object.fromEntries(SERVICES.map(s => [s.id, s]))
        const chips = rivals.map(r => {
          const name = (svcById[r.service_id] && svcById[r.service_id].name_ko) || r.service_id
          const short = name.length > 6 ? name.slice(0, 6) + '…' : name
          const deltaEl = r.delta > 0 ? `<span class="rival-delta-up">+${r.delta}</span>`
                        : r.delta < 0 ? `<span class="rival-delta-down">${r.delta}</span>`
                        : `<span class="rival-delta-same">±0</span>`
          return `<span class="rival-chip" data-svc="${esc(r.service_id)}">
            <span class="rival-name">${esc(short)}</span>
            <span class="rival-cnt">${r.count}건</span>
            ${deltaEl}
          </span>`
        })
        _intelRoll(rl, chips, 4, 5000)
      }
    }

    // ── 차주 예보 (최대 8개, 6초마다 롤링, 창크기 3)
    const el = $('events-list')
    if (el) {
      if (!events || events.length === 0) {
        el.innerHTML = '<span class="events-empty">차주 예정 이벤트 없음</span>'
      } else {
        const chips = events.map(e => {
          const cls     = e.type === 'holiday' ? 'is-holiday' : 'is-alert'
          const icon    = e.type === 'holiday' ? '📅' : '🎪'
          const dateStr = e.date ? e.date.slice(5) : ''
          const locEl   = e.location ? `<span class="event-loc">📍${esc(e.location)}</span>` : ''
          const noteEl  = e.note && !e.location ? `<span class="event-note">${esc(e.note)}</span>` : ''
          const urlAttr = e.url ? `data-url="${esc(e.url)}"` : ''
          return `<span class="event-chip ${cls}" ${urlAttr} style="cursor:${e.url?'pointer':'default'}">
            ${icon}
            <span class="event-date">${esc(dateStr)}</span>
            ${locEl}
            <span class="event-name">${esc(e.name)}</span>
            ${noteEl}
          </span>`
        })
        _intelRoll(el, chips, 3, 6000)
      }
    }
    _setupIntelClicks()
  } catch (_) {
    // intel bar 실패해도 앱은 계속 동작
  }
}

// 수동 수집 제거 — 데이터 수집은 GitHub Actions 크론(매일 KST 07:00) 담당

// ──────────────────────────────────────────────
// 헬퍼
// ──────────────────────────────────────────────

function updateLastUpdated () {
  if (STATUS.last_run && STATUS.last_run.run_at) {
    const dt = new Date(STATUS.last_run.run_at)
    lastUpdated.textContent = `마지막 수집: ${fmt(dt)}`
  } else {
    lastUpdated.textContent = '마지막 수집: —'
  }
}

function fmt (dt) {
  const pad = n => String(n).padStart(2, '0')
  return `${dt.getFullYear()}-${pad(dt.getMonth()+1)}-${pad(dt.getDate())} ${pad(dt.getHours())}:${pad(dt.getMinutes())}`
}

function renderStars (title) {
  const m = title.match(/★(\d)/)
  if (!m) return ''
  const score = parseInt(m[1])
  return `<span class="card-stars">${'★'.repeat(score)}${'☆'.repeat(5 - score)}</span>`
}

function srcLabel (type, title) {
  if (type === 'appstore') {
    if (title.startsWith('[iOS'))     return 'App Store'
    if (title.startsWith('[App'))     return 'App Store'
    if (title.startsWith('[Android')) return 'Google Play'
    if (title.startsWith('[Google'))  return 'Google Play'
    return 'Store'
  }
  const map = {
    news:         'Google News',
    blog:         '보도자료',
    homepage:     '홈페이지',
    ios_appstore: 'App Store',
    youtube:      'YouTube',
  }
  return map[type] || type || '—'
}

function esc (str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function sleep (ms) { return new Promise(r => setTimeout(r, ms)) }

// ──────────────────────────────────────────────
// 시작
// ──────────────────────────────────────────────

// ── 다크/라이트 테마 토글 ────────────────────────
;(function () {
  var saved = localStorage.getItem('theme') || 'light'
  var btn   = document.getElementById('theme-toggle')
  function _apply (t) {
    document.documentElement.setAttribute('data-theme', t)
    localStorage.setItem('theme', t)
    if (btn) btn.textContent = t === 'dark' ? '☀' : '🌙'
  }
  _apply(saved)
  if (btn) btn.addEventListener('click', function () {
    _apply(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark')
  })
})()

window.addEventListener('DOMContentLoaded', init)
