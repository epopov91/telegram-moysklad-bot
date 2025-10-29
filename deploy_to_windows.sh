#!/bin/bash
# Скрипт для автоматического развертывания бота на Windows через SSH
# Использование: ./deploy_to_windows.sh [IP] [USERNAME]

# Цвета для вывода
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Развертывание Telegram бота на Windows...${NC}"

# Проверка параметров
if [ -z "$1" ] || [ -z "$2" ]; then
    echo -e "${RED}❌ Использование: $0 <IP адрес Windows> <Имя пользователя>${NC}"
    echo "Пример: $0 192.168.1.100 User"
    exit 1
fi

WINDOWS_IP=$1
WINDOWS_USER=$2
REPO_URL="https://github.com/epopov91/telegram-moysklad-bot.git"
PROJECT_DIR="telegram-moysklad-bot"

echo -e "${BLUE}Подключение к Windows ($WINDOWS_IP)...${NC}"

# Проверка доступности SSH
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes ${WINDOWS_USER}@${WINDOWS_IP} exit 2>/dev/null; then
    echo -e "${RED}❌ Не удалось подключиться к Windows. Проверьте SSH.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ SSH подключение успешно${NC}"

# Функция для выполнения команд на Windows
run_on_windows() {
    ssh ${WINDOWS_USER}@${WINDOWS_IP} "$1"
}

# Проверка Python
echo -e "${BLUE}Проверка Python...${NC}"
if ! run_on_windows "python --version" 2>/dev/null; then
    echo -e "${RED}❌ Python не установлен на Windows!${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python установлен${NC}"

# Проверка Git
echo -e "${BLUE}Проверка Git...${NC}"
if ! run_on_windows "git --version" 2>/dev/null; then
    echo -e "${RED}❌ Git не установлен на Windows!${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Git установлен${NC}"

# Клонирование или обновление репозитория
echo -e "${BLUE}Синхронизация кода...${NC}"
if run_on_windows "test -d ${PROJECT_DIR}" 2>/dev/null; then
    echo "Репозиторий существует, обновление..."
    run_on_windows "cd ${PROJECT_DIR} && git pull"
else
    echo "Клонирование репозитория..."
    run_on_windows "git clone ${REPO_URL}"
fi
echo -e "${GREEN}✅ Код синхронизирован${NC}"

# Создание .env файла
echo -e "${BLUE}Настройка переменных окружения...${NC}"
run_on_windows "cd ${PROJECT_DIR} && echo TELEGRAM_BOT_TOKEN=8212058302:AAEohwQCCs4cHpC0iKhGnzXRySxkNRv9fD0 > .env"
run_on_windows "cd ${PROJECT_DIR} && echo MOYSKLAD_API_TOKEN=e3d32366294b1b786b2e96989fd57bdedcf4e2a5 >> .env"
echo -e "${GREEN}✅ .env файл создан${NC}"

# Установка зависимостей
echo -e "${BLUE}Установка зависимостей...${NC}"
run_on_windows "cd ${PROJECT_DIR} && python -m pip install -r requirements.txt -q"
echo -e "${GREEN}✅ Зависимости установлены${NC}"

# Остановка старого процесса (если запущен)
echo -e "${BLUE}Остановка старого процесса бота (если запущен)...${NC}"
run_on_windows "taskkill /F /IM python.exe /FI \"WINDOWTITLE eq tg_ms_uploader*\" 2>nul" 2>/dev/null || true
sleep 2

# Создание bat-файла для запуска
echo -e "${BLUE}Создание скрипта запуска...${NC}"
run_on_windows "cd ${PROJECT_DIR} && echo @echo off > start_bot.bat"
run_on_windows "cd ${PROJECT_DIR} && echo cd /d \"%~dp0\" >> start_bot.bat"
run_on_windows "cd ${PROJECT_DIR} && echo python tg_ms_uploader.py >> start_bot.bat"
echo -e "${GREEN}✅ Скрипт запуска создан${NC}"

# Запуск бота
echo -e "${BLUE}Запуск бота...${NC}"
run_on_windows "cd ${PROJECT_DIR} && start /min cmd /c start_bot.bat"
sleep 3

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Бот успешно развернут на Windows!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Проверьте Telegram бота - он должен отвечать на /start"
echo ""
echo "Полезные команды:"
echo "  Просмотр логов:  ssh ${WINDOWS_USER}@${WINDOWS_IP} 'cd ${PROJECT_DIR} && type bot.log'"
echo "  Остановка бота:  ssh ${WINDOWS_USER}@${WINDOWS_IP} 'taskkill /F /IM python.exe'"
echo "  Статус бота:     ssh ${WINDOWS_USER}@${WINDOWS_IP} 'tasklist | findstr python'"

