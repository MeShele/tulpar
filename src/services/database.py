"""
Tulpar Express - PostgreSQL Database Service
Async database operations with asyncpg
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, List, Any

import asyncpg

from src.config import config
from src.models import Client, Parcel, ParcelStatus

logger = logging.getLogger(__name__)


class DatabaseService:
    """PostgreSQL database service"""

    def __init__(self) -> None:
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        """Initialize connection pool"""
        if not config.database_url:
            raise ValueError("DATABASE_URL not configured")

        self._pool = await asyncpg.create_pool(
            config.database_url,
            min_size=2,
            max_size=10,
        )
        logger.info("Database connection pool created")

        # Create tables if not exist
        await self._create_tables()

    async def close(self) -> None:
        """Close connection pool"""
        if self._pool:
            await self._pool.close()
            logger.info("Database connection pool closed")

    async def _create_tables(self) -> None:
        """Create database tables if not exist"""
        async with self._pool.acquire() as conn:
            # Clients table (chat_id can be 0 for imported clients, so no UNIQUE)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS clients (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL DEFAULT 0,
                    code VARCHAR(20) UNIQUE NOT NULL,
                    full_name VARCHAR(255) NOT NULL,
                    phone VARCHAR(50) NOT NULL,
                    reg_date TIMESTAMP DEFAULT NOW()
                )
            """)

            # Index on chat_id for faster lookups (non-unique)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_clients_chat_id ON clients(chat_id) WHERE chat_id > 0
            """)

            # Parcels table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS parcels (
                    id SERIAL PRIMARY KEY,
                    client_code VARCHAR(20) NOT NULL,
                    tracking VARCHAR(100),
                    status VARCHAR(50) NOT NULL DEFAULT 'CHINA_WAREHOUSE',
                    weight_kg DECIMAL(10,2) DEFAULT 0,
                    amount_usd DECIMAL(10,2) DEFAULT 0,
                    amount_som DECIMAL(10,2) DEFAULT 0,
                    date_china TIMESTAMP,
                    date_bishkek TIMESTAMP,
                    date_delivered TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # Indexes for parcels performance
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_parcels_client_code ON parcels(client_code)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_parcels_status ON parcels(status)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_parcels_tracking ON parcels(tracking) WHERE tracking IS NOT NULL
            """)

            # Settings table (for rate, etc)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key VARCHAR(100) PRIMARY KEY,
                    value VARCHAR(255) NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # Codes counter table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS code_counter (
                    id SERIAL PRIMARY KEY,
                    last_number INTEGER DEFAULT 5000
                )
            """)

            # Initialize code counter if empty
            await conn.execute("""
                INSERT INTO code_counter (last_number)
                SELECT 5000 WHERE NOT EXISTS (SELECT 1 FROM code_counter)
            """)

            # Initialize default USD rate if not exists
            await conn.execute("""
                INSERT INTO settings (key, value)
                VALUES ('usd_to_som', '89.5')
                ON CONFLICT (key) DO NOTHING
            """)

            # Payments table for QR payment tracking
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    payment_id VARCHAR(100) UNIQUE NOT NULL,
                    client_code VARCHAR(20) NOT NULL,
                    chat_id BIGINT NOT NULL,
                    amount_som DECIMAL(10,2) NOT NULL,
                    description VARCHAR(255),
                    tracking VARCHAR(100),
                    status VARCHAR(20) DEFAULT 'PENDING',
                    qr_data TEXT,
                    message_id BIGINT,
                    paid_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # Index for payment lookups
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_payments_client_code ON payments(client_code)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_payments_chat_id ON payments(chat_id)
            """)

            logger.info("Database tables created/verified")

    # ============== Settings ==============

    async def get_setting(self, key: str, default: str = "") -> str:
        """Get setting value by key"""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM settings WHERE key = $1", key
            )
            return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        """Set setting value"""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()
            """, key, value)

    async def get_usd_rate(self) -> float:
        """Get current USD to SOM rate"""
        rate_str = await self.get_setting("usd_to_som", "89.5")
        return float(rate_str)

    async def set_usd_rate(self, rate: float) -> None:
        """Set USD to SOM rate"""
        await self.set_setting("usd_to_som", str(rate))

    # ============== Client Operations ==============

    async def get_client_by_chat_id(self, chat_id: int) -> Optional[Client]:
        """Find client by Telegram chat_id"""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM clients WHERE chat_id = $1", chat_id
            )
            return self._row_to_client(row) if row else None

    async def get_client_by_code(self, code: str) -> Optional[Client]:
        """Find client by code (TE-XXXX)"""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM clients WHERE code = $1", code.upper()
            )
            return self._row_to_client(row) if row else None

    async def get_client_by_phone(self, phone: str) -> Optional[Client]:
        """Find client by phone number"""
        phone_digits = "".join(filter(str.isdigit, phone))
        async with self._pool.acquire() as conn:
            # Try exact match first, then suffix match
            row = await conn.fetchrow(
                "SELECT * FROM clients WHERE phone = $1 OR phone LIKE $2",
                phone_digits,
                f"%{phone_digits[-9:]}" if len(phone_digits) >= 9 else phone_digits
            )
            return self._row_to_client(row) if row else None

    async def create_client(self, client: Client) -> Client:
        """Create new client record"""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO clients (chat_id, code, full_name, phone, reg_date)
                VALUES ($1, $2, $3, $4, $5)
            """, client.chat_id, client.code, client.full_name, client.phone, client.reg_date)
        return client

    async def get_all_clients(self) -> List[Client]:
        """Get all registered clients"""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM clients ORDER BY reg_date DESC")
            return [self._row_to_client(row) for row in rows]

    async def generate_client_code(self) -> str:
        """Generate unique client code TE-XXXX"""
        async with self._pool.acquire() as conn:
            # Atomic increment
            row = await conn.fetchrow("""
                UPDATE code_counter SET last_number = last_number + 1
                RETURNING last_number
            """)
            new_number = row["last_number"]
            return f"TE-{new_number:04d}"

    def _row_to_client(self, row: asyncpg.Record) -> Client:
        """Convert database row to Client object"""
        return Client(
            chat_id=row["chat_id"],
            code=row["code"],
            full_name=row["full_name"],
            phone=row["phone"],
            reg_date=row["reg_date"],
        )

    # ============== Parcel Operations ==============

    async def get_parcels_by_client_code(self, client_code: str) -> List[Parcel]:
        """Get all parcels for a client"""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM parcels WHERE client_code = $1 ORDER BY created_at DESC",
                client_code.upper()
            )
            return [self._row_to_parcel(row) for row in rows]

    async def get_parcel_by_tracking(self, tracking: str) -> Optional[Parcel]:
        """Find parcel by tracking number"""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM parcels WHERE tracking = $1", tracking
            )
            return self._row_to_parcel(row) if row else None

    async def create_parcel(self, parcel: Parcel) -> Parcel:
        """Create new parcel record"""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO parcels
                (client_code, tracking, status, weight_kg, amount_usd, amount_som,
                 date_china, date_bishkek, date_delivered)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
                parcel.client_code,
                parcel.tracking,
                parcel.status.value,
                parcel.weight_kg,
                parcel.amount_usd,
                parcel.amount_som,
                parcel.date_china,
                parcel.date_bishkek,
                parcel.date_delivered,
            )
        return parcel

    async def update_parcel_status(
        self,
        client_code: str,
        tracking: str,
        new_status: ParcelStatus,
        **updates
    ) -> bool:
        """Update parcel status and optional fields"""
        async with self._pool.acquire() as conn:
            # Build dynamic update query
            set_parts = ["status = $3"]
            params = [client_code.upper(), tracking, new_status.value]
            param_idx = 4

            field_mapping = {
                "weight_kg": "weight_kg",
                "amount_usd": "amount_usd",
                "amount_som": "amount_som",
                "date_bishkek": "date_bishkek",
                "date_delivered": "date_delivered",
            }

            for key, column in field_mapping.items():
                if key in updates:
                    set_parts.append(f"{column} = ${param_idx}")
                    params.append(updates[key])
                    param_idx += 1

            query = f"""
                UPDATE parcels SET {', '.join(set_parts)}
                WHERE client_code = $1 AND tracking = $2
            """

            result = await conn.execute(query, *params)
            return "UPDATE 1" in result

    def _row_to_parcel(self, row: asyncpg.Record) -> Parcel:
        """Convert database row to Parcel object"""
        return Parcel(
            client_code=row["client_code"],
            tracking=row["tracking"] or "",
            status=ParcelStatus(row["status"]),
            weight_kg=float(row["weight_kg"] or 0),
            amount_usd=float(row["amount_usd"] or 0),
            amount_som=float(row["amount_som"] or 0),
            date_china=row["date_china"],
            date_bishkek=row["date_bishkek"],
            date_delivered=row["date_delivered"],
        )

    async def get_parcels_by_status(self, status: Optional[str] = None, limit: int = 50) -> List[Parcel]:
        """Get parcels filtered by status"""
        async with self._pool.acquire() as conn:
            if status == "ACTIVE":
                # All non-delivered
                rows = await conn.fetch("""
                    SELECT * FROM parcels
                    WHERE status != 'DELIVERED'
                    ORDER BY created_at DESC
                    LIMIT $1
                """, limit)
            elif status:
                rows = await conn.fetch("""
                    SELECT * FROM parcels
                    WHERE status = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                """, status, limit)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM parcels
                    ORDER BY created_at DESC
                    LIMIT $1
                """, limit)
            return [self._row_to_parcel(row) for row in rows]

    # ============== Statistics ==============

    async def get_statistics(self) -> dict:
        """Get basic statistics"""
        async with self._pool.acquire() as conn:
            clients_count = await conn.fetchval("SELECT COUNT(*) FROM clients")
            parcels_count = await conn.fetchval("SELECT COUNT(*) FROM parcels")

            status_rows = await conn.fetch("""
                SELECT status, COUNT(*) as count
                FROM parcels GROUP BY status
            """)
            status_counts = {row["status"]: row["count"] for row in status_rows}

            return {
                "clients_count": clients_count,
                "parcels_count": parcels_count,
                "status_counts": status_counts,
            }

    # ============== Payment Operations ==============

    async def create_payment(
        self,
        payment_id: str,
        client_code: str,
        chat_id: int,
        amount_som: float,
        description: str,
        tracking: Optional[str] = None,
        qr_data: Optional[str] = None,
        message_id: Optional[int] = None,
    ) -> bool:
        """Create a new payment record"""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO payments (payment_id, client_code, chat_id, amount_som, description, tracking, qr_data, message_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """, payment_id, client_code, chat_id, amount_som, description, tracking, qr_data, message_id)
            return True
        except Exception as e:
            logger.error(f"Failed to create payment: {e}")
            return False

    async def get_payment_by_id(self, payment_id: str) -> Optional[dict]:
        """Get payment by payment_id"""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM payments WHERE payment_id = $1", payment_id
            )
            return dict(row) if row else None

    async def get_pending_payment_by_chat(self, chat_id: int) -> Optional[dict]:
        """Get pending payment for a chat"""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM payments
                WHERE chat_id = $1 AND status = 'PENDING'
                ORDER BY created_at DESC
                LIMIT 1
            """, chat_id)
            return dict(row) if row else None

    async def update_payment_status(
        self,
        payment_id: str,
        status: str,
        paid_at: Optional[datetime] = None,
    ) -> bool:
        """Update payment status"""
        try:
            async with self._pool.acquire() as conn:
                if paid_at:
                    await conn.execute("""
                        UPDATE payments SET status = $2, paid_at = $3
                        WHERE payment_id = $1
                    """, payment_id, status, paid_at)
                else:
                    await conn.execute("""
                        UPDATE payments SET status = $2
                        WHERE payment_id = $1
                    """, payment_id, status)
            return True
        except Exception as e:
            logger.error(f"Failed to update payment status: {e}")
            return False

    async def get_payments_by_client(self, client_code: str, limit: int = 20) -> List[dict]:
        """Get payments for a client"""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM payments
                WHERE client_code = $1
                ORDER BY created_at DESC
                LIMIT $2
            """, client_code.upper(), limit)
            return [dict(row) for row in rows]

    async def update_payment_message_id(self, payment_id: str, message_id: int) -> bool:
        """Update payment with message_id for later QR message deletion"""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE payments SET message_id = $1 WHERE payment_id = $2",
                    message_id, payment_id
                )
            return True
        except Exception as e:
            logger.error(f"Failed to update payment message_id: {e}")
            return False

    # ============== Client Table Operations ==============

    async def get_clients_with_parcel_counts(
        self,
        offset: int = 0,
        limit: int = 10,
        search_query: Optional[str] = None,
    ) -> List[dict]:
        """
        Get clients with their parcel counts and total amounts

        Returns list of dicts with: code, full_name, phone, chat_id,
        parcel_count, active_count, total_som, last_activity
        """
        async with self._pool.acquire() as conn:
            if search_query:
                # Search by code, name or phone
                search_pattern = f"%{search_query}%"
                rows = await conn.fetch("""
                    SELECT
                        c.code,
                        c.full_name,
                        c.phone,
                        c.chat_id,
                        c.reg_date,
                        COUNT(p.id) as parcel_count,
                        COUNT(CASE WHEN p.status != 'DELIVERED' THEN 1 END) as active_count,
                        COALESCE(SUM(p.amount_som), 0) as total_som,
                        MAX(COALESCE(p.date_bishkek, p.date_china, p.created_at)) as last_activity
                    FROM clients c
                    LEFT JOIN parcels p ON c.code = p.client_code
                    WHERE c.code ILIKE $1 OR c.full_name ILIKE $1 OR c.phone ILIKE $1
                    GROUP BY c.id, c.code, c.full_name, c.phone, c.chat_id, c.reg_date
                    ORDER BY last_activity DESC NULLS LAST, c.reg_date DESC
                    LIMIT $2 OFFSET $3
                """, search_pattern, limit, offset)
            else:
                rows = await conn.fetch("""
                    SELECT
                        c.code,
                        c.full_name,
                        c.phone,
                        c.chat_id,
                        c.reg_date,
                        COUNT(p.id) as parcel_count,
                        COUNT(CASE WHEN p.status != 'DELIVERED' THEN 1 END) as active_count,
                        COALESCE(SUM(p.amount_som), 0) as total_som,
                        MAX(COALESCE(p.date_bishkek, p.date_china, p.created_at)) as last_activity
                    FROM clients c
                    LEFT JOIN parcels p ON c.code = p.client_code
                    GROUP BY c.id, c.code, c.full_name, c.phone, c.chat_id, c.reg_date
                    ORDER BY last_activity DESC NULLS LAST, c.reg_date DESC
                    LIMIT $1 OFFSET $2
                """, limit, offset)

            return [dict(row) for row in rows]

    async def get_clients_count(self, search_query: Optional[str] = None) -> int:
        """Get total number of clients (for pagination)"""
        async with self._pool.acquire() as conn:
            if search_query:
                search_pattern = f"%{search_query}%"
                return await conn.fetchval("""
                    SELECT COUNT(*) FROM clients
                    WHERE code ILIKE $1 OR full_name ILIKE $1 OR phone ILIKE $1
                """, search_pattern)
            else:
                return await conn.fetchval("SELECT COUNT(*) FROM clients")

    async def get_client_parcels_detailed(self, client_code: str) -> List[dict]:
        """Get detailed parcels for a client with payment status"""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    p.*,
                    pay.status as payment_status,
                    pay.paid_at
                FROM parcels p
                LEFT JOIN payments pay ON p.client_code = pay.client_code
                    AND p.tracking = pay.tracking
                WHERE p.client_code = $1
                ORDER BY p.created_at DESC
            """, client_code.upper())
            return [dict(row) for row in rows]


# Global service instance
db_service = DatabaseService()
