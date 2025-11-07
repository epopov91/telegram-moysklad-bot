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
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from dotenv import load_dotenv
import telebot
from telebot import types

# Загрузка переменных окружения из .env файла
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
MOYSKLAD_API_TOKEN = os.getenv('MOYSKLAD_API_TOKEN')
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID')  # ID администратора для управления ботом
GOOGLE_DRIVE_ROOT_FOLDER_ID = os.getenv('GOOGLE_DRIVE_ROOT_FOLDER_ID', '12SSLkDFGdkmF6xI9F8RPbnZDS1FdKhNH')

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

# Добавляем путь к папке Google таблица для импорта модулей
GOOGLE_TABLE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'Google таблица')
if GOOGLE_TABLE_PATH not in sys.path:
    sys.path.insert(0, GOOGLE_TABLE_PATH)

# Импорты для Google Drive (с обработкой ошибок)
try:
    from oauth2_drive_auth import get_drive_service
    from consolidate_and_download_photos import OAuth2DriveAPI
    from googleapiclient.http import MediaIoBaseUpload
    GOOGLE_DRIVE_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Google Drive модули не найдены: {e}. Загрузка видео будет недоступна.")
    GOOGLE_DRIVE_AVAILABLE = False

# Версия бота
BOT_VERSION = "5.8.0"
BOT_START_TIME = datetime.now()

# Настройки
BACKUP_PHOTOS = False  # Опция сохранения фото на диск

# Инициализация бота
# Локальный Bot API сервер используется только для больших файлов (>20 МБ)
BOT_API_SERVER = os.getenv('BOT_API_SERVER', None)  # Например: http://localhost:8081
if BOT_API_SERVER:
    logger.info(f"Локальный Bot API сервер настроен: {BOT_API_SERVER} (будет использоваться для больших файлов)")
else:
    logger.info("Используется стандартный Telegram Bot API (файлы >20 МБ не поддерживаются)")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Состояния пользователей
user_states = {}
user_data = {}
user_processing = {}  # Флаг обработки запроса
user_photo_queue = {}  # Очередь фотографий для каждого пользователя
user_queue_processing = {}  # Флаг обработки очереди
user_video_queue = {}  # Очередь видео для каждого пользователя
user_video_processing = {}  # Флаг обработки очереди видео

# Константы состояний
STATE_MAIN_MENU = 0
STATE_GET_CODE = 1
STATE_GET_PHOTOS = 2
STATE_STATISTICS = 3
STATE_MANAGEMENT = 4
STATE_NO_PHOTO_LIST = 5
STATE_GET_VIDEO = 6

# Константы кнопок
BTN_UPLOAD = "📸 Загрузить фото"
BTN_UPLOAD_VIDEO = "🎥 Загрузить видео"
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
    keyboard.row(BTN_UPLOAD, BTN_UPLOAD_VIDEO)
    keyboard.row(BTN_STATS, BTN_NO_PHOTO)
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

def get_video_upload_keyboard():
    """Клавиатура во время загрузки видео"""
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
# GOOGLE DRIVE API
# =========================

# Глобальный кэш для Drive API
_drive_api_cache = None

def get_drive_api():
    """Получить экземпляр OAuth2DriveAPI (с кэшированием)"""
    global _drive_api_cache
    
    if not GOOGLE_DRIVE_AVAILABLE:
        logger.error("Google Drive API недоступен")
        return None
    
    if _drive_api_cache is None:
        try:
            drive_service = get_drive_service()
            _drive_api_cache = OAuth2DriveAPI(drive_service)
            logger.info("Google Drive API инициализирован")
        except Exception as e:
            logger.error(f"Ошибка инициализации Google Drive API: {e}")
            return None
    
    return _drive_api_cache

def extract_color_and_size(name: str) -> Tuple[Optional[str], Optional[str]]:
    """Извлечь цвет и размер из названия модификации
    
    Форматы: 
    - "Товар (Цвет, Размер)" или "Товар (Размер, Цвет)"
    - "Товар (Размер)" - только размер, без цвета
    Размер может быть: число (104, 46), диапазон (40-44), или буква (S, M, L)
    
    Returns:
        (color, size) - кортеж с цветом и размером, или (None, None) если не удалось распарсить
    """
    idx = name.find('(')
    if idx == -1:
        return None, None
    
    inside = name[idx + 1:name.rfind(')')].strip()
    if not inside:
        return None, None
    
    parts = [s.strip() for s in inside.split(',') if s.strip()]
    
    # Если в скобках только один элемент - проверяем, является ли он размером
    if len(parts) == 1:
        single = parts[0]
        single_clean = single.replace('см', '').replace(' ', '').upper()
        
        # Проверяем, является ли это размером
        is_size = False
        # Число или диапазон
        if re.fullmatch(r'\d+[\-–]?\d*', single_clean):
            is_size = True
        # Размеры: одна буква (S, M, L) или многосимвольные (XS, XL, XXL и т.д.)
        elif re.fullmatch(r'[X]*[SLM]', single_clean) or single_clean in ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL']:
            is_size = True
        
        if is_size:
            return None, single  # Цвет = None, размер = single
        else:
            return single, None  # Цвет = single, размер = None
    
    # Если в скобках два или больше элементов
    if len(parts) < 2:
        return None, None
    
    first = parts[0]
    second = parts[1] if len(parts) > 1 else None
    
    # Проверяем, является ли первое значение размером
    is_first_size = False
    first_clean = first.replace('см', '').replace(' ', '').upper()
    # Число или диапазон
    if re.fullmatch(r'\d+[\-–]?\d*', first_clean):
        is_first_size = True
    # Размеры: одна буква (S, M, L) или многосимвольные (XS, XL, XXL и т.д.)
    elif re.fullmatch(r'[X]*[SLM]', first_clean) or first_clean in ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL']:
        is_first_size = True
    
    if is_first_size:
        size = first
        color = second if second else None
    else:
        color = first
        size = second if second else None
    
    return color, size

def get_parent_code_from_variant(variant: dict) -> Optional[str]:
    """Получить код родительского товара из варианта"""
    try:
        parent_href = None
        if variant.get('product') and variant['product'].get('meta'):
            parent_href = variant['product']['meta'].get('href')
        
        if not parent_href:
            return None
        
        # Получаем код родителя через API
        headers = {
            'Authorization': f'Bearer {MOYSKLAD_API_TOKEN}',
            'Accept-Encoding': 'gzip'
        }
        
        response = requests.get(parent_href, headers=headers, timeout=10)
        if response.status_code == 200:
            product = response.json()
            parent_code = product.get('code')
            if parent_code:
                logger.debug(f"Получен код родителя: {parent_code}")
                return parent_code
        
        return None
    except Exception as e:
        logger.error(f"Ошибка получения кода родителя: {e}")
        return None

def ensure_video_folder_structure(parent_code: str, color: Optional[str], drive_api) -> Optional[str]:
    """Создать структуру папок для видео: root_folder/код_родителя/цвет/Видео/
    
    Returns:
        folder_id папки "Видео" или None при ошибке
    """
    if not drive_api:
        logger.error("Drive API недоступен")
        return None
    
    try:
        root_folder_id = GOOGLE_DRIVE_ROOT_FOLDER_ID
        
        # 1. Найти/создать папку родителя в корневой папке
        parent_folder_id = drive_api.ensure_folder_exists(parent_code, root_folder_id)
        logger.debug(f"Папка родителя '{parent_code}': {parent_folder_id}")
        
        # 2. Найти/создать папку цвета в папке родителя
        color_name = color if color else 'Без цвета'
        color_folder_id = drive_api.ensure_folder_exists(color_name, parent_folder_id)
        logger.debug(f"Папка цвета '{color_name}': {color_folder_id}")
        
        # 3. Найти/создать папку "Видео" в папке цвета
        video_folder_id = drive_api.ensure_folder_exists('Видео', color_folder_id)
        logger.debug(f"Папка 'Видео': {video_folder_id}")
        
        return video_folder_id
        
    except Exception as e:
        logger.error(f"Ошибка создания структуры папок для видео: {e}")
        return None

def upload_video_to_drive(video_bytes: bytes, filename: str, folder_id: str, drive_api) -> bool:
    """Загрузить видео в Google Drive
    
    Args:
        video_bytes: байты видео
        filename: имя файла
        folder_id: ID папки в Google Drive
        drive_api: экземпляр OAuth2DriveAPI
    
    Returns:
        True если успешно, False при ошибке
    """
    if not drive_api:
        logger.error("Drive API недоступен")
        return False
    
    try:
        # Определяем MIME тип
        mime_type, _ = mimetypes.guess_type(filename)
        if not mime_type or not mime_type.startswith('video/'):
            mime_type = 'video/mp4'  # По умолчанию
        
        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        
        media = MediaIoBaseUpload(
            io.BytesIO(video_bytes),
            mimetype=mime_type,
            resumable=True
        )
        
        file = drive_api.drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        
        logger.info(f"Видео '{filename}' успешно загружено в Google Drive (ID: {file.get('id')})")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка загрузки видео '{filename}' в Google Drive: {e}")
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
        
        # Проверяем наличие git перед использованием
        try:
            subprocess.run(['git', '--version'], capture_output=True, text=True, timeout=5, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            error_msg = (
                "❌ **Git не установлен!**\n\n"
                "Для обновления через бота необходимо установить git:\n"
                "```bash\n"
                "sudo apt-get update\n"
                "sudo apt-get install git -y\n"
                "```\n\n"
                "Или обновите вручную на сервере:\n"
                "```bash\n"
                "cd /path/to/bot\n"
                "git pull\n"
                "sudo systemctl restart telegram-bot\n"
                "```"
            )
            bot.send_message(message.chat.id, error_msg, parse_mode='Markdown')
            logger.error("Git не установлен на сервере")
            return
        
        # Выполняем git pull
        result = subprocess.run(['git', 'pull'], capture_output=True, text=True, 
                              cwd=os.path.dirname(os.path.abspath(__file__)), timeout=30)
        
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
            error_output = result.stderr if result.stderr else result.stdout
            bot.send_message(message.chat.id, f"❌ Ошибка при обновлении:\n```\n{error_output}\n```", parse_mode='Markdown')
            logger.error(f"Ошибка git pull: {error_output}")
    except subprocess.TimeoutExpired:
        bot.send_message(message.chat.id, "❌ Таймаут при обновлении. Попробуйте позже или обновите вручную на сервере.")
        logger.error("Таймаут при выполнении git pull")
    except Exception as e:
        error_msg = f"❌ Ошибка: {str(e)}"
        bot.send_message(message.chat.id, error_msg)
        logger.error(f"Ошибка при обновлении: {e}", exc_info=True)

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
        
        # Шаг 1: Проверяем наличие git и выполняем git pull
        try:
            # Проверяем наличие git
            subprocess.run(['git', '--version'], capture_output=True, text=True, timeout=5, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            error_msg = (
                "❌ **Git не установлен!**\n\n"
                "Установите git на сервере:\n"
                "```bash\n"
                "sudo apt-get update && sudo apt-get install git -y\n"
                "```\n\n"
                "Или обновите вручную и перезапустите бота:\n"
                "```bash\n"
                "cd /path/to/bot\n"
                "git pull\n"
                "sudo systemctl restart telegram-bot\n"
                "```"
            )
            bot.send_message(message.chat.id, error_msg, parse_mode='Markdown')
            logger.error("Git не установлен на сервере")
            return
        
        # Выполняем git pull
        try:
            result = subprocess.run(['git', 'pull'], capture_output=True, text=True, 
                                  cwd=os.path.dirname(os.path.abspath(__file__)), timeout=30)
            
            if result.returncode != 0:
                error_output = result.stderr if result.stderr else result.stdout
                bot.send_message(message.chat.id, f"❌ Ошибка при обновлении:\n```\n{error_output}\n```", parse_mode='Markdown')
                logger.error(f"Ошибка git pull: {error_output}")
                return
        except subprocess.TimeoutExpired:
            bot.send_message(message.chat.id, "❌ Таймаут при обновлении. Попробуйте позже или обновите вручную.")
            logger.error("Таймаут при выполнении git pull")
            return
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка при обновлении: {str(e)}")
            logger.error(f"Ошибка при git pull: {e}", exc_info=True)
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

# Обработчик кликабельных кодов (должен быть ПЕРЕД handle_text!)
@bot.message_handler(func=lambda message: message.text and message.text.startswith('/') and message.text[1:].isdigit() and len(message.text) == 6)
def handle_product_code_command(message):
    """Обработка кликабельных кодов товаров вида /00005"""
    user_id = message.from_user.id
    code = message.text[1:]  # Убираем слеш
    
    logger.info(f"[HANDLER: product_code_command] User: {message.from_user.username} ({user_id}) | Text: '{message.text}' | Code: {code} | State: {user_states.get(user_id, 'None')}")
    
    # Переводим в состояние поиска кода
    user_states[user_id] = STATE_GET_CODE
    
    logger.info(f"Пользователь {message.from_user.username} кликнул на код: {code}")
    
    # Обрабатываем как обычный ввод кода
    handle_code_input_text(message, code)

@bot.message_handler(content_types=['text'])
def handle_text(message):
    """Обработка текстовых сообщений и кнопок"""
    user_id = message.from_user.id
    text = message.text
    state = user_states.get(user_id, STATE_MAIN_MENU)
    
    logger.info(f"[HANDLER: handle_text] User: {message.from_user.username} ({user_id}) | Text: '{text[:50]}...' | State: {state}")
    
    # Обработка универсальных кнопок (работают всегда)
    if text == BTN_BACK or text == BTN_CANCEL or text == "❌ Отмена":
        logger.info(f"[HANDLER: handle_text] -> Кнопка НАЗАД/ОТМЕНА")
        show_main_menu(message)
        return
    
    if text == BTN_FINISH or text == "✅ Завершить":
        finish_upload(message)
        return
    
    if text == BTN_ANOTHER_PRODUCT or text == BTN_ANOTHER_CODE or text == "🔄 Другой товар" or text == "🔄 Другой код":
        # Проверяем тип загрузки (фото или видео)
        upload_type = user_data.get(user_id, {}).get('upload_type', 'photo')
        if upload_type == 'video':
            start_video_upload_flow(message)
        else:
            start_upload_flow(message)
        return
    
    # Обработка кнопок главного меню
    if state == STATE_MAIN_MENU:
        logger.info(f"[HANDLER: handle_text] -> State: MAIN_MENU, Text: '{text}'")
        if text == BTN_UPLOAD:
            logger.info(f"[HANDLER: handle_text] -> BTN_UPLOAD")
            start_upload_flow(message)
        elif text == BTN_UPLOAD_VIDEO:
            logger.info(f"[HANDLER: handle_text] -> BTN_UPLOAD_VIDEO")
            start_video_upload_flow(message)
        elif text == BTN_STATS:
            logger.info(f"[HANDLER: handle_text] -> BTN_STATS")
            show_statistics(message)
        elif text == BTN_NO_PHOTO:
            logger.info(f"[HANDLER: handle_text] -> BTN_NO_PHOTO")
            show_no_photo_menu(message)
        elif text == BTN_MANAGE:
            logger.info(f"[HANDLER: handle_text] -> BTN_MANAGE")
            show_management(message)
        elif text == BTN_HELP:
            logger.info(f"[HANDLER: handle_text] -> BTN_HELP")
            cmd_help(message)
        else:
            # Любой другой текст - показываем подсказку
            logger.warning(f"[HANDLER: handle_text] -> UNKNOWN TEXT in MAIN_MENU: '{text}'")
            bot.send_message(
                message.chat.id, 
                "Используйте кнопки меню для навигации 👇",
                reply_markup=get_main_menu_keyboard()
            )
        return
    
    # Ввод кода модификации
    if state == STATE_GET_CODE:
        logger.info(f"[HANDLER: handle_text] -> State: GET_CODE, Text: '{text}'")
        # Проверяем тип загрузки (фото или видео)
        upload_type = user_data.get(user_id, {}).get('upload_type', 'photo')
        
        # Проверяем, не кнопка ли это из истории
        if text.startswith("🔖 "):
            code = text.replace("🔖 ", "").strip()
            logger.info(f"[HANDLER: handle_text] -> История: код {code}, тип: {upload_type}")
            if upload_type == 'video':
                handle_code_input_text_for_video(message, code)
            else:
                handle_code_input_text(message, code)
        else:
            # Обычный ввод кода
            logger.info(f"[HANDLER: handle_text] -> Ввод кода: {text}, тип: {upload_type}")
            if upload_type == 'video':
                handle_code_input_text_for_video(message, text)
            else:
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
    
    # Загрузка видео - НЕ ПРИНИМАЕМ ТЕКСТ, только видео или кнопки
    if state == STATE_GET_VIDEO:
        bot.send_message(
            message.chat.id, 
            "🎥 Отправьте ВИДЕО товара\n\nИли используйте кнопки ниже:",
            reply_markup=get_video_upload_keyboard()
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

def show_no_photo_menu(message):
    """Показать меню выбора формата выгрузки товаров без фото"""
    user_id = message.from_user.id
    user_states[user_id] = STATE_NO_PHOTO_LIST
    
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton("📄 Просмотр списка", callback_data="no_photo:view:stock"),
        types.InlineKeyboardButton("💾 Скачать CSV", callback_data="no_photo:csv:stock"),
        types.InlineKeyboardButton("🔙 Главное меню", callback_data="no_photo:back")
    )
    
    bot.send_message(
        message.chat.id,
        "📋 **ТОВАРЫ БЕЗ ФОТО**\n\n"
        "Выберите формат выгрузки:\n\n"
        "📄 **Просмотр списка** - интерактивный список с кликабельными кодами\n"
        "💾 **Скачать CSV** - файл для работы в Excel/Google Sheets",
        parse_mode='Markdown',
        reply_markup=keyboard
    )

def show_products_without_photos(message, page=0, with_stock_only=True):
    """Показать страницу товаров без фото с inline-кнопками"""
    user_id = message.from_user.id if hasattr(message, 'from_user') else message.chat.id
    chat_id = message.chat.id
    
    # Отправляем сообщение о загрузке
    loading_msg = bot.send_message(
        chat_id,
        "⏳ **Загружаю список товаров без фото...**\n\n"
        "Это может занять 30-60 секунд...",
        parse_mode='Markdown'
    )
    
    try:
        # Получаем товары без фото
        variants = get_variants_without_photos(with_stock_only=with_stock_only)
        
        # Удаляем сообщение о загрузке
        try:
            bot.delete_message(chat_id, loading_msg.message_id)
        except:
            pass
        
        if not variants:
            bot.send_message(
                chat_id,
                "✅ **Отлично!**\n\nВсе товары с остатком уже имеют фотографии! 🎉",
                reply_markup=get_main_menu_keyboard(),
                parse_mode='Markdown'
            )
            return
        
        # Сохраняем список для CSV и других действий
        if user_id not in user_data:
            user_data[user_id] = {}
        user_data[user_id]['no_photo_list'] = variants
        
        # Пагинация: 50 товаров на страницу
        per_page = 50
        total_pages = (len(variants) - 1) // per_page + 1
        start = page * per_page
        end = min(start + per_page, len(variants))
        page_variants = variants[start:end]
        
        # Формируем заголовок
        filter_text = "✅ С остатком > 0" if with_stock_only else "📦 Все товары"
        text = (
            f"📋 **ТОВАРЫ БЕЗ ФОТО** (стр. {page+1}/{total_pages})\n\n"
            f"Фильтр: {filter_text}\n"
            f"Всего: **{len(variants)} шт.**\n"
            f"На странице: {start+1}-{end}\n\n"
            f"👇 **Кликните на код для загрузки фото:**\n\n"
        )
        
        # Добавляем список товаров с кликабельными кодами-командами
        for v in page_variants:
            if v['code']:
                code = v['code']
                stock = v['stock']
                name = v['name'][:40]  # Обрезаем длинные названия
                text += f"/{code} ({stock}) {name}\n"
        
        # Создаем inline-кнопки только для навигации и действий
        keyboard = types.InlineKeyboardMarkup(row_width=4)
        
        # Навигация между страницами
        nav_buttons = []
        if page > 0:
            nav_buttons.append(types.InlineKeyboardButton(
                "⬅️ Назад", 
                callback_data=f"no_photo_page:{page-1}:{'stock' if with_stock_only else 'all'}"
            ))
        nav_buttons.append(types.InlineKeyboardButton(
            f"📄 {page+1}/{total_pages}", 
            callback_data="no_photo:noop"
        ))
        if page < total_pages - 1:
            nav_buttons.append(types.InlineKeyboardButton(
                "➡️ Вперед", 
                callback_data=f"no_photo_page:{page+1}:{'stock' if with_stock_only else 'all'}"
            ))
        keyboard.row(*nav_buttons)
        
        # Кнопки действий
        btn_csv = types.InlineKeyboardButton("💾 Скачать CSV", callback_data="no_photo:csv:current")
        btn_filter = types.InlineKeyboardButton(
            "📦 Все товары" if with_stock_only else "✅ Только с остатком",
            callback_data=f"no_photo:filter:{'all' if with_stock_only else 'stock'}"
        )
        keyboard.row(btn_csv, btn_filter)
        
        # Кнопка возврата
        keyboard.row(types.InlineKeyboardButton("🔙 Главное меню", callback_data="no_photo:back"))
        
        bot.send_message(
            chat_id,
            text,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        
        logger.info(f"Показана страница {page+1}/{total_pages} товаров без фото (пользователь {user_id})")
        
    except Exception as e:
        logger.error(f"Ошибка при показе товаров без фото: {e}", exc_info=True)
        
        # Удаляем сообщение о загрузке если есть
        try:
            bot.delete_message(chat_id, loading_msg.message_id)
        except:
            pass
        
        bot.send_message(
            chat_id,
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
    upload_type = data.get('upload_type', 'photo')
    
    if upload_type == 'video':
        bot.send_message(
            message.chat.id,
            f"✅ **Загрузка завершена!**\n\n"
            f"Товар: {variant_name}\n"
            f"Загружено видео: {uploaded_count}",
            reply_markup=get_main_menu_keyboard(),
            parse_mode='Markdown'
        )
    else:
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
    
    # Проверяем, что это не видео документ
    if message.content_type == 'document':
        if message.document.mime_type and message.document.mime_type.startswith('video/'):
            # Это видео, пропускаем обработку (будет обработано handle_video)
            return
    
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
# ОБРАБОТКА ВИДЕО
# =========================

def start_video_upload_flow(message):
    """Начать процесс загрузки видео"""
    user_id = message.from_user.id
    
    if not GOOGLE_DRIVE_AVAILABLE:
        bot.send_message(
            message.chat.id,
            "❌ **Загрузка видео недоступна**\n\n"
            "Google Drive API не настроен. Обратитесь к администратору.",
            reply_markup=get_main_menu_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    user_states[user_id] = STATE_GET_CODE
    user_data[user_id] = user_data.get(user_id, {})
    user_data[user_id]['upload_type'] = 'video'  # Помечаем что это загрузка видео
    
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

def handle_code_input_text_for_video(message, code):
    """Обработка ввода кода модификации для загрузки видео"""
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
            user_states[user_id] = STATE_GET_CODE
            user_processing[user_id] = False
            return
        
        variant_name = variant.get('name', 'Без названия')
        variant_id = variant['id']
        
        # Извлекаем цвет и размер
        color, size = extract_color_and_size(variant_name)
        
        # Получаем код родителя
        parent_code = get_parent_code_from_variant(variant)
        
        if not parent_code:
            try:
                bot.delete_message(message.chat.id, search_msg.message_id)
            except:
                pass
            
            bot.send_message(
                message.chat.id,
                f"❌ **Ошибка**\n\n"
                f"Не удалось получить код родительского товара для {variant_name}.\n"
                f"Попробуйте еще раз или обратитесь к администратору.",
                reply_markup=get_code_input_keyboard(),
                parse_mode='Markdown'
            )
            user_states[user_id] = STATE_GET_CODE
            user_processing[user_id] = False
            return
        
        # Получаем товарный остаток
        stock = None
        try:
            stock = get_variant_stock(variant_id)
        except Exception as e:
            logger.warning(f"Не удалось получить остаток для {variant_id}: {e}")
        
        # Инициализируем user_data
        if user_id not in user_data:
            user_data[user_id] = {}
        
        # Добавляем код в историю
        if 'history' not in user_data[user_id]:
            user_data[user_id]['history'] = []
        if code not in user_data[user_id]['history']:
            user_data[user_id]['history'].append(code)
            user_data[user_id]['history'] = user_data[user_id]['history'][-5:]
        
        # Сохраняем данные
        # Для видео используем код родителя (parent_code), а не код варианта
        user_data[user_id].update({
            'variant_id': variant_id,
            'variant_code': code,
            'variant_name': variant_name,
            'color': color,
            'parent_code': parent_code,  # Используем код родителя для структуры папок
            'upload_type': 'video',
            'uploaded_count': 0
        })
        user_states[user_id] = STATE_GET_VIDEO
        
        # Удаляем сообщение о поиске
        try:
            bot.delete_message(message.chat.id, search_msg.message_id)
        except:
            pass
        
        # Формируем сообщение
        color_info = f"🎨 Цвет: **{color if color else 'Без цвета'}**\n" if color else ""
        stock_info = f"📦 Товарный остаток: **{stock} шт.**\n\n" if stock is not None and stock > 0 else ""
        
        bot.send_message(
            message.chat.id,
            f"✅ **Найдено:** {variant_name}\n\n"
            f"{color_info}"
            f"{stock_info}"
            f"🎥 **Теперь отправьте видео**\n\n"
            f"Видео будет загружено в папку: `{parent_code}/{color if color else 'Без цвета'}/Видео/`\n\n"
            f"Когда закончите - нажмите **✅ Завершить**",
            reply_markup=get_video_upload_keyboard(),
            parse_mode='Markdown'
        )
        
        user_processing[user_id] = False
        logger.info(f"Пользователь {message.from_user.username} нашел товар для видео: {variant_name} (код: {code}, цвет: {color})")
        
    except Exception as e:
        logger.error(f"Ошибка при обработке кода {code} для видео: {e}", exc_info=True)
        
        try:
            bot.delete_message(message.chat.id, search_msg.message_id)
        except:
            pass
        
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
        user_states[user_id] = STATE_GET_CODE
        user_processing[user_id] = False

@bot.message_handler(content_types=['video', 'document'])
def handle_video(message):
    """Обработка видео (включая документы с видео)"""
    user_id = message.from_user.id
    state = user_states.get(user_id, STATE_MAIN_MENU)
    
    # Проверяем, что это действительно видео
    is_video = False
    if message.content_type == 'video':
        is_video = True
    elif message.content_type == 'document':
        # Проверяем MIME тип документа
        if message.document.mime_type and message.document.mime_type.startswith('video/'):
            is_video = True
    
    # Видео принимаем ТОЛЬКО в состоянии загрузки видео
    if state == STATE_GET_VIDEO and is_video:
        process_video(message)
    elif state == STATE_GET_VIDEO and not is_video:
        # Если прислан документ, но не видео
        bot.send_message(
            message.chat.id,
            "❌ Отправьте видео файл, а не документ другого типа.",
            reply_markup=get_video_upload_keyboard()
        )
    else:
        # Если пользователь прислал видео не в том состоянии
        bot.send_message(
            message.chat.id, 
            "🎥 Сначала выберите товар!\n\nНажмите кнопку ниже:",
            reply_markup=get_main_menu_keyboard()
        )

def process_video(message):
    """Обработка загруженного видео - добавление в очередь"""
    user_id = message.from_user.id
    
    data = user_data.get(user_id, {})
    
    if not data or 'variant_id' not in data or data.get('upload_type') != 'video':
        bot.send_message(
            message.chat.id, 
            "❌ Данные потеряны. Начните заново:",
            reply_markup=get_main_menu_keyboard()
        )
        user_states[user_id] = STATE_MAIN_MENU
        return
    
    # Инициализируем очередь если её нет
    if user_id not in user_video_queue:
        user_video_queue[user_id] = []
    
    # Добавляем видео в очередь
    user_video_queue[user_id].append(message)
    queue_size = len(user_video_queue[user_id])
    
    logger.info(f"Видео добавлено в очередь пользователя {user_id}. Размер очереди: {queue_size}")
    
    # Отправляем подтверждение
    bot.send_message(
        message.chat.id,
        f"📥 Видео принято! В очереди: {queue_size}",
        parse_mode='Markdown'
    )
    
    # Запускаем обработку очереди если она еще не запущена
    if not user_video_processing.get(user_id, False):
        user_video_processing[user_id] = True
        # Запускаем обработку в отдельном потоке
        thread = threading.Thread(target=process_video_queue, args=(user_id,))
        thread.daemon = True
        thread.start()

def process_video_queue(user_id):
    """Обработка очереди видео пользователя"""
    try:
        while user_id in user_video_queue and len(user_video_queue[user_id]) > 0:
            # Берем первое видео из очереди
            message = user_video_queue[user_id].pop(0)
            remaining = len(user_video_queue[user_id])
            
            data = user_data.get(user_id, {})
            if not data or 'variant_id' not in data or data.get('upload_type') != 'video':
                bot.send_message(
                    message.chat.id,
                    "❌ Данные потеряны. Начните заново:",
                    reply_markup=get_main_menu_keyboard()
                )
                user_states[user_id] = STATE_MAIN_MENU
                break
            
            variant_code = data['variant_code']
            variant_name = data['variant_name']
            color = data.get('color')
            parent_code = data.get('parent_code')
            
            if not parent_code:
                bot.send_message(
                    message.chat.id,
                    "❌ Ошибка: не найден код родителя. Начните заново:",
                    reply_markup=get_main_menu_keyboard()
                )
                user_states[user_id] = STATE_MAIN_MENU
                break
            
            try:
                # Получаем файл видео
                video_bytes = None
                filename = None
                
                if message.content_type == 'video':
                    file_id = message.video.file_id
                    file_size = getattr(message.video, 'file_size', None)
                    # Используем оригинальное имя или генерируем
                    if message.video.file_name:
                        filename = message.video.file_name
                    else:
                        filename = f"video_{variant_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                    
                    logger.info(f"Обработка видео: file_id={file_id}, size={file_size} bytes")
                    
                    # Получаем file_path через прямой запрос к Telegram API
                    file_path = None
                    try:
                        # Пробуем стандартный способ
                        file_info = bot.get_file(file_id)
                        file_path = file_info.file_path
                        logger.info(f"Получен file_path через bot.get_file: {file_path}")
                    except Exception as e:
                        error_str = str(e).lower()
                        if "too big" in error_str or "400" in error_str or "file is too big" in error_str:
                            # Для больших файлов используем локальный Bot API сервер
                            logger.info(f"bot.get_file вернул ошибку для большого файла, используем локальный Bot API сервер")
                            try:
                                # Используем локальный сервер, если настроен
                                if BOT_API_SERVER:
                                    local_api_url = f"{BOT_API_SERVER.rstrip('/')}/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}"
                                    logger.info(f"Запрос к локальному серверу: {local_api_url}")
                                    api_response = requests.get(local_api_url, timeout=10)
                                    api_response.raise_for_status()
                                    api_data = api_response.json()
                                    if api_data.get('ok') and api_data.get('result'):
                                        file_path_result = api_data['result'].get('file_path')
                                        # Локальный сервер возвращает абсолютный путь вида /var/lib/telegram-bot-api/TOKEN/path
                                        # Извлекаем относительный путь для использования в URL скачивания
                                        if file_path_result and file_path_result.startswith('/var/lib/telegram-bot-api/'):
                                            parts = file_path_result.split('/')
                                            if len(parts) > 5:
                                                file_path = '/'.join(parts[5:])  # Пропускаем /var/lib/telegram-bot-api/TOKEN/
                                            else:
                                                file_path = file_path_result
                                        else:
                                            file_path = file_path_result
                                        # Сохраняем оригинальный путь для скачивания из контейнера
                                        if user_id not in user_data:
                                            user_data[user_id] = {}
                                        user_data[user_id]['local_file_path'] = file_path_result
                                        logger.info(f"✅ Получен file_path через локальный Bot API сервер: {file_path} (из {file_path_result})")
                                    else:
                                        raise Exception(f"Локальный Bot API вернул ошибку: {api_data}")
                                else:
                                    # Стандартный API (не сработает для больших файлов)
                                    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}"
                                    api_response = requests.get(api_url, timeout=10)
                                    api_response.raise_for_status()
                                    api_data = api_response.json()
                                    if api_data.get('ok') and api_data.get('result'):
                                        file_path = api_data['result'].get('file_path')
                                        logger.info(f"Получен file_path через стандартный API: {file_path}")
                                    else:
                                        raise Exception(f"Telegram API вернул ошибку: {api_data}")
                            except Exception as api_e:
                                error_str = str(api_e).lower()
                                # Если файл слишком большой и локальный сервер не помог
                                if "400" in error_str or "bad request" in error_str or "too big" in error_str or "404" in error_str:
                                    logger.warning(f"Не удалось получить file_path для большого файла (размер: {file_size} bytes): {api_e}")
                                    size_mb = file_size // (1024*1024) if file_size else "неизвестно"
                                    bot.send_message(
                                        message.chat.id,
                                        f"❌ Ошибка: Файл слишком большой ({size_mb} МБ).\n"
                                        "Обратитесь к администратору для настройки локального Bot API сервера.",
                                        reply_markup=get_video_upload_keyboard() if remaining == 0 else None
                                    )
                                    continue
                                else:
                                    logger.error(f"Ошибка при получении file_path: {api_e}")
                                    bot.send_message(
                                        message.chat.id,
                                        f"❌ Ошибка получения информации о файле: {api_e}\n"
                                        "Попробуйте отправить видео еще раз.",
                                        reply_markup=get_video_upload_keyboard() if remaining == 0 else None
                                    )
                                    continue
                        else:
                            raise
                    
                    if not file_path:
                        raise Exception("Не удалось получить file_path")
                    
                    # Скачиваем файл (для больших файлов используем локальный сервер или прямую ссылку)
                    try:
                        video_bytes = None
                        # Проверяем, есть ли сохраненный путь от локального сервера
                        local_file_path = user_data.get(user_id, {}).get('local_file_path')
                        
                        if BOT_API_SERVER and local_file_path and file_size and file_size > 20 * 1024 * 1024:
                            # Для больших файлов с локального сервера читаем из Docker контейнера
                            logger.info(f"Чтение большого файла из Docker контейнера: {local_file_path}")
                            try:
                                # Используем docker exec для чтения файла из контейнера
                                import subprocess
                                # Используем полный путь к docker
                                docker_path = '/usr/bin/docker'
                                result = subprocess.run(
                                    [docker_path, 'exec', 'telegram-bot-api', 'cat', local_file_path],
                                    capture_output=True,
                                    timeout=300
                                )
                                if result.returncode == 0:
                                    video_bytes = result.stdout
                                    logger.info(f"✅ Файл прочитан из контейнера ({len(video_bytes)} bytes)")
                                else:
                                    error_msg = result.stderr.decode() if result.stderr else "Unknown error"
                                    raise Exception(f"Docker exec вернул код {result.returncode}: {error_msg}")
                            except FileNotFoundError:
                                logger.warning("Docker не найден по пути /usr/bin/docker, пробуем найти в PATH")
                                try:
                                    # Пробуем найти docker в PATH
                                    result = subprocess.run(
                                        ['which', 'docker'],
                                        capture_output=True,
                                        timeout=5
                                    )
                                    if result.returncode == 0:
                                        docker_path = result.stdout.decode().strip()
                                        logger.info(f"Найден docker по пути: {docker_path}")
                                        result = subprocess.run(
                                            [docker_path, 'exec', 'telegram-bot-api', 'cat', local_file_path],
                                            capture_output=True,
                                            timeout=300
                                        )
                                        if result.returncode == 0:
                                            video_bytes = result.stdout
                                            logger.info(f"✅ Файл прочитан из контейнера ({len(video_bytes)} bytes)")
                                        else:
                                            raise Exception(f"Docker exec вернул код {result.returncode}")
                                    else:
                                        raise FileNotFoundError("Docker не найден")
                                except Exception as e2:
                                    logger.error(f"Не удалось использовать docker: {e2}")
                                    raise Exception(f"Не удалось прочитать файл из контейнера: {e2}")
                        elif BOT_API_SERVER and file_size and file_size > 20 * 1024 * 1024:
                            # Для больших файлов используем локальный сервер через HTTP
                            file_url = f"{BOT_API_SERVER.rstrip('/')}/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                            logger.info(f"Скачивание большого файла через локальный сервер: {file_url}")
                            response = requests.get(file_url, stream=True, timeout=600)
                            response.raise_for_status()
                            video_bytes = response.content
                            logger.info(f"✅ Файл скачан через локальный сервер ({len(video_bytes)} bytes)")
                        elif file_size and file_size > 20 * 1024 * 1024:
                            # Если локальный сервер не настроен, используем стандартный (может не сработать)
                            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                            logger.info(f"Скачивание большого файла через стандартный API: {file_url}")
                            response = requests.get(file_url, stream=True, timeout=600)
                            response.raise_for_status()
                            video_bytes = response.content
                            logger.info(f"✅ Файл скачан через стандартный API ({len(video_bytes)} bytes)")
                        else:
                            # Для маленьких файлов пробуем стандартный способ
                            try:
                                video_bytes = bot.download_file(file_path)
                                logger.info(f"Файл скачан через bot.download_file ({len(video_bytes)} bytes)")
                            except Exception as e:
                                if "too big" in str(e).lower() or "400" in str(e):
                                    logger.info(f"bot.download_file не сработал, используем прямую ссылку")
                                    if BOT_API_SERVER:
                                        file_url = f"{BOT_API_SERVER.rstrip('/')}/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                                    else:
                                        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                                    response = requests.get(file_url, stream=True, timeout=600)
                                    response.raise_for_status()
                                    video_bytes = response.content
                                    logger.info(f"✅ Файл скачан через прямую ссылку ({len(video_bytes)} bytes)")
                                else:
                                    raise
                        
                        if not video_bytes:
                            raise Exception("Не удалось скачать файл")
                    except Exception as e:
                        logger.error(f"Ошибка скачивания файла: {e}")
                        raise
                            
                elif message.content_type == 'document':
                    file_id = message.document.file_id
                    file_size = getattr(message.document, 'file_size', None)
                    filename = message.document.file_name or f"video_{variant_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                    
                    logger.info(f"Обработка документа-видео: file_id={file_id}, size={file_size} bytes")
                    
                    # Получаем file_path через прямой запрос к Telegram API
                    file_path = None
                    try:
                        # Пробуем стандартный способ
                        file_info = bot.get_file(file_id)
                        file_path = file_info.file_path
                        logger.info(f"Получен file_path через bot.get_file: {file_path}")
                    except Exception as e:
                        error_str = str(e).lower()
                        if "too big" in error_str or "400" in error_str or "file is too big" in error_str:
                            # Для больших файлов используем локальный Bot API сервер
                            logger.info(f"bot.get_file вернул ошибку для большого файла, используем локальный Bot API сервер")
                            try:
                                # Используем локальный сервер, если настроен
                                if BOT_API_SERVER:
                                    local_api_url = f"{BOT_API_SERVER.rstrip('/')}/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}"
                                    logger.info(f"Запрос к локальному серверу: {local_api_url}")
                                    api_response = requests.get(local_api_url, timeout=10)
                                    api_response.raise_for_status()
                                    api_data = api_response.json()
                                    if api_data.get('ok') and api_data.get('result'):
                                        file_path_result = api_data['result'].get('file_path')
                                        # Локальный сервер возвращает абсолютный путь вида /var/lib/telegram-bot-api/TOKEN/path
                                        # Извлекаем относительный путь для использования в URL скачивания
                                        if file_path_result and file_path_result.startswith('/var/lib/telegram-bot-api/'):
                                            parts = file_path_result.split('/')
                                            if len(parts) > 5:
                                                file_path = '/'.join(parts[5:])  # Пропускаем /var/lib/telegram-bot-api/TOKEN/
                                            else:
                                                file_path = file_path_result
                                        else:
                                            file_path = file_path_result
                                        # Сохраняем оригинальный путь для скачивания из контейнера
                                        if user_id not in user_data:
                                            user_data[user_id] = {}
                                        user_data[user_id]['local_file_path'] = file_path_result
                                        logger.info(f"✅ Получен file_path через локальный Bot API сервер: {file_path} (из {file_path_result})")
                                    else:
                                        raise Exception(f"Локальный Bot API вернул ошибку: {api_data}")
                                else:
                                    # Стандартный API (не сработает для больших файлов)
                                    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}"
                                    api_response = requests.get(api_url, timeout=10)
                                    api_response.raise_for_status()
                                    api_data = api_response.json()
                                    if api_data.get('ok') and api_data.get('result'):
                                        file_path = api_data['result'].get('file_path')
                                        logger.info(f"Получен file_path через стандартный API: {file_path}")
                                    else:
                                        raise Exception(f"Telegram API вернул ошибку: {api_data}")
                            except Exception as api_e:
                                error_str = str(api_e).lower()
                                # Если файл слишком большой и локальный сервер не помог
                                if "400" in error_str or "bad request" in error_str or "too big" in error_str or "404" in error_str:
                                    logger.warning(f"Не удалось получить file_path для большого файла (размер: {file_size} bytes): {api_e}")
                                    size_mb = file_size // (1024*1024) if file_size else "неизвестно"
                                    bot.send_message(
                                        message.chat.id,
                                        f"❌ Ошибка: Файл слишком большой ({size_mb} МБ).\n"
                                        "Обратитесь к администратору для настройки локального Bot API сервера.",
                                        reply_markup=get_video_upload_keyboard() if remaining == 0 else None
                                    )
                                    continue
                                else:
                                    logger.error(f"Ошибка при получении file_path: {api_e}")
                                    bot.send_message(
                                        message.chat.id,
                                        f"❌ Ошибка получения информации о файле: {api_e}\n"
                                        "Попробуйте отправить видео еще раз.",
                                        reply_markup=get_video_upload_keyboard() if remaining == 0 else None
                                    )
                                    continue
                        else:
                            raise
                    
                    if not file_path:
                        raise Exception("Не удалось получить file_path")
                    
                    # Скачиваем файл (для больших файлов используем локальный сервер или прямую ссылку)
                    try:
                        video_bytes = None
                        # Проверяем, есть ли сохраненный путь от локального сервера
                        local_file_path = user_data.get(user_id, {}).get('local_file_path')
                        
                        if BOT_API_SERVER and local_file_path and file_size and file_size > 20 * 1024 * 1024:
                            # Для больших файлов с локального сервера читаем из Docker контейнера
                            logger.info(f"Чтение большого файла из Docker контейнера: {local_file_path}")
                            try:
                                # Используем docker exec для чтения файла из контейнера
                                import subprocess
                                # Используем полный путь к docker
                                docker_path = '/usr/bin/docker'
                                result = subprocess.run(
                                    [docker_path, 'exec', 'telegram-bot-api', 'cat', local_file_path],
                                    capture_output=True,
                                    timeout=300
                                )
                                if result.returncode == 0:
                                    video_bytes = result.stdout
                                    logger.info(f"✅ Файл прочитан из контейнера ({len(video_bytes)} bytes)")
                                else:
                                    error_msg = result.stderr.decode() if result.stderr else "Unknown error"
                                    raise Exception(f"Docker exec вернул код {result.returncode}: {error_msg}")
                            except FileNotFoundError:
                                logger.warning("Docker не найден по пути /usr/bin/docker, пробуем найти в PATH")
                                try:
                                    # Пробуем найти docker в PATH
                                    result = subprocess.run(
                                        ['which', 'docker'],
                                        capture_output=True,
                                        timeout=5
                                    )
                                    if result.returncode == 0:
                                        docker_path = result.stdout.decode().strip()
                                        logger.info(f"Найден docker по пути: {docker_path}")
                                        result = subprocess.run(
                                            [docker_path, 'exec', 'telegram-bot-api', 'cat', local_file_path],
                                            capture_output=True,
                                            timeout=300
                                        )
                                        if result.returncode == 0:
                                            video_bytes = result.stdout
                                            logger.info(f"✅ Файл прочитан из контейнера ({len(video_bytes)} bytes)")
                                        else:
                                            raise Exception(f"Docker exec вернул код {result.returncode}")
                                    else:
                                        raise FileNotFoundError("Docker не найден")
                                except Exception as e2:
                                    logger.error(f"Не удалось использовать docker: {e2}")
                                    raise Exception(f"Не удалось прочитать файл из контейнера: {e2}")
                        elif BOT_API_SERVER and file_size and file_size > 20 * 1024 * 1024:
                            # Для больших файлов используем локальный сервер через HTTP
                            file_url = f"{BOT_API_SERVER.rstrip('/')}/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                            logger.info(f"Скачивание большого файла через локальный сервер: {file_url}")
                            response = requests.get(file_url, stream=True, timeout=600)
                            response.raise_for_status()
                            video_bytes = response.content
                            logger.info(f"✅ Файл скачан через локальный сервер ({len(video_bytes)} bytes)")
                        elif file_size and file_size > 20 * 1024 * 1024:
                            # Если локальный сервер не настроен, используем стандартный (может не сработать)
                            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                            logger.info(f"Скачивание большого файла через стандартный API: {file_url}")
                            response = requests.get(file_url, stream=True, timeout=600)
                            response.raise_for_status()
                            video_bytes = response.content
                            logger.info(f"✅ Файл скачан через стандартный API ({len(video_bytes)} bytes)")
                        else:
                            # Для маленьких файлов пробуем стандартный способ
                            try:
                                video_bytes = bot.download_file(file_path)
                                logger.info(f"Файл скачан через bot.download_file ({len(video_bytes)} bytes)")
                            except Exception as e:
                                if "too big" in str(e).lower() or "400" in str(e):
                                    logger.info(f"bot.download_file не сработал, используем прямую ссылку")
                                    if BOT_API_SERVER:
                                        file_url = f"{BOT_API_SERVER.rstrip('/')}/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                                    else:
                                        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                                    response = requests.get(file_url, stream=True, timeout=600)
                                    response.raise_for_status()
                                    video_bytes = response.content
                                    logger.info(f"✅ Файл скачан через прямую ссылку ({len(video_bytes)} bytes)")
                                else:
                                    raise
                        
                        if not video_bytes:
                            raise Exception("Не удалось скачать файл")
                    except Exception as e:
                        logger.error(f"Ошибка скачивания файла: {e}")
                        raise
                else:
                    bot.send_message(
                        message.chat.id,
                        "❌ Неподдерживаемый тип файла. Отправьте видео.",
                        reply_markup=get_video_upload_keyboard() if remaining == 0 else None
                    )
                    continue
                
                if not video_bytes:
                    raise Exception("Не удалось скачать видео")
                
                # Показываем прогресс
                progress_msg = f"⏳ Загружаю '{filename}' в Google Drive..."
                if remaining > 0:
                    progress_msg += f"\n📋 Осталось в очереди: {remaining}"
                
                bot.send_message(message.chat.id, progress_msg)
                
                # Получаем Drive API
                drive_api = get_drive_api()
                if not drive_api:
                    bot.send_message(
                        message.chat.id,
                        "❌ Ошибка: Google Drive API недоступен. Обратитесь к администратору.",
                        reply_markup=get_video_upload_keyboard() if remaining == 0 else None
                    )
                    continue
                
                # Создаем структуру папок
                video_folder_id = ensure_video_folder_structure(parent_code, color, drive_api)
                if not video_folder_id:
                    bot.send_message(
                        message.chat.id,
                        f"❌ Ошибка создания папок в Google Drive.\n"
                        f"Проверьте логи или обратитесь к администратору.",
                        reply_markup=get_video_upload_keyboard() if remaining == 0 else None
                    )
                    continue
                
                # Загружаем в Google Drive
                success = upload_video_to_drive(video_bytes, filename, video_folder_id, drive_api)
                
                if success:
                    # Увеличиваем счетчик
                    user_data[user_id]['uploaded_count'] = user_data[user_id].get('uploaded_count', 0) + 1
                    uploaded = user_data[user_id]['uploaded_count']
                    
                    result_msg = f"✅ Видео '{filename}' загружено в Google Drive!\n\n"
                    result_msg += f"📁 Путь: `{parent_code}/{color if color else 'Без цвета'}/Видео/`\n"
                    result_msg += f"🎥 Загружено видео: {uploaded}"
                    
                    if remaining > 0:
                        result_msg += f"\n⏳ Обрабатываю следующее ({remaining} в очереди)..."
                    else:
                        result_msg += f"\n\nМожете загрузить еще или нажмите '✅ Завершить'"
                    
                    bot.send_message(
                        message.chat.id,
                        result_msg,
                        reply_markup=get_video_upload_keyboard() if remaining == 0 else None,
                        parse_mode='Markdown'
                    )
                else:
                    bot.send_message(
                        message.chat.id,
                        f"❌ Ошибка при загрузке '{filename}' в Google Drive\n"
                        f"{'⏳ Обрабатываю следующее...' if remaining > 0 else 'Попробуйте другое видео'}",
                        reply_markup=get_video_upload_keyboard() if remaining == 0 else None
                    )
                
                # Небольшая пауза между загрузками
                if remaining > 0:
                    time.sleep(0.5)
            
            except Exception as e:
                logger.error(f"Ошибка при обработке видео из очереди: {e}", exc_info=True)
                bot.send_message(
                    message.chat.id,
                    f"❌ Ошибка: {e}\n"
                    f"{'⏳ Обрабатываю следующее...' if remaining > 0 else 'Попробуйте другое видео'}",
                    reply_markup=get_video_upload_keyboard() if remaining == 0 else None
                )
        
        # Очередь обработана
        logger.info(f"Очередь видео пользователя {user_id} обработана полностью")
        
    finally:
        # Снимаем флаг обработки
        user_video_processing[user_id] = False
        # Очищаем пустую очередь
        if user_id in user_video_queue and len(user_video_queue[user_id]) == 0:
            del user_video_queue[user_id]

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
        
        # Меню товаров без фото
        elif data.startswith('no_photo:'):
            parts = data.split(':')
            action = parts[1] if len(parts) > 1 else ''
            param = parts[2] if len(parts) > 2 else ''
            
            # Создаем фейковое сообщение
            class FakeMessage:
                def __init__(self, chat_id, from_user):
                    self.chat = type('obj', (object,), {'id': chat_id})()
                    self.from_user = from_user
            
            fake_msg = FakeMessage(call.message.chat.id, call.from_user)
            
            if action == 'view':
                # Просмотр списка
                with_stock = (param == 'stock')
                bot.answer_callback_query(call.id, "Загружаю список...")
                show_products_without_photos(fake_msg, page=0, with_stock_only=with_stock)
            
            elif action == 'csv':
                # Скачать CSV
                bot.answer_callback_query(call.id, "Формирую CSV файл...")
                
                # Если param == 'current', используем сохраненный список
                variants = user_data.get(user_id, {}).get('no_photo_list', [])
                
                if not variants:
                    # Загружаем список
                    with_stock = (param == 'stock')
                    variants = get_variants_without_photos(with_stock_only=with_stock)
                    if user_id not in user_data:
                        user_data[user_id] = {}
                    user_data[user_id]['no_photo_list'] = variants
                
                if not variants:
                    bot.answer_callback_query(call.id, "✅ Нет товаров без фото!", show_alert=True)
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
            
            elif action == 'filter':
                # Изменить фильтр на текущей странице
                with_stock = (param == 'stock')
                bot.answer_callback_query(call.id, "🔄 Обновляю список...")
                show_products_without_photos(fake_msg, page=0, with_stock_only=with_stock)
            
            elif action == 'back':
                # Вернуться в главное меню
                bot.answer_callback_query(call.id)
                user_states[user_id] = STATE_MAIN_MENU
                bot.send_message(
                    call.message.chat.id,
                    "🏠 **Главное меню**\n\nВыберите действие:",
                    reply_markup=get_main_menu_keyboard(),
                    parse_mode='Markdown'
                )
            
            elif action == 'noop':
                # Ничего не делать (кнопка с номером страницы)
                bot.answer_callback_query(call.id)
        
        # Пагинация товаров без фото
        elif data.startswith('no_photo_page:'):
            parts = data.split(':')
            page = int(parts[1])
            filter_type = parts[2] if len(parts) > 2 else 'stock'
            with_stock = (filter_type == 'stock')
            
            bot.answer_callback_query(call.id, f"Страница {page+1}")
            
            # Создаем фейковое сообщение
            class FakeMessage:
                def __init__(self, chat_id, from_user):
                    self.chat = type('obj', (object,), {'id': chat_id})()
                    self.from_user = from_user
            
            fake_msg = FakeMessage(call.message.chat.id, call.from_user)
            
            # Показываем нужную страницу
            show_products_without_photos(fake_msg, page=page, with_stock_only=with_stock)
        
        # Переключение фильтра (старый callback, оставляем для совместимости)
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
            show_products_without_photos(fake_msg, page=0, with_stock_only=with_stock)
        
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
        
        # Проверяем наличие git
        try:
            subprocess.run(['git', '--version'], capture_output=True, text=True, timeout=5, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            logger.warning("⚠️ Git не установлен, пропускаю проверку обновлений")
            return
        
        # Делаем git fetch
        try:
            subprocess.run(['git', 'fetch'], capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("⏱ Таймаут при git fetch, пропускаю проверку обновлений")
            return
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при git fetch: {e}, пропускаю проверку обновлений")
            return
        
        # Проверяем есть ли новые коммиты
        try:
            result = subprocess.run(['git', 'status', '-uno'], capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("⏱ Таймаут при git status, пропускаю проверку обновлений")
            return
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при git status: {e}, пропускаю проверку обновлений")
            return
        
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
            try:
                pull_result = subprocess.run(['git', 'pull'], capture_output=True, text=True, timeout=15)
                
                if pull_result.returncode == 0:
                    logger.info(f"✅ Код обновлен успешно!")
                    logger.info("🔄 Перезапуск бота с новой версией...")
                    
                    # Перезапуск с новой версией
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                else:
                    error_output = pull_result.stderr if pull_result.stderr else pull_result.stdout
                    logger.error(f"❌ Ошибка при обновлении: {error_output}")
                    if send_notification and ADMIN_USER_ID:
                        try:
                            bot.send_message(
                                ADMIN_USER_ID,
                                f"❌ Ошибка при обновлении:\n```\n{error_output}\n```",
                                parse_mode='Markdown'
                            )
                        except:
                            pass
            except subprocess.TimeoutExpired:
                logger.warning("⏱ Таймаут при git pull, продолжаю работу...")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при git pull: {e}, продолжаю работу...")
        else:
            logger.info("✅ Бот уже использует последнюю версию")
            
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
