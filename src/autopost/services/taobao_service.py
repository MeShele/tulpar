"""Taobao API service for fetching products via RapidAPI (Otapi)."""

from __future__ import annotations

import threading
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from src.autopost.config import settings
from src.autopost.exceptions import ServiceError
from src.autopost.models import RawProduct
from src.autopost.services.base import BaseService, ServiceResult

# RapidAPI Taobao API endpoint (Otapi)
RAPIDAPI_BASE_URL = "https://taobao-tmall1.p.rapidapi.com"
RAPIDAPI_HOST = "taobao-tmall1.p.rapidapi.com"

# Daily rate limit for RapidAPI requests
DAILY_RATE_LIMIT = 100

# Taobao product URL template
TAOBAO_URL_TEMPLATE = "https://item.taobao.com/item.htm?id={product_id}"


class RateLimitExceededError(ServiceError):
    """Raised when daily API rate limit is exceeded."""

    def __init__(self, current_count: int, limit: int) -> None:
        super().__init__(
            message=f"Daily rate limit exceeded: {current_count}/{limit}",
            service_name="taobao",
        )
        self.current_count = current_count
        self.limit = limit


class TaobaoService(BaseService):
    """Service for fetching products from Taobao via RapidAPI (Otapi).

    Handles API communication, rate limiting, and response parsing.
    Uses tenacity for automatic retries on transient failures.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        """Initialize Taobao service.

        Args:
            client: Optional httpx.AsyncClient for HTTP requests.
        """
        super().__init__(client)
        self._request_count = 0
        self._request_date = date.today()
        self._rate_limit_lock = threading.Lock()

    def _get_headers(self) -> dict[str, str]:
        """Get RapidAPI headers for requests.

        Returns:
            Dictionary with required RapidAPI headers.
        """
        return {
            "X-RapidAPI-Key": settings.rapidapi_key,
            "X-RapidAPI-Host": RAPIDAPI_HOST,
        }

    def _check_rate_limit(self) -> None:
        """Check and update rate limit counter.

        Resets counter if date has changed. Thread-safe.

        Raises:
            RateLimitExceededError: If daily limit is exceeded.
        """
        with self._rate_limit_lock:
            today = date.today()
            if today != self._request_date:
                self._request_count = 0
                self._request_date = today

            if self._request_count >= DAILY_RATE_LIMIT:
                self.logger.warning(
                    "rate_limit_exceeded",
                    current_count=self._request_count,
                    limit=DAILY_RATE_LIMIT,
                )
                raise RateLimitExceededError(self._request_count, DAILY_RATE_LIMIT)

    def _increment_request_count(self) -> None:
        """Increment the daily request counter. Thread-safe."""
        with self._rate_limit_lock:
            self._request_count += 1
            self.logger.debug(
                "request_count_updated",
                count=self._request_count,
                limit=DAILY_RATE_LIMIT,
            )

    def _parse_product(self, data: dict[str, Any]) -> RawProduct | None:
        """Parse Taobao API response item into RawProduct.

        Args:
            data: Raw product data from API response.

        Returns:
            RawProduct if parsing successful, None otherwise.
        """
        try:
            # Extract product ID
            product_id = str(data.get("Id", ""))
            if not product_id:
                return None

            # Extract title (prefer translated, fallback to original)
            title = data.get("Title", data.get("OriginalTitle", ""))
            if not title:
                return None

            # Extract price
            price_data = data.get("Price", {})
            if isinstance(price_data, dict):
                price_cny = Decimal(str(price_data.get("OriginalPrice", 0)))
            else:
                price_cny = Decimal(str(price_data)) if price_data else Decimal("0")

            # Skip products with zero price
            if price_cny <= 0:
                return None

            # Extract image URL
            image_url = data.get("MainPictureUrl", "")
            if not image_url:
                # Try Pictures array
                pictures = data.get("Pictures", [])
                if pictures and isinstance(pictures, list):
                    image_url = pictures[0].get("Url", "") if isinstance(pictures[0], dict) else str(pictures[0])

            # Add https: if missing
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url

            if not image_url:
                return None

            # Extract rating (VendorScore is 0-20, convert to 0-5)
            vendor_score = data.get("VendorScore", 15)
            rating = min(5.0, max(0.0, float(vendor_score) / 4))

            # Volume as sales count
            sales_count = int(data.get("Volume", 0))

            # Calculate discount if we have margin price
            discount = 0
            if isinstance(price_data, dict):
                margin_price = price_data.get("MarginPrice", 0)
                original_price = price_data.get("OriginalPrice", 0)
                if margin_price and original_price and margin_price > original_price:
                    discount = int((1 - original_price / margin_price) * 100)

            return RawProduct(
                id=product_id,
                title=title,
                price_cny=price_cny,
                image_url=image_url,
                rating=rating,
                discount=discount,
                sales_count=sales_count,
                source="taobao",
            )
        except (ValueError, TypeError, KeyError) as e:
            self.logger.warning(
                "product_parse_error",
                data_id=data.get("Id"),
                error=str(e),
            )
            return None

    async def fetch_products(
        self,
        keyword: str,
        page_size: int = 10,
    ) -> ServiceResult[list[RawProduct]]:
        """Fetch products from Taobao API.

        Args:
            keyword: Search keyword.
            page_size: Number of products to fetch (default: 10).

        Returns:
            ServiceResult containing list of RawProduct on success,
            or error message on failure.

        Raises:
            RateLimitExceededError: If daily rate limit is exceeded.
        """
        self._check_rate_limit()

        self.logger.info(
            "fetching_products",
            keyword=keyword,
            page_size=page_size,
            source="taobao",
        )

        try:
            url = f"{RAPIDAPI_BASE_URL}/BatchSearchItemsFrame"

            params = {
                "frame": "Taobao",
                "framePosition": "1",
                "frameSize": str(page_size),
                "language": "en",
                "ItemTitle": keyword,
            }

            response = await self._get(
                url,
                params=params,
                headers=self._get_headers(),
            )

            self._increment_request_count()

            response_data = response.json()

            # Check for API error
            if response_data.get("ErrorCode") and response_data.get("ErrorCode") != "Ok":
                error_msg = response_data.get("ErrorDescription", "Unknown error")
                self.logger.error(
                    "api_error",
                    error=error_msg,
                    error_code=response_data.get("ErrorCode"),
                )
                return ServiceResult.fail(f"API error: {error_msg}")

            # Parse response - Otapi structure:
            # Result.Items.Items.Content[]
            try:
                items_data = (
                    response_data
                    .get("Result", {})
                    .get("Items", {})
                )

                # Items is a dict with 'Items' key containing 'Content'
                if isinstance(items_data, dict) and "Items" in items_data:
                    items = items_data["Items"].get("Content", [])
                else:
                    items = []
            except (AttributeError, TypeError):
                items = []

            if not isinstance(items, list):
                self.logger.warning(
                    "unexpected_response_format",
                    response_keys=list(response_data.keys()) if isinstance(response_data, dict) else type(response_data),
                )
                items = []

            products = []
            for item in items:
                product = self._parse_product(item)
                if product and product.image_url:
                    products.append(product)

            self.logger.info(
                "products_fetched",
                keyword=keyword,
                total=len(products),
                request_count=self._request_count,
                source="taobao",
            )

            return ServiceResult.ok(products)

        except RateLimitExceededError:
            raise
        except ServiceError as e:
            self.logger.error(
                "fetch_products_error",
                keyword=keyword,
                error=str(e),
            )
            return ServiceResult.fail(str(e))
        except Exception as e:
            self.logger.error(
                "unexpected_error",
                keyword=keyword,
                error=str(e),
                error_type=type(e).__name__,
            )
            return ServiceResult.fail(f"Unexpected error: {e}")

    @property
    def requests_remaining(self) -> int:
        """Get remaining API requests for today.

        Returns:
            Number of requests remaining before hitting daily limit.
        """
        today = date.today()
        if today != self._request_date:
            return DAILY_RATE_LIMIT
        return max(0, DAILY_RATE_LIMIT - self._request_count)

    def reset_rate_limit(self) -> None:
        """Reset the rate limit counter (for testing purposes)."""
        self._request_count = 0
        self._request_date = date.today()
