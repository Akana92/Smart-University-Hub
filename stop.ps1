# Smart University — остановить базу документов (данные в volume pgdata целы).
#   ./stop.ps1            # docker compose stop (быстрый повторный старт)
#   ./stop.ps1 -Down      # docker compose down (удалить контейнер; volume pgdata остаётся)
param([switch]$Down)
$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

if ($Down) {
    Write-Host "-> docker compose down (контейнер удаляется, данные в volume pgdata сохраняются)" -ForegroundColor Cyan
    docker compose down 2>&1 | Out-Null
} else {
    Write-Host "-> docker compose stop (контейнер сохраняется - быстрый старт в следующий раз)" -ForegroundColor Cyan
    docker compose stop 2>&1 | Out-Null
}
if ($LASTEXITCODE -eq 0) { Write-Host "OK  База остановлена." -ForegroundColor Green }
else { Write-Host "!!  Не удалось остановить (код $LASTEXITCODE). Docker запущен?" -ForegroundColor Yellow }
