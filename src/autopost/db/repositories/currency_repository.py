"""Currency rate repository for database operations."""

from __future__ import annotations

from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.autopost.db.models import CurrencyRateDB

logger = structlog.get_logger(__name__)


class CurrencyRepository:
    """Repository for currency rate database operations.

    Provides methods to save and retrieve exchange rates from the database.
    Used for fallback when external API is unavailable.

    Attributes:
        session: SQLAlchemy async session for database operations.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize CurrencyRepository with database session.

        Args:
            session: SQLAlchemy async session.
        """
        self.session = session

    async def save_rate(
        self, from_currency: str, to_currency: str, rate: Decimal
    ) -> CurrencyRateDB:
        """Save a new exchange rate to the database.

        Args:
            from_currency: Source currency code (e.g., "CNY").
            to_currency: Target currency code (e.g., "KGS").
            rate: Exchange rate value.

        Returns:
            Created CurrencyRateDB record.
        """
        rate_record = CurrencyRateDB(
            from_currency=from_currency.upper(),
            to_currency=to_currency.upper(),
            rate=rate,
        )

        self.session.add(rate_record)
        await self.session.commit()
        await self.session.refresh(rate_record)

        logger.info(
            "currency_rate_saved",
            from_currency=from_currency,
            to_currency=to_currency,
            rate=float(rate),
        )

        return rate_record

    async def get_latest_rate(
        self, from_currency: str, to_currency: str
    ) -> Decimal | None:
        """Get the most recent exchange rate from the database.

        Used as fallback when external API is unavailable.

        Args:
            from_currency: Source currency code (e.g., "CNY").
            to_currency: Target currency code (e.g., "KGS").

        Returns:
            Latest exchange rate or None if not found.
        """
        stmt = (
            select(CurrencyRateDB.rate)
            .where(CurrencyRateDB.from_currency == from_currency.upper())
            .where(CurrencyRateDB.to_currency == to_currency.upper())
            .order_by(CurrencyRateDB.fetched_at.desc())
            .limit(1)
        )

        result = await self.session.execute(stmt)
        rate = result.scalar()

        if rate is not None:
            logger.debug(
                "latest_rate_found",
                from_currency=from_currency,
                to_currency=to_currency,
                rate=float(rate),
            )
        else:
            logger.warning(
                "no_rate_found",
                from_currency=from_currency,
                to_currency=to_currency,
            )

        return Decimal(str(rate)) if rate is not None else None

    async def get_rate_history(
        self, from_currency: str, to_currency: str, limit: int = 30
    ) -> list[CurrencyRateDB]:
        """Get exchange rate history for a currency pair.

        Args:
            from_currency: Source currency code.
            to_currency: Target currency code.
            limit: Maximum number of records to return.

        Returns:
            List of CurrencyRateDB records ordered by date descending.
        """
        stmt = (
            select(CurrencyRateDB)
            .where(CurrencyRateDB.from_currency == from_currency.upper())
            .where(CurrencyRateDB.to_currency == to_currency.upper())
            .order_by(CurrencyRateDB.fetched_at.desc())
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())
