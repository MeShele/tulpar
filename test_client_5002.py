"""Test client TE-5002 - full verification"""
import asyncio
import sys
sys.path.insert(0, '.')

from datetime import datetime
from src.services.database import db_service
from src.services.sheets import sheets_service
from src.models import Client, Parcel, ParcelStatus
from src.config import config


async def test_client_5002():
    print("=" * 60)
    print("Проверка клиента TE-5002")
    print("=" * 60)

    # Connect to DB
    if config.database_url:
        await db_service.connect()
        print("✅ PostgreSQL подключен")
    else:
        print("⚠️ PostgreSQL не настроен, использую Google Sheets")

    # Test 1: Get client by code
    print("\n--- Тест 1: Поиск клиента по коду ---")
    client = await db_service.get_client_by_code("TE-5002")

    if client:
        print(f"✅ Клиент найден:")
        print(f"   Код: {client.code}")
        print(f"   ФИО: {client.full_name}")
        print(f"   Телефон: {client.phone}")
        print(f"   Chat ID: {client.chat_id}")
        print(f"   Дата регистрации: {client.reg_date}")
    else:
        print("❌ Клиент TE-5002 не найден!")
        # Create client
        print("\n🔧 Создаю тестового клиента TE-5002...")
        client = Client(
            chat_id=857269158,
            code="TE-5002",
            full_name="Руслан Айдарбекулы",
            phone="0700123456",
            reg_date=datetime.now(),
        )
        await db_service.create_client(client)
        print(f"✅ Клиент создан: {client.code}")

    # Test 2: Check parcels
    print("\n--- Тест 2: Посылки клиента ---")
    parcels = await db_service.get_parcels_by_client_code("TE-5002")

    if parcels:
        print(f"✅ Найдено посылок: {len(parcels)}")
        for p in parcels:
            print(f"   📦 {p.tracking}: {p.status.display_name} - {p.amount_som:.0f} сом")
    else:
        print("📦 У клиента нет посылок. Создаю тестовую...")

        # Create test parcel
        parcel = Parcel(
            client_code="TE-5002",
            tracking="TEST5002ABC",
            status=ParcelStatus.CHINA_WAREHOUSE,
            weight_kg=2.5,
            amount_usd=8.75,  # $3.50 * 2.5kg
            amount_som=783.125,  # 8.75 * 89.5
            date_china=datetime.now(),
            date_bishkek=None,
            date_delivered=None,
        )
        await db_service.create_parcel(parcel)
        print(f"✅ Создана посылка: {parcel.tracking}")
        print(f"   Вес: {parcel.weight_kg} кг")
        print(f"   Сумма: ${parcel.amount_usd:.2f} ({parcel.amount_som:.0f} сом)")

    # Test 3: Test status update flow
    print("\n--- Тест 3: Изменение статуса посылки ---")
    parcels = await db_service.get_parcels_by_client_code("TE-5002")

    if parcels:
        parcel = parcels[0]
        print(f"   Текущий статус: {parcel.status.display_name}")

        # Update to next status
        next_status = {
            ParcelStatus.CHINA_WAREHOUSE: ParcelStatus.BISHKEK_ARRIVED,
            ParcelStatus.BISHKEK_ARRIVED: ParcelStatus.READY_PICKUP,
            ParcelStatus.READY_PICKUP: ParcelStatus.DELIVERED,
            ParcelStatus.DELIVERED: None,
        }

        new_status = next_status.get(parcel.status)
        if new_status:
            print(f"   Обновляю до: {new_status.display_name}")
            await db_service.update_parcel_status(
                client_code=parcel.client_code,
                tracking=parcel.tracking,
                new_status=new_status,
                date_bishkek=datetime.now() if new_status == ParcelStatus.BISHKEK_ARRIVED else None,
            )
            print(f"   ✅ Статус обновлён!")
        else:
            print("   ℹ️ Посылка уже выдана, статус не меняю")

    # Test 4: Verify phone search (for "Forgot Code")
    print("\n--- Тест 4: Поиск по телефону (Забыл код) ---")
    if client:
        phone = client.phone
        found = await db_service.get_client_by_phone(phone)
        if found:
            print(f"✅ Поиск по телефону {phone}: найден {found.code}")
        else:
            print(f"❌ Поиск по телефону {phone}: не найден")

    # Test 5: Statistics
    print("\n--- Тест 5: Статистика ---")
    stats = await db_service.get_statistics()
    print(f"   Клиентов: {stats['clients_count']}")
    print(f"   Посылок: {stats['parcels_count']}")
    print(f"   По статусам: {stats['status_counts']}")

    # Close DB
    if config.database_url:
        await db_service.close()

    print("\n" + "=" * 60)
    print("✅ Проверка клиента TE-5002 завершена!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_client_5002())
