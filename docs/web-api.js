/**
 * THE PARKING GAZETTE — 인증 + API 레이어
 * Google Identity Services(@socar.kr 전용) + Google Apps Script 백엔드
 */

// ── 설정 ──────────────────────────────────────
var CLIENT_ID = '495055817211-o0m1u8d2aglluhng1kr6fvua95u8emqp.apps.googleusercontent.com';
var GAS_URL   = 'https://script.google.com/macros/s/AKfycbwxXILqQ5DzXSvLRwn4PkmqkWKr9METUfXwago3bXnwIylfnZXusQ9gpNxWc4U5-qW5yw/exec';

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
    if (authUser && payload) { var _e2 = payload.email || ''; authUser.textContent = _e2.split('@')[0] || _e2; }
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

// ── 데이터 정제 ───────────────────────────────
var _PRESS_SUFFIX = /[\s│├└\-–—·]+(?:지디넷코리아|한스경제|디지털투데이|파이낸셜뉴스|서울경제TV|오피니언뉴스|파이낸셜포스트|이데일리|블로터|ChosunBiz|Chosunbiz|뉴스1|뉴시스|연합뉴스|헤럴드경제|매일경제|한국경제|조선비즈|아이뉴스24|아이티조선|전자신문|더페어뉴스|thefairnews|워크투데이|딜팩|네이트|네이버|Naver)\s*$/i;
var _BOX_CHARS   = /[├│└┌┐┘┼┤┬┴─━|▶▷◀◁◆◇●○■□※→←↑↓]/g;
var _NAV_PATTERN = /(?:홈|메뉴|로그인|회원가입|구독|광고문의|사이트맵|개인정보처리방침|이용약관|저작권|COPYRIGHT|All rights reserved)[^\n]*/gi;
var _MULTI_NL    = /\n{3,}/g;

function _cleanText (s) {
  if (!s) return s;
  return s
    .replace(/<[^>]+>/g, '')        // HTML 태그 제거
    .replace(_BOX_CHARS, ' ')       // 박스 그리기 문자 제거
    .replace(_NAV_PATTERN, '')      // 내비·푸터 문구 제거
    .replace(/\s{3,}/g, '  ')       // 3칸 이상 공백 → 2칸
    .replace(_MULTI_NL, '\n\n')     // 3줄 이상 빈줄 → 2줄
    .trim();
}

function _cleanItem (item) {
  var t = _cleanText(item.title || '');
  // 제목 끝 언론사명 제거
  t = t.replace(_PRESS_SUFFIX, '').trim();
  var s = _cleanText(item.summary || '');
  // 요약 첫 문장이 제목과 90% 이상 같으면 제거 (중복 첫줄)
  if (s) {
    var firstLine = s.split('\n')[0].trim();
    var tWords = t.split(/\s+/);
    var fWords = firstLine.split(/\s+/);
    var common = tWords.filter(function(w){ return fWords.indexOf(w) !== -1; }).length;
    var ratio  = common / Math.max(tWords.length, fWords.length, 1);
    if (ratio >= 0.8) {
      s = s.slice(firstLine.length).replace(/^\n+/, '').trim();
    }
  }
  return Object.assign({}, item, { title: t, summary: s });
}

// GAS published_at 파싱 — ISO(YYYY-MM-DD), 한국식(2025. 11. 10.), toString() 포맷 모두 처리
function _dateMs (raw) {
  if (!raw) return 0;
  // 1) ISO prefix YYYY-MM-DD
  var isoM = String(raw).match(/(\d{4})-(\d{2})-(\d{2})/);
  if (isoM) {
    var d = new Date(isoM[1] + '-' + isoM[2] + '-' + isoM[3] + 'T12:00:00+09:00');
    if (!isNaN(d.getTime()) && d.getFullYear() >= 2020) return d.getTime();
  }
  // 2) 한국식 점 구분 "2025. 11. 10."
  var krM = String(raw).match(/(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})/);
  if (krM) {
    var d2 = new Date(parseInt(krM[1]), parseInt(krM[2]) - 1, parseInt(krM[3]), 12);
    if (!isNaN(d2.getTime()) && d2.getFullYear() >= 2020) return d2.getTime();
  }
  // 3) 표준 Date.toString() 계열 파싱
  var d3 = new Date(raw);
  if (!isNaN(d3.getTime()) && d3.getFullYear() >= 2020) return d3.getTime();
  return 0;
}

async function _loadAll () {
  var now = Date.now();
  if (_allData && now - _cacheTs < CACHE_TTL) return _allData;

  // 로그인 확인
  if (!_getStoredJwt()) {
    _showAuthOverlay();
    _initGis();
    throw new Error('로그인이 필요합니다.');
  }

  // 정적 data.json 직접 로드 (GAS 불필요)
  var res  = await fetch('./data.json?t=' + Math.floor(now / 60000));
  if (!res.ok) throw new Error('data.json 로드 실패 (' + res.status + ')');
  var json = await res.json();
  if (!json.ok) throw new Error(json.error || 'data.json 오류');

  // 정제 + 정렬 (A열 published_at 우선, 없으면 J열 collected_at, 최신순)
  json.items = json.items
    .map(_cleanItem)
    .filter(function(c){ return (c.title || '').length > 2; })
    .sort(function (a, b) {
      var dateB = _dateMs(b.published_at) || _dateMs(b.collected_at);
      var dateA = _dateMs(a.published_at) || _dateMs(a.collected_at);
      return dateB - dateA;
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

  async getRecentReviews () {
    var data = await _loadAll();
    var reviews = data.items.filter(function (i) {
      return i.source_type === 'appstore' || i.source_type === 'ios_appstore';
    });
    // A열(published_at) 우선, 공란이면 J열(collected_at), 최신순 내림차순
    reviews.sort(function (a, b) {
      var dateB = _dateMs(b.published_at) || _dateMs(b.collected_at);
      var dateA = _dateMs(a.published_at) || _dateMs(a.collected_at);
      return dateB - dateA;
    });
    return reviews;
  },

  async getTrendingKeywords () {
    var data = await _loadAll();
    var now  = Date.now();
    var d7   = new Date(now - 7  * 86400000).toISOString().slice(0, 10);
    var d14  = new Date(now - 14 * 86400000).toISOString().slice(0, 10);

    var STOP = new Set([
      // 주차 도메인 범용
      '주차','이용','서비스','주차장','고객','주차권','안내','제공','관련','통해','대한',
      '진행','운영','기준','경우','이번','없음','완료','처리','가능','위해','통한',
      '하여','있는','있어','있습','합니다','됩니다','입니다','했습','했다','한다',
      // 추상명사 (단독으로는 의미 없음)
      '역량','전략','방향','목표','계획','추진','강화','개선','확대','도입','발표',
      '시작','종료','확인','사용','출시','시행','참여','구축','활용','지원','협력',
      '성장','혁신','변화','효과','성과','결과','현황','상황','부분','내용','사항',
      '방법','정보','시스템','솔루션','플랫폼','서비스','기술','기능','기준','기반',
      // 시간·수량
      '시간','오전','오후','하루','당일','매일','매주','매월','올해','지난','최근','현재',
      // 형용사·부사
      '너무','정말','매우','아직','바로','계속','특히','다른','여러','가장','조금',
      // 지역 (단독으로는 노이즈)
      '서울','부산','경기','인천','전국','지역',
      // 비주차 노이즈
      '카페','맛집','후기','방문','식당','블로그','사람',
      // 일반 명사
      '모두','전체','일부','이용자','사용자','소비자','기업','업체','회사','시장','업계',
      '사업','투자','규모','분야','관계자','담당자','대표','관련사','파트너',
    ]);

    var _JOSA = /[을를이가은는도으로에서의와과만까지에게부터]/g;
    function stripJosa(w) { var s = w.replace(_JOSA, ''); return s.length >= 2 ? s : w; }
    // 제목에서 의미 토큰 추출 (3자 이상 한글, 2자 이상 영문)
    function tokTitle(t) {
      return ((t||'').match(/[가-힣]{2,}|[A-Za-z]{2,}/g)||[]).map(stripJosa).filter(function(w){
        return w.length >= 2 && !STOP.has(w);
      });
    }

    var thisW = {}, prevW = {};
    data.items.forEach(function (item) {
      if (item.source_type !== 'news') return;
      var date = (item.collected_at||item.published_at||'').slice(0, 10);
      var tokens = tokTitle(item.title || '');

      // 단어 + 인접 2단어 조합(바이그램)으로 문맥 있는 키워드 생성
      var candidates = tokens.slice();
      for (var i = 0; i < tokens.length - 1; i++) {
        candidates.push(tokens[i] + ' ' + tokens[i + 1]);
      }
      candidates.forEach(function(w) {
        if (date >= d7)       thisW[w] = (thisW[w]||0) + 1;
        else if (date >= d14) prevW[w] = (prevW[w]||0) + 1;
      });
    });

    return Object.keys(thisW)
      .filter(function(w) { return thisW[w] >= 2; })
      .map(function(w) {
        var c = thisW[w], p = prevW[w]||0;
        return { word: w, curr: c, prev: p, score: c * (c / (p + 1)) };
      })
      .sort(function(a, b) { return b.score - a.score; })
      .slice(0, 8);
  },

  async getCompetitorActivity () {
    var data    = await _loadAll();
    var cutoff  = new Date(Date.now() -  7 * 86400000).toISOString().slice(0, 10);
    var cutoff2 = new Date(Date.now() - 14 * 86400000).toISOString().slice(0, 10);
    var RSTOP = new Set(['주차','이용','서비스','주차장','고객','주차권','안내','제공','관련','통해',
                         '대한','진행','운영','기준','경우','이번','없음','완료','처리','가능','위해',
                         '통한','하여','있는','있어','합니다','됩니다','모두','전체','일부','방법',
                         '정보','내용','사항','부분','상황','결과','사업','기업','업체','회사','시장']);
    function rtok(t) { return ((t||'').match(/[가-힣]{3,}|[A-Z]{2,}/g)||[]); }
    var tw = {}, pw = {}, topicBag = {};
    data.items.forEach(function (item) {
      if (item.service_id === 'moduparking') return;
      var date = (item.collected_at||item.published_at||'').slice(0,10);
      if (date >= cutoff) {
        tw[item.service_id] = (tw[item.service_id]||0) + 1;
        if (!topicBag[item.service_id]) topicBag[item.service_id] = {};
        rtok(item.title||'').forEach(function(w) {
          if (RSTOP.has(w)) return;
          topicBag[item.service_id][w] = (topicBag[item.service_id][w]||0) + 1;
        });
      } else if (date >= cutoff2) {
        pw[item.service_id] = (pw[item.service_id]||0) + 1;
      }
    });
    return Object.keys(tw)
      .map(function (sid) {
        var c = tw[sid], p = pw[sid]||0;
        var bag = topicBag[sid]||{};
        var topic = Object.keys(bag)
          .sort(function(a,b){ return bag[b]-bag[a]; })
          .slice(0, 2).join('·');
        return { service_id: sid, count: c, prev: p, delta: c - p, topic: topic };
      })
      .sort(function (a, b) { return b.count - a.count; })
      .slice(0, 6);
  },

  async getUpcomingEvents () {
    var KR_HOLIDAYS = [
      {date:'2026-05-25', name:'부처님오신날', note:'연등행렬·법회'},
      {date:'2026-06-03', name:'지방선거', note:'투표·교통 혼잡'},
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
      '한강','강릉','전주','춘천','경기','인천공항','김포','속초','경주',
      '상암','송도','성수','을지로','명동','동대문','신촌','이태원'
    ];
    function extractLoc (text) {
      for (var i = 0; i < REGIONS.length; i++) {
        if (text.includes(REGIONS[i])) return REGIONS[i];
      }
      return null;
    }

    /* 제목 키워드로 이벤트 유형 자동 분류 */
    function classifyEvent (title) {
      var t = title || '';
      if (/마라톤|달리기 대회|런 대회|하프마라톤/.test(t)) return 'marathon';
      if (/팝업|팝-업|pop.?up/i.test(t))                   return 'popup';
      if (/콘서트|공연|뮤지컬|페스티벌|페스타|쇼케이스/.test(t)) return 'concert';
      if (/전시|박람회|아트페어|갤러리|아트 페어/.test(t))  return 'exhibit';
      if (/축제|불꽃|불꽃놀이|플리마켓|마켓|카니발/.test(t)) return 'festival';
      return 'event';
    }

    /* 5일 전 ~ 21일 후 창 (진행 중 이벤트 포함) */
    var _now = new Date();
    var fromStr  = new Date(_now.getTime() - 5 * 86400000).toISOString().slice(0, 10);
    var toStr    = new Date(_now.getTime() + 21 * 86400000).toISOString().slice(0, 10);
    var cutoff14 = new Date(_now.getTime() - 14 * 86400000).toISOString().slice(0, 10);

    /* 공휴일 (5일 전 ~ 21일 후) */
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
        if (date < cutoff14) return;

        var key = (item.title||'').slice(0, 15);
        if (!topicMap[key]) topicMap[key] = { count: 0, item: item };
        topicMap[key].count++;
      });

      /* Phase 2: 기사 수 내림차순 → 이벤트 유형 자동 분류 후 추가 */
      Object.keys(topicMap).forEach(function (k) {
        var entry  = topicMap[k];
        var item   = entry.item;
        var text   = (item.title||'') + ' ' + (item.summary||'');
        var loc    = extractLoc(text);
        var name   = (item.title||'').replace(/<[^>]+>/g, '').trim();
        var etype  = classifyEvent(name);
        events.push({
          date:     (item.published_at||item.collected_at||'').slice(0,10),
          name:     name,
          location: loc,
          type:     etype,
          url:      item.url || ('https://search.naver.com/search.naver?where=news&query=' + encodeURIComponent(name)),
          count:    entry.count,
        });
      });
    } catch (_) {}

    /* 공휴일 날짜순 → 나머지 기사수 내림차순 */
    events.sort(function (a, b) {
      if (a.type === 'holiday' && b.type !== 'holiday') return -1;
      if (b.type === 'holiday' && a.type !== 'holiday') return  1;
      if (a.type === 'holiday') return (a.date||'').localeCompare(b.date||'');
      return (b.count||0) - (a.count||0);
    });
    return events.slice(0, 10);
  }
};

console.info('[web-api] GitHub Pages + GIS 인증 모드');
