# Smart University — запуск одной командой: поднять БД (pgvector) + API.
#   ./start.ps1              # БД + сервер на http://localhost:8000
#   ./start.ps1 -DbOnly      # только база (без сервера)
#   ./start.ps1 -Port 8080   # другой порт
#   ./start.ps1 -Open        # ещё и открыть браузер
# Требуется запущенный Docker Desktop. Данные документов лежат в volume pgdata (не теряются).
param(
    [switch]$DbOnly,
    [switch]$Open,
    [int]$Port = 8000
)
# Continue (не Stop): docker пишет в stderr предупреждения (seccomp и пр.); под Stop PowerShell 5.1
# превратил бы их в фатальную ошибку. Реальные сбои ловим явно по $LASTEXITCODE.
$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

function Step($m){ Write-Host "-> $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "OK  $m" -ForegroundColor Green }
function Warn($m){ Write-Host "!!  $m" -ForegroundColor Yellow }

# 1) Docker запущен?
Step "Проверяю Docker..."
docker info 1>$null 2>$null
if ($LASTEXITCODE -ne 0) {
    Warn "Docker не запущен. Открой Docker Desktop, дождись зелёного статуса и запусти скрипт снова."
    exit 1
}
Ok "Docker работает"

# 2) Поднять базу документов
Step "Поднимаю базу документов (pgvector) на :55432..."
docker compose up -d 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Warn "Не удалось поднять контейнер БД (docker compose up -d)."; exit 1 }

# 3) Дождаться healthcheck
Step "Жду готовности БД..."
$deadline = (Get-Date).AddSeconds(60)
do {
    Start-Sleep -Seconds 2
    $status = (docker inspect --format '{{.State.Health.Status}}' smartuni-pg 2>$null)
} while ($status -ne "healthy" -and (Get-Date) -lt $deadline)
if ($status -ne "healthy") {
    Warn "БД не стала healthy за 60с (статус: '$status'). Логи: docker compose logs postgres"
    exit 1
}
Ok "БД готова (healthy)"

# 4) Есть ли проиндексированные документы?
$cnt = (docker exec smartuni-pg psql -U postgres -d smartuni -tAc "SELECT count(*) FROM chunks" 2>$null)
if ($LASTEXITCODE -ne 0 -or $cnt -notmatch '^\s*\d+\s*$') {
    Warn "Таблица чанков пуста или отсутствует - нужна индексация (см. Быстрый старт в README)."
} else {
    Ok "Документов в базе: $($cnt.Trim()) чанк(ов)"
}

if ($DbOnly) { Ok "Готово: база поднята. Сервер не запускаю (-DbOnly)."; exit 0 }

# 5) Запустить API (foreground; Ctrl+C — остановить сервер, база останется работать)
Write-Host ""
Ok "Приложение:  http://localhost:$Port"
Ok "Админка:     http://localhost:$Port/admin"
Write-Host "   Ctrl+C - остановить сервер (база продолжит работать; остановить БД - ./stop.ps1)" -ForegroundColor DarkGray
Write-Host ""
if ($Open) { Start-Process "http://localhost:$Port" }
python -m uvicorn api.main:app --port $Port
