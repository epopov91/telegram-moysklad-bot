#!/bin/bash
# Скрипт для обновления бота на VPS сервере

set -e  # Остановка при ошибке

echo "=========================================="
echo "  Обновление Telegram бота"
echo "=========================================="
echo ""

# Определяем директорию скрипта
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "📁 Рабочая директория: $SCRIPT_DIR"
echo ""

# Проверяем наличие git
if ! command -v git &> /dev/null; then
    echo "❌ Git не установлен!"
    echo ""
    echo "Устанавливаю git..."
    sudo apt-get update
    sudo apt-get install git -y
    echo "✅ Git установлен"
    echo ""
fi

# Проверяем, что это git репозиторий
if [ ! -d ".git" ]; then
    echo "❌ Это не git репозиторий!"
    echo "Убедитесь, что вы находитесь в правильной директории."
    exit 1
fi

echo "🔄 Получаю обновления из GitHub..."
git fetch origin

# Проверяем есть ли обновления
if git diff --quiet HEAD origin/main; then
    echo "✅ Бот уже использует последнюю версию"
    exit 0
fi

echo "📥 Найдены обновления! Загружаю..."
git pull origin main

echo ""
echo "📦 Устанавливаю зависимости..."
pip3 install -r requirements.txt --quiet

echo ""
echo "🔄 Перезапускаю бота..."

# Пытаемся перезапустить через systemd
if systemctl is-active --quiet telegram-bot 2>/dev/null; then
    echo "Перезапуск через systemd..."
    sudo systemctl restart telegram-bot
    echo "✅ Бот перезапущен через systemd"
elif systemctl is-active --quiet telegram-moysklad-bot 2>/dev/null; then
    echo "Перезапуск через systemd (telegram-moysklad-bot)..."
    sudo systemctl restart telegram-moysklad-bot
    echo "✅ Бот перезапущен через systemd"
else
    echo "⚠️  Systemd сервис не найден"
    echo "Перезапустите бота вручную:"
    echo "  sudo systemctl restart telegram-bot"
    echo "или"
    echo "  python3 tg_ms_uploader.py"
fi

echo ""
echo "=========================================="
echo "✅ Обновление завершено!"
echo "=========================================="
echo ""
echo "Версия бота должна быть 5.8.0"
echo "Отправьте /start в Telegram для обновления меню"

