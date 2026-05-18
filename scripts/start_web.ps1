# THE PARKING GAZETTE — 웹 서버 실행 스크립트
# 사용법: .\scripts\start_web.ps1

$ErrorActionPreference = "Continue"
$ROOT    = Split-Path -Parent $PSScriptRoot
$VENV_PY = Join-Path $ROOT ".venv\Scripts\python.exe"
$SERVER  = Join-Path $ROOT "backend\server.py"

if (-not (Test-Path $VENV_PY)) {
    Write-Host ""
    Write-Host "  [오류] .venv가 없습니다. 먼저 아래 명령을 실행하세요:" -ForegroundColor Red
    Write-Host ""
    Write-Host "    python -m venv .venv" -ForegroundColor Yellow
    Write-Host "    .venv\Scripts\pip install -r backend\requirements.txt" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# 패키지 설치 확인 (requirements.txt 기준)
Write-Host "  패키지 확인 중..." -ForegroundColor Cyan
& $VENV_PY -m pip install -r (Join-Path $ROOT "backend\requirements.txt") --quiet 2>&1 | Out-Null

# .env 파일 자동 로드
$ENV_FILE = Join-Path $ROOT ".env"
if (Test-Path $ENV_FILE) {
    Get-Content $ENV_FILE | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
    Write-Host "  .env 로드 완료 (네이버 API 키 포함)" -ForegroundColor Cyan
}

Write-Host "  웹 서버 시작 중..." -ForegroundColor Green
& $VENV_PY $SERVER
