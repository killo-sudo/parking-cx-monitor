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
// CRAWLING 플래그 제거 — 수동 수집 기능 없음

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
const searchInput   = $('search-input')
const searchResults = $('search-results')
const summaryList   = $('summary-list')
const todayCount    = $('today-count')
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
    await renderSummary()
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
      await renderSummary()
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
  if (!changes || changes.length === 0) {
    timeline.innerHTML = `
      <div class="empty-state">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <p>수집된 변경사항이 없습니다.</p>
        <p style="font-size:11px">상단 "다시 수집" 버튼으로 갱신해보세요.</p>
      </div>`
    return
  }

  const cutoff24h = new Date(Date.now() - 24 * 60 * 60 * 1000)

  timeline.innerHTML = changes.map(c => {
    const isNew   = new Date(c.collected_at) > cutoff24h
    const typeKl  = `type-${c.change_type || '기타'}`
    const srcLbl  = srcLabel(c.source_type, c.title || '')

    const svcBadge = (!svc && c.name_ko)
      ? `<span class="card-svc-badge">${esc(c.name_ko)}</span>`
      : ''

    const starsEl = renderStars(c.title || '')

    // 50자 이상이고 제목과 앞 30자가 다르면 진짜 요약으로 판단
    const hasSummary = c.summary &&
                       c.summary.trim().length > 50 &&
                       c.summary.trim().slice(0, 30) !== (c.title || '').trim().slice(0, 30)

    // 진짜 요약 있을 때만 expand; URL은 카드 우측에 작은 링크로 항상 노출
    const hasExpand  = hasSummary

    const urlLink    = c.url
      ? `<a class="card-url-link" href="${esc(c.url)}" target="_blank">↗ 원문</a>`
      : ''

    const expandSection = hasSummary ? `
      <div class="card-expand">
        <div class="card-summary">${esc(c.summary)}</div>
        ${c.url
          ? `<a class="card-goto-btn" href="${esc(c.url)}" target="_blank">↗ 원문 바로가기</a>`
          : ''
        }
      </div>` : ''

    return `
      <div class="change-card ${isNew ? 'is-new' : ''}"
           data-type="${esc(c.change_type || '기타')}"
           ${hasExpand ? 'data-expandable="true"' : ''}>
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
          ${hasExpand ? '<span class="card-expand-icon">▾</span>' : ''}
        </div>
        ${expandSection}
      </div>`
  }).join('')
}

// 카드 클릭 시 요약 펼치기/접기 (이벤트 위임)
timeline.addEventListener('click', e => {
  if (e.target.closest('a')) return   // 링크 클릭은 통과
  const card = e.target.closest('.change-card[data-expandable]')
  if (!card) return
  card.dataset.expanded = card.dataset.expanded === 'true' ? 'false' : 'true'
})

// ──────────────────────────────────────────────
// 오늘의 요약 렌더링
// ──────────────────────────────────────────────

async function renderSummary () {
  try {
    const items = await window.api.getSummary()
    todayCount.textContent = items.length

    if (items.length === 0) {
      summaryList.innerHTML = `
        <div class="empty-state" style="padding:20px">
          <p style="font-size:11px">오늘 수집된 항목이 없습니다.</p>
        </div>`
      return
    }

    summaryList.innerHTML = items.map(item => `
      <div class="summary-item" data-svc="${esc(item.service_id)}">
        <div class="summary-item-svc">${esc(item.name_ko || item.service_id)}</div>
        <div class="summary-item-title">${esc(item.title || '')}</div>
      </div>`
    ).join('')

    summaryList.querySelectorAll('.summary-item').forEach(el => {
      el.addEventListener('click', () => selectService(el.dataset.svc))
    })
  } catch (_) {
    summaryList.innerHTML = ''
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
// 기능 검색
// ──────────────────────────────────────────────

let _searchTimer = null

searchInput.addEventListener('input', () => {
  clearTimeout(_searchTimer)
  _searchTimer = setTimeout(doSearch, 250)
})

async function doSearch () {
  const q = searchInput.value.trim()
  if (!q) { searchResults.innerHTML = ''; return }

  try {
    const feats = await window.api.searchFeats(q)
    if (!feats || feats.length === 0) {
      searchResults.innerHTML = `<div style="font-size:11px;color:var(--ink-ghost);padding:4px 0">일치하는 기능 없음</div>`
      return
    }

    searchResults.innerHTML = feats.map(f => {
      const chips = (f.providers || []).map(pid => {
        const svc  = SERVICES.find(s => s.id === pid)
        const name = svc ? svc.name_ko : pid
        return `<span class="feat-provider-chip">${esc(name)}</span>`
      }).join('')
      return `
        <div class="feat-result">
          <div class="feat-name">${esc(f.name_ko)}</div>
          <div class="feat-providers">${chips}</div>
        </div>`
    }).join('')
  } catch (_) {
    searchResults.innerHTML = ''
  }
}

// ──────────────────────────────────────────────
// 인텔리전스 바
// ──────────────────────────────────────────────

async function renderIntelBar () {
  try {
    const [keywords, rivals, events] = await Promise.all([
      window.api.getTrendingKeywords(),
      window.api.getCompetitorActivity(),
      window.api.getUpcomingEvents(),
    ])

    // ── 급상승 키워드
    const tl = $('trending-list')
    if (tl) {
      if (!keywords || keywords.length === 0) {
        tl.innerHTML = '<span class="intel-loading">데이터 부족</span>'
      } else {
        tl.innerHTML = keywords.map((k, i) => {
          const arrow = k.prev === 0 ? '<span class="trend-arrow-up">NEW</span>'
                      : k.curr > k.prev ? '<span class="trend-arrow-up">▲</span>'
                      : k.curr < k.prev ? '<span class="trend-arrow-down">▼</span>'
                      : '<span class="trend-arrow-same">—</span>'
          return `<span class="trend-chip">
            <span class="trend-rank">${i+1}</span>
            <span class="trend-word">${esc(k.word)}</span>
            ${arrow}
            <span class="trend-cnt">${k.curr}</span>
          </span>`
        }).join('')
      }
    }

    // ── 경쟁사 동향
    const rl = $('rival-list')
    if (rl) {
      if (!rivals || rivals.length === 0) {
        rl.innerHTML = '<span class="intel-loading">데이터 부족</span>'
      } else {
        const svcById = Object.fromEntries(SERVICES.map(s => [s.id, s]))
        rl.innerHTML = rivals.map(r => {
          const name = (svcById[r.service_id] && svcById[r.service_id].name_ko) || r.service_id
          const short = name.length > 6 ? name.slice(0, 6) + '…' : name
          const deltaEl = r.delta > 0 ? `<span class="rival-delta-up">+${r.delta}</span>`
                        : r.delta < 0 ? `<span class="rival-delta-down">${r.delta}</span>`
                        : `<span class="rival-delta-same">±0</span>`
          return `<span class="rival-chip">
            <span class="rival-name">${esc(short)}</span>
            <span class="rival-cnt">${r.count}건</span>
            ${deltaEl}
          </span>`
        }).join('')
      }
    }

    // ── 차주 예보
    const el = $('events-list')
    if (el) {
      if (!events || events.length === 0) {
        el.innerHTML = '<span class="events-empty">차주 예정 이벤트 없음</span>'
      } else {
        el.innerHTML = events.map(e => {
          const cls = e.type === 'holiday' ? 'is-holiday' : 'is-alert'
          const icon = e.type === 'holiday' ? '📅' : '🚗'
          const dateStr = e.date ? e.date.slice(5) : ''
          return `<span class="event-chip ${cls}">
            ${icon}
            <span class="event-date">${esc(dateStr)}</span>
            <span class="event-name">${esc(e.name)}</span>
          </span>`
        }).join('')
      }
    }
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

window.addEventListener('DOMContentLoaded', init)
