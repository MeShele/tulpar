"""Product repository for database operations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import structlog
from cachetools import TTLCache
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.autopost.db.models import ProductDB
from src.autopost.models import RawProduct

logger = structlog.get_logger(__name__)

# TTL Cache: 24 hours, max 1000 entries (100 products * 10 categories)
CACHE_TTL_SECONDS = 86400  # 24 hours
CACHE_MAX_SIZE = 1000
OLD_PRODUCTS_DAYS = 7


class ProductRepository:
    """Repository for product database operations.

    Provides CRUD operations for cached products with in-memory TTLCache
    for improved performance. Implements upsert logic for deduplication
    and automatic cleanup of old products.

    Attributes:
        session: SQLAlchemy async session for database operations.
        cache: TTLCache for in-memory product caching.
    """

    # Class-level cache shared across instances
    _cache: TTLCache[str, list[RawProduct]] = TTLCache(
        maxsize=CACHE_MAX_SIZE, ttl=CACHE_TTL_SECONDS
    )

    def __init__(self, session: AsyncSession) -> None:
        """Initialize ProductRepository with database session.

        Args:
            session: SQLAlchemy async session.
        """
        self.session = session

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the in-memory cache.

        Useful for testing or when cache invalidation is needed.
        """
        cls._cache.clear()
        logger.info("product_cache_cleared")

    @classmethod
    def get_cache_key(cls, category: str) -> str:
        """Generate cache key for a category.

        Args:
            category: Product category name.

        Returns:
            Cache key string.
        """
        return f"products:{category}"

    async def save_products(
        self, products: list[RawProduct], category: str
    ) -> int:
        """Save products to database with upsert logic.

        Uses PostgreSQL INSERT ... ON CONFLICT DO UPDATE to handle duplicates.
        Products with existing pdd_id are updated, new products are inserted.

        Args:
            products: List of products to save.
            category: Product category for all products.

        Returns:
            Number of products saved/updated.
        """
        if not products:
            logger.debug("save_products_empty_list")
            return 0

        logger.info(
            "saving_products",
            count=len(products),
            category=category,
        )

        # Prepare data for bulk upsert
        values = [
            {
                "pdd_id": p.id,
                "title": p.title,
                "price_cny": p.price_cny,
                "image_url": p.image_url,
                "rating": float(p.rating),
                "discount": p.discount,
                "sales_count": p.sales_count,
                "category": category,
            }
            for p in products
        ]

        # PostgreSQL upsert statement
        stmt = insert(ProductDB).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["pdd_id"],
            set_={
                "title": stmt.excluded.title,
                "price_cny": stmt.excluded.price_cny,
                "image_url": stmt.excluded.image_url,
                "rating": stmt.excluded.rating,
                "discount": stmt.excluded.discount,
                "sales_count": stmt.excluded.sales_count,
                "category": stmt.excluded.category,
                "updated_at": datetime.now(timezone.utc),
            },
        )

        await self.session.execute(stmt)
        await self.session.commit()

        # Invalidate cache for this category
        cache_key = self.get_cache_key(category)
        if cache_key in self._cache:
            del self._cache[cache_key]

        logger.info(
            "products_saved",
            count=len(products),
            category=category,
        )

        return len(products)

    async def get_products_by_category(
        self, category: str, limit: int = 10
    ) -> list[RawProduct]:
        """Get products by category from database.

        Results are cached in TTLCache for 24 hours.

        Args:
            category: Product category to fetch.
            limit: Maximum number of products to return.

        Returns:
            List of RawProduct from database.
        """
        cache_key = self.get_cache_key(category)

        # Check cache first
        if cache_key in self._cache:
            cached = self._cache[cache_key][:limit]
            logger.debug(
                "products_from_cache",
                category=category,
                count=len(cached),
            )
            return cached

        # Fetch from database
        stmt = (
            select(ProductDB)
            .where(ProductDB.category == category)
            .order_by(ProductDB.updated_at.desc())
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        db_products = result.scalars().all()

        # Convert to RawProduct
        products = [
            RawProduct(
                id=p.pdd_id,
                title=p.title,
                price_cny=Decimal(str(p.price_cny)),
                image_url=p.image_url,
                rating=float(p.rating),
                discount=p.discount,
                sales_count=p.sales_count,
            )
            for p in db_products
        ]

        # Store in cache
        self._cache[cache_key] = products

        logger.debug(
            "products_from_db",
            category=category,
            count=len(products),
        )

        return products

    async def get_cached_products(self, category: str, limit: int = 10) -> list[RawProduct]:
        """Get cached products for fallback when API is unavailable.

        Same as get_products_by_category but with explicit fallback intent.

        Args:
            category: Product category to fetch.
            limit: Maximum number of products to return.

        Returns:
            List of cached RawProduct.
        """
        logger.info(
            "fallback_to_cached_products",
            category=category,
        )
        return await self.get_products_by_category(category, limit)

    async def delete_old_products(self, days: int = OLD_PRODUCTS_DAYS) -> int:
        """Delete products older than specified days.

        Args:
            days: Number of days after which products are considered old.

        Returns:
            Number of deleted products.
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = delete(ProductDB).where(ProductDB.updated_at < cutoff_date)
        result = await self.session.execute(stmt)
        await self.session.commit()

        deleted_count = result.rowcount

        if deleted_count > 0:
            # Clear entire cache since we don't know which categories were affected
            self.clear_cache()

        logger.info(
            "old_products_deleted",
            days=days,
            deleted_count=deleted_count,
        )

        return deleted_count

    async def get_product_count(self, category: str | None = None) -> int:
        """Get count of products in database.

        Args:
            category: Optional category filter.

        Returns:
            Number of products.
        """
        from sqlalchemy import func

        stmt = select(func.count(ProductDB.id))
        if category:
            stmt = stmt.where(ProductDB.category == category)

        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_all_categories(self) -> list[str]:
        """Get list of all categories with cached products.

        Returns:
            List of unique category names.
        """
        from sqlalchemy import distinct

        stmt = select(distinct(ProductDB.category))
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]
