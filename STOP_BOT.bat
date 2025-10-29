@echo off
:: Остановка Telegram бота

echo ========================================
echo   Остановка бота...
echo ========================================
echo.

taskkill /F /IM python.exe >nul 2>&1

if %errorlevel% equ 0 (
    echo [OK] Бот остановлен
) else (
    echo [INFO] Бот не был запущен
)

echo.
echo ========================================
timeout /t 3 >nul

