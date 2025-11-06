#!/bin/bash
# Быстрое обновление бота - выполнить на VPS сервере

cd /opt/moysklad-bot 2>/dev/null || cd "$(dirname "$0")"

# Установка git если нужно
if ! command -v git &> /dev/null; then
    echo "Устанавливаю git..."
    sudo apt-get update -qq && sudo apt-get install git -y -qq
fi

# Обновление кода
echo "Обновляю код..."
git pull origin main

# Установка зависимостей
echo "Устанавливаю зависимости..."
pip3 install -r requirements.txt --quiet 2>/dev/null || python3 -m pip install -r requirements.txt --quiet

# Перезапуск
echo "Перезапускаю бота..."
sudo systemctl restart moysklad-bot 2>/dev/null || sudo systemctl restart telegram-bot 2>/dev/null || echo "Перезапустите бота вручную"

echo "Готово! Версия: 5.8.0"

