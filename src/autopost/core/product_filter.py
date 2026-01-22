"""Product filtering and selection logic."""

from __future__ import annotations

from typing import Sequence

import structlog

from src.autopost.config import settings
from src.autopost.models import RawProduct

logger = structlog.get_logger(__name__)


class ProductFilter:
    """Filters and ranks products based on business criteria.

    Implements filtering by discount, rating, and selection of top products
    based on profitability score (discount * sales_count).

    Attributes:
        min_discount: Minimum discount percentage (default: 40).
        min_rating: Minimum product rating (default: 4.5).
        top_limit: Maximum number of products to return (default: 10).
    """

    def __init__(
        self,
        min_discount: int | None = None,
        min_rating: float | None = None,
        top_limit: int | None = None,
    ) -> None:
        """Initialize ProductFilter with filtering criteria.

        Args:
            min_discount: Minimum discount percentage. Defaults to settings.min_discount.
            min_rating: Minimum product rating. Defaults to settings.min_rating.
            top_limit: Maximum products to return. Defaults to settings.top_products_limit.
        """
        self.min_discount = min_discount if min_discount is not None else settings.min_discount
        self.min_rating = min_rating if min_rating is not None else settings.min_rating
        self.top_limit = top_limit if top_limit is not None else settings.top_products_limit

    def filter_by_discount(
        self, products: Sequence[RawProduct], min_discount: int | None = None
    ) -> list[RawProduct]:
        """Filter products by minimum discount percentage.

        Args:
            products: List of products to filter.
            min_discount: Minimum discount percentage. Uses instance default if not provided.

        Returns:
            List of products with discount >= min_discount.
        """
        threshold = min_discount if min_discount is not None else self.min_discount
        filtered = [p for p in products if p.discount >= threshold]

        logger.debug(
            "filtered_by_discount",
            threshold=threshold,
            input_count=len(products),
            output_count=len(filtered),
        )

        return filtered

    def filter_by_rating(
        self, products: Sequence[RawProduct], min_rating: float | None = None
    ) -> list[RawProduct]:
        """Filter products by minimum rating.

        Args:
            products: List of products to filter.
            min_rating: Minimum rating threshold. Uses instance default if not provided.

        Returns:
            List of products with rating >= min_rating.
        """
        threshold = min_rating if min_rating is not None else self.min_rating
        filtered = [p for p in products if p.rating >= threshold]

        logger.debug(
            "filtered_by_rating",
            threshold=threshold,
            input_count=len(products),
            output_count=len(filtered),
        )

        return filtered

    def sort_by_profitability(self, products: Sequence[RawProduct]) -> list[RawProduct]:
        """Sort products by profitability score (discount * sales_count).

        Products with higher discount and more sales are ranked higher.

        Args:
            products: List of products to sort.

        Returns:
            List of products sorted by profitability in descending order.
        """
        sorted_products = sorted(
            products,
            key=lambda p: p.discount * p.sales_count,
            reverse=True,
        )

        logger.debug(
            "sorted_by_profitability",
            count=len(sorted_products),
        )

        return sorted_products

    def get_top_products(
        self, products: Sequence[RawProduct], limit: int | None = None
    ) -> list[RawProduct]:
        """Get top N products from the list.

        Args:
            products: List of products to limit.
            limit: Maximum number of products. Uses instance default if not provided.

        Returns:
            List of up to `limit` products.
        """
        max_count = limit if limit is not None else self.top_limit
        top = list(products[:max_count])

        logger.debug(
            "get_top_products",
            limit=max_count,
            input_count=len(products),
            output_count=len(top),
        )

        return top

    def filter(self, products: Sequence[RawProduct]) -> list[RawProduct]:
        """Apply full filtering pipeline to products.

        Applies filters in order:
        1. Filter by minimum discount (>= min_discount)
        2. Filter by minimum rating (>= min_rating)
        3. Balance sources (equal from each platform)
        4. Sort by profitability (discount * sales_count)
        5. Take top N products (default: 10)

        Args:
            products: List of raw products from API.

        Returns:
            List of top filtered and sorted products.
        """
        logger.info(
            "starting_product_filter",
            input_count=len(products),
            min_discount=self.min_discount,
            min_rating=self.min_rating,
            top_limit=self.top_limit,
        )

        # Balance sources with smart filtering
        # This applies discount/rating filters per-source and ensures
        # we get products from both Pinduoduo and Taobao
        result = self._balance_sources(list(products))

        # Final sort and limit (filtering already done in _balance_sources)
        result = self.sort_by_profitability(result)
        result = self.get_top_products(result)

        logger.info(
            "product_filter_complete",
            input_count=len(products),
            output_count=len(result),
        )

        return result

    def _balance_sources(self, products: Sequence[RawProduct]) -> list[RawProduct]:
        """Balance products from different sources with smart filtering.

        Takes equal number of products from each source (pinduoduo, taobao).
        Applies discount filter only to sources that have discount data.

        Args:
            products: List of products to balance.

        Returns:
            List with balanced source representation.
        """
        # Group by source
        by_source: dict[str, list[RawProduct]] = {}
        for p in products:
            source = getattr(p, 'source', 'pinduoduo')
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(p)

        # Calculate per-source limit
        num_sources = len(by_source)
        if num_sources == 0:
            return []

        per_source_limit = max(1, self.top_limit // num_sources)

        # Take from each source with smart filtering
        balanced = []
        for source, source_products in by_source.items():
            # Apply discount filter only if source has discount data
            # Taobao often has 0% discount, so skip discount filter for it
            has_discount_data = any(p.discount > 0 for p in source_products)

            if has_discount_data and self.min_discount > 0:
                # Apply discount filter
                filtered = [p for p in source_products if p.discount >= self.min_discount]
            else:
                # Skip discount filter for sources without discount data
                filtered = list(source_products)

            # Apply rating filter
            filtered = [p for p in filtered if p.rating >= self.min_rating]

            # Sort by profitability (or just price for sources without discount)
            if has_discount_data:
                sorted_source = sorted(
                    filtered,
                    key=lambda p: p.discount * p.sales_count,
                    reverse=True,
                )
            else:
                # For sources without discount, sort by sales count
                sorted_source = sorted(
                    filtered,
                    key=lambda p: p.sales_count,
                    reverse=True,
                )

            balanced.extend(sorted_source[:per_source_limit])

            logger.debug(
                "balanced_source",
                source=source,
                available=len(source_products),
                has_discount_data=has_discount_data,
                after_filter=len(filtered),
                selected=min(len(sorted_source), per_source_limit),
            )

        logger.info(
            "sources_balanced",
            sources=list(by_source.keys()),
            per_source_limit=per_source_limit,
            total_selected=len(balanced),
        )

        return balanced

    @staticmethod
    def calculate_profitability(product: RawProduct) -> int:
        """Calculate profitability score for a product.

        Args:
            product: Product to calculate score for.

        Returns:
            Profitability score (discount * sales_count).
        """
        return product.discount * product.sales_count
