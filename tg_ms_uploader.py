import logging
import requests
import io
import mimetypes
import base64
import os
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

# Проверка наличия токенов
if not TELEGRAM_BOT_TOKEN or not MOYSKLAD_API_TOKEN:
    raise ValueError("Не найдены токены! Создайте файл .env с TELEGRAM_BOT_TOKEN и MOYSKLAD_API_TOKEN")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

GET_CODE, GET_PHOTOS, MENU = range(3)

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

def upload_photo_to_variant(variant_id: str, photo_bytes: bytes, original_filename: str) -> bool:
    url = f'https://api.moysklad.ru/api/remap/1.2/entity/variant/{variant_id}/images'
    headers = get_moysklad_headers()
    content_base64 = base64.b64encode(photo_bytes).decode('utf-8')
    payload = {'filename': original_filename, 'content': content_base64}
    try:
        import json
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        response.raise_for_status()
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
    success = upload_photo_to_variant(variant_id, photo_bytes, original_filename)
    image_count = get_variant_image_count(images_href)
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

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
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
    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == '__main__':
    main()
