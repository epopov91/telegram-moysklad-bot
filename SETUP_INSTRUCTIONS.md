# 🚀 Инструкция по первоначальной настройке бота

## Шаг 1: Установка Python и Git на Windows

### Python
1. Скачайте с https://www.python.org/downloads/
2. При установке **ОБЯЗАТЕЛЬНО** поставьте галочку **"Add Python to PATH"**
3. Проверьте: откройте командную строку и введите `python --version`

### Git
1. Скачайте с https://git-scm.com/download/win
2. Установите с настройками по умолчанию
3. Проверьте: `git --version`

---

## Шаг 2: Клонирование репозитория на Windows

Откройте командную строку и выполните:

```cmd
cd C:\Users\ВашеИмя\Documents
git clone https://github.com/epopov91/telegram-moysklad-bot.git
cd telegram-moysklad-bot
```

---

## Шаг 3: Узнайте свой Telegram User ID

Это нужно для админ-команд бота.

**Вариант 1:** Напишите боту [@userinfobot](https://t.me/userinfobot) в Telegram
- Он сразу пришлёт ваш ID (например: `123456789`)

**Вариант 2:** Напишите боту [@getmyid_bot](https://t.me/getmyid_bot)

**Скопируйте этот ID** - он понадобится дальше!

---

## Шаг 4: Создание .env файла

В папке с ботом создайте файл `.env`:

```cmd
copy .env.example .env
notepad .env
```

Вставьте в него ваши данные:

```
TELEGRAM_BOT_TOKEN=8212058302:AAEohwQCCs4cHpC0iKhGnzXRySxkNRv9fD0
MOYSKLAD_API_TOKEN=e3d32366294b1b786b2e96989fd57bdedcf4e2a5
ADMIN_USER_ID=ваш_telegram_user_id
```

**Замените `ваш_telegram_user_id`** на ID, который узнали в Шаге 3!

Сохраните файл (Ctrl+S) и закройте.

---

## Шаг 5: Установка зависимостей

```cmd
pip install -r requirements.txt
```

---

## Шаг 6: Запуск бота! 🎉

```cmd
python tg_ms_uploader.py
```

Вы должны увидеть:
```
2025-10-29 ... - INFO - База данных инициализирована
2025-10-29 ... - INFO - Запуск бота версии 2.0.0
2025-10-29 ... - INFO - Бот запущен и готов к работе!
```

**Бот работает!** ✅

---

## Шаг 7: Проверка админ-команд

Откройте Telegram и напишите вашему боту:

```
/admin
```

Вы должны увидеть список доступных команд:
- `/status` - Статус и статистика
- `/logs` - Последние логи
- `/backup_on/off` - Управление бэкапом фото
- `/update` - Обновление из GitHub
- `/restart` - Перезапуск

**Попробуйте:**
```
/status
```

Должна показаться информация о боте!

---

## 🎯 Вы всё сделали! Что дальше?

### На Mac (редактирование кода):
```bash
# Внесите изменения в Cursor
git add .
git commit -m "Описание изменений"
git push
```

### В Telegram (обновление бота на Windows):
Просто напишите боту:
```
/update
```

Бот сам:
1. Скачает новый код из GitHub
2. Перезапустится
3. Начнёт работать с новым кодом

---

## 🔧 Автозапуск при включении Windows (опционально)

### Способ 1: Через планировщик задач

1. Win+R → `taskschd.msc` → Enter
2. Создать простую задачу
3. Имя: "Telegram Bot"
4. Триггер: При входе в систему
5. Действие: Запустить программу
6. Программа: `C:\Users\ВашеИмя\Documents\telegram-moysklad-bot\start_bot.bat`

### Способ 2: Создать start_bot.bat

Создайте файл `start_bot.bat` в папке с ботом:

```batch
@echo off
cd /d "%~dp0"
python tg_ms_uploader.py
pause
```

Перетащите ярлык этого файла в:
- Win+R → `shell:startup`

---

## ❓ Частые вопросы

**Q: Бот не отвечает на /status**  
A: Проверьте, что вы указали правильный ADMIN_USER_ID в .env

**Q: /update не работает**  
A: Убедитесь, что Git установлен: `git --version`

**Q: Где хранятся фото?**  
A: Если включен бэкап (/backup_on), то в папке `uploaded_photos/дата/артикул/`

**Q: Как посмотреть логи?**  
A: Напишите боту `/logs` или откройте файл `bot.log`

---

**Готово! Теперь бот работает на Windows 24/7, а вы управляете им из Telegram!** 🚀

