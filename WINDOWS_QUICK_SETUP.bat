@echo off
chcp 65001 >nul
title Автоматическая установка Telegram бота

echo ==========================================
echo   Автоустановка Telegram бота v2.0
echo ==========================================
echo.

:: Проверка Git
echo [1/7] Проверка Git...
git --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git не установлен!
    echo.
    echo Скачайте и установите Git:
    echo https://git-scm.com/download/win
    echo.
    echo После установки запустите этот скрипт заново.
    pause
    exit /b 1
)
echo [OK] Git установлен
echo.

:: Проверка Python
echo [2/7] Проверка Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python не установлен!
    echo.
    echo Скачайте и установите Python:
    echo https://www.python.org/downloads/
    echo.
    echo ВАЖНО: При установке поставьте галочку "Add Python to PATH"!
    echo.
    echo После установки запустите этот скрипт заново.
    pause
    exit /b 1
)
echo [OK] Python установлен
echo.

:: Переход в Documents
echo [3/7] Переход в папку Documents...
cd /d "%USERPROFILE%\Documents"
echo [OK] Текущая папка: %CD%
echo.

:: Клонирование репозитория
echo [4/7] Клонирование кода бота...
if exist telegram-moysklad-bot (
    echo [INFO] Папка уже существует, обновление...
    cd telegram-moysklad-bot
    git pull
) else (
    git clone https://github.com/epopov91/telegram-moysklad-bot.git
    cd telegram-moysklad-bot
)
echo [OK] Код получен
echo.

:: Создание .env файла
echo [5/7] Создание конфигурационного файла...
(
echo TELEGRAM_BOT_TOKEN=8212058302:AAEohwQCCs4cHpC0iKhGnzXRySxkNRv9fD0
echo MOYSKLAD_API_TOKEN=e3d32366294b1b786b2e96989fd57bdedcf4e2a5
echo ADMIN_USER_ID=347723389
) > .env
echo [OK] Файл .env создан
echo.

:: Установка зависимостей
echo [6/7] Установка библиотек Python...
pip install -r requirements.txt --quiet
echo [OK] Все библиотеки установлены
echo.

:: Запуск бота
echo [7/7] Запуск бота...
echo.
echo ==========================================
echo   Бот запускается!
echo ==========================================
echo.
echo Откройте Telegram и напишите боту:
echo   /admin
echo   /status
echo.
echo Для остановки бота нажмите Ctrl+C
echo ==========================================
echo.

python tg_ms_uploader.py

pause

