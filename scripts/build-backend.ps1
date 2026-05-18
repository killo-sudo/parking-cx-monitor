# Python 백엔드를 PyInstaller로 단일 .exe 파일로 컴파일
# 실행 전: .venv가 세팅돼 있어야 함
#
# 사용법:
#   cd C:\Users\jh199\projects\parking-cx-monitor
#   .\scripts\build-backend.ps1

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $PSScriptRoot
$VENV_PY = Join-Path $ROOT ".venv\Scripts\python.exe"
$BACKEND = Join-Path $ROOT "backend"
$DIST_DIR = Join-Path $ROOT "backend-dist"
$DATA_DIR = Join-Path $ROOT "data"

Write-Host "=== PyInstaller 백엔드 빌드 ===" -ForegroundColor Cyan

# PyInstaller 설치 확인
$pipCheck = & $VENV_PY -m pip show pyinstaller 2>$null
if (-not $pipCheck) {
    Write-Host "PyInstaller 설치 중..." -ForegroundColor Yellow
    & $VENV_PY -m pip install pyinstaller --quiet
}

# 출력 폴더 초기화
if (Test-Path $DIST_DIR) { Remove-Item $DIST_DIR -Recurse -Force }
$null = New-Item -ItemType Directory -Path $DIST_DIR -Force

# 공통 PyInstaller 옵션
$COMMON_OPTS = @(
    "--onefile",
    "--clean",
    "--noconfirm",
    "--distpath", $DIST_DIR,
    "--workpath", (Join-Path $ROOT "build-pyinstaller"),
    "--specpath", (Join-Path $ROOT "build-pyinstaller"),
    # data/ 폴더 번들 (sources.yaml, services.json 등)
    "--add-data", "${DATA_DIR};data",
    # backend/ 내 모듈들 번들
    "--add-data", "${BACKEND};backend"
)

# db.py 컴파일
Write-Host "`n[1/2] db.py 컴파일 중..." -ForegroundColor Green
& $VENV_PY -m PyInstaller @COMMON_OPTS --name db (Join-Path $BACKEND "db.py")
if ($LASTEXITCODE -ne 0) { Write-Error "db.py 컴파일 실패"; exit 1 }

# daily_crawl.py 컴파일
Write-Host "`n[2/2] daily_crawl.py 컴파일 중..." -ForegroundColor Green
& $VENV_PY -m PyInstaller @COMMON_OPTS --name daily_crawl (Join-Path $BACKEND "daily_crawl.py")
if ($LASTEXITCODE -ne 0) { Write-Error "daily_crawl.py 컴파일 실패"; exit 1 }

# 임시 빌드 폴더 정리
$BUILD_TEMP = Join-Path $ROOT "build-pyinstaller"
if (Test-Path $BUILD_TEMP) { Remove-Item $BUILD_TEMP -Recurse -Force }

Write-Host "`n=== 컴파일 완료 ===" -ForegroundColor Cyan
Write-Host "생성된 파일:" -ForegroundColor Green
Get-ChildItem $DIST_DIR | ForEach-Object {
    $size = [math]::Round($_.Length / 1MB, 1)
    Write-Host "  $($_.Name)  ($size MB)"
}
Write-Host "`n다음 단계: npm run build:installer" -ForegroundColor Yellow
