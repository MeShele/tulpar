"""
Setup test data for QR payment testing
Clears parcels/payments and creates a test parcel for client TE-5002
"""
import asyncio
import asyncpg
from datetime import datetime

DATABASE_URL = "postgresql://neondb_owner:npg_3Z0yYxcaoKLk@ep-gentle-art-ag21l1tu-pooler.c-2.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"


async def main():
    print("Connecting to database...")
    conn = await asyncpg.connect(DATABASE_URL)

    try:
        # 1. Clear payments table
        result = await conn.execute("DELETE FROM payments")
        print(f"✅ Cleared payments: {result}")

        # 2. Clear parcels table
        result = await conn.execute("DELETE FROM parcels")
        print(f"✅ Cleared parcels: {result}")

        # 3. Check if client TE-5002 exists
        client = await conn.fetchrow(
            "SELECT * FROM clients WHERE code = $1", "TE-5002"
        )

        if client:
            print(f"✅ Found client: {client['full_name']} (chat_id: {client['chat_id']})")
        else:
            print("⚠️ Client TE-5002 not found! Creating...")
            await conn.execute("""
                INSERT INTO clients (chat_id, code, full_name, phone, reg_date)
                VALUES ($1, $2, $3, $4, $5)
            """, 0, "TE-5002", "Test Client 5002", "996555123456", datetime.now())
            print("✅ Created test client TE-5002")

        # 4. Create test parcel with status READY_PICKUP and 50 som
        await conn.execute("""
            INSERT INTO parcels
            (client_code, tracking, status, weight_kg, amount_usd, amount_som, date_china, date_bishkek)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
            "TE-5002",
            "TEST-QR-001",
            "READY_PICKUP",  # Ready for pickup - triggers payment button
            0.5,             # 0.5 kg
            0.56,            # ~50 som / 89.5 rate
            50.0,            # 50 som - small test amount
            datetime.now(),
            datetime.now(),
        )
        print("✅ Created test parcel:")
        print("   - Tracking: TEST-QR-001")
        print("   - Status: READY_PICKUP (Готово к выдаче)")
        print("   - Amount: 50 сом")

        # 5. Verify
        parcel = await conn.fetchrow(
            "SELECT * FROM parcels WHERE client_code = $1", "TE-5002"
        )
        print(f"\n📦 Verification: {parcel['tracking']} - {parcel['status']} - {parcel['amount_som']} сом")

        print("\n🎉 Done! Client TE-5002 can now test QR payment in the bot.")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
