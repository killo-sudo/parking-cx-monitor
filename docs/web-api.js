/**
 * THE PARKING GAZETTE — 인증 + API 레이어
 * Google Identity Services(@socar.kr 전용) + Google Apps Script 백엔드
 */

// ── 설정 ──────────────────────────────────────
var CLIENT_ID = '1024138918729-3kmpkjb07fs7a0i8uhbtni6el991q4gs.apps.googleusercontent.com';
var GAS_URL   = 'GAS_URL_PLACEHOLDER';  // GAS 배포 후 교체

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
  if (authUser) authUser.textContent = payload.name || payload.email;

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

  async getAppStats () { return await _loadAppInfo(); }
};

console.info('[web-api] GitHub Pages + GIS 인증 모드');
