# local_cron.ps1 - Daily crawl from local PC
# Bypasses GHA IP blocking by running google-play-scraper from home IP.
#
# Prereqs:
#   1) .env file with NAVER_CLIENT_ID / NAVER_CLIENT_SECRET / SPREADSHEET_ID
#   2) google_credentials.json in project root
#   3) APIFY_TOKEN optional (add to .env)
#   4) python + backend/requirements.txt installed
#
# Manual test:
#   powershell -ExecutionPolicy Bypass -File scripts\local_cron.ps1
#
# Register Task Scheduler (run daily at 10:00):
#   schtasks /Create /TN "parking-cx-monitor-daily" /SC DAILY /ST 10:00 `
#     /TR "powershell.exe -ExecutionPolicy Bypass -NoProfile -File C:\Users\jh199\projects\parking-cx-monitor\scripts\local_cron.ps1"

$ErrorActionPreference = "Continue"
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

$LogDir = Join-Path $ProjectDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir "local_cron_$(Get-Date -Format 'yyyy-MM-dd').log"

function Log($msg) {
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

Log "=== local_cron start ==="

# 1) Load .env
if (Test-Path "$ProjectDir\.env") {
    Get-Content "$ProjectDir\.env" | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line -match '^([^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim().Trim('"').Trim("'")
            [System.Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }
    Log ".env loaded"
} else {
    Log "[WARN] .env not found"
}

# 2) google_credentials.json -> GOOGLE_CREDENTIALS env var
$credsPath = Join-Path $ProjectDir "google_credentials.json"
if (Test-Path $credsPath) {
    $env:GOOGLE_CREDENTIALS = Get-Content $credsPath -Raw
    Log "GOOGLE_CREDENTIALS env set"
} else {
    Log "[ERROR] google_credentials.json missing"
}

# 3) git pull (latest code/data)
try {
    Log "git pull..."
    $pullOut = & git pull --rebase --autostash origin main 2>&1 | Out-String
    Log $pullOut
} catch {
    Log "[ERROR git pull] $_"
}

# 4) Run crawler
try {
    Log "Running python backend\daily_crawl.py..."
    $crawlOut = & python backend\daily_crawl.py 2>&1 | Out-String
    $crawlExitCode = $LASTEXITCODE
    Log $crawlOut
    Log "Crawler exit code: $crawlExitCode"
} catch {
    Log "[ERROR crawler] $_"
}

# 5) Commit + push changes
try {
    Log "Checking for changes..."
    & git add -f docs/data.json docs/app_info.json
    & git add -f docs/gazette_latest.html docs/gazette_meta.json
    & git add -f "docs/gazette_*.html"

    $diffStat = & git diff --cached --stat | Out-String
    if ($diffStat) {
        Log "Changes detected:"
        Log $diffStat
        $commitOut = & git commit -m "chore: local cron data update [skip ci]" 2>&1 | Out-String
        Log $commitOut
        $pullOut2 = & git pull --rebase --autostash origin main 2>&1 | Out-String
        Log $pullOut2
        $pushOut = & git push origin main 2>&1 | Out-String
        Log $pushOut
        Log "Push complete"
    } else {
        Log "No changes - 0 new items"
    }
} catch {
    Log "[ERROR commit/push] $_"
}

Log "=== local_cron end ==="
