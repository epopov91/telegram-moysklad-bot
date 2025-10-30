import logging
import requests
import io
import mimetypes
import base64
import os
import sys
import subprocess
import sqlite3
import threading
import time
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
BOT_VERSION = "5.5.2"
BOT_START_TIME = datetime.now()

# Настройки
BACKUP_PHOTOS = False  # Опция сохранения фото на диск

# Инициализация бота
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Состояния пользователей
user_states = {}
user_data = {}
user_processing = {}  # Флаг обработки запроса
user_photo_queue = {}  # Очередь фотографий для каждого пользователя
user_queue_processing = {}  # Флаг обработки очереди

# Константы состояний
STATE_MAIN_MENU = 0
STATE_GET_CODE = 1
STATE_GET_PHOTOS = 2
STATE_STATISTICS = 3
STATE_MANAGEMENT = 4
STATE_NO_PHOTO_LIST = 5

# Константы кнопок
BTN_UPLOAD = "📸 Загрузить фото"
BTN_STATS = "📊 Статистика"
BTN_NO_PHOTO = "📋 Товары без фото"
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
    keyboard.row(BTN_NO_PHOTO, BTN_MANAGE)
    keyboard.row(BTN_HELP)
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

def get_moysklad_statistics():
    """Получение статистики по МойСклад"""
    try:
        url_variants = "https://api.moysklad.ru/api/remap/1.2/entity/variant"
        headers = {
            'Authorization': f'Bearer {MOYSKLAD_API_TOKEN}',
            'Accept-Encoding': 'gzip'
        }
        
        response = requests.get(f"{url_variants}?limit=0", headers=headers, timeout=10)
        response.raise_for_status()
        total_variants = response.json()['meta']['size']
        logger.info(f"Всего модификаций: {total_variants}")
        
        logger.info("Получаю количество позиций с остатком...")
        url_stock = "https://api.moysklad.ru/api/remap/1.2/report/stock/all"
        response_stock = requests.get(f"{url_stock}?limit=0&stockMode=positiveOnly", headers=headers, timeout=30)
        
        variants_with_stock = 0
        if response_stock.status_code == 200:
            variants_with_stock = response_stock.json()['meta']['size']
            logger.info(f"Позиций с остатком > 0: {variants_with_stock}")
        
        logger.info("Подсчитываю модификации с фото...")
        variants_with_images = 0
        offset = 0
        limit = 100
        
        while offset < min(total_variants, 1000):
            response_page = requests.get(f"{url_variants}?limit={limit}&offset={offset}", headers=headers, timeout=30)
            if response_page.status_code != 200:
                break
            
            variants = response_page.json().get('rows', [])
            if not variants:
                break
            
            for variant in variants:
                if variant.get('images') and variant['images'].get('meta', {}).get('size', 0) > 0:
                    variants_with_images += 1
            
            offset += limit
        
        logger.info(f"Модификаций с фото: {variants_with_images}")
        
        return {
            'total': total_variants,
            'with_stock': variants_with_stock,
            'with_images': variants_with_images,
            'checked': min(offset, total_variants)
        }
    except Exception as e:
        logger.error(f"Ошибка при получении статистики МойСклад: {e}")
        return {'total': 0, 'with_stock': 0, 'with_images': 0, 'checked': 0}

def get_variant_stock(variant_id: str):
    """Получение товарного остатка по variant_id с повторными попытками"""
    url = "https://api.moysklad.ru/api/remap/1.2/report/stock/all"
    headers = {
        'Authorization': f'Bearer {MOYSKLAD_API_TOKEN}',
        'Accept-Encoding': 'gzip'
    }
    
    params = {
        'filter': f'variant=https://api.moysklad.ru/api/remap/1.2/entity/variant/{variant_id}'
    }
    
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            rows = data.get('rows', [])
            if rows:
                # Суммируем stock по всем складам
                total_stock = sum(row.get('stock', 0) for row in rows)
                return int(total_stock)
            else:
                return 0
                
        except requests.exceptions.Timeout:
            logger.warning(f"Таймаут при получении остатка (попытка {attempt + 1}/3)")
            if attempt < 2:
                time.sleep(2)
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Ошибка соединения при получении остатка (попытка {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(2)
        except Exception as e:
            logger.error(f"Ошибка при получении остатка товара {variant_id}: {e}")
            if attempt < 2:
                time.sleep(2)
            else:
                return None
    
    return None

def get_variants_without_photos(with_stock_only=True):
    """Получение списка товаров без фотографий"""
    try:
        url_variants = "https://api.moysklad.ru/api/remap/1.2/entity/variant"
        url_stock = "https://api.moysklad.ru/api/remap/1.2/report/stock/all"
        headers = {
            'Authorization': f'Bearer {MOYSKLAD_API_TOKEN}',
            'Accept-Encoding': 'gzip'
        }
        
        logger.info(f"Получение товаров без фото (с остатком: {with_stock_only})")
        
        # Получаем список variant_id с остатками если нужен фильтр
        stock_variant_ids = set()
        stock_data = {}  # variant_id -> stock
        
        if with_stock_only:
            logger.info("Получаю товары с остатком...")
            offset = 0
            limit = 1000
            
            while True:
                response = requests.get(
                    f"{url_stock}?limit={limit}&offset={offset}&stockMode=positiveOnly",
                    headers=headers,
                    timeout=30
                )
                if response.status_code != 200:
                    break
                
                rows = response.json().get('rows', [])
                if not rows:
                    break
                
                for row in rows:
                    variant_meta = row.get('meta', {})
                    if variant_meta.get('type') == 'variant':
                        variant_href = variant_meta.get('href', '')
                        if '/variant/' in variant_href:
                            variant_id = variant_href.split('/variant/')[-1].split('?')[0]
                            stock_variant_ids.add(variant_id)
                            stock_data[variant_id] = int(row.get('stock', 0))
                
                offset += limit
                if len(rows) < limit:
                    break
            
            logger.info(f"Найдено {len(stock_variant_ids)} товаров с остатком")
        
        # Получаем все варианты и проверяем наличие фото
        variants_without_photos = []
        offset = 0
        limit = 100
        
        while True:
            response = requests.get(
                f"{url_variants}?limit={limit}&offset={offset}",
                headers=headers,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Ошибка получения вариантов: {response.status_code}")
                break
            
            data = response.json()
            variants = data.get('rows', [])
            
            if not variants:
                break
            
            for variant in variants:
                variant_id = variant.get('id')
                
                # Фильтр по остаткам
                if with_stock_only and variant_id not in stock_variant_ids:
                    continue
                
                # Проверяем наличие фото
                images = variant.get('images', {})
                has_images = images.get('meta', {}).get('size', 0) > 0
                
                if not has_images:
                    variants_without_photos.append({
                        'id': variant_id,
                        'code': variant.get('code', ''),
                        'name': variant.get('name', 'Без названия'),
                        'stock': stock_data.get(variant_id, 0) if with_stock_only else 0
                    })
            
            offset += limit
            
            # Прогресс
            if offset % 500 == 0:
                logger.info(f"Обработано {offset} вариантов, найдено без фото: {len(variants_without_photos)}")
            
            if len(variants) < limit:
                break
        
        # Сортируем по коду (возрастание) для удобного поиска
        variants_without_photos.sort(key=lambda x: x['code'] or 'ЯЯЯЯ')  # Товары без кода - в конец
        
        logger.info(f"Найдено товаров без фото: {len(variants_without_photos)}")
        return variants_without_photos
        
    except Exception as e:
        logger.error(f"Ошибка при получении товаров без фото: {e}", exc_info=True)
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
/restart - Обычный перезапуск бота
/reboot - Экстренный перезапуск (если завис)
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
            bot.send_message(
                message.chat.id, 
                f"✅ Обновлено!\n```\n{result.stdout}\n```\n\n🔄 Перезапуск...\n\n"
                f"⚠️ **После перезапуска нажмите** /start **для обновления меню!**",
                parse_mode='Markdown'
            )
            logger.info("Обновление кода и перезапуск бота")
            time.sleep(1)  # Даем время отправить сообщение
            
            # Перезапуск (правильная команда для Windows и Unix)
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            bot.send_message(message.chat.id, f"❌ Ошибка:\n```\n{result.stderr}\n```", parse_mode='Markdown')
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

@bot.message_handler(commands=['restart'])
def cmd_restart(message):
    """Перезапуск бота"""
    bot.send_message(
        message.chat.id, 
        "🔄 **Перезапускаю бота...**\n\n"
        "Подождите 5-10 секунд\n\n"
        "⚠️ **После перезапуска нажмите** /start **для обновления меню!**",
        parse_mode='Markdown'
    )
    logger.info(f"Перезапуск бота по команде {message.from_user.username}")
    time.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)

@bot.message_handler(commands=['reboot'])
def cmd_reboot(message):
    """Экстренный перезапуск с очисткой"""
    bot.send_message(
        message.chat.id, 
        "🆘 **Экстренный перезапуск!**\n\n"
        "Очищаю состояния и перезапускаю...\n\n"
        "⚠️ **После перезапуска нажмите** /start **для обновления меню!**",
        parse_mode='Markdown'
    )
    logger.warning(f"ЭКСТРЕННЫЙ перезапуск по команде {message.from_user.username}")
    
    # Очищаем все состояния
    user_states.clear()
    user_data.clear()
    user_processing.clear()
    
    time.sleep(1)
    # Перезапуск
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
            bot.send_message(
                message.chat.id, 
                "✅ Зависимости проверены\n\n"
                "3️⃣ Перезапуск бота...\n\n"
                "⚠️ **После перезапуска нажмите** /start **для обновления меню!**",
                parse_mode='Markdown'
            )
        else:
            bot.send_message(
                message.chat.id, 
                f"⚠️ Предупреждение при установке:\n```\n{result.stderr}\n```\n\n"
                f"3️⃣ Перезапуск бота...\n\n"
                f"⚠️ **После перезапуска нажмите** /start **для обновления меню!**",
                parse_mode='Markdown'
            )
        
        logger.info(f"Автоматическое исправление и перезапуск по команде {message.from_user.username}")
        
        time.sleep(1)  # Даем время отправить сообщение
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
        elif text == BTN_NO_PHOTO:
            show_products_without_photos(message)
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
    # Статистика загрузок
    total_uploads, unique_products = get_upload_stats()
    
    # Отправляем первое сообщение с общей статистикой
    first_msg = bot.send_message(
        message.chat.id,
        f"📊 **Статистика загрузок**\n\n"
        f"📸 Всего фото загружено: {total_uploads}\n"
        f"🏷 Уникальных товаров: {unique_products}",
        parse_mode='Markdown'
    )
    
    # Отправляем отдельное сообщение о загрузке из МойСклад
    loading_msg = bot.send_message(
        message.chat.id,
        "⏳ **Загружаю статистику из МойСклад...**\n\n"
        "📦 Проверяю количество модификаций\n"
        "✅ Считаю товары с остатком\n"
        "📸 Проверяю наличие фотографий\n\n"
        "_Это займет 10-20 секунд..._",
        parse_mode='Markdown'
    )
    
    # Получаем статистику из МойСклад (это может занять время)
    ms_stats = get_moysklad_statistics()
    
    # ЗАМЕНЯЕМ содержимое сообщения о загрузке на результат
    stats_text = f"📊 **Статистика МойСклад**\n\n"
    stats_text += f"📦 Всего модификаций: {ms_stats['total']}\n"
    stats_text += f"✅ С товарным остатком: {ms_stats['with_stock']}\n"
    stats_text += f"📸 С фотографиями: {ms_stats['with_images']}"
    
    if ms_stats['checked'] < ms_stats['total']:
        stats_text += f"\n\n⚠️ Проверено: {ms_stats['checked']} из {ms_stats['total']}"
    
    try:
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=loading_msg.message_id,
            text=stats_text,
            parse_mode='Markdown'
        )
    except:
        # Если не удалось изменить, отправляем новым сообщением
        bot.send_message(
            message.chat.id,
            stats_text,
            parse_mode='Markdown'
        )
    
    # Отправляем клавиатуру отдельным сообщением
    bot.send_message(
        message.chat.id,
        "Выберите действие:",
        reply_markup=get_main_menu_keyboard()
    )

def show_products_without_photos(message, with_stock_only=True):
    """Показать список товаров без фото"""
    user_id = message.from_user.id
    user_states[user_id] = STATE_NO_PHOTO_LIST
    
    # Отправляем сообщение о загрузке
    loading_msg = bot.send_message(
        message.chat.id,
        "⏳ **Загружаю список товаров без фото...**\n\n"
        "Это может занять 30-60 секунд...",
        parse_mode='Markdown'
    )
    
    try:
        # Получаем товары без фото
        variants = get_variants_without_photos(with_stock_only=with_stock_only)
        
        # Удаляем сообщение о загрузке
        try:
            bot.delete_message(message.chat.id, loading_msg.message_id)
        except:
            pass
        
        if not variants:
            bot.send_message(
                message.chat.id,
                "✅ **Отлично!**\n\nВсе товары с остатком уже имеют фотографии! 🎉",
                reply_markup=get_main_menu_keyboard(),
                parse_mode='Markdown'
            )
            return
        
        # Формируем текст списка
        total_count = len(variants)
        filter_text = "✅ С остатком > 0" if with_stock_only else "📦 Все товары"
        
        # Формируем сообщения (макс 4096 символов на сообщение)
        messages = []
        current_message = f"📋 **ТОВАРЫ БЕЗ ФОТО**\n\n"
        current_message += f"Фильтр: {filter_text} | Всего: **{total_count}** шт.\n"
        current_message += f"Сортировка: По коду ↑\n\n"
        current_message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        item_number = 1
        for variant in variants:
            code = variant['code'] or 'Н/Д'
            name = variant['name'][:80]  # Ограничиваем длину названия
            stock = variant['stock']
            
            # Форматируем строку
            line = f"**{code}** ({stock}) {name}\n"
            
            # Проверяем не превысим ли лимит
            if len(current_message) + len(line) > 4000:  # Оставляем запас
                messages.append(current_message)
                current_message = f"📋 **ТОВАРЫ БЕЗ ФОТО** (продолжение)\n\n"
            
            current_message += line
            item_number += 1
        
        # Добавляем последнее сообщение
        if current_message:
            messages.append(current_message)
        
        # Отправляем сообщения
        for i, msg_text in enumerate(messages):
            if i == len(messages) - 1:
                # В последнем сообщении добавляем итог и кнопки
                msg_text += f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                msg_text += f"💡 **Для загрузки фото** введите код товара\n"
                
                # Создаем inline-кнопки для топ-10 товаров
                keyboard = types.InlineKeyboardMarkup(row_width=5)
                top_variants = variants[:min(10, len(variants))]
                buttons = []
                
                for v in top_variants:
                    if v['code']:
                        btn = types.InlineKeyboardButton(
                            text=v['code'],
                            callback_data=f"select_code:{v['code']}"
                        )
                        buttons.append(btn)
                
                # Добавляем кнопки по 5 в ряд
                for j in range(0, len(buttons), 5):
                    keyboard.row(*buttons[j:j+5])
                
                # Добавляем кнопки действий
                btn_csv = types.InlineKeyboardButton("📄 Скачать CSV", callback_data="download_csv")
                btn_filter = types.InlineKeyboardButton(
                    "📦 Все товары" if with_stock_only else "✅ С остатком",
                    callback_data=f"filter_stock:{'all' if with_stock_only else 'stock'}"
                )
                keyboard.row(btn_csv, btn_filter)
                
                bot.send_message(
                    message.chat.id,
                    msg_text,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
            else:
                # Промежуточные сообщения без кнопок
                bot.send_message(
                    message.chat.id,
                    msg_text,
                    parse_mode='Markdown'
                )
                time.sleep(0.5)  # Небольшая пауза между сообщениями
        
        # Сохраняем данные в user_data для возможных действий
        if user_id not in user_data:
            user_data[user_id] = {}
        user_data[user_id]['no_photo_list'] = variants
        
        logger.info(f"Показан список товаров без фото: {total_count} шт. (пользователь {message.from_user.username})")
        
    except Exception as e:
        logger.error(f"Ошибка при показе товаров без фото: {e}", exc_info=True)
        
        # Удаляем сообщение о загрузке если есть
        try:
            bot.delete_message(message.chat.id, loading_msg.message_id)
        except:
            pass
        
        bot.send_message(
            message.chat.id,
            f"❌ **Ошибка при загрузке списка**\n\n"
            f"Ошибка: {str(e)}\n\n"
            f"Попробуйте позже или обратитесь к администратору",
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
        
        # Получаем товарный остаток (необязательно - если ошибка, просто не показываем)
        stock = None
        try:
            stock = get_variant_stock(variant_id)
        except Exception as e:
            logger.warning(f"Не удалось получить остаток для {variant_id}: {e}")
            # Не падаем, просто пропускаем показ остатка
        
        # Инициализируем user_data для пользователя если его нет
        if user_id not in user_data:
            user_data[user_id] = {}
        
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
            photos_info = f"📷 Текущих фото: {images_count} {photos_emoji}\n"
        else:
            photos_info = "📷 Текущих фото: нет\n"
        
        # Добавляем информацию об остатках
        if stock is not None:
            if stock > 0:
                stock_info = f"📦 Товарный остаток: **{stock} шт.**\n\n"
            else:
                stock_info = f"⚠️ Товарный остаток: **0 шт.**\n\n"
        else:
            stock_info = ""
        
        bot.send_message(
            message.chat.id,
            f"✅ **Найдено:** {variant_name}\n\n"
            f"{photos_info}"
            f"{stock_info}"
            f"📸 **Теперь отправьте фото** (можно несколько)\n\n"
            f"Когда закончите - нажмите **✅ Завершить**",
            reply_markup=get_photo_upload_keyboard(),
            parse_mode='Markdown'
        )
        
        # Снимаем флаг обработки
        user_processing[user_id] = False
        
        logger.info(f"Пользователь {message.from_user.username} нашел товар: {variant_name} (код: {code}, фото: {images_count})")
        
    except Exception as e:
        logger.error(f"Ошибка при обработке кода {code}: {e}", exc_info=True)
        
        # Удаляем сообщение о поиске
        try:
            bot.delete_message(message.chat.id, search_msg.message_id)
        except:
            pass
        
        # Показываем РЕАЛЬНУЮ ошибку для отладки
        error_msg = f"❌ **Ошибка при поиске**\n\n"
        error_msg += f"Код: `{code}`\n"
        error_msg += f"Ошибка: `{str(e)}`\n\n"
        error_msg += f"Попробуйте еще раз или обратитесь к администратору"
        
        bot.send_message(
            message.chat.id, 
            error_msg,
            reply_markup=get_code_input_keyboard(),
            parse_mode='Markdown'
        )
        # Остаемся в состоянии ввода кода
        user_states[user_id] = STATE_GET_CODE
        # Снимаем флаг обработки
        user_processing[user_id] = False

def process_photo(message):
    """Обработка загруженного фото - добавление в очередь"""
    user_id = message.from_user.id
    
    data = user_data.get(user_id, {})
    
    if not data or 'variant_id' not in data:
        bot.send_message(
            message.chat.id, 
            "❌ Данные потеряны. Начните заново:",
            reply_markup=get_main_menu_keyboard()
        )
        user_states[user_id] = STATE_MAIN_MENU
        return
    
    # Инициализируем очередь если её нет
    if user_id not in user_photo_queue:
        user_photo_queue[user_id] = []
    
    # Добавляем фото в очередь
    user_photo_queue[user_id].append(message)
    queue_size = len(user_photo_queue[user_id])
    
    logger.info(f"Фото добавлено в очередь пользователя {user_id}. Размер очереди: {queue_size}")
    
    # Отправляем подтверждение
    bot.send_message(
        message.chat.id,
        f"📥 Фото принято! В очереди: {queue_size}",
        parse_mode='Markdown'
    )
    
    # Запускаем обработку очереди если она еще не запущена
    if not user_queue_processing.get(user_id, False):
        user_queue_processing[user_id] = True
        # Запускаем обработку в отдельном потоке
        thread = threading.Thread(target=process_photo_queue, args=(user_id,))
        thread.daemon = True
        thread.start()

def process_photo_queue(user_id):
    """Обработка очереди фотографий пользователя"""
    try:
        while user_id in user_photo_queue and len(user_photo_queue[user_id]) > 0:
            # Берем первое фото из очереди
            message = user_photo_queue[user_id].pop(0)
            remaining = len(user_photo_queue[user_id])
            
            data = user_data.get(user_id, {})
            if not data or 'variant_id' not in data:
                bot.send_message(
                    message.chat.id,
                    "❌ Данные потеряны. Начните заново:",
                    reply_markup=get_main_menu_keyboard()
                )
                user_states[user_id] = STATE_MAIN_MENU
                break
            
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
                
                # Показываем прогресс
                progress_msg = f"⏳ Загружаю '{filename}'..."
                if remaining > 0:
                    progress_msg += f"\n📋 Осталось в очереди: {remaining}"
                
                bot.send_message(message.chat.id, progress_msg)
                
                # Загружаем в МойСклад
                success = upload_photo_to_variant(variant_id, photo_bytes, filename, variant_code)
                
                if success:
                    # Увеличиваем счетчик
                    user_data[user_id]['uploaded_count'] = user_data[user_id].get('uploaded_count', 0) + 1
                    uploaded = user_data[user_id]['uploaded_count']
                    
                    result_msg = f"✅ Фото '{filename}' загружено!\n\n"
                    result_msg += f"📸 Загружено фото: {uploaded}"
                    
                    if remaining > 0:
                        result_msg += f"\n⏳ Обрабатываю следующее ({remaining} в очереди)..."
                    else:
                        result_msg += f"\n\nМожете загрузить еще или нажмите '✅ Завершить'"
                    
                    bot.send_message(
                        message.chat.id,
                        result_msg,
                        reply_markup=get_photo_upload_keyboard() if remaining == 0 else None
                    )
                    save_upload_to_db(user_id, message.from_user.username, variant_code, variant_name, filename, True)
                else:
                    bot.send_message(
                        message.chat.id,
                        f"❌ Ошибка при загрузке '{filename}'\n"
                        f"{'⏳ Обрабатываю следующее...' if remaining > 0 else 'Попробуйте другое фото'}",
                        reply_markup=get_photo_upload_keyboard() if remaining == 0 else None
                    )
                    save_upload_to_db(user_id, message.from_user.username, variant_code, variant_name, filename, False)
                
                # Небольшая пауза между загрузками
                if remaining > 0:
                    time.sleep(0.5)
            
            except Exception as e:
                logger.error(f"Ошибка при обработке фото из очереди: {e}")
                bot.send_message(
                    message.chat.id,
                    f"❌ Ошибка: {e}\n"
                    f"{'⏳ Обрабатываю следующее...' if remaining > 0 else 'Попробуйте другое фото'}",
                    reply_markup=get_photo_upload_keyboard() if remaining == 0 else None
                )
        
        # Очередь обработана
        logger.info(f"Очередь пользователя {user_id} обработана полностью")
        
    finally:
        # Снимаем флаг обработки
        user_queue_processing[user_id] = False
        # Очищаем пустую очередь
        if user_id in user_photo_queue and len(user_photo_queue[user_id]) == 0:
            del user_photo_queue[user_id]


# =========================
# CALLBACK HANDLERS
# =========================

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Обработка нажатий inline-кнопок"""
    try:
        user_id = call.from_user.id
        data = call.data
        
        # Выбор кода товара
        if data.startswith('select_code:'):
            code = data.split(':')[1]
            
            # Переводим в состояние ввода кода и обрабатываем
            user_states[user_id] = STATE_GET_CODE
            
            # Создаем фейковое сообщение для handle_code_input_text
            class FakeMessage:
                def __init__(self, chat_id, from_user):
                    self.chat = type('obj', (object,), {'id': chat_id})()
                    self.from_user = from_user
            
            fake_msg = FakeMessage(call.message.chat.id, call.from_user)
            
            # Отвечаем на callback
            bot.answer_callback_query(call.id, f"Выбран код: {code}")
            
            # Обрабатываем как будто пользователь ввел код
            handle_code_input_text(fake_msg, code)
        
        # Скачивание CSV
        elif data == 'download_csv':
            bot.answer_callback_query(call.id, "Формирую CSV файл...")
            
            # Получаем сохраненный список
            variants = user_data.get(user_id, {}).get('no_photo_list', [])
            
            if not variants:
                bot.answer_callback_query(call.id, "❌ Список устарел, обновите")
                return
            
            # Формируем CSV
            import io
            csv_content = "Код,Название,Остаток\n"
            for v in variants:
                code = v['code'] or 'Н/Д'
                name = v['name'].replace('"', '""')  # Экранируем кавычки
                stock = v['stock']
                csv_content += f'"{code}","{name}",{stock}\n'
            
            # Отправляем файл
            csv_file = io.BytesIO(csv_content.encode('utf-8-sig'))  # BOM для Excel
            csv_file.name = f'products_without_photos_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            
            bot.send_document(
                call.message.chat.id,
                csv_file,
                caption=f"📄 **Товары без фото**\n\nВсего: {len(variants)} шт.",
                parse_mode='Markdown'
            )
            
            bot.answer_callback_query(call.id, "✅ CSV файл отправлен!")
        
        # Переключение фильтра
        elif data.startswith('filter_stock:'):
            filter_type = data.split(':')[1]
            with_stock = (filter_type == 'stock')
            
            bot.answer_callback_query(call.id, "🔄 Обновляю список...")
            
            # Создаем фейковое сообщение
            class FakeMessage:
                def __init__(self, chat_id, from_user):
                    self.chat = type('obj', (object,), {'id': chat_id})()
                    self.from_user = from_user
            
            fake_msg = FakeMessage(call.message.chat.id, call.from_user)
            
            # Показываем список с новым фильтром
            show_products_without_photos(fake_msg, with_stock_only=with_stock)
        
        else:
            bot.answer_callback_query(call.id, "Неизвестное действие")
    
    except Exception as e:
        logger.error(f"Ошибка в callback handler: {e}", exc_info=True)
        bot.answer_callback_query(call.id, f"❌ Ошибка: {str(e)}")

# =========================
# ЗАПУСК БОТА
# =========================

def check_and_update(send_notification=False):
    """Автоматическая проверка и установка обновлений"""
    try:
        logger.info("🔍 Проверка обновлений из GitHub...")
        
        # Делаем git fetch
        subprocess.run(['git', 'fetch'], capture_output=True, text=True, timeout=10)
        
        # Проверяем есть ли новые коммиты
        result = subprocess.run(['git', 'status', '-uno'], capture_output=True, text=True, timeout=5)
        
        if 'Your branch is behind' in result.stdout or 'behind' in result.stdout:
            logger.info("📥 Найдены обновления! Устанавливаю...")
            
            # Отправляем уведомление если запрошено
            if send_notification and ADMIN_USER_ID:
                try:
                    bot.send_message(
                        ADMIN_USER_ID,
                        "🔄 **Обнаружено обновление!**\n\n"
                        "Устанавливаю обновление и перезапускаю бота...",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            
            # Делаем git pull
            pull_result = subprocess.run(['git', 'pull'], capture_output=True, text=True, timeout=15)
            
            if pull_result.returncode == 0:
                logger.info(f"✅ Код обновлен успешно!")
                logger.info("🔄 Перезапуск бота с новой версией...")
                
                # Перезапуск с новой версией
                os.execv(sys.executable, [sys.executable] + sys.argv)
            else:
                logger.error(f"❌ Ошибка при обновлении: {pull_result.stderr}")
                if send_notification and ADMIN_USER_ID:
                    try:
                        bot.send_message(
                            ADMIN_USER_ID,
                            f"❌ Ошибка при обновлении:\n```\n{pull_result.stderr}\n```",
                            parse_mode='Markdown'
                        )
                    except:
                        pass
        else:
            logger.info("✅ Бот уже использует последнюю версию")
            
    except subprocess.TimeoutExpired:
        logger.warning("⏱ Таймаут при проверке обновлений, продолжаю работу...")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось проверить обновления: {e}, продолжаю работу...")

def auto_update_loop():
    """Фоновая проверка обновлений каждые 30 минут"""
    while True:
        try:
            # Ждем 30 минут (1800 секунд)
            time.sleep(1800)
            logger.info("⏰ Плановая проверка обновлений...")
            check_and_update(send_notification=True)
        except Exception as e:
            logger.error(f"Ошибка в фоновой проверке обновлений: {e}")
            time.sleep(1800)  # Продолжаем проверять даже при ошибках

def main():
    # Автоматическая проверка обновлений при запуске
    check_and_update(send_notification=False)
    
    init_database()
    logger.info(f"🚀 Запуск бота версии {BOT_VERSION}")
    logger.info("✅ Бот запущен и готов к работе!")
    
    # Запускаем фоновый поток для автообновлений
    update_thread = threading.Thread(target=auto_update_loop, daemon=True)
    update_thread.start()
    logger.info("🔄 Фоновая проверка обновлений запущена (каждые 30 минут)")
    
    # Отправляем уведомление администратору о запуске
    if ADMIN_USER_ID:
        try:
            bot.send_message(
                ADMIN_USER_ID,
                f"✅ **Бот запущен!**\n\n"
                f"Версия: {BOT_VERSION}\n"
                f"Автообновление: включено ✅\n\n"
                f"💡 **Нажмите** /start **для обновления меню с новыми кнопками!**",
                parse_mode='Markdown'
            )
        except:
            pass
    
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}")

if __name__ == '__main__':
    main()
