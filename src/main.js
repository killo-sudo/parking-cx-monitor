/**
 * Electron 메인 프로세스
 * - BrowserWindow 생성
 * - Python 크롤러/DB 쿼리를 child_process로 실행
 * - IPC 핸들러 등록
 * - 패키지 배포 모드: PyInstaller .exe 사용
 */

const { app, BrowserWindow, ipcMain, shell } = require('electron')
const { spawn, execSync }                     = require('child_process')
const path                                    = require('path')
const fs                                      = require('fs')

// ──────────────────────────────────────────────
// 경로 상수 — 개발/패키지 모드 자동 분기
// ──────────────────────────────────────────────

const IS_PACKAGED  = app.isPackaged
const ROOT_DIR     = IS_PACKAGED ? process.resourcesPath : path.join(__dirname, '..')
const BACKEND_DIR  = path.join(ROOT_DIR, IS_PACKAGED ? '' : '', 'backend')
const DATA_DIR     = path.join(ROOT_DIR, 'data')
const RENDERER     = path.join(__dirname, 'renderer', 'index.html')

// ──────────────────────────────────────────────
// 실행기 탐지 — 개발: Python / 배포: .exe
// ──────────────────────────────────────────────

function findRunner (scriptName) {
  if (IS_PACKAGED) {
    // 배포 모드: PyInstaller로 컴파일된 .exe 사용
    const exeName = scriptName.replace('.py', '.exe')
    const exePath = path.join(BACKEND_DIR, exeName)
    if (fs.existsSync(exePath)) return { type: 'exe', path: exePath }
    // fallback: 같은 폴더의 Python 스크립트
  }

  // 개발 모드: venv Python 사용
  const venvPy = path.join(IS_PACKAGED ? process.resourcesPath : ROOT_DIR,
                            '.venv', 'Scripts', 'python.exe')
  if (fs.existsSync(venvPy)) return { type: 'python', interpreter: venvPy }

  // 시스템 Python fallback
  for (const cmd of ['python', 'python3', 'py']) {
    try {
      const v = execSync(`${cmd} --version`, { encoding: 'utf-8', stdio: 'pipe' })
      if (v.includes('Python 3')) return { type: 'python', interpreter: cmd }
    } catch (_) {}
  }
  return { type: 'python', interpreter: 'python' }
}

function buildSpawnArgs (scriptName, extraArgs = []) {
  const runner     = findRunner(scriptName)
  const scriptPath = path.join(BACKEND_DIR, scriptName)

  if (runner.type === 'exe') {
    return { cmd: runner.path, args: extraArgs }
  }
  return { cmd: runner.interpreter, args: [scriptPath, ...extraArgs] }
}

// ──────────────────────────────────────────────
// 창 생성
// ──────────────────────────────────────────────

let mainWindow = null

function createWindow () {
  mainWindow = new BrowserWindow({
    width:     1400,
    height:    900,
    minWidth:  1000,
    minHeight: 650,
    title:     '주차 서비스 CX 모니터',
    backgroundColor: '#F4EFE3',
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
    },
  })

  mainWindow.loadFile(RENDERER)

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })
}

app.whenReady().then(createWindow)
app.on('window-all-closed', () => app.quit())

// ──────────────────────────────────────────────
// Python/exe 실행 헬퍼
// ──────────────────────────────────────────────

function runBackendJson (scriptName, extraArgs = []) {
  return new Promise((resolve, reject) => {
    const { cmd, args } = buildSpawnArgs(scriptName, extraArgs)
    const proc = spawn(cmd, args, {
      cwd: ROOT_DIR,
      env: { ...process.env, PYTHONUTF8: '1' },
    })

    let stdout = ''
    let stderr = ''

    proc.stdout.on('data', d => { stdout += d })
    proc.stderr.on('data', d => { stderr += d })

    proc.on('close', code => {
      if (code !== 0) {
        reject(new Error(`백엔드 오류 (${scriptName}): ${stderr.slice(0, 400)}`))
        return
      }
      // stdout의 마지막 JSON 행만 파싱 (logging 출력이 섞일 수 있음)
      const lines = stdout.trim().split('\n').filter(l => l.startsWith('{') || l.startsWith('['))
      const lastJson = lines[lines.length - 1] || stdout.trim()
      try {
        resolve(JSON.parse(lastJson))
      } catch (e) {
        reject(new Error(`JSON 파싱 실패: ${lastJson.slice(0, 200)}`))
      }
    })

    proc.on('error', err => reject(new Error(`프로세스 실행 실패: ${err.message}`)))
  })
}

// ──────────────────────────────────────────────
// IPC 핸들러
// ──────────────────────────────────────────────

ipcMain.handle('db:status',      ()           => runBackendJson('db.py', ['status']))
ipcMain.handle('db:changes',     (_, svcId)  => runBackendJson('db.py', ['changes', svcId]))
ipcMain.handle('db:all_changes', (_, changeType) => {
  const args = ['all_changes']
  if (changeType) args.push(changeType)
  return runBackendJson('db.py', args)
})
ipcMain.handle('db:summary',     ()          => runBackendJson('db.py', ['summary']))
ipcMain.handle('db:search',      (_, query)  => runBackendJson('db.py', ['search', query]))
ipcMain.handle('db:services',    ()          => runBackendJson('db.py', ['services']))
ipcMain.handle('db:app_stats',   ()          => runBackendJson('db.py', ['app_stats']))

// 크롤러 실행 (진행 메시지 실시간 스트리밍)
ipcMain.handle('crawl:run', () => {
  return new Promise((resolve, reject) => {
    const { cmd, args } = buildSpawnArgs('daily_crawl.py')
    const proc = spawn(cmd, args, {
      cwd: ROOT_DIR,
      env: { ...process.env, PYTHONUTF8: '1' },
    })

    let stderr = ''

    proc.stdout.on('data', d => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('crawl:log', d.toString())
      }
    })
    proc.stderr.on('data', d => { stderr += d })

    proc.on('close', code => {
      if (code === 0) resolve({ success: true })
      else reject(new Error(stderr.slice(0, 400)))
    })

    proc.on('error', err => reject(new Error(`크롤러 실행 실패: ${err.message}`)))
  })
})
