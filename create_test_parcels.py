"""Create 2 test parcels for TE-5002 with 10 som payment"""
import asyncio
import sys
sys.path.insert(0, '.')

from datetime import datetime
from src.services.database import db_service
from src.models import Parcel, ParcelStatus
from src.config import config


async def create_parcels():
    # Connect to DB
    if config.database_url:
        await db_service.connect()
        print("✅ PostgreSQL подключен")
    else:
        print("❌ PostgreSQL не настроен")
        return

    # Create 2 test parcels for TE-5002
    parcels = [
        Parcel(
            client_code="TE-5002",
            tracking="CN2025011501",
            status=ParcelStatus.READY_PICKUP,  # Готово к выдаче - показывает кнопку оплаты
            weight_kg=0.5,
            amount_usd=0.11,
            amount_som=10.0,  # 10 сом
            date_china=datetime(2025, 1, 10),
            date_bishkek=datetime(2025, 1, 15),
            date_delivered=None,
        ),
        Parcel(
            client_code="TE-5002",
            tracking="CN2025011502",
            status=ParcelStatus.READY_PICKUP,  # Готово к выдаче - показывает кнопку оплаты
            weight_kg=0.5,
            amount_usd=0.11,
            amount_som=10.0,  # 10 сом
            date_china=datetime(2025, 1, 10),
            date_bishkek=datetime(2025, 1, 15),
            date_delivered=None,
        ),
    ]

    for parcel in parcels:
        try:
            await db_service.create_parcel(parcel)
            print(f"✅ Создана посылка: {parcel.tracking}")
            print(f"   Статус: {parcel.status.display_name}")
            print(f"   Сумма: {parcel.amount_som:.0f} сом")
        except Exception as e:
            print(f"⚠️ Ошибка создания {parcel.tracking}: {e}")

    # Close DB
    await db_service.close()

    print(f"\n🎉 Готово! Создано 2 посылки для TE-5002")
    print(f"   Каждая по 10 сом, статус 'Готово к выдаче'")
    print(f"   Клиент увидит кнопку 'Оплатить' при просмотре посылок")


if __name__ == "__main__":
    asyncio.run(create_parcels())
