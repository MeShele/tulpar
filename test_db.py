"""Test PostgreSQL connection and tables"""
import asyncio
import asyncpg
import os
from pathlib import Path
from dotenv import load_dotenv

# Load env
env_path = Path(__file__).parent / "docker" / ".env"
load_dotenv(env_path)

DATABASE_URL = os.getenv("DATABASE_URL")


async def test_db():
    print(f"Connecting to PostgreSQL...")

    conn = await asyncpg.connect(DATABASE_URL)

    # Check tables
    print("\n=== TABLES ===")
    tables = await conn.fetch("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
    """)
    for t in tables:
        print(f"  - {t['table_name']}")

    # Check clients
    print("\n=== CLIENTS ===")
    clients = await conn.fetch("SELECT * FROM clients LIMIT 5")
    print(f"  Count: {len(clients)}")
    for c in clients:
        print(f"  - {c['code']}: {c['full_name']} (chat_id: {c['chat_id']})")

    # Check parcels
    print("\n=== PARCELS ===")
    parcels = await conn.fetch("SELECT * FROM parcels LIMIT 5")
    print(f"  Count: {len(parcels)}")
    for p in parcels:
        print(f"  - {p['tracking']}: {p['status']} ({p['client_code']})")

    # Check settings
    print("\n=== SETTINGS ===")
    settings = await conn.fetch("SELECT * FROM settings")
    for s in settings:
        print(f"  - {s['key']}: {s['value']}")

    # Check code counter
    print("\n=== CODE COUNTER ===")
    counter = await conn.fetchval("SELECT last_number FROM code_counter")
    print(f"  Last number: {counter}")

    await conn.close()
    print("\n✅ Database check complete!")


if __name__ == "__main__":
    asyncio.run(test_db())
