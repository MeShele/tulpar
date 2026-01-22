"""Currency exchange rate service."""

from __future__ import annotations

from decimal import Decimal

import httpx
import structlog
from cachetools import TTLCache

from src.autopost.db.repositories import CurrencyRepository
from src.autopost.exceptions import ServiceError
from src.autopost.services.base import BaseService, ServiceResult

logger = structlog.get_logger(__name__)

# TTL Cache: 1 hour for exchange rates
RATE_CACHE_TTL = 3600  # 1 hour in seconds
RATE_CACHE_MAX_SIZE = 10  # Max currency pairs to cache

# Exchange rate API URL (using exchangerate-api.com)
EXCHANGE_RATE_API_URL = "https://api.exchangerate-api.com/v4/latest/{base}"

# Default rate for CNY/KGS if no rate is available
DEFAULT_CNY_KGS_RATE = Decimal("12.0")


class CurrencyService(BaseService):
    """Service for fetching and caching currency exchange rates.

    Fetches exchange rates from external API with:
    - 1 hour TTL caching
    - 3 retries with exponential backoff
    - Fallback to database on API failure

    Attributes:
        repository: Optional CurrencyRepository for fallback and persistence.
    """

    # Class-level cache shared across instances
    _rate_cache: TTLCache[str, Decimal] = TTLCache(
        maxsize=RATE_CACHE_MAX_SIZE, ttl=RATE_CACHE_TTL
    )

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        repository: CurrencyRepository | None = None,
    ) -> None:
        """Initialize CurrencyService.

        Args:
            client: Optional httpx.AsyncClient for HTTP requests.
            repository: Optional CurrencyRepository for DB fallback.
        """
        super().__init__(client)
        self.repository = repository

    @classmethod
    def get_cache_key(cls, from_currency: str, to_currency: str) -> str:
        """Generate cache key for a currency pair.

        Args:
            from_currency: Source currency code.
            to_currency: Target currency code.

        Returns:
            Cache key string.
        """
        return f"{from_currency.upper()}:{to_currency.upper()}"

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the rate cache.

        Useful for testing or when cache invalidation is needed.
        """
        cls._rate_cache.clear()
        logger.info("currency_cache_cleared")

    async def get_rate(
        self, from_currency: str, to_currency: str
    ) -> ServiceResult[Decimal]:
        """Get exchange rate between two currencies.

        Tries sources in order:
        1. In-memory TTLCache (1 hour TTL)
        2. External API with retry
        3. Database fallback (last known rate)

        Args:
            from_currency: Source currency code (e.g., "CNY").
            to_currency: Target currency code (e.g., "KGS").

        Returns:
            ServiceResult containing the exchange rate or error message.
        """
        from_curr = from_currency.upper()
        to_curr = to_currency.upper()
        cache_key = self.get_cache_key(from_curr, to_curr)

        # 1. Check cache first
        if cache_key in self._rate_cache:
            rate = self._rate_cache[cache_key]
            logger.debug(
                "rate_from_cache",
                from_currency=from_curr,
                to_currency=to_curr,
                rate=float(rate),
            )
            return ServiceResult.ok(rate)

        # 2. Try external API
        try:
            rate = await self._fetch_rate_from_api(from_curr, to_curr)

            # Cache the rate
            self._rate_cache[cache_key] = rate

            # Save to database for future fallback
            if self.repository:
                await self.repository.save_rate(from_curr, to_curr, rate)

            logger.info(
                "rate_from_api",
                from_currency=from_curr,
                to_currency=to_curr,
                rate=float(rate),
            )

            return ServiceResult.ok(rate)

        except (ServiceError, httpx.HTTPStatusError, httpx.ConnectError) as e:
            logger.warning(
                "api_fetch_failed",
                from_currency=from_curr,
                to_currency=to_curr,
                error=str(e),
            )

            # 3. Fallback to database
            return await self._fallback_to_db(from_curr, to_curr)

    async def _fetch_rate_from_api(
        self, from_currency: str, to_currency: str
    ) -> Decimal:
        """Fetch exchange rate from external API.

        Uses BaseService retry logic (3 attempts, exponential backoff).

        Args:
            from_currency: Source currency code.
            to_currency: Target currency code.

        Returns:
            Exchange rate as Decimal.

        Raises:
            ServiceError: If API request fails.
        """
        url = EXCHANGE_RATE_API_URL.format(base=from_currency)

        self.logger.debug(
            "fetching_exchange_rate",
            from_currency=from_currency,
            to_currency=to_currency,
            url=url,
        )

        response = await self._get(url)
        data = response.json()

        rates = data.get("rates", {})
        if to_currency not in rates:
            raise ServiceError(
                message=f"Currency {to_currency} not found in API response",
                service_name="CurrencyService",
            )

        rate = Decimal(str(rates[to_currency]))
        return rate

    async def _fallback_to_db(
        self, from_currency: str, to_currency: str
    ) -> ServiceResult[Decimal]:
        """Fallback to database for last known rate.

        Args:
            from_currency: Source currency code.
            to_currency: Target currency code.

        Returns:
            ServiceResult with rate from DB or error if not found.
        """
        if self.repository:
            rate = await self.repository.get_latest_rate(from_currency, to_currency)
            if rate is not None:
                # Cache the fallback rate
                cache_key = self.get_cache_key(from_currency, to_currency)
                self._rate_cache[cache_key] = rate

                logger.info(
                    "rate_from_db_fallback",
                    from_currency=from_currency,
                    to_currency=to_currency,
                    rate=float(rate),
                )
                return ServiceResult.ok(rate)

        # No rate available anywhere
        logger.error(
            "no_rate_available",
            from_currency=from_currency,
            to_currency=to_currency,
        )
        return ServiceResult.fail(
            f"No exchange rate available for {from_currency}/{to_currency}"
        )

    async def get_cny_kgs_rate(self) -> ServiceResult[Decimal]:
        """Convenience method to get CNY/KGS exchange rate.

        Returns:
            ServiceResult containing CNY to KGS exchange rate.
        """
        return await self.get_rate("CNY", "KGS")
