/**
 * THE PARKING GAZETTE — Google Apps Script API
 * Google Sheets 데이터를 JSON으로 반환하는 무료 백엔드
 *
 * 배포 방법:
 *   1. script.google.com → 새 프로젝트 → 이 코드 붙여넣기
 *   2. 배포 → 새 배포 → 유형: 웹 앱
 *      실행 계정: 나 / 액세스 권한: 모든 사용자(익명 포함)
 *   3. 배포 URL을 복사해서 docs/web-api.js 의 GAS_URL 에 붙여넣기
 */

var SPREADSHEET_ID = '1OOBLCnnQRD5jKm-1CQLqjEI9ZhpL4u4XDVFFdwtjZJA';
var SHEET_NAME     = '수집데이터';

// 열 매핑 (HEADERS와 동일 순서)
var COL = {
  published_at: 0,
  service_id:   1,
  name_ko:      2,
  source_type:  3,
  change_type:  4,
  title:        5,
  summary:      6,
  url:          7,
  sentiment:    8,
  collected_at: 9
};

function doGet(e) {
  try {
    var ss   = SpreadsheetApp.openById(SPREADSHEET_ID);
    var ws   = ss.getSheetByName(SHEET_NAME);
    var rows = ws.getDataRange().getValues();

    var items = [];
    for (var i = 1; i < rows.length; i++) {
      var r = rows[i];
      var url = String(r[COL.url] || '').trim();
      if (!url) continue;  // URL 없는 빈 행 스킵
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
        collected_at: String(r[COL.collected_at]  || '')
      });
    }

    var payload = JSON.stringify({
      ok:           true,
      items:        items,
      total:        items.length,
      last_updated: new Date().toISOString()
    });

    return ContentService
      .createTextOutput(payload)
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
