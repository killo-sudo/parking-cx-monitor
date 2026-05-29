/**
 * THE PARKING GAZETTE — 데일리 에디션 렌더러
 * 흐름: 인증 → curated.json(매일 아침 Claude 루틴이 종합) 로드 → 기사 피드 렌더
 * 우측: 타사 앱 리뷰 / 하단: 운영사별 현재 별점
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
}

// 리뷰 브랜드 정렬 순서 (경쟁사)
const RIVAL_ORDER = ['kakaot_parking', 'tmap_parking', 'iparking', 'nicepark', 'highparking', 'parkingfriends', 'zoomansa', 'amano_korea', 'kmpark', 'parkingcloud', 'sk_shielders']

// ──────────────────────────────────────────────
// 상태
// ──────────────────────────────────────────────
let SERVICES   = []
let SVC_BY_ID  = {}
let EDITION    = null
let _articles  = []
let ACTIVE_WEEK = ''   // 'YYYY-WW' 선택 주차, '' = 전체
let FEED_KW    = ''

let _allReviews     = []
let REVIEW_PLATFORM = ''
let REVIEW_BRAND    = ''

// ──────────────────────────────────────────────
// DOM 참조
// ──────────────────────────────────────────────
const $ = id => document.getElementById(id)

const splash       = $('splash')
const splashMsg    = $('splash-msg')
const splashLog    = $('splash-log')
const feedEl       = $('article-feed')
const subtitle     = $('content-subtitle')
const editionDate  = $('edition-date')
const lastUpdated  = $('last-updated')
const reviewsBody  = $('reviews-body')
const appstatsList = $('appstats-list')

// ──────────────────────────────────────────────
// 스플래시
// ──────────────────────────────────────────────
function showSplash (msg) { splashMsg.textContent = msg; splash.classList.remove('hidden') }
function appendSplashLog (line) { splashLog.textContent += line; splashLog.scrollTop = splashLog.scrollHeight }
function hideSplash () { splash.classList.add('hidden') }

// ──────────────────────────────────────────────
// 초기화 흐름
// ──────────────────────────────────────────────
async function init () {
  showSplash('데이터 확인 중...')
  setupFeedFilter()
  setupReviewFilters()

  try {
    SERVICES = await window.api.getServices()
    SVC_BY_ID = Object.fromEntries(SERVICES.map(s => [s.id, s]))
  } catch (_) { SERVICES = []; SVC_BY_ID = {} }

  try {
    EDITION = await window.api.getCuratedEdition()
    _articles = EDITION.articles || []
    updateEditionMeta()
    buildWeekNav()
    renderFeed()
  } catch (err) {
    feedEl.innerHTML = `<div class="empty-state"><p>${esc(err.message)}</p></div>`
  }

  try { await renderReviews() } catch (_) {}
  try { await renderAppStats() } catch (_) {}
  updateLastUpdated()
  hideSplash()
}

// ──────────────────────────────────────────────
// 에디션 메타
// ──────────────────────────────────────────────
function updateEditionMeta () {
  if (!EDITION) return
  if (editionDate) editionDate.textContent = EDITION.edition_date ? `${EDITION.edition_date} 종합` : ''
  const n = _articles.length
  const win = EDITION.source_window ? ` · 수집창 ${EDITION.source_window}` : ''
  const dropped = (EDITION.dropped && (EDITION.dropped.noise || EDITION.dropped.duplicates))
    ? ` · 노이즈 ${EDITION.dropped.noise || 0}건·중복 ${EDITION.dropped.duplicates || 0}건 제외`
    : ''
  if (subtitle) subtitle.textContent = `${n}개 종합 기사${win}${dropped}`
}

// ──────────────────────────────────────────────
// 주차 네비게이션 (연도 → 주차)
// ──────────────────────────────────────────────
function _weekKeyOf (a) {
  const w = _isoWeek(a.published_at)
  return w ? `${w.year}-${String(w.week).padStart(2, '0')}` : ''
}

function buildWeekNav () {
  const navList = $('week-nav-list')
  if (!navList) return

  // 주차별 집계
  const byWeek = {}
  _articles.forEach(a => {
    const k = _weekKeyOf(a)
    if (!k) return
    if (!byWeek[k]) {
      const w = _isoWeek(a.published_at)
      byWeek[k] = { key: k, year: w.year, week: w.week, range: _weekRange(a.published_at), count: 0 }
    }
    byWeek[k].count++
  })
  const weeks = Object.values(byWeek).sort((a, b) => b.key.localeCompare(a.key))

  // 기본 선택 = 최신 주차
  if (!ACTIVE_WEEK && weeks.length) ACTIVE_WEEK = weeks[0].key

  // 연도 그룹 렌더
  const byYear = {}
  weeks.forEach(w => { (byYear[w.year] = byYear[w.year] || []).push(w) })
  const years = Object.keys(byYear).sort((a, b) => b - a)

  const allItem = `<div class="week-item ${ACTIVE_WEEK === '' ? 'active' : ''}" data-week="">
      <span class="week-name">전체 보기</span>
      <span class="week-cnt">${_articles.length}</span>
    </div>`

  const yearsHtml = years.map(y => {
    const items = byYear[y].map(w =>
      `<div class="week-item ${ACTIVE_WEEK === w.key ? 'active' : ''}" data-week="${w.key}">
        <span class="week-name">${w.week}주차</span>
        <span class="week-range">${w.range}</span>
        <span class="week-cnt">${w.count}</span>
      </div>`
    ).join('')
    return `<div class="week-year-group"><div class="week-year">${y}년</div>${items}</div>`
  }).join('')

  navList.innerHTML = allItem + yearsHtml

  navList.querySelectorAll('.week-item').forEach(el => {
    el.addEventListener('click', () => {
      ACTIVE_WEEK = el.dataset.week || ''
      navList.querySelectorAll('.week-item').forEach(x => x.classList.remove('active'))
      el.classList.add('active')
      renderFeed()
    })
  })
}

// ──────────────────────────────────────────────
// 피드 필터 (카테고리 칩 + 키워드)
// ──────────────────────────────────────────────
function setupFeedFilter () {
  const kwInput = $('filter-kw-input')
  const kwClear = $('filter-kw-clear')
  let _t = null
  if (kwInput) kwInput.addEventListener('input', () => {
    clearTimeout(_t)
    _t = setTimeout(() => { FEED_KW = kwInput.value.trim().toLowerCase(); renderFeed() }, 250)
  })
  if (kwClear) kwClear.addEventListener('click', () => {
    FEED_KW = ''; if (kwInput) kwInput.value = ''; renderFeed()
  })
}

// ──────────────────────────────────────────────
// 기사 피드 렌더링
// ──────────────────────────────────────────────
function renderFeed () {
  let arts = _articles.slice()
  if (ACTIVE_WEEK) arts = arts.filter(a => _weekKeyOf(a) === ACTIVE_WEEK)
  if (FEED_KW) {
    const kws = FEED_KW.split(/\s+/).filter(Boolean)
    arts = arts.filter(a => {
      const hay = `${a.headline || ''} ${a.deck || ''} ${a.body || ''} ${a.cx_note || ''}`.toLowerCase()
      return kws.every(k => hay.includes(k))
    })
  }

  // 선택 주차를 제목/부제에 반영
  const titleEl = $('content-title-text')
  if (ACTIVE_WEEK) {
    const w = _isoWeek(arts[0] ? arts[0].published_at : null) || _parseWeekKey(ACTIVE_WEEK)
    if (titleEl) titleEl.textContent = w ? `${w.year}년 ${w.week}주차` : '주차별 종합'
  } else if (titleEl) {
    titleEl.textContent = '전체 종합'
  }

  if (arts.length === 0) {
    feedEl.innerHTML = `
      <div class="empty-state">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <p>${FEED_KW ? '조건에 맞는 기사가 없습니다.' : '이 주차에 종합된 기사가 없습니다.'}</p>
      </div>`
    return
  }

  // 전체 보기: 주차별 헤더로 구분 / 특정 주차: 평면 목록
  if (!ACTIVE_WEEK) {
    const groups = {}
    arts.forEach(a => {
      const k = _weekKeyOf(a) || '0000-00'
      ;(groups[k] = groups[k] || []).push(a)
    })
    const keys = Object.keys(groups).sort((a, b) => b.localeCompare(a))
    feedEl.innerHTML = keys.map(k => {
      const items = groups[k]
      const w = _isoWeek(items[0].published_at)
      const hdr = w
        ? `<div class="gz-week-header"><span class="gz-week-num">${w.year}년 ${w.week}주차</span><span class="gz-week-range">${_weekRange(items[0].published_at)} · ${items.length}건</span></div>`
        : ''
      return hdr + items.map(renderArticleCard).join('')
    }).join('')
  } else {
    feedEl.innerHTML = arts.map(renderArticleCard).join('')
  }
}

function _parseWeekKey (key) {
  const m = (key || '').match(/^(\d{4})-(\d{2})$/)
  return m ? { year: +m[1], week: +m[2] } : null
}

function renderArticleCard (a) {
  const cat   = a.category || '기타'
  const svcEls = (a.service_ids || []).map(sid => {
    const svc = SVC_BY_ID[sid]
    const nm  = svc ? svc.name_ko : sid
    const col = SVC_COLORS[sid] || 'var(--text-3)'
    return `<span class="gz-svc" style="--svc:${col}">${esc(nm)}</span>`
  }).join('')

  const impEl = a.importance === 'high'
    ? `<span class="gz-imp imp-high">핵심</span>`
    : (a.importance === 'mid' ? `<span class="gz-imp imp-mid">주목</span>` : '')

  const bodyHtml = (a.body || '').split(/\n\n+/).map(p => `<p>${esc(p.trim())}</p>`).join('')

  const cxHtml = a.cx_note
    ? `<div class="gz-cxnote">
         <div class="gz-cxnote-label">🅼 모두의주차장 관점</div>
         <div class="gz-cxnote-text">${esc(a.cx_note)}</div>
       </div>`
    : ''

  const srcChips = (a.sources || []).map(s =>
    `<a class="gz-src" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.outlet || '원문')}</a>`
  ).join('')
  const srcExtra = (a.source_count && a.source_count > (a.sources || []).length)
    ? `<span class="gz-src-more">+${a.source_count - (a.sources || []).length}건</span>` : ''

  return `
    <article class="gz-article" data-cat="${esc(cat)}">
      <div class="gz-meta">
        <span class="gz-cat type-${esc(cat)}">${esc(cat)}</span>
        ${impEl}
        <span class="gz-date">${_fmtDate(a.published_at || '')}</span>
        ${svcEls}
        <span class="gz-srccount">출처 ${a.source_count || (a.sources || []).length}건</span>
      </div>
      <h2 class="gz-headline">${esc(a.headline || '')}</h2>
      ${a.deck ? `<p class="gz-deck">${esc(a.deck)}</p>` : ''}
      <div class="gz-body">${bodyHtml}</div>
      ${cxHtml}
      ${srcChips ? `<div class="gz-sources"><span class="gz-sources-label">출처</span>${srcChips}${srcExtra}</div>` : ''}
    </article>`
}

// ──────────────────────────────────────────────
// 타사 앱 리뷰 패널
// ──────────────────────────────────────────────
function setupReviewFilters () {
  const platRow  = $('review-filter-platform')
  const brandRow = $('review-filter-brand')
  if (platRow) platRow.addEventListener('click', e => {
    const chip = e.target.closest('.review-filter-chip[data-platform]')
    if (!chip) return
    platRow.querySelectorAll('.review-filter-chip').forEach(c => c.classList.remove('active'))
    chip.classList.add('active')
    REVIEW_PLATFORM = chip.dataset.platform || ''
    _renderReviewCards()
  })
  if (brandRow) brandRow.addEventListener('click', e => {
    const chip = e.target.closest('.review-filter-chip[data-brand]')
    if (!chip) return
    brandRow.querySelectorAll('.review-filter-chip').forEach(c => c.classList.remove('active'))
    chip.classList.add('active')
    REVIEW_BRAND = chip.dataset.brand || ''
    _renderReviewCards()
  })
}

function _renderReviewBrandChips (brandIds) {
  const brandRow = $('review-filter-brand')
  if (!brandRow) return
  const chips = brandIds.map(sid => {
    const name = (SVC_BY_ID[sid] && SVC_BY_ID[sid].name_ko) || sid
    return `<button class="review-filter-chip" data-brand="${esc(sid)}">${esc(name)}</button>`
  }).join('')
  brandRow.innerHTML = `<button class="review-filter-chip active" data-brand="">전체</button>${chips}`
}

function _renderReviewCards () {
  if (!reviewsBody) return
  let filtered = _allReviews
  if (REVIEW_PLATFORM === 'ios') {
    filtered = filtered.filter(r => r.source_type === 'ios_appstore' || (r.title || '').startsWith('[iOS'))
  } else if (REVIEW_PLATFORM === 'android') {
    filtered = filtered.filter(r => r.source_type === 'appstore' && !(r.title || '').startsWith('[iOS'))
  }
  if (REVIEW_BRAND) filtered = filtered.filter(r => r.service_id === REVIEW_BRAND)

  const countEl = $('reviews-count')
  if (countEl) countEl.textContent = filtered.length > 0 ? `${filtered.length}건` : ''

  if (filtered.length === 0) {
    reviewsBody.innerHTML = `<div class="empty-state" style="padding:20px"><p style="font-size:11px">수집된 리뷰가 없습니다.</p></div>`
    return
  }

  reviewsBody.innerHTML = filtered.map(r => {
    const title = r.title || ''
    const isIos = r.source_type === 'ios_appstore' || title.startsWith('[iOS')
    const platLabel = isIos ? 'iOS' : 'Android'
    const platCls   = isIos ? 'review-card-platform--ios' : 'review-card-platform--android'
    const svc       = SVC_BY_ID[r.service_id]
    const brandName = svc ? svc.name_ko : (r.service_id || '')
    const m     = title.match(/★(\d)/)
    const score = m ? parseInt(m[1]) : 0
    const stars = score > 0 ? '★'.repeat(score) + '☆'.repeat(5 - score) : ''
    const dateStr = _fmtReviewDate(r.published_at || '') || _fmtReviewDate(r.collected_at || '')
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
  const reviews = await window.api.getRecentReviews()
  // 우측 패널 = 타사 리뷰. 자사(모두의주차장) VOC는 CSAT 리포트가 담당.
  _allReviews = reviews.filter(r => r.service_id !== 'moduparking')

  const brandSet = new Set(_allReviews.map(r => r.service_id).filter(Boolean))
  const brandIds = [...brandSet].sort((a, b) => {
    const ia = RIVAL_ORDER.indexOf(a), ib = RIVAL_ORDER.indexOf(b)
    if (ia === -1 && ib === -1) return 0
    if (ia === -1) return 1
    if (ib === -1) return -1
    return ia - ib
  })
  _renderReviewBrandChips(brandIds)
  _renderReviewCards()
}

// ──────────────────────────────────────────────
// 운영사별 현재 별점 (하단)
// ──────────────────────────────────────────────
async function renderAppStats () {
  const stats = await window.api.getAppStats()
  if (!stats || stats.length === 0) {
    appstatsList.innerHTML = '<div class="appstats-empty">수집 후 표시됩니다</div>'
    return
  }
  const byService = {}
  for (const r of stats) {
    if (!byService[r.service_id]) byService[r.service_id] = { name: r.name_ko, platforms: [] }
    byService[r.service_id].platforms.push(r)
  }
  for (const svc of SERVICES) {
    if (!byService[svc.id]) {
      const meta = svc.meta || {}
      if (meta.appstore_id_google || meta.appstore_id_ios) byService[svc.id] = { name: svc.name_ko, platforms: [] }
    }
  }
  const sorted = Object.entries(byService).sort((a, b) => {
    if (a[0] === 'moduparking') return -1
    if (b[0] === 'moduparking') return 1
    const sumA = a[1].platforms.reduce((s, p) => s + (p.num_ratings || 0), 0)
    const sumB = b[1].platforms.reduce((s, p) => s + (p.num_ratings || 0), 0)
    return sumB - sumA
  })

  appstatsList.innerHTML = sorted.map(([sid, { name, platforms }]) => {
    const totalReviews = platforms.reduce((s, p) => s + (p.num_ratings || 0), 0)
    const totalLabel   = totalReviews > 0 ? `총 ${fmtCount(totalReviews).trim()}리뷰` : ''
    const isModu = sid === 'moduparking'
    const rows = platforms.map(p => {
      const plat   = p.platform === 'google_play' ? 'Android' : 'iOS'
      const star   = p.rating != null ? `★${Number(p.rating).toFixed(1)}` : '—'
      const cnt    = p.num_ratings != null ? `${fmtCount(p.num_ratings).trim()}리뷰` : '—'
      const barPct = p.rating != null ? Math.round((p.rating / 5) * 100) : 0
      return `<div class="appstats-row">
        <span class="appstats-plat">${plat}</span>
        <span class="appstats-star">${star}</span>
        <div class="appstats-bar-track"><div class="appstats-bar-fill" style="width:${barPct}%"></div></div>
        <span class="appstats-cnt">${cnt}</span>
      </div>`
    }).join('')
    const noData = platforms.length === 0 ? `<div class="appstats-empty" style="font-size:10px;padding:6px 0">수집 중</div>` : ''
    return `<div class="appstats-item${isModu ? ' is-modu' : ''}">
      <div class="appstats-name">${esc(name || sid)}${isModu ? ' <span class="appstats-tag">자사</span>' : ''}</div>
      ${totalLabel ? `<div class="appstats-total">${totalLabel}</div>` : ''}
      ${rows}${noData}
    </div>`
  }).join('')
}

function fmtCount (n) {
  if (n >= 10000) return `${Math.round(n / 10000)}만 `
  if (n >= 1000)  return `${(n / 1000).toFixed(1)}천 `
  return `${n} `
}

// ──────────────────────────────────────────────
// 헬퍼
// ──────────────────────────────────────────────
function updateLastUpdated () {
  // data.json 기반 마지막 수집시각이 있으면 표시
  if (window.api.getStatus) {
    window.api.getStatus().then(st => {
      if (st && st.last_run && st.last_run.run_at) {
        const dt = new Date(st.last_run.run_at)
        if (!isNaN(dt.getTime())) lastUpdated.textContent = `마지막 수집: ${fmt(dt)}`
      }
    }).catch(() => {})
  }
}

function fmt (dt) {
  const pad = n => String(n).padStart(2, '0')
  return `${dt.getFullYear()}-${pad(dt.getMonth()+1)}-${pad(dt.getDate())} ${pad(dt.getHours())}:${pad(dt.getMinutes())}`
}

// ISO 주차(연도·주차번호) — 기존 가제트 week_num과 동일 체계
function _isoWeek (dateStr) {
  const m = (dateStr || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return null
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]))
  const dayNr = (d.getUTCDay() + 6) % 7          // Mon=0
  d.setUTCDate(d.getUTCDate() - dayNr + 3)        // 해당 주 목요일
  const firstThu = new Date(Date.UTC(d.getUTCFullYear(), 0, 4))
  const firstThuDayNr = (firstThu.getUTCDay() + 6) % 7
  firstThu.setUTCDate(firstThu.getUTCDate() - firstThuDayNr + 3)
  const week = 1 + Math.round((d - firstThu) / (7 * 86400000))
  return { year: d.getUTCFullYear(), week }
}
function _weekRange (dateStr) {
  const m = (dateStr || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return ''
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]))
  const dayNr = (d.getUTCDay() + 6) % 7
  const mon = new Date(d); mon.setUTCDate(d.getUTCDate() - dayNr)
  const sun = new Date(mon); sun.setUTCDate(mon.getUTCDate() + 6)
  const f = x => `${String(x.getUTCMonth() + 1).padStart(2, '0')}.${String(x.getUTCDate()).padStart(2, '0')}`
  return `${f(mon)} ~ ${f(sun)}`
}

function _fmtDate (raw) {
  if (!raw) return ''
  const iso = raw.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (iso) return `${iso[1]}.${iso[2]}.${iso[3]}`
  try {
    const d = new Date(raw)
    if (!isNaN(d.getTime())) {
      const pad = n => String(n).padStart(2, '0')
      return `${d.getFullYear()}.${pad(d.getMonth()+1)}.${pad(d.getDate())}`
    }
  } catch (_) {}
  return raw.slice(0, 10)
}

function _fmtReviewDate (raw) {
  if (!raw) return ''
  const iso = raw.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (iso && parseInt(iso[1]) >= 2020) return `${iso[1]}.${iso[2]}.${iso[3]}`
  try {
    const d = new Date(raw)
    if (!isNaN(d.getTime()) && d.getFullYear() >= 2020) {
      const pad = n => String(n).padStart(2, '0')
      return `${d.getFullYear()}.${pad(d.getMonth()+1)}.${pad(d.getDate())}`
    }
  } catch (_) {}
  return ''
}

function esc (str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

// ──────────────────────────────────────────────
// 다크/라이트 테마 토글
// ──────────────────────────────────────────────
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
