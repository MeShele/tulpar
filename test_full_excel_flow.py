"""
Full test of Excel upload flow with notifications
Simulates owner uploading Excel file to bot
"""
import asyncio
import sys
sys.path.insert(0, '.')

from datetime import datetime
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.services.database import db_service
from src.services.excel_parser import parse_excel
from src.services.notifications import send_parcel_notification
from src.models import Parcel, ParcelStatus
from src.config import config


# Rate constants
USD_PER_KG = 3.50


async def test_full_flow(excel_path: str, file_type: str = "bishkek"):
    """
    Test full Excel processing flow:
    1. Parse Excel
    2. Match clients
    3. Create parcels
    4. Send notifications
    """
    print("=" * 60)
    print(f"ТЕСТ: Полный цикл обработки Excel")
    print(f"Файл: {excel_path}")
    print(f"Тип: {file_type}")
    print("=" * 60)

    # Connect to DB
    await db_service.connect()
    print("✅ PostgreSQL подключен")

    # Get USD rate
    usd_rate = await db_service.get_usd_rate()
    print(f"💱 Курс: {usd_rate} сом/$")

    # Initialize bot
    bot = Bot(
        token=config.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Parse Excel
    print("\n📁 Парсинг Excel...")
    with open(excel_path, 'rb') as f:
        result = parse_excel(f, excel_path.split('/')[-1])

    print(f"   Тип файла: {result.file_type}")
    print(f"   Всего строк: {len(result.rows)}")
    print(f"   Валидных: {len(result.valid_rows)}")
    if result.errors:
        print(f"   Ошибки: {result.errors}")

    # Process each row
    print("\n📦 Обработка посылок...")

    clients_notified = []
    not_found = []
    notifications_sent = 0
    notifications_failed = 0

    for row in result.valid_rows:
        # Find client
        client = await db_service.get_client_by_code(row.client_code)

        if not client:
            not_found.append(row.client_code)
            continue

        # Calculate payment
        weight = row.weight_kg or 0
        amount_usd = weight * USD_PER_KG
        amount_som = amount_usd * usd_rate

        # Determine status based on file type
        if file_type == "china" or result.file_type == "china":
            status = ParcelStatus.CHINA_WAREHOUSE
            status_msg = "📦 Посылка на складе в Китае"
        else:
            status = ParcelStatus.BISHKEK_ARRIVED
            status_msg = "✅ Посылка прибыла в Бишкек!"

        # Create parcel
        parcel = Parcel(
            client_code=client.code,
            tracking=row.tracking or f"AUTO-{datetime.now().strftime('%H%M%S')}",
            status=status,
            weight_kg=weight,
            amount_usd=amount_usd,
            amount_som=amount_som,
            date_china=datetime.now() if status == ParcelStatus.CHINA_WAREHOUSE else None,
            date_bishkek=datetime.now() if status == ParcelStatus.BISHKEK_ARRIVED else None,
            date_delivered=None,
        )

        # Check if parcel exists
        existing = await db_service.get_parcel_by_tracking(parcel.tracking)
        if existing:
            # Update status
            await db_service.update_parcel_status(
                client_code=client.code,
                tracking=parcel.tracking,
                new_status=status,
                weight_kg=weight,
                amount_usd=amount_usd,
                amount_som=amount_som,
            )
            print(f"   📦 Обновлена: {parcel.tracking} -> {client.code}")
        else:
            # Create new
            await db_service.create_parcel(parcel)
            print(f"   📦 Создана: {parcel.tracking} -> {client.code}")

        # Send notification
        success = await send_parcel_notification(
            bot=bot,
            client=client,
            status_message=status_msg,
            tracking=parcel.tracking,
            amount=amount_som if status == ParcelStatus.BISHKEK_ARRIVED else None,
        )

        if success:
            notifications_sent += 1
            if client.code not in [c[0] for c in clients_notified]:
                clients_notified.append((client.code, client.full_name, client.chat_id))
            print(f"   📤 Уведомление отправлено: {client.full_name}")
        else:
            notifications_failed += 1
            print(f"   ❌ Ошибка отправки: {client.code}")

    # Report
    print("\n" + "=" * 60)
    print("📊 ОТЧЁТ")
    print("=" * 60)
    print(f"✅ Обработано строк: {len(result.valid_rows)}")
    print(f"✅ Уведомлений отправлено: {notifications_sent}")
    if notifications_failed:
        print(f"❌ Ошибок отправки: {notifications_failed}")

    print(f"\n👥 Уведомлённые клиенты ({len(clients_notified)}):")
    for code, name, chat_id in clients_notified:
        print(f"   ✅ {code}: {name}")

    if not_found:
        unique_not_found = list(set(not_found))
        print(f"\n⚠️ Не найдено клиентов: {len(unique_not_found)}")
        print(f"   Коды: {unique_not_found[:5]}{'...' if len(unique_not_found) > 5 else ''}")

    # Close connections
    await bot.session.close()
    await db_service.close()

    print("\n" + "=" * 60)
    print("✅ ТЕСТ ЗАВЕРШЁН!")
    print("=" * 60)


if __name__ == "__main__":
    # Test with our sample file
    asyncio.run(test_full_flow(
        '/Users/mac/Desktop/tulpar/samples/test-real-format.xlsx',
        'bishkek'
    ))
