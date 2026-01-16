"""Migrate data from Google Sheets to PostgreSQL"""
import asyncio
import asyncpg
import gspread
from google.oauth2.service_account import Credentials
from pathlib import Path
from dotenv import load_dotenv
import os

# Load env
env_path = Path(__file__).parent / "docker" / ".env"
load_dotenv(env_path)

DATABASE_URL = os.getenv("DATABASE_URL")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
GOOGLE_CREDENTIALS_PATH = str(Path(__file__).parent / "docker" / "google-service-account.json")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_sheets_data():
    """Get data from Google Sheets"""
    credentials = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(GOOGLE_SHEETS_ID)

    # Get clients
    clients_sheet = spreadsheet.worksheet("clients")
    clients = clients_sheet.get_all_records()

    # Get parcels
    try:
        parcels_sheet = spreadsheet.worksheet("parcels")
        parcels = parcels_sheet.get_all_records()
    except gspread.exceptions.WorksheetNotFound:
        parcels = []

    # Get last code number
    try:
        codes_sheet = spreadsheet.worksheet("codes")
        last_number = codes_sheet.acell("A2").value
        last_number = int(last_number) if last_number else 5000
    except:
        last_number = 5000

    return clients, parcels, last_number


async def migrate():
    print("Starting migration from Google Sheets to PostgreSQL...")

    # Get data from Sheets
    print("\n1. Reading Google Sheets data...")
    clients, parcels, last_number = get_sheets_data()
    print(f"   Found {len(clients)} clients, {len(parcels)} parcels, last_code={last_number}")

    # Connect to PostgreSQL
    print("\n2. Connecting to PostgreSQL...")
    conn = await asyncpg.connect(DATABASE_URL)

    # Migrate clients
    print("\n3. Migrating clients...")
    migrated_clients = 0
    for c in clients:
        try:
            await conn.execute("""
                INSERT INTO clients (chat_id, code, full_name, phone)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (chat_id) DO NOTHING
            """,
                int(c.get("chat_id", 0)),
                str(c.get("code", "")),
                str(c.get("full_name", "")),
                str(c.get("phone", "")),
            )
            migrated_clients += 1
        except Exception as e:
            print(f"   Error migrating client {c.get('code')}: {e}")
    print(f"   Migrated {migrated_clients} clients")

    # Migrate parcels
    print("\n4. Migrating parcels...")
    migrated_parcels = 0
    for p in parcels:
        try:
            await conn.execute("""
                INSERT INTO parcels (client_code, tracking, status, weight_kg, amount_usd, amount_som)
                VALUES ($1, $2, $3, $4, $5, $6)
            """,
                p.get("client_code", ""),
                p.get("tracking", ""),
                p.get("status", "CHINA_WAREHOUSE"),
                float(p.get("weight_kg", 0) or 0),
                float(p.get("amount_usd", 0) or 0),
                float(p.get("amount_som", 0) or 0),
            )
            migrated_parcels += 1
        except Exception as e:
            print(f"   Error migrating parcel {p.get('tracking')}: {e}")
    print(f"   Migrated {migrated_parcels} parcels")

    # Update code counter
    print("\n5. Updating code counter...")
    await conn.execute("UPDATE code_counter SET last_number = $1", last_number)
    print(f"   Set last_number to {last_number}")

    await conn.close()
    print("\n✅ Migration complete!")


if __name__ == "__main__":
    asyncio.run(migrate())
