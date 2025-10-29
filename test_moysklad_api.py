#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки API МойСклад
Запустите: python3 test_moysklad_api.py
"""

import requests
import os
from dotenv import load_dotenv

# Загружаем токены
load_dotenv()
MOYSKLAD_API_TOKEN = os.getenv('MOYSKLAD_API_TOKEN')

if not MOYSKLAD_API_TOKEN:
    print("❌ ОШИБКА: Не найден MOYSKLAD_API_TOKEN в .env файле")
    exit(1)

print("✅ Токен загружен")
print("=" * 80)

# Заголовки для всех запросов
headers = {
    'Authorization': f'Bearer {MOYSKLAD_API_TOKEN}',
    'Accept-Encoding': 'gzip'
}

# ТЕСТ 1: Получение общего количества модификаций
print("\n📦 ТЕСТ 1: Получение общего количества модификаций")
print("-" * 80)

url_variants = "https://api.moysklad.ru/api/remap/1.2/entity/variant"
response = requests.get(f"{url_variants}?limit=1", headers=headers, timeout=10)

if response.status_code == 200:
    data = response.json()
    total = data['meta']['size']
    print(f"✅ Всего модификаций: {total}")
    
    # Показываем первую модификацию для примера
    if data.get('rows'):
        variant = data['rows'][0]
        print(f"\n📋 Пример модификации:")
        print(f"   Название: {variant.get('name', 'N/A')}")
        print(f"   Код: {variant.get('code', 'N/A')}")
        print(f"   ID: {variant.get('id', 'N/A')}")
        print(f"   Stock (прямой): {variant.get('stock', 'N/A')}")
else:
    print(f"❌ Ошибка: {response.status_code}")
    print(f"   {response.text}")

# ТЕСТ 2: Получение модификации с expand=stock
print("\n📊 ТЕСТ 2: Получение модификации с expand=stock")
print("-" * 80)

response = requests.get(f"{url_variants}?limit=1&expand=stock", headers=headers, timeout=10)

if response.status_code == 200:
    data = response.json()
    if data.get('rows'):
        variant = data['rows'][0]
        print(f"✅ Модификация с expand=stock:")
        print(f"   Название: {variant.get('name', 'N/A')}")
        print(f"   Код: {variant.get('code', 'N/A')}")
        print(f"   Stock: {variant.get('stock', 'N/A')}")
        print(f"   Quantity: {variant.get('quantity', 'N/A')}")
        
        # Показываем всю структуру stock если есть
        if 'stock' in variant:
            print(f"\n   🔍 Структура поля 'stock':")
            print(f"   {variant['stock']}")
else:
    print(f"❌ Ошибка: {response.status_code}")

# ТЕСТ 3: Отчет по остаткам (stock report)
print("\n📈 ТЕСТ 3: Отчет по остаткам товаров")
print("-" * 80)

url_stock = "https://api.moysklad.ru/api/remap/1.2/report/stock/all"
response = requests.get(f"{url_stock}?limit=5", headers=headers, timeout=10)

if response.status_code == 200:
    data = response.json()
    print(f"✅ Отчет по остаткам (первые 5 позиций):")
    
    for idx, row in enumerate(data.get('rows', []), 1):
        print(f"\n   {idx}. {row.get('name', 'N/A')}")
        print(f"      Код: {row.get('code', 'N/A')}")
        print(f"      Остаток (stock): {row.get('stock', 'N/A')}")
        print(f"      Количество (quantity): {row.get('quantity', 'N/A')}")
        print(f"      Резерв (reserve): {row.get('reserve', 'N/A')}")
        print(f"      В пути (inTransit): {row.get('inTransit', 'N/A')}")
else:
    print(f"❌ Ошибка: {response.status_code}")
    print(f"   {response.text}")

# ТЕСТ 4: Поиск конкретного товара по коду (00042)
print("\n🔍 ТЕСТ 4: Поиск товара с кодом 00042")
print("-" * 80)

test_code = "00042"
response = requests.get(
    f"{url_variants}?filter=code={test_code}", 
    headers=headers, 
    timeout=10
)

if response.status_code == 200:
    data = response.json()
    if data.get('rows'):
        variant = data['rows'][0]
        print(f"✅ Найден товар:")
        print(f"   Название: {variant.get('name', 'N/A')}")
        print(f"   Код: {variant.get('code', 'N/A')}")
        print(f"   ID: {variant.get('id', 'N/A')}")
        print(f"   Stock: {variant.get('stock', 'N/A')}")
        
        # Получаем фото
        variant_id = variant['id']
        url_images = f"https://api.moysklad.ru/api/remap/1.2/entity/variant/{variant_id}/images"
        img_response = requests.get(url_images, headers=headers, timeout=10)
        
        if img_response.status_code == 200:
            images = img_response.json().get('rows', [])
            print(f"   📸 Фото: {len(images)} шт")
        else:
            print(f"   📸 Фото: ошибка получения")
    else:
        print(f"❌ Товар с кодом {test_code} не найден")
else:
    print(f"❌ Ошибка поиска: {response.status_code}")
    print(f"   {response.text}")

# ТЕСТ 5: Подсчет модификаций с остатком (правильный способ)
print("\n🎯 ТЕСТ 5: Подсчет модификаций с положительным остатком")
print("-" * 80)

print("Метод 1: Через отчет stock/all с фильтром stockMode=positiveOnly")
response = requests.get(
    "https://api.moysklad.ru/api/remap/1.2/report/stock/all?limit=0&stockMode=positiveOnly",
    headers=headers,
    timeout=30
)

if response.status_code == 200:
    total_positive = response.json()['meta']['size']
    print(f"✅ Позиций с остатком > 0: {total_positive}")
else:
    print(f"❌ Ошибка: {response.status_code}")

print("\nМетод 2: Ручной подсчет (первые 100 модификаций)")
response = requests.get(
    f"{url_variants}?limit=100&expand=stock",
    headers=headers,
    timeout=30
)

if response.status_code == 200:
    variants = response.json().get('rows', [])
    count_with_stock = 0
    
    for variant in variants:
        stock = variant.get('stock', 0)
        if stock and stock > 0:
            count_with_stock += 1
    
    print(f"✅ Из первых 100 модификаций с остатком > 0: {count_with_stock}")
else:
    print(f"❌ Ошибка: {response.status_code}")

print("\n" + "=" * 80)
print("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
print("=" * 80)

