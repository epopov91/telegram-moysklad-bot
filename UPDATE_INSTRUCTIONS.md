# Инструкция по обновлению бота на VPS

## Быстрое обновление (если git установлен)

Выполните на сервере:

```bash
cd /opt/moysklad-bot
git pull
pip3 install -r requirements.txt
sudo systemctl restart moysklad-bot
```

Или используйте скрипт:

```bash
cd /opt/moysklad-bot
chmod +x update_bot.sh
./update_bot.sh
```

## Если git не установлен

1. Установите git:
```bash
sudo apt-get update
sudo apt-get install git -y
```

2. Затем выполните обновление (см. выше)

## Проверка после обновления

1. Отправьте `/start` в боте
2. Должна появиться кнопка "🎥 Загрузить видео"
3. Версия бота должна быть 5.8.0

## Если обновление через /update не работает

Используйте команду `/shell` в боте для выполнения команд на сервере:

```
/shell cd /opt/moysklad-bot && git pull && pip3 install -r requirements.txt && sudo systemctl restart moysklad-bot
```

