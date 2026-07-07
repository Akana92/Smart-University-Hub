@echo off
REM Smart University — двойной клик по этому файлу поднимает БД + сервер.
REM (обёртка над start.ps1; -ExecutionPolicy Bypass, чтобы не упереться в политику запуска)
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
echo.
echo ==== сервер остановлен ====  нажми любую клавишу, чтобы закрыть окно
pause >nul
