@echo off
chcp 65001 >nul
title Автообновление бота

echo ==========================================
echo   Автообновление Telegram бота
echo ==========================================
echo.

:: Остановка бота
echo [1/3] Остановка бота...
taskkill /F /IM python.exe >nul 2>&1
if errorlevel 1 (
    echo [INFO] Бот не был запущен
) else (
    echo [OK] Бот остановлен
)
timeout /t 2 >nul
echo.

:: Переход в папку проекта
cd /d "%~dp0"

:: Обновление кода
echo [2/3] Обновление кода из GitHub...
git pull
if errorlevel 1 (
    echo [ERROR] Не удалось обновить код
    echo Проверьте подключение к интернету
    pause
    exit /b 1
)
echo [OK] Код обновлен
echo.

:: Запуск бота
echo [3/3] Запуск бота...
echo.
echo ==========================================
echo   Бот запускается!
echo ==========================================
echo.

start "Telegram Bot" cmd /k python tg_ms_uploader.py

echo.
echo [OK] Бот запущен в отдельном окне!
echo.
echo Можете закрыть это окно.
timeout /t 3
exit

