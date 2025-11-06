#!/bin/bash
# Скрипт для настройки локального Telegram Bot API сервера
# Позволяет работать с файлами до 2 ГБ

set -e

echo "🚀 Настройка локального Telegram Bot API сервера..."

# Создаем директорию
mkdir -p /opt/telegram-bot-api
cd /opt/telegram-bot-api

# Проверяем Docker
if ! command -v docker &> /dev/null; then
    echo "📦 Устанавливаю Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    systemctl start docker
    systemctl enable docker
fi

# Создаем docker-compose.yml
cat > docker-compose.yml << 'EOF'
services:
  telegram-bot-api:
    image: aiogram/telegram-bot-api:latest
    container_name: telegram-bot-api
    restart: unless-stopped
    ports:
      - '8081:8081'
    command: --local --http-port=8081 --dir=/var/lib/telegram-bot-api
    volumes:
      - ./data:/var/lib/telegram-bot-api
EOF

# Запускаем сервер
echo "🐳 Запускаю Bot API сервер..."
docker compose pull
docker compose up -d

# Ждем запуска
sleep 5

# Проверяем статус
if docker ps | grep -q telegram-bot-api; then
    echo "✅ Bot API сервер запущен на http://localhost:8081"
    echo ""
    echo "📝 Добавьте в .env файл бота:"
    echo "BOT_API_SERVER=http://localhost:8081"
    echo ""
    echo "🔄 Перезапустите бота: systemctl restart moysklad-bot"
else
    echo "❌ Ошибка запуска Bot API сервера"
    docker compose logs
    exit 1
fi

