@echo off
chcp 65001 >nul
title Telegram Bot для МойСклад

echo ==========================================
echo   Telegram Bot для МойСклад
echo ==========================================
echo.

cd /d "%~dp0"

echo [INFO] Проверка зависимостей...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python не установлен!
    echo Скачайте с https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python установлен
echo.

echo [INFO] Запуск бота...
echo.
python tg_ms_uploader.py

echo.
echo ==========================================
echo   Бот остановлен
echo ==========================================
pause

