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
BOT_VERSION = "4.2.2"
BOT_START_TIME = datetime.now()

# Настройки
BACKUP_PHOTOS = False  # Опция сохранения фото на диск

# Инициализация бота
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Состояния пользователей
user_states = {}
user_data = {}
user_processing = {}  # Флаг обработки запроса

# Константы состояний
STATE_MAIN_MENU = 0
STATE_GET_CODE = 1
STATE_GET_PHOTOS = 2
STATE_STATISTICS = 3
STATE_MANAGEMENT = 4

# Константы кнопок
BTN_UPLOAD = "📸 Загрузить фото"
BTN_STATS = "📊 Статистика"
BTN_MANAGE = "⚙️ Управление"
BTN_HELP = "ℹ️ Помощь"
BTN_BACK = "🔙 Главное меню"
BTN_CANCEL = "❌ Отмена"
BTN_SEND_PHOTO = "📸 Отправить фото"
BTN_ANOTHER_CODE = "🔄 Другой код"
BTN_MORE_PHOTOS = "➕ Еще фото"
BTN_FINISH = "✅ Завершить"
BTN_ANOTHER_PRODUCT = "🔄 Другой товар"

# =========================
# КЛАВИАТУРЫ
# =========================

def get_main_menu_keyboard():
    """Главное меню"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(BTN_UPLOAD, BTN_STATS)
    keyboard.row(BTN_MANAGE, BTN_HELP)
    return keyboard

def get_code_input_keyboard():
    """Клавиатура для ввода кода"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(BTN_BACK, BTN_CANCEL)
    return keyboard

def get_product_info_keyboard():
    """Клавиатура после нахождения товара"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(BTN_SEND_PHOTO)
    keyboard.row(BTN_ANOTHER_CODE, BTN_BACK)
    return keyboard

def get_photo_upload_keyboard():
    """Клавиатура во время загрузки фото"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(BTN_FINISH)
    keyboard.row(BTN_ANOTHER_PRODUCT, BTN_BACK)
    return keyboard

def get_management_keyboard():
    """Клавиатура управления"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row("🔄 Перезапуск", "🔧 Исправить")
    keyboard.row("📋 Логи", "⚠️ Ошибки")
    keyboard.row(BTN_BACK)
    return keyboard

def get_history_keyboard(user_id):
    """Клавиатура с историей последних кодов"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    
    # Получаем историю из user_data
    history = user_data.get(user_id, {}).get('history', [])
    
    # Добавляем кнопки с историей (максимум 5)
    for code in history[-5:]:
        keyboard.row(f"🔖 {code}")
    
    keyboard.row(BTN_BACK, BTN_CANCEL)
    return keyboard

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
    """Поиск модификации по коду с повторными попытками"""
    url = f"https://api.moysklad.ru/api/remap/1.2/entity/variant?filter=code={code}"
    headers = {
        'Authorization': f'Bearer {MOYSKLAD_API_TOKEN}',
        'Accept-Encoding': 'gzip'
    }
    
    # Пробуем 3 раза с паузой
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('rows'):
                return data['rows'][0]
            return None
            
        except requests.exceptions.Timeout:
            logger.warning(f"Таймаут при поиске {code}, попытка {attempt + 1}/3")
            if attempt < 2:
                import time
                time.sleep(1)
                continue
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Ошибка подключения при поиске {code}, попытка {attempt + 1}/3: {e}")
            if attempt < 2:
                import time
                time.sleep(2)
                continue
        except Exception as e:
            logger.error(f"Ошибка при поиске модификации {code}: {e}")
            break
    
    return None

def get_variant_images(variant_id: str):
    """Получение списка фото модификации с повторными попытками"""
    url = f"https://api.moysklad.ru/api/remap/1.2/entity/variant/{variant_id}/images"
    headers = {
        'Authorization': f'Bearer {MOYSKLAD_API_TOKEN}',
        'Accept-Encoding': 'gzip'
    }
    
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            return data.get('rows', [])
            
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning(f"Ошибка при получении фото, попытка {attempt + 1}/3: {e}")
            if attempt < 2:
                import time
                time.sleep(1)
                continue
        except Exception as e:
            logger.error(f"Ошибка при получении фото модификации {variant_id}: {e}")
            break
    
        return []

def upload_photo_to_variant(variant_id: str, photo_bytes: bytes, filename: str, variant_code: str):
    """Загрузка фото к модификации с повторными попытками"""
    url = f"https://api.moysklad.ru/api/remap/1.2/entity/variant/{variant_id}/images"
    headers = {
        'Authorization': f'Bearer {MOYSKLAD_API_TOKEN}',
        'Content-Type': 'application/json'
    }
    
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
    
    # Пробуем 3 раза
    for attempt in range(3):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            logger.info(f"Фото {filename} успешно загружено для модификации {variant_id}")
            return True
            
        except requests.exceptions.Timeout:
            logger.warning(f"Таймаут загрузки фото, попытка {attempt + 1}/3")
            if attempt < 2:
                import time
                time.sleep(2)
                continue
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Ошибка подключения при загрузке фото, попытка {attempt + 1}/3: {e}")
            if attempt < 2:
                import time
                time.sleep(3)
                continue
        except Exception as e:
            logger.error(f"Ошибка при загрузке фото: {e}")
            break
    
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
    """Команда /start - показывает главное меню"""
    user_id = message.from_user.id
    user_states[user_id] = STATE_MAIN_MENU
    
    # Инициализируем данные пользователя если нет
    if user_id not in user_data:
        user_data[user_id] = {'history': []}
    
    bot.send_message(
        message.chat.id,
        "👋 **Привет!** Я бот для загрузки фото в МойСклад.\n\n"
        "Выберите действие:",
        reply_markup=get_main_menu_keyboard(),
        parse_mode='Markdown'
    )
    logger.info(f"Пользователь {message.from_user.username} ({user_id}) открыл главное меню")

def show_main_menu(message):
    """Показать главное меню"""
    user_id = message.from_user.id
    user_states[user_id] = STATE_MAIN_MENU
    
    # Снимаем флаг обработки если был
    user_processing[user_id] = False
    
    bot.send_message(
        message.chat.id,
        "🏠 **Главное меню**\n\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(),
        parse_mode='Markdown'
    )

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
/logs - Последние 50 строк логов
/errors - Только ошибки из логов

**Быстрое управление:**
/fix - Автоматическое исправление и перезапуск
/shell <команда> - Выполнить команду на сервере

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
        
        bot.send_message(message.chat.id, f"📋 **Последние 50 строк:**\n```\n{last_lines}\n```", parse_mode='Markdown')
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка при чтении логов: {e}")

@bot.message_handler(commands=['errors'])
def cmd_errors(message):
    """Показать только ошибки из логов"""
    try:
        with open('bot.log', 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        # Фильтруем только строки с ERROR и WARNING
        error_lines = [line for line in lines if 'ERROR' in line or 'WARNING' in line]
        
        if not error_lines:
            bot.send_message(message.chat.id, "✅ Ошибок не найдено!")
            return
        
        last_errors = ''.join(error_lines[-30:])  # Последние 30 ошибок
        
        if len(last_errors) > 4000:
            last_errors = last_errors[-4000:]
        
        bot.send_message(message.chat.id, f"⚠️ **Ошибки и предупреждения:**\n```\n{last_errors}\n```", parse_mode='Markdown')
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
            
            # Перезапуск (правильная команда для Windows и Unix)
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            bot.send_message(message.chat.id, f"❌ Ошибка:\n```\n{result.stderr}\n```", parse_mode='Markdown')
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['restart'])
def cmd_restart(message):
    """Перезапуск бота"""
    bot.send_message(message.chat.id, "🔄 Перезапуск бота...")
    logger.info(f"Перезапуск бота по команде {message.from_user.username}")
    os.execv(sys.executable, [sys.executable] + sys.argv)

@bot.message_handler(commands=['stop'])
def cmd_stop(message):
    """Остановка бота"""
    bot.send_message(message.chat.id, "🛑 Остановка бота...")
    logger.info(f"Остановка бота по команде {message.from_user.username}")
    bot.stop_polling()
    sys.exit(0)

@bot.message_handler(commands=['fix'])
def cmd_fix(message):
    """Автоматическое исправление проблем и перезапуск"""
    try:
        bot.send_message(message.chat.id, "🔧 **Автоматическое исправление...**\n\n1️⃣ Обновление кода из GitHub...")
        
        # Шаг 1: Git pull
        result = subprocess.run(['git', 'pull'], capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
        
        if result.returncode != 0:
            bot.send_message(message.chat.id, f"❌ Ошибка при обновлении:\n```\n{result.stderr}\n```", parse_mode='Markdown')
            return
        
        bot.send_message(message.chat.id, f"✅ Код обновлен:\n```\n{result.stdout}\n```\n\n2️⃣ Проверка зависимостей...", parse_mode='Markdown')
        
        # Шаг 2: Установка зависимостей
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', '--quiet'], 
                              capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
        
        if result.returncode == 0:
            bot.send_message(message.chat.id, "✅ Зависимости проверены\n\n3️⃣ Перезапуск бота...")
        else:
            bot.send_message(message.chat.id, f"⚠️ Предупреждение при установке:\n```\n{result.stderr}\n```\n\n3️⃣ Перезапуск бота...", parse_mode='Markdown')
        
        logger.info(f"Автоматическое исправление и перезапуск по команде {message.from_user.username}")
        
        # Шаг 3: Перезапуск (правильная команда для Windows и Unix)
        os.execv(sys.executable, [sys.executable] + sys.argv)
        
    except Exception as e:
        logger.error(f"Ошибка при выполнении /fix: {e}")
        bot.send_message(message.chat.id, f"❌ Критическая ошибка: {e}\n\nПопробуйте /restart")

@bot.message_handler(commands=['shell'])
def cmd_shell(message):
    """Выполнение shell команд"""
    try:
        # Получаем команду после /shell
        command = message.text.replace('/shell', '').strip()
        
        if not command:
            bot.send_message(message.chat.id, "❌ Использование: `/shell <команда>`\n\nПример: `/shell dir`", parse_mode='Markdown')
            return
        
        bot.send_message(message.chat.id, f"⚙️ Выполняю: `{command}`", parse_mode='Markdown')
        
        # Выполняем команду
        result = subprocess.run(command, shell=True, capture_output=True, text=True, 
                              cwd=os.path.dirname(os.path.abspath(__file__)), timeout=30)
        
        output = result.stdout if result.stdout else result.stderr
        
        if not output:
            output = "(команда выполнена без вывода)"
        
        # Ограничиваем вывод
        if len(output) > 4000:
            output = output[-4000:]
        
        status = "✅" if result.returncode == 0 else "⚠️"
        bot.send_message(message.chat.id, f"{status} **Результат:**\n```\n{output}\n```", parse_mode='Markdown')
        
        logger.info(f"Команда shell от {message.from_user.username}: {command}")
        
    except subprocess.TimeoutExpired:
        bot.send_message(message.chat.id, "❌ Команда выполнялась слишком долго (timeout 30 сек)")
    except Exception as e:
        logger.error(f"Ошибка при выполнении shell команды: {e}")
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

# =========================
# ОБРАБОТКА СОСТОЯНИЙ
# =========================

@bot.message_handler(content_types=['text'])
def handle_text(message):
    """Обработка текстовых сообщений и кнопок"""
    user_id = message.from_user.id
    text = message.text
    state = user_states.get(user_id, STATE_MAIN_MENU)
    
    # Обработка универсальных кнопок (работают всегда)
    if text == BTN_BACK or text == BTN_CANCEL or text == "❌ Отмена":
        show_main_menu(message)
        return
    
    if text == BTN_FINISH or text == "✅ Завершить":
        finish_upload(message)
        return
    
    if text == BTN_ANOTHER_PRODUCT or text == BTN_ANOTHER_CODE or text == "🔄 Другой товар" or text == "🔄 Другой код":
        start_upload_flow(message)
        return
    
    # Обработка кнопок главного меню
    if state == STATE_MAIN_MENU:
        if text == BTN_UPLOAD:
            start_upload_flow(message)
        elif text == BTN_STATS:
            show_statistics(message)
        elif text == BTN_MANAGE:
            show_management(message)
        elif text == BTN_HELP:
            cmd_help(message)
        else:
            # Любой другой текст - показываем подсказку
            bot.send_message(
                message.chat.id, 
                "Используйте кнопки меню для навигации 👇",
                reply_markup=get_main_menu_keyboard()
            )
        return
    
    # Ввод кода модификации
    if state == STATE_GET_CODE:
        # Проверяем, не кнопка ли это из истории
        if text.startswith("🔖 "):
            code = text.replace("🔖 ", "").strip()
            handle_code_input_text(message, code)
        else:
            # Обычный ввод кода
            handle_code_input_text(message, text)
        return
    
    # Загрузка фото - НЕ ПРИНИМАЕМ ТЕКСТ, только фото или кнопки
    if state == STATE_GET_PHOTOS:
        bot.send_message(
            message.chat.id, 
            "📸 Отправьте ФОТО товара\n\nИли используйте кнопки ниже:",
            reply_markup=get_photo_upload_keyboard()
        )
        return
    
    # Управление
    if state == STATE_MANAGEMENT:
        if text == "🔄 Перезапуск":
            cmd_restart(message)
        elif text == "🔧 Исправить":
            cmd_fix(message)
        elif text == "📋 Логи":
            cmd_logs(message)
        elif text == "⚠️ Ошибки":
            cmd_errors(message)
    else:
            bot.send_message(
                message.chat.id,
                "Используйте кнопки управления:",
                reply_markup=get_management_keyboard()
            )
        return
    
    # Если состояние неизвестно - показываем главное меню
    show_main_menu(message)

def start_upload_flow(message):
    """Начать процесс загрузки фото"""
    user_id = message.from_user.id
    user_states[user_id] = STATE_GET_CODE
    
    # Проверяем историю
    history = user_data.get(user_id, {}).get('history', [])
    
    if history:
        keyboard = get_history_keyboard(user_id)
        bot.send_message(
            message.chat.id,
            "📝 **Введите код модификации** или выберите из истории:\n\n"
            "Можно ввести код вручную или нажать на один из недавних:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    else:
        keyboard = get_code_input_keyboard()
        bot.send_message(
            message.chat.id,
            "📝 **Введите код модификации товара:**",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )

def show_statistics(message):
    """Показать статистику"""
    total_uploads, unique_products = get_upload_stats()
    
    bot.send_message(
        message.chat.id,
        f"📊 **Статистика загрузок**\n\n"
        f"📸 Всего фото загружено: {total_uploads}\n"
        f"🏷 Уникальных товаров: {unique_products}",
        reply_markup=get_main_menu_keyboard(),
        parse_mode='Markdown'
    )

def show_management(message):
    """Показать меню управления"""
    user_id = message.from_user.id
    user_states[user_id] = STATE_MANAGEMENT
    
    bot.send_message(
        message.chat.id,
        "⚙️ **Управление ботом**\n\nВыберите действие:",
        reply_markup=get_management_keyboard(),
        parse_mode='Markdown'
    )

def finish_upload(message):
    """Завершить загрузку"""
    user_id = message.from_user.id
    data = user_data.get(user_id, {})
    
    variant_name = data.get('variant_name', 'товара')
    uploaded_count = data.get('uploaded_count', 0)
    
    bot.send_message(
        message.chat.id,
        f"✅ **Загрузка завершена!**\n\n"
        f"Товар: {variant_name}\n"
        f"Загружено фото: {uploaded_count}",
        reply_markup=get_main_menu_keyboard(),
        parse_mode='Markdown'
    )
    
    user_states[user_id] = STATE_MAIN_MENU

@bot.message_handler(content_types=['photo', 'document'])
def handle_photo(message):
    """Обработка фото"""
    user_id = message.from_user.id
    state = user_states.get(user_id, STATE_MAIN_MENU)
    
    # Фото принимаем ТОЛЬКО в состоянии загрузки
    if state == STATE_GET_PHOTOS:
        process_photo(message)
            else:
        # Если пользователь прислал фото не в том состоянии
        bot.send_message(
            message.chat.id, 
            "📸 Сначала выберите товар!\n\nНажмите кнопку ниже:",
            reply_markup=get_main_menu_keyboard()
        )

def handle_code_input_text(message, code):
    """Обработка ввода кода модификации"""
    user_id = message.from_user.id
    
    # ПРОВЕРКА: если уже обрабатывается запрос - игнорируем
    if user_processing.get(user_id, False):
        bot.send_message(
            message.chat.id,
            "⏳ **Подождите!**\n\nЯ обрабатываю предыдущий запрос.\n"
            "Дождитесь ответа или нажмите 🔙 для отмены.",
            parse_mode='Markdown',
            reply_markup=get_code_input_keyboard()
        )
        return
    
    code = code.strip()
    
    # Устанавливаем флаг обработки
    user_processing[user_id] = True
    
    # Показываем что ищем
    search_msg = bot.send_message(message.chat.id, f"🔍 Ищу товар с кодом: {code}...")
    
    try:
        variant = get_variant_by_code(code)
        
        if not variant:
            # Удаляем сообщение о поиске
            try:
                bot.delete_message(message.chat.id, search_msg.message_id)
            except:
                pass
            
            bot.send_message(
                message.chat.id, 
                f"❌ Товар с кодом **{code}** не найден\n\n"
                f"Проверьте код и попробуйте еще раз:",
                reply_markup=get_code_input_keyboard(),
                parse_mode='Markdown'
            )
            # Остаемся в состоянии ввода кода
            user_states[user_id] = STATE_GET_CODE
            # Снимаем флаг обработки
            user_processing[user_id] = False
            return
        
        variant_name = variant.get('name', 'Без названия')
        variant_id = variant['id']
        
        # Получаем текущие фото (с обработкой ошибок)
        try:
            existing_images = get_variant_images(variant_id)
            images_count = len(existing_images)
        except Exception as e:
            logger.error(f"Ошибка при получении фото: {e}")
            images_count = 0
        
        # Добавляем код в историю
        if 'history' not in user_data[user_id]:
            user_data[user_id]['history'] = []
        if code not in user_data[user_id]['history']:
            user_data[user_id]['history'].append(code)
            # Ограничиваем историю 5 элементами
            user_data[user_id]['history'] = user_data[user_id]['history'][-5:]
        
        # Сохраняем данные
        user_data[user_id].update({
            'variant_id': variant_id,
            'variant_code': code,
            'variant_name': variant_name,
            'existing_images_count': images_count,
            'uploaded_count': 0
        })
        user_states[user_id] = STATE_GET_PHOTOS
        
        # Удаляем сообщение о поиске
        try:
            bot.delete_message(message.chat.id, search_msg.message_id)
        except:
            pass
        
        # Формируем сообщение с информацией о фото
        if images_count > 0:
            photos_emoji = "📸" * min(images_count, 5)
            photos_info = f"📷 Текущих фото: {images_count} {photos_emoji}\n\n"
        else:
            photos_info = "📷 Текущих фото: нет\n\n"
        
        bot.send_message(
            message.chat.id,
            f"✅ **Найдено:** {variant_name}\n\n"
            f"{photos_info}"
            f"📸 **Теперь отправьте фото** (можно несколько)\n\n"
            f"Когда закончите - нажмите **✅ Завершить**",
            reply_markup=get_photo_upload_keyboard(),
            parse_mode='Markdown'
        )
        
        # Снимаем флаг обработки
        user_processing[user_id] = False
        
        logger.info(f"Пользователь {message.from_user.username} нашел товар: {variant_name} (код: {code}, фото: {images_count})")
        
    except Exception as e:
        logger.error(f"Ошибка при обработке кода {code}: {e}")
        
        # Удаляем сообщение о поиске
        try:
            bot.delete_message(message.chat.id, search_msg.message_id)
        except:
            pass
        
        bot.send_message(
            message.chat.id, 
            f"❌ Произошла ошибка при поиске\n\n"
            f"Попробуйте еще раз или вернитесь в главное меню:",
            reply_markup=get_code_input_keyboard()
        )
        # Остаемся в состоянии ввода кода
        user_states[user_id] = STATE_GET_CODE
        # Снимаем флаг обработки
        user_processing[user_id] = False

def process_photo(message):
    """Обработка загруженного фото"""
    user_id = message.from_user.id
    
    # ПРОВЕРКА: если уже обрабатывается фото - игнорируем
    if user_processing.get(user_id, False):
        bot.send_message(
            message.chat.id,
            "⏳ **Подождите!**\n\nЯ загружаю предыдущее фото.\nДождитесь завершения.",
            parse_mode='Markdown'
        )
        return
    
    data = user_data.get(user_id, {})
    
    if not data or 'variant_id' not in data:
        bot.send_message(
            message.chat.id, 
            "❌ Данные потеряны. Начните заново:",
            reply_markup=get_main_menu_keyboard()
        )
        user_states[user_id] = STATE_MAIN_MENU
        return
    
    variant_id = data['variant_id']
    variant_code = data['variant_code']
    variant_name = data['variant_name']
    
    # Устанавливаем флаг обработки
    user_processing[user_id] = True
    
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
            # Увеличиваем счетчик
            user_data[user_id]['uploaded_count'] = user_data[user_id].get('uploaded_count', 0) + 1
            uploaded = user_data[user_id]['uploaded_count']
            
            bot.send_message(
                message.chat.id, 
                f"✅ Фото '{filename}' загружено!\n\n"
                f"📸 Загружено фото: {uploaded}\n\n"
                f"Можете загрузить еще или нажмите '✅ Завершить'",
                reply_markup=get_photo_upload_keyboard()
            )
            save_upload_to_db(user_id, message.from_user.username, variant_code, variant_name, filename, True)
    else:
            bot.send_message(
                message.chat.id, 
                f"❌ Ошибка при загрузке '{filename}'\n\nПопробуйте другое фото или нажмите '✅ Завершить'",
                reply_markup=get_photo_upload_keyboard()
            )
            save_upload_to_db(user_id, message.from_user.username, variant_code, variant_name, filename, False)
        
        # Снимаем флаг обработки
        user_processing[user_id] = False
    
    except Exception as e:
        logger.error(f"Ошибка при обработке фото: {e}")
        bot.send_message(
            message.chat.id, 
            f"❌ Ошибка: {e}\n\nПопробуйте другое фото или нажмите '✅ Завершить'",
            reply_markup=get_photo_upload_keyboard()
        )
        # Снимаем флаг обработки
        user_processing[user_id] = False


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
