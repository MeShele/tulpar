"""Test new features: Table and Forgot Code"""
import asyncio
import sys
sys.path.insert(0, '.')

from src.services.database import db_service
from src.services.sheets import sheets_service
from src.config import config


async def test_features():
    print("=" * 50)
    print("Testing Tulpar Express Bot Features")
    print("=" * 50)

    # Connect to DB
    if config.database_url:
        await db_service.connect()
        print("✅ PostgreSQL connected")

    # Test 1: Get client by phone (for "Забыл код")
    print("\n--- Test 1: Forgot Code (get_client_by_phone) ---")
    test_phone = "999841015"

    if config.database_url:
        client = await db_service.get_client_by_phone(test_phone)
    else:
        client = await sheets_service.get_client_by_phone(test_phone)

    if client:
        print(f"✅ Found client by phone {test_phone}:")
        print(f"   Code: {client.code}")
        print(f"   Name: {client.full_name}")
        print(f"   Chat ID: {client.chat_id}")
    else:
        print(f"❌ Client not found for phone: {test_phone}")

    # Test 2: Get parcels by status (for "Таблица")
    print("\n--- Test 2: Dynamic Table (get_parcels_by_status) ---")

    statuses = ["ACTIVE", "CHINA_WAREHOUSE", "BISHKEK_ARRIVED", "DELIVERED"]

    for status in statuses:
        if config.database_url:
            parcels = await db_service.get_parcels_by_status(status, limit=10)
        else:
            parcels = await sheets_service.get_parcels_by_status(status, limit=10)

        print(f"\n   Filter: {status}")
        print(f"   Found: {len(parcels)} parcels")

        if parcels:
            print(f"   {'Code':<10} {'Tracking':<15} {'Status':<15} {'Amount':>8}")
            print(f"   {'-'*50}")
            for p in parcels[:5]:
                print(f"   {p.client_code:<10} {p.tracking:<15} {p.status.value:<15} {p.amount_som:>8.0f}")

    # Test 3: Get USD rate (for setrate)
    print("\n--- Test 3: USD Rate ---")
    if config.database_url:
        rate = await db_service.get_usd_rate()
        print(f"✅ Current rate: {rate} сом/$")
        print(f"   Price per kg: $3.50 × {rate} = {3.50 * rate:.0f} сом")

    # Close DB
    if config.database_url:
        await db_service.close()

    print("\n" + "=" * 50)
    print("✅ All tests completed!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(test_features())
