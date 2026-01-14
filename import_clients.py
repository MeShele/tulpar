#!/usr/bin/env python3
"""
Tulpar Express - Import clients from Excel file
Импорт клиентов из файла коды S-700-799.xlsx в Google Sheets
"""

import asyncio
from datetime import datetime

import pandas as pd

from src.services.sheets import sheets_service
from src.models import Client


async def import_clients():
    """Import clients from Excel file to Google Sheets"""

    # Читаем файл
    print("📖 Читаю файл 'коды S-700-799.xlsx'...")
    df = pd.read_excel('коды S-700-799.xlsx', header=None)

    # Данные начинаются со строки 3 (после заголовков)
    data = df.iloc[3:].copy()
    data.columns = ['date', 'code', 'full_name', 'phone', 'price']

    # Парсим клиентов
    clients_to_import = []
    for _, row in data.iterrows():
        code = str(row['code']).strip() if pd.notna(row['code']) else ''
        full_name = str(row['full_name']).strip() if pd.notna(row['full_name']) else ''
        phone = str(row['phone']).strip() if pd.notna(row['phone']) else ''

        # Пропускаем пустые и невалидные
        if code and full_name and (code.startswith('М-') or code.startswith('M-')):
            # Нормализуем телефон (убираем .0 от float и пробелы)
            phone = phone.replace('.0', '').replace(' ', '')
            if phone == 'nan':
                phone = ''

            clients_to_import.append({
                'code': code,
                'full_name': full_name,
                'phone': phone
            })

    print(f"📊 Найдено {len(clients_to_import)} клиентов для импорта\n")

    # Получаем существующих клиентов для проверки дубликатов
    print("🔍 Проверяю существующих клиентов...")
    existing_clients = await sheets_service.get_all_clients()
    existing_codes = {c.code for c in existing_clients}
    existing_phones = {c.phone for c in existing_clients if c.phone}

    print(f"   В системе уже {len(existing_clients)} клиентов\n")

    # Импортируем
    imported = 0
    skipped_code = 0
    skipped_phone = 0

    for client_data in clients_to_import:
        code = client_data['code']
        phone = client_data['phone']

        # Проверяем дубликат по коду
        if code in existing_codes:
            print(f"   ⏭️ Пропуск {code} - код уже существует")
            skipped_code += 1
            continue

        # Проверяем дубликат по телефону
        if phone and phone in existing_phones:
            print(f"   ⏭️ Пропуск {code} - телефон {phone} уже зарегистрирован")
            skipped_phone += 1
            continue

        # Создаём клиента
        client = Client(
            chat_id=0,  # Привяжется когда клиент напишет боту
            code=code,
            full_name=client_data['full_name'],
            phone=phone,
            reg_date=datetime.now()
        )

        try:
            await sheets_service.create_client(client)
            print(f"   ✅ Импортирован: {code} - {client.full_name}")
            imported += 1
            existing_codes.add(code)
            if phone:
                existing_phones.add(phone)
        except Exception as e:
            print(f"   ❌ Ошибка {code}: {e}")

    print(f"\n📈 Результат:")
    print(f"   ✅ Импортировано: {imported}")
    print(f"   ⏭️ Пропущено (код существует): {skipped_code}")
    print(f"   ⏭️ Пропущено (телефон существует): {skipped_phone}")


if __name__ == "__main__":
    asyncio.run(import_clients())
