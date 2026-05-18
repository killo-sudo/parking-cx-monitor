/**
 * Preload 스크립트 — contextBridge로 렌더러에 안전한 API 노출.
 */

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('api', {
  // ── DB 조회 ──────────────────────────────────
  getStatus:      ()       => ipcRenderer.invoke('db:status'),
  getChanges:     (svcId)  => ipcRenderer.invoke('db:changes', svcId),
  getAllChanges:   (ct)     => ipcRenderer.invoke('db:all_changes', ct || null),
  getSummary:     ()       => ipcRenderer.invoke('db:summary'),
  searchFeats:    (query)  => ipcRenderer.invoke('db:search', query),
  getServices:    ()       => ipcRenderer.invoke('db:services'),
  getAppStats:    ()       => ipcRenderer.invoke('db:app_stats'),

  // ── 크롤러 ───────────────────────────────────
  runCrawl:     ()       => ipcRenderer.invoke('crawl:run'),

  // ── 크롤러 진행 로그 수신 ─────────────────────
  onCrawlLog:   (cb)     => ipcRenderer.on('crawl:log', (_, msg) => cb(msg)),
  offCrawlLog:  ()       => ipcRenderer.removeAllListeners('crawl:log'),
})
