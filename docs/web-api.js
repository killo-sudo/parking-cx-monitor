/**
 * THE PARKING GAZETTE — 정적 사이트용 API 레이어
 * Google Apps Script를 백엔드로 사용 (Railway 없음, 완전 무료)
 *
 * GAS 배포 후 아래 GAS_URL을 실제 배포 URL로 교체하세요.
 */

var GAS_URL = 'GAS_URL_PLACEHOLDER';

// ── 캐시 ──────────────────────────────────────
var _allData  = null;
var _cacheTs  = 0;
var CACHE_TTL = 5 * 60 * 1000; // 5분

async function _loadAll() {
  var now = Date.now();
  if (_allData && now - _cacheTs < CACHE_TTL) return _allData;

  if (!GAS_URL || GAS_URL === 'GAS_URL_PLACEHOLDER') {
    throw new Error('GAS_URL이 설정되지 않았습니다. docs/web-api.js를 확인하세요.');
  }

  var res  = await fetch(GAS_URL);
  var json = await res.json();
  if (!json.ok) throw new Error(json.error || 'GAS 오류');

  // 날짜 내림차순 정렬 (클라이언트 정렬)
  json.items.sort(function(a, b) {
    return (b.published_at || '').localeCompare(a.published_at || '');
  });

  _allData = json;
  _cacheTs = now;
  return _allData;
}

// ── services.json 로드 (정적 파일) ──────────────
var _svcs     = null;
var _appInfos = null;

async function _loadServices() {
  if (_svcs) return _svcs;
  var res  = await fetch('services.json');
  var data = await res.json();
  _svcs = data.services || [];
  return _svcs;
}

async function _loadAppInfo() {
  if (_appInfos !== null) return _appInfos;
  try {
    var res  = await fetch('app_info.json');
    var data = await res.json();
    _appInfos = Array.isArray(data) ? data : (data.app_info || []);
  } catch (_) {
    _appInfos = [];
  }
  return _appInfos;
}

// ── window.api 구현 ───────────────────────────
window.api = {

  async getStatus() {
    var data = await _loadAll();
    return {
      crawled_today: true,
      today_total:   data.total || 0,
      last_run:      { run_at: data.last_updated }
    };
  },

  async getServices() {
    var svcs = await _loadServices();
    var data = await _loadAll();

    // 서비스별 아이템 수 집계
    var counts = {};
    for (var i = 0; i < data.items.length; i++) {
      var sid = data.items[i].service_id;
      counts[sid] = (counts[sid] || 0) + 1;
    }

    return svcs.map(function(s) {
      return {
        id:       s.id,
        name_ko:  s.name_ko,
        operator: s.operator,
        category: s.category,
        count:    counts[s.id] || 0,
        meta:     s
      };
    });
  },

  async getChanges(svcId) {
    var data = await _loadAll();
    return data.items.filter(function(i) {
      return i.service_id === svcId;
    });
  },

  async getAllChanges(type) {
    var data = await _loadAll();
    if (!type) return data.items;
    return data.items.filter(function(i) {
      return i.change_type === type;
    });
  },

  async getSummary() {
    var data   = await _loadAll();
    var cutoff = new Date(Date.now() - 48 * 60 * 60 * 1000)
                   .toISOString().slice(0, 10);
    return data.items.filter(function(i) {
      var col = (i.collected_at || i.published_at || '').slice(0, 10);
      return col >= cutoff;
    }).slice(0, 50);
  },

  async searchFeats(q) {
    if (!q) return [];
    var data = await _loadAll();
    var ql   = q.toLowerCase();
    var seen = {};
    var results = [];

    for (var i = 0; i < data.items.length; i++) {
      var item = data.items[i];
      var text = ((item.title || '') + ' ' + (item.summary || '')).toLowerCase();
      if (!text.includes(ql)) continue;

      var key = item.url || (item.title + item.service_id);
      if (seen[key]) continue;
      seen[key] = true;

      results.push({
        name_ko:   item.title,
        providers: [item.service_id],
        url:       item.url
      });
      if (results.length >= 30) break;
    }
    return results;
  },

  async getAppStats() {
    return await _loadAppInfo();
  }
};

console.info('[web-api] GitHub Pages 모드 — GAS 백엔드 사용');
