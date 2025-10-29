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
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# Загрузка переменных окружения из .env файла
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
MOYSKLAD_API_TOKEN = os.getenv('MOYSKLAD_API_TOKEN')
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID')  # ID администратора для управления ботом

# Проверка наличия токенов
if not TELEGRAM_BOT_TOKEN or not MOYSKLAD_API_TOKEN:
    raise ValueError("Не найдены токены! Создайте файл .env с TELEGRAM_BOT_TOKEN и MOYSKLAD_API_TOKEN")

# Настройка логирования в файл и консоль
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Версия бота
BOT_VERSION = "2.0.0"
BOT_START_TIME = datetime.now()

# Настройки
BACKUP_PHOTOS = False  # Опция сохранения фото на диск

GET_CODE, GET_PHOTOS, MENU = range(3)

# ===== БАЗА ДАННЫХ =====
def init_database():
    """Инициализация базы данных для истории загрузок"""
    conn = sqlite3.connect('uploads_history.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            variant_code TEXT NOT NULL,
            variant_name TEXT NOT NULL,
            filename TEXT NOT NULL,
            success INTEGER NOT NULL
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

def save_upload_to_db(user_id: int, username: str, variant_code: str, variant_name: str, filename: str, success: bool):
    """Сохранение записи о загрузке в базу данных"""
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
        total_uploads = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(DISTINCT variant_code) FROM uploads')
        unique_products = cursor.fetchone()[0]
        conn.close()
        return total_uploads, unique_products
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        return 0, 0

# ===== СОХРАНЕНИЕ ФОТО НА ДИСК =====
def save_photo_backup(photo_bytes: bytes, filename: str, variant_code: str):
    """Сохранение резервной копии фото на диск"""
    if not BACKUP_PHOTOS:
        return
    
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        backup_dir = Path('uploaded_photos') / today / variant_code
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = backup_dir / filename
        with open(filepath, 'wb') as f:
            f.write(photo_bytes)
        logger.info(f"Фото сохранено в бэкап: {filepath}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении бэкапа фото: {e}")

# ===== ПРОВЕРКА ПРАВ АДМИНИСТРАТОРА =====
def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    if not ADMIN_USER_ID:
        return True  # Если не указан admin ID, все имеют доступ
    return str(user_id) == ADMIN_USER_ID

def get_moysklad_headers() -> dict:
    return {
        'Authorization': 'Bearer ' + MOYSKLAD_API_TOKEN,
        'Accept': 'application/json;charset=utf-8',
        'Content-Type': 'application/json;charset=utf-8'
    }

def find_variant_by_code(code: str) -> dict | None:
    url = f'https://api.moysklad.ru/api/remap/1.2/entity/variant?filter=code={code}'
    try:
        response = requests.get(url, headers=get_moysklad_headers())
        response.raise_for_status()
        data = response.json()
        if data.get('rows') and len(data['rows']) > 0:
            variant = data['rows'][0]
            images_href = variant.get('images', {}).get('meta', {}).get('href')
            return {
                'id': variant.get('id'),
                'name': variant.get('name'),
                'images_href': images_href
            }
        return None
    except Exception as e:
        logger.error(f"Ошибка при поиске модификации: {e}")
        return None

def get_variant_image_count(images_href: str | None) -> int:
    if not images_href:
        return 0
    try:
        response = requests.get(images_href, headers=get_moysklad_headers())
        response.raise_for_status()
        data = response.json()
        return data.get('meta', {}).get('size', 0)
    except Exception as e:
        logger.error(f"Ошибка при получении изображений: {e}")
        return 0

def get_variant_images(images_href: str) -> list:
    try:
        response = requests.get(images_href, headers=get_moysklad_headers())
        response.raise_for_status()
        data = response.json()
        return [img['meta']['downloadHref'] for img in data.get('rows', []) if 'meta' in img and 'downloadHref' in img['meta']]
    except Exception as e:
        logger.error(f"Ошибка при загрузке ссылок на изображения: {e}")
        return []

def upload_photo_to_variant(variant_id: str, photo_bytes: bytes, original_filename: str, variant_code: str = "") -> bool:
    url = f'https://api.moysklad.ru/api/remap/1.2/entity/variant/{variant_id}/images'
    headers = get_moysklad_headers()
    content_base64 = base64.b64encode(photo_bytes).decode('utf-8')
    payload = {'filename': original_filename, 'content': content_base64}
    try:
        import json
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        response.raise_for_status()
        
        # Сохранение бэкапа фото если включено
        save_photo_backup(photo_bytes, original_filename, variant_code)
        
        return True
    except Exception as e:
        logger.error(f"Ошибка при загрузке фото: {e}")
        return False

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Загрузить ещё фото"), KeyboardButton("Посмотреть фото")],
            [KeyboardButton("Сменить артикул"), KeyboardButton("В начало")]
        ],
        resize_keyboard=True
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Введите код модификации товара:", reply_markup=get_main_keyboard()
    )
    return GET_CODE

async def get_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip()
    if code == "В начало":
        await update.message.reply_text("Диалог сброшен.", reply_markup=get_main_keyboard())
        context.user_data.clear()
        return GET_CODE
    variant_info = find_variant_by_code(code)
    if variant_info:
        context.user_data['code'] = code
        context.user_data['variant_id'] = variant_info['id']
        context.user_data['variant_name'] = variant_info['name']
        context.user_data['images_href'] = variant_info['images_href']
        image_count = get_variant_image_count(variant_info['images_href'])
        message = f'Модификация "{variant_info["name"]}" найдена.\n'
        message += f'Изображений сейчас: {image_count}.\n\n'
        message += "Можете отправить фото, чтобы загрузить."
        await update.message.reply_text(message, reply_markup=get_main_keyboard())
        return MENU
    else:
        await update.message.reply_text("Модификация не найдена, введите корректный артикул.", reply_markup=get_main_keyboard())
        return GET_CODE

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    variant_id = context.user_data.get('variant_id')
    code = context.user_data.get('code')
    variant_name = context.user_data.get('variant_name')
    images_href = context.user_data.get('images_href')
    
    if not variant_id:
        await update.message.reply_text("Сначала введите артикул!", reply_markup=get_main_keyboard())
        return GET_CODE
    
    file_to_download, original_filename = None, None
    if update.message.photo:
        photo_info = update.message.photo[-1]
        file_to_download = await photo_info.get_file()
        file_ext = '.jpg'
        if file_to_download.file_path and '.' in file_to_download.file_path:
            file_ext = '.' + file_to_download.file_path.split('.')[-1]
        original_filename = f"photo_{file_to_download.file_unique_id}{file_ext}"
    elif update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith('image/'):
        doc_info = update.message.document
        file_to_download = await doc_info.get_file()
        original_filename = doc_info.file_name if doc_info.file_name else f"file_{file_to_download.file_unique_id}"
    
    if not file_to_download:
        await update.message.reply_text("Не удалось получить файл изображения.", reply_markup=get_main_keyboard())
        return MENU
    
    photo_stream = io.BytesIO()
    await file_to_download.download_to_memory(photo_stream)
    photo_bytes = photo_stream.getvalue()
    
    success = upload_photo_to_variant(variant_id, photo_bytes, original_filename, code)
    image_count = get_variant_image_count(images_href)
    
    # Сохранение в БД
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    save_upload_to_db(user_id, username, code, variant_name, original_filename, success)
    
    if success:
        await update.message.reply_text(
            f'Фото "{original_filename}" успешно загружено!\nСейчас у товара изображений: {image_count}',
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            f'Ошибка загрузки фото "{original_filename}". Попробуйте ещё раз.',
            reply_markup=get_main_keyboard()
        )
    return MENU

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    variant_id = context.user_data.get('variant_id')
    code = context.user_data.get('code')
    images_href = context.user_data.get('images_href')
    if text == "загрузить ещё фото":
        await update.message.reply_text("Пришлите файл или фото.", reply_markup=get_main_keyboard())
        return MENU
    elif text == "посмотреть фото":
        if images_href:
            img_urls = get_variant_images(images_href)
            if img_urls:
                for url in img_urls:
                    await update.message.reply_photo(photo=url, reply_markup=get_main_keyboard())
            else:
                await update.message.reply_text("У товара нет фото.", reply_markup=get_main_keyboard())
        else:
            await update.message.reply_text("Сначала выберите модификацию по артикулу.", reply_markup=get_main_keyboard())
        return MENU
    elif text == "сменить артикул":
        await update.message.reply_text("Введите новый артикул.", reply_markup=get_main_keyboard())
        context.user_data.clear()
        return GET_CODE
    elif text == "в начало":
        await update.message.reply_text("Диалог сброшен.", reply_markup=get_main_keyboard())
        context.user_data.clear()
        return GET_CODE
    else:
        await update.message.reply_text("Выберите действие через кнопки ниже.", reply_markup=get_main_keyboard())
        return MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Действие отменено.', reply_markup=get_main_keyboard())
    context.user_data.clear()
    return ConversationHandler.END

# ===== АДМИН КОМАНДЫ =====

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status - показывает статус бота"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    
    uptime = datetime.now() - BOT_START_TIME
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    total_uploads, unique_products = get_upload_stats()
    
    status_msg = f"""
🤖 Статус бота

📌 Версия: {BOT_VERSION}
⏰ Работает: {hours}ч {minutes}м {seconds}с
📊 Загружено фото: {total_uploads}
📦 Уникальных товаров: {unique_products}
💾 Бэкап фото: {'Включен' if BACKUP_PHOTOS else 'Выключен'}

Все системы в норме! ✅
"""
    await update.message.reply_text(status_msg)

async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /logs - показывает последние логи"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    
    try:
        with open('bot.log', 'r', encoding='utf-8') as f:
            lines = f.readlines()
            last_lines = lines[-50:]  # Последние 50 строк
            log_text = ''.join(last_lines)
            
        if len(log_text) > 4000:
            log_text = log_text[-4000:]
            
        await update.message.reply_text(f"📋 Последние логи:\n\n<code>{log_text}</code>", parse_mode='HTML')
    except FileNotFoundError:
        await update.message.reply_text("Файл логов не найден.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка при чтении логов: {e}")

async def cmd_backup_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /backup_on - включает сохранение фото на диск"""
    global BACKUP_PHOTOS
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    
    BACKUP_PHOTOS = True
    logger.info(f"Бэкап фото включен пользователем {update.effective_user.id}")
    await update.message.reply_text("✅ Бэкап фото ВКЛЮЧЕН. Все загружаемые фото будут сохраняться в папку uploaded_photos/")

async def cmd_backup_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /backup_off - выключает сохранение фото на диск"""
    global BACKUP_PHOTOS
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    
    BACKUP_PHOTOS = False
    logger.info(f"Бэкап фото выключен пользователем {update.effective_user.id}")
    await update.message.reply_text("⛔ Бэкап фото ВЫКЛЮЧЕН. Фото не будут сохраняться на диск.")

async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /update - обновляет код из GitHub и перезапускает бота"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    
    await update.message.reply_text("🔄 Обновление кода из GitHub...")
    logger.info(f"Обновление инициировано пользователем {update.effective_user.id}")
    
    try:
        # Выполнение git pull
        result = subprocess.run(['git', 'pull'], capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            await update.message.reply_text(f"✅ Код обновлен!\n\n{result.stdout}\n\nПерезапуск бота...")
            logger.info("Git pull успешен, перезапуск...")
            
            # Перезапуск бота
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            await update.message.reply_text(f"❌ Ошибка обновления:\n{result.stderr}")
            logger.error(f"Git pull ошибка: {result.stderr}")
    except subprocess.TimeoutExpired:
        await update.message.reply_text("❌ Превышено время ожидания обновления")
    except FileNotFoundError:
        await update.message.reply_text("❌ Git не установлен на сервере")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        logger.error(f"Ошибка при обновлении: {e}")

async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /restart - перезапускает бота"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    
    await update.message.reply_text("🔄 Перезапуск бота...")
    logger.info(f"Перезапуск инициирован пользователем {update.effective_user.id}")
    
    # Перезапуск бота
    os.execv(sys.executable, [sys.executable] + sys.argv)

async def cmd_help_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin - показывает список админ-команд"""
    if not is_admin(update.effective_user.id):
        return
    
    help_text = """
🔧 Админ-команды:

/status - Статус бота и статистика
/logs - Последние 50 строк логов
/backup_on - Включить сохранение фото на диск
/backup_off - Выключить сохранение фото
/update - Обновить код из GitHub и перезапустить
/restart - Перезапустить бота
/admin - Эта справка

🎯 Основные команды:
/start - Начать работу с ботом
/cancel - Отменить текущую операцию
"""
    await update.message.reply_text(help_text)

def main() -> None:
    # Инициализация базы данных
    init_database()
    logger.info(f"Запуск бота версии {BOT_VERSION}")
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Основной conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GET_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_code)],
            GET_PHOTOS: [MessageHandler(filters.PHOTO | (filters.Document.IMAGE), photo_handler)],
            MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler),
                MessageHandler(filters.PHOTO | (filters.Document.IMAGE), photo_handler),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )
    
    # Добавление handlers
    application.add_handler(conv_handler)
    
    # Админ-команды
    application.add_handler(CommandHandler('status', cmd_status))
    application.add_handler(CommandHandler('logs', cmd_logs))
    application.add_handler(CommandHandler('backup_on', cmd_backup_on))
    application.add_handler(CommandHandler('backup_off', cmd_backup_off))
    application.add_handler(CommandHandler('update', cmd_update))
    application.add_handler(CommandHandler('restart', cmd_restart))
    application.add_handler(CommandHandler('admin', cmd_help_admin))
    
    logger.info("Бот запущен и готов к работе!")
    application.run_polling()

if __name__ == '__main__':
    main()
