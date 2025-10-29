import logging
import requests
import io
import mimetypes
import base64
import os
import sys
import subprocess
import sqlite3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import telebot
from telebot import types

# Загрузка переменных окружения из .env файла
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
MOYSKLAD_API_TOKEN = os.getenv('MOYSKLAD_API_TOKEN')
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID')  # ID администратора для управления ботом

# Проверка наличия токенов
if not TELEGRAM_BOT_TOKEN or not MOYSKLAD_API_TOKEN:
    print("ОШИБКА: Необходимо указать TELEGRAM_BOT_TOKEN и MOYSKLAD_API_TOKEN в .env файле")
    sys.exit(1)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Версия бота
BOT_VERSION = "3.2.1"
BOT_START_TIME = datetime.now()

# Настройки
BACKUP_PHOTOS = False  # Опция сохранения фото на диск

# Инициализация бота
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Состояния пользователей
user_states = {}
user_data = {}

# Константы состояний
STATE_MENU = 0
STATE_GET_CODE = 1
STATE_GET_PHOTOS = 2

# =========================
# БАЗА ДАННЫХ
# =========================

def init_database():
    """Инициализация базы данных для хранения истории загрузок"""
    conn = sqlite3.connect('uploads_history.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            variant_code TEXT NOT NULL,
            variant_name TEXT,
            filename TEXT NOT NULL,
            success INTEGER NOT NULL
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

def save_upload_to_db(user_id, username, variant_code, variant_name, filename, success):
    """Сохранение записи о загрузке в БД"""
    try:
        conn = sqlite3.connect('uploads_history.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO uploads (timestamp, user_id, username, variant_code, variant_name, filename, success)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (datetime.now().isoformat(), user_id, username, variant_code, variant_name, filename, int(success)))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка при сохранении в БД: {e}")

def get_upload_stats():
    """Получение статистики загрузок"""
    try:
        conn = sqlite3.connect('uploads_history.db')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM uploads WHERE success = 1')
        total = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(DISTINCT variant_code) FROM uploads WHERE success = 1')
        unique = cursor.fetchone()[0]
        conn.close()
        return total, unique
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        return 0, 0

# =========================
# СОХРАНЕНИЕ ФОТО
# =========================

def save_photo_backup(variant_code, filename, photo_bytes):
    """Сохранение фото в локальную папку"""
    if not BACKUP_PHOTOS:
        return
    
    try:
        date_str = datetime.now().strftime('%Y-%m-%d')
        backup_dir = Path('uploaded_photos') / date_str / variant_code
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = backup_dir / filename
        with open(filepath, 'wb') as f:
            f.write(photo_bytes)
        logger.info(f"Фото сохранено: {filepath}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении фото: {e}")

# =========================
# MOYSKLAD API
# =========================

def get_variant_by_code(code: str):
    """Поиск модификации по коду"""
    url = f"https://api.moysklad.ru/api/remap/1.2/entity/variant?filter=code={code}"
    headers = {
        'Authorization': f'Bearer {MOYSKLAD_API_TOKEN}',
        'Accept-Encoding': 'gzip'
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if data.get('rows'):
            return data['rows'][0]
        return None
    except Exception as e:
        logger.error(f"Ошибка при поиске модификации {code}: {e}")
        return None

def get_variant_images(variant_id: str):
    """Получение списка фото модификации"""
    url = f"https://api.moysklad.ru/api/remap/1.2/entity/variant/{variant_id}/images"
    headers = {
        'Authorization': f'Bearer {MOYSKLAD_API_TOKEN}',
        'Accept-Encoding': 'gzip'
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        return data.get('rows', [])
    except Exception as e:
        logger.error(f"Ошибка при получении фото модификации {variant_id}: {e}")
        return []

def upload_photo_to_variant(variant_id: str, photo_bytes: bytes, filename: str, variant_code: str):
    """Загрузка фото к модификации"""
    url = f"https://api.moysklad.ru/api/remap/1.2/entity/variant/{variant_id}/images"
    headers = {
        'Authorization': f'Bearer {MOYSKLAD_API_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    try:
        # Сохраняем бэкап если включено
        save_photo_backup(variant_code, filename, photo_bytes)
        
        # Кодируем фото в base64
        photo_base64 = base64.b64encode(photo_bytes).decode('utf-8')
        
        # Определяем тип файла
        mime_type, _ = mimetypes.guess_type(filename)
        if not mime_type or not mime_type.startswith('image/'):
            mime_type = 'image/jpeg'
        
        payload = {
            'filename': filename,
            'content': photo_base64
        }
        
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        logger.info(f"Фото {filename} успешно загружено для модификации {variant_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при загрузке фото: {e}")
        return False

# =========================
# ПРОВЕРКА АДМИНА
# =========================

def is_admin(user_id):
    """Проверка, является ли пользователь администратором"""
    if not ADMIN_USER_ID:
        return False
    try:
        return str(user_id) == str(ADMIN_USER_ID)
    except:
        return False

# =========================
# ОСНОВНЫЕ КОМАНДЫ
# =========================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    """Команда /start"""
    user_id = message.from_user.id
    user_states[user_id] = STATE_GET_CODE
    user_data[user_id] = {}
    
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton('❌ Отмена'))
    
    bot.send_message(
        message.chat.id,
        "👋 Привет! Я бот для загрузки фото в МойСклад.\n\n"
        "📝 Отправьте код модификации товара:",
        reply_markup=keyboard
    )
    logger.info(f"Пользователь {message.from_user.username} ({user_id}) начал работу")

@bot.message_handler(commands=['cancel'])
def cmd_cancel(message):
    """Команда /cancel"""
    user_id = message.from_user.id
    user_states[user_id] = STATE_MENU
    user_data[user_id] = {}
    
    keyboard = types.ReplyKeyboardRemove()
    bot.send_message(
        message.chat.id,
        "❌ Операция отменена. Отправьте /start для начала работы.",
        reply_markup=keyboard
    )

# =========================
# КОМАНДЫ УПРАВЛЕНИЯ
# =========================

@bot.message_handler(commands=['help', 'admin'])
def cmd_help(message):
    """Список команд"""
    help_text = """
🔧 **Команды бота**

**Мониторинг:**
/status - Статус бота и статистика
/logs - Последние логи (для диагностики)

**Управление:**
/backup_on - Включить сохранение фото на диск
/backup_off - Выключить сохранение фото
/restart - Перезапустить бота
/update - Обновить бота из GitHub
/stop - Остановить бота

**Основное:**
/start - Начать загрузку фото
/cancel - Отменить текущую операцию
"""
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['status'])
def cmd_status(message):
    """Статус бота"""
    uptime = datetime.now() - BOT_START_TIME
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds % 3600) // 60
    
    total_uploads, unique_products = get_upload_stats()
    
    backup_status = "✅ Включено" if BACKUP_PHOTOS else "❌ Выключено"
    
    status_text = f"""
📊 **Статус бота**

🤖 Версия: {BOT_VERSION}
⏱ Работает: {uptime.days}д {hours}ч {minutes}м

📸 Загружено фото: {total_uploads}
🏷 Уникальных товаров: {unique_products}
💾 Сохранение фото: {backup_status}
"""
    bot.send_message(message.chat.id, status_text, parse_mode='Markdown')

@bot.message_handler(commands=['logs'])
def cmd_logs(message):
    """Последние логи"""
    try:
        with open('bot.log', 'r', encoding='utf-8') as f:
            lines = f.readlines()
            last_lines = ''.join(lines[-50:])
            
        if len(last_lines) > 4000:
            last_lines = last_lines[-4000:]
        
        bot.send_message(message.chat.id, f"```\n{last_lines}\n```", parse_mode='Markdown')
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка при чтении логов: {e}")

@bot.message_handler(commands=['backup_on'])
def cmd_backup_on(message):
    """Включить сохранение фото"""
    global BACKUP_PHOTOS
    BACKUP_PHOTOS = True
    bot.send_message(message.chat.id, "✅ Сохранение фото включено")
    logger.info("Сохранение фото включено")

@bot.message_handler(commands=['backup_off'])
def cmd_backup_off(message):
    """Выключить сохранение фото"""
    global BACKUP_PHOTOS
    BACKUP_PHOTOS = False
    bot.send_message(message.chat.id, "✅ Сохранение фото выключено")
    logger.info("Сохранение фото выключено")

@bot.message_handler(commands=['update'])
def cmd_update(message):
    """Обновление бота из Git"""
    try:
        bot.send_message(message.chat.id, "🔄 Обновление кода из GitHub...")
        result = subprocess.run(['git', 'pull'], capture_output=True, text=True)
        
        if result.returncode == 0:
            bot.send_message(message.chat.id, f"✅ Обновлено!\n```\n{result.stdout}\n```\n🔄 Перезапуск...", parse_mode='Markdown')
            logger.info("Обновление кода и перезапуск бота")
            
            # Перезапуск
            os.execv(sys.executable, ['python'] + sys.argv)
        else:
            bot.send_message(message.chat.id, f"❌ Ошибка:\n```\n{result.stderr}\n```", parse_mode='Markdown')
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['restart'])
def cmd_restart(message):
    """Перезапуск бота"""
    bot.send_message(message.chat.id, "🔄 Перезапуск бота...")
    logger.info(f"Перезапуск бота по команде {message.from_user.username}")
    os.execv(sys.executable, ['python'] + sys.argv)

@bot.message_handler(commands=['stop'])
def cmd_stop(message):
    """Остановка бота"""
    bot.send_message(message.chat.id, "🛑 Остановка бота...")
    logger.info(f"Остановка бота по команде {message.from_user.username}")
    bot.stop_polling()
    sys.exit(0)

# =========================
# ОБРАБОТКА СОСТОЯНИЙ
# =========================

@bot.message_handler(func=lambda message: message.text == '❌ Отмена')
def handle_cancel_button(message):
    """Обработка кнопки Отмена"""
    cmd_cancel(message)

@bot.message_handler(content_types=['text'])
def handle_text(message):
    """Обработка текстовых сообщений"""
    user_id = message.from_user.id
    state = user_states.get(user_id, STATE_MENU)
    
    if state == STATE_GET_CODE:
        handle_code_input(message)
    elif state == STATE_MENU:
        bot.send_message(message.chat.id, "Используйте /start для начала работы")

@bot.message_handler(content_types=['photo', 'document'])
def handle_photo(message):
    """Обработка фото"""
    user_id = message.from_user.id
    state = user_states.get(user_id, STATE_MENU)
    
    if state == STATE_GET_PHOTOS:
        process_photo(message)
    else:
        bot.send_message(message.chat.id, "Сначала отправьте код модификации. Используйте /start")

def handle_code_input(message):
    """Обработка ввода кода модификации"""
    user_id = message.from_user.id
    code = message.text.strip()
    
    bot.send_message(message.chat.id, f"🔍 Ищу модификацию с кодом: {code}...")
    
    try:
        variant = get_variant_by_code(code)
        
        if not variant:
            bot.send_message(message.chat.id, f"❌ Модификация с кодом '{code}' не найдена. Попробуйте другой код или /cancel")
            return
        
        variant_name = variant.get('name', 'Без названия')
        variant_id = variant['id']
        
        # Получаем текущие фото (с обработкой ошибок)
        try:
            existing_images = get_variant_images(variant_id)
            images_count = len(existing_images)
        except Exception as e:
            logger.error(f"Ошибка при получении фото: {e}")
            images_count = 0  # Если не удалось получить - считаем что 0
        
        # Сохраняем данные
        user_data[user_id] = {
            'variant_id': variant_id,
            'variant_code': code,
            'variant_name': variant_name,
            'existing_images_count': images_count
        }
        user_states[user_id] = STATE_GET_PHOTOS
        
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.row(types.KeyboardButton('✅ Завершить'), types.KeyboardButton('❌ Отмена'))
        
        # Формируем сообщение с информацией о фото
        if images_count > 0:
            photos_emoji = "📸" * min(images_count, 5)  # Максимум 5 эмодзи
            photos_info = f"📷 **Текущих фото:** {images_count} {photos_emoji}\n\n"
        else:
            photos_info = "📷 **Текущих фото:** нет\n\n"
        
        bot.send_message(
            message.chat.id,
            f"✅ **Найдено:** {variant_name}\n"
            f"{photos_info}"
            f"➕ **Отправьте фото** (можно несколько).\n"
            f"Когда закончите - нажмите '✅ Завершить'",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        
        logger.info(f"Пользователь {message.from_user.username} нашел товар: {variant_name} (код: {code}, фото: {images_count})")
        
    except Exception as e:
        logger.error(f"Ошибка при обработке кода {code}: {e}")
        bot.send_message(message.chat.id, f"❌ Произошла ошибка при поиске товара. Попробуйте еще раз или обратитесь к администратору.")

def process_photo(message):
    """Обработка загруженного фото"""
    user_id = message.from_user.id
    data = user_data.get(user_id, {})
    
    if not data:
        bot.send_message(message.chat.id, "❌ Данные потеряны. Начните заново с /start")
        return
    
    variant_id = data['variant_id']
    variant_code = data['variant_code']
    variant_name = data['variant_name']
    
    try:
        # Получаем файл
        if message.content_type == 'photo':
            file_id = message.photo[-1].file_id
            file_info = bot.get_file(file_id)
            filename = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        else:  # document
            file_id = message.document.file_id
            file_info = bot.get_file(file_id)
            filename = message.document.file_name
        
        # Скачиваем файл
        photo_bytes = bot.download_file(file_info.file_path)
        
        # Загружаем в МойСклад
        bot.send_message(message.chat.id, f"⏳ Загружаю '{filename}'...")
        
        success = upload_photo_to_variant(variant_id, photo_bytes, filename, variant_code)
        
        if success:
            bot.send_message(message.chat.id, f"✅ Фото '{filename}' успешно загружено!")
            save_upload_to_db(user_id, message.from_user.username, variant_code, variant_name, filename, True)
        else:
            bot.send_message(message.chat.id, f"❌ Ошибка при загрузке '{filename}'")
            save_upload_to_db(user_id, message.from_user.username, variant_code, variant_name, filename, False)
    
    except Exception as e:
        logger.error(f"Ошибка при обработке фото: {e}")
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

@bot.message_handler(func=lambda message: message.text == '✅ Завершить')
def handle_finish_button(message):
    """Обработка кнопки Завершить"""
    user_id = message.from_user.id
    user_states[user_id] = STATE_MENU
    
    keyboard = types.ReplyKeyboardRemove()
    bot.send_message(
        message.chat.id,
        "✅ Загрузка завершена!\n\nОтправьте /start для новой загрузки.",
        reply_markup=keyboard
    )

# =========================
# ЗАПУСК БОТА
# =========================

def main():
    init_database()
    logger.info(f"🚀 Запуск бота версии {BOT_VERSION}")
    logger.info("✅ Бот запущен и готов к работе!")
    
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}")

if __name__ == '__main__':
    main()
