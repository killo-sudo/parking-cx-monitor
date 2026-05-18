/**
 * 웹 모드 API 호환 레이어
 * Electron 환경이 아닐 때(브라우저 직접 접속) fetch / EventSource로 대체.
 * Electron에서는 preload.js가 먼저 window.api를 설정하므로 이 블록은 실행되지 않음.
 */
if (typeof window.api === 'undefined') {
  window.api = {

    getStatus:    ()   => fetch('/api/status').then(r => r.json()),
    getServices:  ()   => fetch('/api/services').then(r => r.json()),
    getChanges:   (id) => fetch(`/api/changes/${encodeURIComponent(id)}`).then(r => r.json()),
    getAllChanges: (ct) => fetch(
      `/api/all_changes${ct ? '?type=' + encodeURIComponent(ct) : ''}`
    ).then(r => r.json()),
    getSummary:   ()   => fetch('/api/summary').then(r => r.json()),
    searchFeats:  (q)  => fetch(`/api/search?q=${encodeURIComponent(q)}`).then(r => r.json()),
    getAppStats:  ()   => fetch('/api/app_stats').then(r => r.json()),

    runCrawl () {
      return new Promise((resolve, reject) => {
        const es = new EventSource('/api/crawl')

        es.onmessage = e => {
          let msg
          try { msg = JSON.parse(e.data) } catch { msg = e.data }

          if (typeof msg === 'string' && msg.startsWith('__DONE__')) {
            es.close()
            const code = parseInt(msg.split(':')[1] || '0', 10)
            if (code === 0) resolve({ success: true })
            else reject(new Error('크롤러 오류 (exit ' + code + ')'))
          } else if (window._crawlLogCb) {
            window._crawlLogCb((typeof msg === 'string' ? msg : JSON.stringify(msg)) + '\n')
          }
        }

        es.onerror = () => {
          es.close()
          reject(new Error('서버 연결 오류'))
        }
      })
    },

    onCrawlLog:  cb => { window._crawlLogCb = cb },
    offCrawlLog: ()  => { window._crawlLogCb = null },
  }

  console.info('[web-api] 웹 모드로 실행 중 (Flask 서버 연결)')
}
