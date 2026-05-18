#!/usr/bin/env pwsh
# GitHub Secrets 일괄 등록 스크립트
# 터미널에서 실행: pwsh scripts/setup_secrets.ps1

$repo = "killo-sudo/parking-cx-monitor"
$projectRoot = Split-Path $PSScriptRoot -Parent

Write-Host "=== GitHub Secrets 등록 ===" -ForegroundColor Cyan

# 1. GOOGLE_CREDENTIALS
$credPath = Join-Path $projectRoot "google_credentials.json"
if (Test-Path $credPath) {
    Get-Content $credPath -Raw | gh secret set GOOGLE_CREDENTIALS --repo $repo
    Write-Host "[OK] GOOGLE_CREDENTIALS" -ForegroundColor Green
} else {
    Write-Host "[SKIP] google_credentials.json 파일 없음" -ForegroundColor Yellow
}

# 2. NAVER_CLIENT_ID
gh secret set NAVER_CLIENT_ID --body "xqUsgonSnfCfVh6f3oCa" --repo $repo
Write-Host "[OK] NAVER_CLIENT_ID" -ForegroundColor Green

# 3. NAVER_CLIENT_SECRET
gh secret set NAVER_CLIENT_SECRET --body "OMOCfXeaos" --repo $repo
Write-Host "[OK] NAVER_CLIENT_SECRET" -ForegroundColor Green

# 4. SPREADSHEET_ID
gh secret set SPREADSHEET_ID --body "1OOBLCnnQRD5jKm-1CQLqjEI9ZhpL4u4XDVFFdwtjZJA" --repo $repo
Write-Host "[OK] SPREADSHEET_ID" -ForegroundColor Green

# 5. SLACK_WEBHOOK_URL — 별도 입력 필요
Write-Host ""
Write-Host "SLACK_WEBHOOK_URL 는 나중에 따로 설정 필요:" -ForegroundColor Yellow
Write-Host "  gh secret set SLACK_WEBHOOK_URL --body `"https://hooks.slack.com/services/...`" --repo $repo"

Write-Host ""
Write-Host "=== 등록 완료 ===" -ForegroundColor Cyan
Write-Host "확인: gh secret list --repo $repo"
