"""Pinduoduo API service for fetching products via RapidAPI."""

from __future__ import annotations

import threading
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

import httpx

from src.autopost.config import settings
from src.autopost.exceptions import ServiceError
from src.autopost.models import RawProduct
from src.autopost.services.base import BaseService, ServiceResult

# RapidAPI Pinduoduo API endpoint
RAPIDAPI_BASE_URL = "https://pinduoduo1.p.rapidapi.com"
RAPIDAPI_HOST = "pinduoduo1.p.rapidapi.com"

# Daily rate limit for RapidAPI requests
DAILY_RATE_LIMIT = 100

# Pinduoduo product URL template
PINDUODUO_URL_TEMPLATE = "https://mobile.yangkeduo.com/goods.html?goods_id={product_id}"

# Category keywords for search (Chinese keywords work best)
CATEGORY_KEYWORDS = {
    "headphones": "蓝牙耳机 无线",
    "gadgets": "智能手表 数码",
    "bags": "背包 双肩包",
    "clothing": "卫衣 男女",
    "unisex": "休闲服装 男女通用",  # Unisex clothing
    "home": "家居 收纳",
    "kitchen": "厨房 用品",
    "beauty": "护肤 化妆",
    "kids": "儿童 玩具",
    "sports": "运动 健身",
    "auto": "汽车 配件",
}

# Daily category rotation (3 categories per day for variety)
# Each day shows different mix of product types
CATEGORY_GROUPS = [
    ["headphones", "bags", "beauty"],       # Day 1: Tech + Fashion + Beauty
    ["gadgets", "unisex", "home"],          # Day 2: Tech + Unisex + Home
    ["sports", "kids", "kitchen"],          # Day 3: Active + Kids + Kitchen
    ["headphones", "unisex", "beauty"],     # Day 4: Tech + Unisex + Beauty
    ["gadgets", "bags", "sports"],          # Day 5: Tech + Fashion + Active
    ["home", "kids", "unisex"],             # Day 6: Home + Kids + Unisex
    ["headphones", "kitchen", "unisex"],    # Day 7: Tech + Kitchen + Unisex
    ["gadgets", "beauty", "sports"],        # Day 8: Tech + Beauty + Active
    ["bags", "home", "unisex"],             # Day 9: Fashion + Home + Unisex
    ["headphones", "auto", "beauty"],       # Day 10: Tech + Auto + Beauty
]


def get_daily_categories() -> list[str]:
    """Get 3 categories for today based on rotation.

    Returns:
        List of 3 category strings for today.
    """
    day_of_year = date.today().timetuple().tm_yday
    index = day_of_year % len(CATEGORY_GROUPS)
    return CATEGORY_GROUPS[index]


def get_daily_category() -> str:
    """Get primary category for today (backward compatibility).

    Returns:
        First category from today's group.
    """
    return get_daily_categories()[0]


class ProductCategory(str, Enum):
    """Product categories for Kyrgyzstan market."""

    HEADPHONES = "headphones"
    GADGETS = "gadgets"
    BAGS = "bags"
    CLOTHING = "clothing"
    UNISEX = "unisex"
    HOME = "home"
    KITCHEN = "kitchen"
    BEAUTY = "beauty"
    KIDS = "kids"
    SPORTS = "sports"
    AUTO = "auto"


class RateLimitExceededError(ServiceError):
    """Raised when daily API rate limit is exceeded."""

    def __init__(self, current_count: int, limit: int) -> None:
        super().__init__(
            message=f"Daily rate limit exceeded: {current_count}/{limit}",
            service_name="pinduoduo",
        )
        self.current_count = current_count
        self.limit = limit


class PinduoduoService(BaseService):
    """Service for fetching products from Pinduoduo via RapidAPI.

    Handles API communication, rate limiting, and response parsing.
    Uses tenacity for automatic retries on transient failures.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        """Initialize Pinduoduo service.

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

    def _parse_sales_count(self, sales_str: str) -> int:
        """Parse sales count from string like '已抢6475件', '总售24万+件'.

        Args:
            sales_str: Sales string from API.

        Returns:
            Integer sales count.
        """
        if not sales_str or not isinstance(sales_str, str):
            return 0

        # Remove common Chinese suffixes
        sales_str = sales_str.replace("件", "").replace("已抢", "").replace("总售", "").replace("+", "").strip()

        # Handle "万" (10,000)
        if "万" in sales_str:
            sales_str = sales_str.replace("万", "")
            try:
                return int(float(sales_str) * 10000)
            except ValueError:
                return 0

        # Handle plain numbers
        try:
            return int(float(sales_str)) if sales_str else 0
        except ValueError:
            return 0

    def _get_high_res_image_url(self, url: str) -> str:
        """Convert thumbnail URL to high resolution version.

        Pinduoduo/AliCDN images often have size parameters that can be modified
        to get higher resolution versions (up to 800x800).

        Args:
            url: Original image URL (possibly thumbnail).

        Returns:
            High resolution image URL (800x800 if supported).
        """
        import re

        if not url:
            return url

        # Replace imageMogr2 thumbnail size with 800 (max supported)
        # Example: ?imageMogr2/thumbnail/x200 -> ?imageMogr2/thumbnail/x800
        if 'imageMogr2/thumbnail/' in url:
            url = re.sub(r'imageMogr2/thumbnail/x\d+', 'imageMogr2/thumbnail/x800', url)
            return url

        # For URLs without imageMogr2, try adding it for pddpic.com
        if 'pddpic.com' in url and '?' not in url:
            url = url + '?imageMogr2/thumbnail/x800'
            return url

        # Remove size suffixes like _200x200, _400x400, etc.
        url = re.sub(r'_\d+x\d+(?=\.\w+$|\?)', '', url)

        # Remove @w=NNN&h=NNN or similar query params that limit size
        url = re.sub(r'[@?&]w=\d+', '', url)
        url = re.sub(r'[@?&]h=\d+', '', url)

        # Remove _q\d+ quality suffix (keep high quality)
        url = re.sub(r'_q\d+(?=\.\w+$|\?)', '', url)

        # For alicdn.com URLs, try to get larger version
        url = re.sub(r'\.\w+_\d+x\d+\.\w+$', '.jpg', url)

        # Clean up any double extensions
        url = re.sub(r'\.jpg\.jpg$', '.jpg', url)
        url = re.sub(r'\.png\.png$', '.png', url)

        return url

    def _parse_product(self, data: dict[str, Any]) -> RawProduct | None:
        """Parse Pinduoduo API response item into RawProduct.

        Args:
            data: Raw product data from API response.

        Returns:
            RawProduct if parsing successful, None otherwise.
        """
        try:
            # Extract product ID
            product_id = str(data.get("goods_id", ""))
            if not product_id:
                return None

            # Extract title
            title = data.get("goods_name", "")
            if not title:
                return None

            # Extract price (in fen/cents, divide by 100)
            price_fen = data.get("default_price", data.get("market_price", 0))
            try:
                price_cny = Decimal(str(price_fen)) / 100
            except (ValueError, TypeError):
                price_cny = Decimal("0")

            # Skip products with zero price
            if price_cny <= 0:
                return None

            # Extract image URL and get high resolution version
            image_url = data.get("hd_thumb_url", data.get("thumb_url", ""))

            # Add https: if missing
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url

            # Get high resolution version of the image
            if image_url:
                image_url = self._get_high_res_image_url(image_url)

            if not image_url:
                return None

            # Default rating (Pinduoduo doesn't provide ratings)
            rating = 4.5

            # Extract sales count
            sales_str = data.get("side_sales_tip", "0")
            sales_count = self._parse_sales_count(sales_str)

            # Calculate discount from market vs default price
            discount = 0
            market_price = data.get("market_price", 0)
            default_price = data.get("default_price", 0)
            if market_price and default_price and market_price > default_price:
                discount = int((1 - default_price / market_price) * 100)

            return RawProduct(
                id=product_id,
                title=title,
                price_cny=price_cny,
                image_url=image_url,
                rating=rating,
                discount=discount,
                sales_count=sales_count,
                source="pinduoduo",
            )
        except (ValueError, TypeError, KeyError) as e:
            self.logger.warning(
                "product_parse_error",
                data_id=data.get("goods_id"),
                error=str(e),
            )
            return None

    async def fetch_products(
        self,
        category: ProductCategory | str = ProductCategory.HEADPHONES,
        page: int = 1,
        page_size: int = 10,
    ) -> ServiceResult[list[RawProduct]]:
        """Fetch products from Pinduoduo API.

        Args:
            category: Product category to search.
            page: Page number for pagination (default: 1).
            page_size: Number of products per page (default: 10).

        Returns:
            ServiceResult containing list of RawProduct on success,
            or error message on failure.

        Raises:
            RateLimitExceededError: If daily rate limit is exceeded.
        """
        self._check_rate_limit()

        category_value = category.value if isinstance(category, ProductCategory) else category

        # Get Chinese keyword for category
        keyword = CATEGORY_KEYWORDS.get(category_value, category_value)

        self.logger.info(
            "fetching_products",
            category=category_value,
            keyword=keyword,
            page=page,
            page_size=page_size,
            source="pinduoduo",
        )

        try:
            url = f"{RAPIDAPI_BASE_URL}/pinduoduo/search"

            params = {
                "keyword": keyword,
                "page": str(page),
            }

            response = await self._get(
                url,
                params=params,
                headers=self._get_headers(),
            )

            self._increment_request_count()

            response_data = response.json()

            # Check for API error
            if not response_data.get("success", True):
                error_msg = response_data.get("message", "Unknown error")
                self.logger.error(
                    "api_error",
                    error=error_msg,
                )
                return ServiceResult.fail(f"API error: {error_msg}")

            # Parse response - Pinduoduo structure:
            # data.items[]
            try:
                items = response_data.get("data", {}).get("items", [])
            except (AttributeError, TypeError):
                items = []

            if not isinstance(items, list):
                self.logger.warning(
                    "unexpected_response_format",
                    response_keys=list(response_data.keys()) if isinstance(response_data, dict) else type(response_data),
                )
                items = []

            products = []
            for item in items[:page_size]:
                product = self._parse_product(item)
                if product and product.image_url:
                    products.append(product)

            self.logger.info(
                "products_fetched",
                category=category_value,
                total=len(products),
                request_count=self._request_count,
                source="pinduoduo",
            )

            return ServiceResult.ok(products)

        except RateLimitExceededError:
            raise
        except ServiceError as e:
            self.logger.error(
                "fetch_products_error",
                category=category_value,
                error=str(e),
            )
            return ServiceResult.fail(str(e))
        except Exception as e:
            self.logger.error(
                "unexpected_error",
                category=category_value,
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
