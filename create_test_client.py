"""Create test client TE-5002"""
import asyncio
import sys
sys.path.insert(0, '.')

from datetime import datetime
from src.services.database import db_service
from src.services.sheets import sheets_service
from src.models import Client
from src.config import config


async def create_client():
    # Connect to DB
    if config.database_url:
        await db_service.connect()

    # Test client data (same chat_id as admin for testing notifications)
    client = Client(
        chat_id=6082797818,  # Your chat_id to receive notifications
        code="TE-5002",
        full_name="Тест Клиент",
        phone="0555123456",
        reg_date=datetime.now(),
    )

    # Create in PostgreSQL
    if config.database_url:
        try:
            await db_service.create_client(client)
            print(f"✅ Created in PostgreSQL: {client.code}")
        except Exception as e:
            print(f"⚠️ PostgreSQL: {e}")

    # Create in Google Sheets
    try:
        await sheets_service.create_client(client)
        print(f"✅ Created in Google Sheets: {client.code}")
    except Exception as e:
        print(f"⚠️ Google Sheets: {e}")

    # Update code counter
    if config.database_url:
        await db_service._pool.execute("UPDATE code_counter SET last_number = 5002")
        print("✅ Updated code counter to 5002")
        await db_service.close()

    print(f"\n🎉 Client created!")
    print(f"   Code: {client.code}")
    print(f"   Name: {client.full_name}")
    print(f"   Phone: {client.phone}")
    print(f"   Chat ID: {client.chat_id}")


if __name__ == "__main__":
    asyncio.run(create_client())
