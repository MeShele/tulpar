"""
Send test notification to client TE-5002 (Ruslan)
Run this to verify notifications are working
"""
import asyncio
import sys
sys.path.insert(0, '.')

from datetime import datetime
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.services.database import db_service
from src.services.notifications import send_parcel_notification
from src.models import Parcel, ParcelStatus
from src.config import config


async def send_test_notification():
    print("=" * 60)
    print("Отправка тестового уведомления клиенту TE-5002")
    print("=" * 60)

    # Connect to DB
    if config.database_url:
        await db_service.connect()
        print("✅ PostgreSQL подключен")

    # Get client TE-5002
    client = await db_service.get_client_by_code("TE-5002")
    if not client:
        print("❌ Клиент TE-5002 не найден!")
        return

    print(f"\n📋 Клиент: {client.full_name}")
    print(f"   Chat ID: {client.chat_id}")
    print(f"   Телефон: {client.phone}")

    # Initialize bot
    bot = Bot(
        token=config.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Get current rate for calculation
    usd_rate = await db_service.get_usd_rate()
    print(f"\n💱 Курс: {usd_rate} сом/$")

    # Create test parcels
    test_parcels = [
        ("RUSLAN001TEST", 3.2),  # tracking, weight_kg
        ("RUSLAN002TEST", 1.8),
    ]

    USD_PER_KG = 3.50

    print("\n📦 Создаю посылки и отправляю уведомления...")

    for tracking, weight in test_parcels:
        amount_usd = weight * USD_PER_KG
        amount_som = amount_usd * usd_rate

        # Check if parcel exists
        existing = await db_service.get_parcel_by_tracking(tracking)

        if existing:
            # Update existing parcel
            await db_service.update_parcel_status(
                client_code="TE-5002",
                tracking=tracking,
                new_status=ParcelStatus.BISHKEK_ARRIVED,
                weight_kg=weight,
                amount_usd=amount_usd,
                amount_som=amount_som,
                date_bishkek=datetime.now(),
            )
            print(f"   📦 Обновлена: {tracking}")
        else:
            # Create new parcel
            parcel = Parcel(
                client_code="TE-5002",
                tracking=tracking,
                status=ParcelStatus.BISHKEK_ARRIVED,
                weight_kg=weight,
                amount_usd=amount_usd,
                amount_som=amount_som,
                date_china=None,
                date_bishkek=datetime.now(),
                date_delivered=None,
            )
            await db_service.create_parcel(parcel)
            print(f"   📦 Создана: {tracking}")

        # Send notification
        print(f"\n   📤 Отправляю уведомление для {tracking}...")

        success = await send_parcel_notification(
            bot=bot,
            client=client,
            status_message="✅ Посылка прибыла в Бишкек!",
            tracking=tracking,
            amount=amount_som,
        )

        if success:
            print(f"   ✅ Уведомление отправлено!")
            print(f"      Вес: {weight} кг")
            print(f"      Сумма: ${amount_usd:.2f} = {amount_som:.0f} сом")
        else:
            print(f"   ❌ Ошибка отправки!")

    # Close connections
    await bot.session.close()
    await db_service.close()

    print("\n" + "=" * 60)
    print("✅ Готово! Проверьте Telegram у Руслана (chat_id: 857269158)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(send_test_notification())
