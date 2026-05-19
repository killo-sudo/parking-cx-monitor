/**
 * THE PARKING GAZETTE — Google Apps Script API
 * @socar.kr 계정만 데이터 접근 가능
 *
 * 배포 방법:
 *   1. script.google.com → 새 프로젝트 → 이 코드 붙여넣기
 *   2. 배포 → 새 배포 → 유형: 웹 앱
 *      실행 계정: 나 / 액세스 권한: 모든 사용자(익명 포함)
 *   3. 배포 URL → docs/web-api.js 의 GAS_URL 에 붙여넣기
 */

var SPREADSHEET_ID  = '1m9I0_l0ue_eCZQ9sWcpw7TLTlPcnlp21SpNneAvYOJs';
var SHEET_NAME      = '수집데이터';
var ALLOWED_DOMAIN  = 'socar.kr';

var COL = {
  published_at: 0, service_id: 1, name_ko: 2, source_type: 3,
  change_type: 4, title: 5, summary: 6, url: 7, sentiment: 8, collected_at: 9,
  full_text: 10
};

// ── 토큰 검증 ─────────────────────────────────
function _verifyToken (token) {
  if (!token) return null;
  try {
    var res  = UrlFetchApp.fetch(
      'https://oauth2.googleapis.com/tokeninfo?id_token=' + encodeURIComponent(token),
      { muteHttpExceptions: true }
    );
    if (res.getResponseCode() !== 200) return null;
    var info = JSON.parse(res.getContentText());
    var email = info.email || '';
    if (!email.endsWith('@' + ALLOWED_DOMAIN)) return null;
    return email;
  } catch (_) { return null; }
}

// ── 메인 핸들러 ───────────────────────────────
function doGet (e) {
  var token = (e.parameter && e.parameter.token) || '';
  var email = _verifyToken(token);

  if (!email) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, auth: false, error: '@socar.kr 계정으로 로그인하세요.' }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  try {
    var ss   = SpreadsheetApp.openById(SPREADSHEET_ID);
    var ws   = ss.getSheetByName(SHEET_NAME);
    var rows = ws.getDataRange().getValues();

    var items = [];
    for (var i = 1; i < rows.length; i++) {
      var r   = rows[i];
      var url = String(r[COL.url] || '').trim();
      if (!url) continue;
      items.push({
        published_at: String(r[COL.published_at] || ''),
        service_id:   String(r[COL.service_id]   || ''),
        name_ko:      String(r[COL.name_ko]       || ''),
        source_type:  String(r[COL.source_type]   || ''),
        change_type:  String(r[COL.change_type]   || ''),
        title:        String(r[COL.title]         || ''),
        summary:      String(r[COL.summary]       || ''),
        url:          url,
        sentiment:    String(r[COL.sentiment]     || 'neutral'),
        collected_at: String(r[COL.collected_at]  || ''),
        full_text:    String(r[COL.full_text]     || '')
      });
    }

    return ContentService
      .createTextOutput(JSON.stringify({
        ok: true, auth: true,
        items: items, total: items.length,
        last_updated: new Date().toISOString(),
        viewer: email
      }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, auth: true, error: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
