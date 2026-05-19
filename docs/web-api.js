/**
 * THE PARKING GAZETTE — 인증 + API 레이어
 * Google Identity Services(@socar.kr 전용) + Google Apps Script 백엔드
 */

// ── 설정 ──────────────────────────────────────
var CLIENT_ID = '495055817211-o0m1u8d2aglluhng1kr6fvua95u8emqp.apps.googleusercontent.com';
var GAS_URL   = 'https://script.google.com/a/macros/socar.kr/s/AKfycbxFtyFS5wvJ6jYu8f-FZZGM8L0fdkxu41XpifuNfUTwgVor6DbvzRGfyC3GocL_a2A2qg/exec';

var JWT_KEY  = 'pg_jwt';
var JWT_TTL  = 6 * 60 * 60 * 1000;   // 6시간
var ALLOWED_DOMAIN = 'socar.kr';

// ── JWT 저장 / 조회 ───────────────────────────
function _getStoredJwt () {
  try {
    var item = JSON.parse(localStorage.getItem(JWT_KEY) || 'null');
    if (!item) return null;
    if (Date.now() > item.exp) { localStorage.removeItem(JWT_KEY); return null; }
    return item.token;
  } catch (_) { return null; }
}

function _storeJwt (token) {
  localStorage.setItem(JWT_KEY, JSON.stringify({
    token: token,
    exp:   Date.now() + JWT_TTL
  }));
}

function _decodeJwt (token) {
  try {
    var payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(payload));
  } catch (_) { return null; }
}

// ── 인증 오버레이 ──────────────────────────────
var authOverlay = document.getElementById('auth-overlay');
var authMsg     = document.getElementById('auth-msg');
var authUser    = document.getElementById('auth-user');

function _showAuthOverlay () {
  if (authOverlay) authOverlay.style.display = 'flex';
}

function _hideAuthOverlay () {
  if (authOverlay) authOverlay.style.display = 'none';
}

function _setAuthError (msg) {
  if (authMsg) { authMsg.textContent = msg; authMsg.style.color = '#ef4444'; }
}

// ── GIS 초기화 ────────────────────────────────
var _gisReady = false;

function _initGis () {
  if (typeof google === 'undefined' || !google.accounts) {
    setTimeout(_initGis, 200);
    return;
  }
  _gisReady = true;

  google.accounts.id.initialize({
    client_id:         CLIENT_ID,
    callback:          _onGisCallback,
    auto_select:       false,
    cancel_on_tap_outside: false
  });

  var btnEl = document.getElementById('auth-gsi-btn');
  if (btnEl) {
    google.accounts.id.renderButton(btnEl, {
      type:  'standard',
      theme: 'outline',
      size:  'large',
      text:  'signin_with',
      logo_alignment: 'left',
      locale: 'ko'
    });
  }
}

function _onGisCallback (response) {
  var token   = response.credential;
  var payload = _decodeJwt(token);

  if (!payload || !payload.email) {
    _setAuthError('인증 정보를 읽을 수 없습니다.');
    return;
  }

  var domain = payload.email.split('@')[1];
  if (domain !== ALLOWED_DOMAIN) {
    _setAuthError('@socar.kr 계정만 접근 가능합니다. (' + payload.email + ')');
    google.accounts.id.revoke(payload.email, function () {});
    return;
  }

  _storeJwt(token);
  _hideAuthOverlay();
  if (authUser) { var _e = payload.email || ''; authUser.textContent = _e.split('@')[0] || _e; }

  // 앱 초기화 재시작
  if (typeof init === 'function') init();
}

// ── 앱 시작 진입점 ────────────────────────────
(function bootstrap () {
  var stored = _getStoredJwt();
  if (stored) {
    var payload = _decodeJwt(stored);
    _hideAuthOverlay();
    if (authUser && payload) authUser.textContent = payload.name || payload.email;
    // app.js의 DOMContentLoaded → init() 이 자동 실행됨
  } else {
    _showAuthOverlay();
    _initGis();
    // 인증 완료 후 _onGisCallback에서 init() 호출
  }
})();

// ── 데이터 캐시 ───────────────────────────────
var _allData = null;
var _cacheTs = 0;
var CACHE_TTL = 5 * 60 * 1000;

async function _loadAll () {
  var now = Date.now();
  if (_allData && now - _cacheTs < CACHE_TTL) return _allData;

  if (!GAS_URL || GAS_URL === 'GAS_URL_PLACEHOLDER') {
    throw new Error('GAS_URL이 설정되지 않았습니다.');
  }

  var token = _getStoredJwt();
  var url   = GAS_URL + (token ? '?token=' + encodeURIComponent(token) : '');
  var res   = await fetch(url);
  var json  = await res.json();

  if (json.auth === false) {
    // 토큰 만료 — 재로그인
    localStorage.removeItem(JWT_KEY);
    _showAuthOverlay();
    _initGis();
    throw new Error('세션이 만료되었습니다. 다시 로그인해주세요.');
  }
  if (!json.ok) throw new Error(json.error || 'GAS 오류');

  json.items.sort(function (a, b) {
    return (b.published_at || '').localeCompare(a.published_at || '');
  });

  _allData = json;
  _cacheTs = now;
  return _allData;
}

var _svcs     = null;
var _appInfos = null;

async function _loadServices () {
  if (_svcs) return _svcs;
  var res  = await fetch('services.json');
  var data = await res.json();
  _svcs = data.services || [];
  return _svcs;
}

async function _loadAppInfo () {
  if (_appInfos !== null) return _appInfos;
  try {
    var res  = await fetch('app_info.json');
    var data = await res.json();
    _appInfos = Array.isArray(data) ? data : (data.app_info || []);
  } catch (_) { _appInfos = []; }
  return _appInfos;
}

// ── window.api ────────────────────────────────
window.api = {

  async getStatus () {
    var data = await _loadAll();
    return {
      crawled_today: true,
      today_total:   data.total || 0,
      last_run:      { run_at: data.last_updated }
    };
  },

  async getServices () {
    var svcs = await _loadServices();
    var data = await _loadAll();
    var counts = {};
    for (var i = 0; i < data.items.length; i++) {
      var sid = data.items[i].service_id;
      counts[sid] = (counts[sid] || 0) + 1;
    }
    return svcs.map(function (s) {
      return { id: s.id, name_ko: s.name_ko, operator: s.operator,
               category: s.category, count: counts[s.id] || 0, meta: s };
    });
  },

  async getChanges (svcId) {
    var data = await _loadAll();
    return data.items.filter(function (i) { return i.service_id === svcId; });
  },

  async getAllChanges (type) {
    var data = await _loadAll();
    if (!type) return data.items;
    return data.items.filter(function (i) { return i.change_type === type; });
  },

  async getSummary () {
    var data   = await _loadAll();
    var cutoff = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString().slice(0, 10);
    return data.items.filter(function (i) {
      return ((i.collected_at || i.published_at || '').slice(0, 10)) >= cutoff;
    }).slice(0, 50);
  },

  async searchFeats (q) {
    if (!q) return [];
    var data = await _loadAll();
    var ql   = q.toLowerCase();
    var seen = {}, results = [];
    for (var i = 0; i < data.items.length; i++) {
      var item = data.items[i];
      var text = ((item.title || '') + ' ' + (item.summary || '')).toLowerCase();
      if (!text.includes(ql)) continue;
      var key = item.url || (item.title + item.service_id);
      if (seen[key]) continue;
      seen[key] = true;
      results.push({ name_ko: item.title, providers: [item.service_id], url: item.url });
      if (results.length >= 30) break;
    }
    return results;
  },

  async getAppStats () { return await _loadAppInfo(); },

  async getTrendingKeywords () {
    var data = await _loadAll();
    var now  = Date.now();
    var d7   = new Date(now - 7  * 86400000).toISOString().slice(0, 10);
    var d14  = new Date(now - 14 * 86400000).toISOString().slice(0, 10);
    var STOP = new Set(['주차','이용','서비스','주차장','고객','주차권','안내','제공','관련','통해',
                        '대한','진행','운영','기준','경우','이번','없음','완료','처리','가능','위해',
                        '통한','하여','으로','에서','있는','있어','있습','합니다','됩니다','합니다']);
    function tok (t) { return ((t||'').match(/[가-힣]{2,}/g)||[]); }
    var thisW = {}, prevW = {};
    data.items.forEach(function (item) {
      var date = (item.collected_at||item.published_at||'').slice(0,10);
      tok((item.title||'')+' '+(item.summary||'')).forEach(function (w) {
        if (STOP.has(w)) return;
        if (date >= d7)       { thisW[w] = (thisW[w]||0) + 1; }
        else if (date >= d14) { prevW[w] = (prevW[w]||0) + 1; }
      });
    });
    return Object.keys(thisW)
      .filter(function (w) { return thisW[w] >= 2; })
      .map(function (w) {
        var c = thisW[w], p = prevW[w]||0;
        return { word: w, curr: c, prev: p, score: c * (c / (p + 1)) };
      })
      .sort(function (a, b) { return b.score - a.score; })
      .slice(0, 8);
  },

  async getCompetitorActivity () {
    var data    = await _loadAll();
    var cutoff  = new Date(Date.now() -  7 * 86400000).toISOString().slice(0, 10);
    var cutoff2 = new Date(Date.now() - 14 * 86400000).toISOString().slice(0, 10);
    var tw = {}, pw = {};
    data.items.forEach(function (item) {
      if (item.service_id === 'moduparking') return;
      var date = (item.collected_at||item.published_at||'').slice(0,10);
      if (date >= cutoff)       { tw[item.service_id] = (tw[item.service_id]||0) + 1; }
      else if (date >= cutoff2) { pw[item.service_id] = (pw[item.service_id]||0) + 1; }
    });
    return Object.keys(tw)
      .map(function (sid) {
        var c = tw[sid], p = pw[sid]||0;
        return { service_id: sid, count: c, prev: p, delta: c - p };
      })
      .sort(function (a, b) { return b.count - a.count; })
      .slice(0, 6);
  },

  async getUpcomingEvents () {
    var KR_HOLIDAYS = [
      {date:'2026-05-25', name:'부처님오신날', note:'연등행렬·법회'},
      {date:'2026-06-06', name:'현충일', note:'추모 행사'},
      {date:'2026-08-14', name:'광복절 연휴', note:'귀향 차량 증가'},
      {date:'2026-08-15', name:'광복절', note:'행사·집회'},
      {date:'2026-09-24', name:'추석 연휴', note:'귀성 차량 증가'},
      {date:'2026-09-25', name:'추석', note:'명절'},
      {date:'2026-09-26', name:'추석 연휴', note:'귀경 차량 증가'},
      {date:'2026-09-27', name:'추석 연휴', note:'귀경 차량 증가'},
      {date:'2026-10-03', name:'개천절'},
      {date:'2026-10-09', name:'한글날'},
      {date:'2026-12-25', name:'크리스마스', note:'쇼핑몰 주차 혼잡'},
      {date:'2026-12-31', name:'연말', note:'카운트다운 행사'},
      {date:'2027-01-01', name:'신정'},
    ];

    /* 지역명 추출용 */
    var REGIONS = [
      '서울','부산','대구','인천','광주','대전','울산','수원','성남','제주',
      '강남','강북','종로','마포','홍대','여의도','광화문','잠실','코엑스',
      '한강','강릉','전주','춘천','경기','인천공항','김포','속초','경주'
    ];
    function extractLoc (text) {
      for (var i = 0; i < REGIONS.length; i++) {
        if (text.includes(REGIONS[i])) return REGIONS[i];
      }
      return null;
    }

    /* 차주 월요일 ~ 차차주 일요일 (2주 창) 계산 */
    var _now = new Date();
    var _dow = _now.getDay(); // 0=일, 1=월
    var _daysToNextMon = (_dow === 1) ? 7 : (8 - _dow) % 7;
    var _nextMon  = new Date(_now.getTime() + _daysToNextMon       * 86400000);
    var _windowEnd = new Date(_nextMon.getTime() + 13              * 86400000);
    var fromStr   = _nextMon.toISOString().slice(0, 10);
    var toStr     = _windowEnd.toISOString().slice(0, 10);
    var cutoff7   = new Date(Date.now() -  7 * 86400000).toISOString().slice(0, 10);

    /* 공휴일 (차주 월~차차주 일) */
    var events = KR_HOLIDAYS.filter(function (h) {
      return h.date >= fromStr && h.date <= toStr;
    }).map(function (h) {
      return Object.assign({ type:'holiday', url: 'https://search.naver.com/search.naver?where=news&query=' + encodeURIComponent(h.name + ' 행사') }, h);
    });

    try {
      var data = await _loadAll();

      /* Phase 1: 토픽별 기사 수 집계 — service_id=events 뉴스만 */
      var topicMap = {};
      data.items.forEach(function (item) {
        if (item.service_id !== 'events') return;
        var date = (item.collected_at||item.published_at||'').slice(0,10);
        if (date < cutoff7) return;

        var key = (item.title||'').slice(0, 15);
        if (!topicMap[key]) topicMap[key] = { count: 0, item: item };
        topicMap[key].count++;
      });

      /* Phase 2: 기사 수 내림차순 → 인기 이벤트 앞에 */
      Object.keys(topicMap).forEach(function (k) {
        var entry = topicMap[k];
        var item  = entry.item;
        var text  = (item.title||'') + ' ' + (item.summary||'');
        var loc   = extractLoc(text);
        var name  = (item.title||'').replace(/<[^>]+>/g, '').trim();
        events.push({
          date:     (item.published_at||'').slice(0,10),
          name:     name,
          location: loc,
          type:     'event',
          url:      item.url || ('https://search.naver.com/search.naver?where=news&query=' + encodeURIComponent(name)),
          count:    entry.count,
        });
      });
    } catch (_) {}

    /* 공휴일 날짜순 + 이벤트 Naver 인기순(기사 수↓) */
    events.sort(function (a, b) {
      if (a.type === 'holiday' && b.type !== 'holiday') return -1;
      if (b.type === 'holiday' && a.type !== 'holiday') return  1;
      if (a.type === 'holiday') return (a.date||'').localeCompare(b.date||'');
      return (b.count||0) - (a.count||0);
    });
    return events.slice(0, 8);
  }
};

console.info('[web-api] GitHub Pages + GIS 인증 모드');
