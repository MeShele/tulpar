"""Daily pipeline orchestration for automated content publishing."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import structlog
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncSession

from src.autopost.core.content_formatter import ContentFormatter
from src.autopost.core.hashtag_generator import HashtagGenerator
from src.autopost.core.price_converter import PriceConverter
from src.autopost.core.product_card import ProductCardGenerator
from src.autopost.core.product_filter import ProductFilter
from src.autopost.db.models import PostStatus
from src.autopost.db.repositories.post_repository import PostRepository
from src.autopost.db.repositories.product_repository import ProductRepository
from src.autopost.exceptions import PipelineError
from src.autopost.models import Product, RawProduct
from src.autopost.services.currency import CurrencyService
from src.autopost.services.image_service import ImageService
from src.autopost.services.instagram_service import InstagramService
from src.autopost.services.notification_service import ErrorInfo, NotificationService, PostInfo
from src.autopost.services.openai_service import OpenAIService
from src.autopost.services.pinduoduo import (
    CATEGORY_KEYWORDS,
    PinduoduoService,
    ProductCategory,
    get_daily_categories,
    get_daily_category,
)
from src.autopost.services.taobao_service import TaobaoService
from src.autopost.services.telegram_service import TelegramService

# Products per source (fetch more to ensure 10 after filtering)
PRODUCTS_PER_SOURCE = 10  # Target 10 from each source, filter will reduce to final 10


class FallbackType(str, Enum):
    """Types of fallback strategies used in pipeline."""

    PINDUODUO_CACHED = "pinduoduo_cached"  # Used cached products from DB
    CURRENCY_DB = "currency_db"  # Used last known rate from DB
    OPENAI_TEMPLATE = "openai_template"  # Used template text instead of AI
    INSTAGRAM_SKIPPED = "instagram_skipped"  # Published only to Telegram

logger = structlog.get_logger(__name__)


class PipelineStage(str, Enum):
    """Stages of the daily pipeline."""

    FETCH_PRODUCTS = "fetch_products"
    CONVERT_PRICES = "convert_prices"
    FILTER_PRODUCTS = "filter_products"
    GENERATE_CONTENT = "generate_content"
    DOWNLOAD_IMAGES = "download_images"
    CREATE_CARDS = "create_cards"
    PUBLISH_TELEGRAM = "publish_telegram"
    PUBLISH_INSTAGRAM = "publish_instagram"
    SAVE_TO_DB = "save_to_db"
    NOTIFY_OWNER = "notify_owner"


@dataclass
class StageResult:
    """Result of a pipeline stage execution."""

    stage: PipelineStage
    success: bool
    duration_ms: float
    data: Any = None
    error: Optional[str] = None


@dataclass
class PipelineResult:
    """Result of the full pipeline execution."""

    success: bool
    total_duration_ms: float
    stages: list[StageResult] = field(default_factory=list)
    telegram_message_id: Optional[int] = None
    instagram_post_id: Optional[str] = None
    products_count: int = 0
    error: Optional[str] = None
    fallbacks_used: list[FallbackType] = field(default_factory=list)

    @property
    def failed_stage(self) -> Optional[PipelineStage]:
        """Get the first failed stage, if any."""
        for stage in self.stages:
            if not stage.success:
                return stage.stage
        return None

    @property
    def used_fallbacks(self) -> bool:
        """Check if any fallback strategies were used."""
        return len(self.fallbacks_used) > 0


class DailyPipeline:
    """Orchestrates the daily content publishing pipeline.

    Executes stages in sequence:
    1. Fetch products from Pinduoduo
    2. Convert prices to KGS
    3. Filter top products
    4. Generate content (descriptions)
    5. Download images
    6. Create product cards
    7. Publish to Telegram
    8. Publish to Instagram
    9. Save to database
    10. Notify owner

    Each stage is logged with timing information.
    """

    def __init__(
        self,
        pinduoduo_service: PinduoduoService,
        currency_service: CurrencyService,
        taobao_service: TaobaoService | None = None,
        text_service: OpenAIService | None = None,
        image_service: ImageService | None = None,
        telegram_service: TelegramService | None = None,
        instagram_service: InstagramService | None = None,
        notification_service: NotificationService | None = None,
        session: AsyncSession | None = None,
        product_filter: Optional[ProductFilter] = None,
        price_converter: Optional[type[PriceConverter]] = None,
        content_formatter: Optional[type[ContentFormatter]] = None,
        hashtag_generator: Optional[HashtagGenerator] = None,
        product_card_creator: Optional[ProductCardGenerator] = None,
        product_repository: Optional[ProductRepository] = None,
    ) -> None:
        """Initialize the daily pipeline.

        Args:
            pinduoduo_service: Service for fetching products from Pinduoduo.
            currency_service: Service for currency conversion.
            taobao_service: Service for fetching products from Taobao.
            text_service: Service for text generation (OpenAI via RapidAPI).
            image_service: Service for image download.
            telegram_service: Service for Telegram publishing.
            instagram_service: Service for Instagram publishing.
            notification_service: Service for owner notifications.
            session: Database session for persistence.
            product_filter: Optional custom product filter.
            price_converter: Optional custom price converter class.
            content_formatter: Optional custom content formatter class.
            hashtag_generator: Optional custom hashtag generator class.
            product_card_creator: Optional custom card creator.
            product_repository: Optional product repository for fallback.
        """
        self.pinduoduo = pinduoduo_service
        self.taobao = taobao_service
        self.currency = currency_service
        # Use OpenAI via RapidAPI for text generation
        self.text_service = text_service or OpenAIService()
        self.image = image_service
        self.telegram = telegram_service
        self.instagram = instagram_service
        self.notification = notification_service
        self.session = session

        self.product_filter = product_filter or ProductFilter()
        self.price_converter = price_converter or PriceConverter
        self.content_formatter = content_formatter or ContentFormatter
        self.hashtag_generator = hashtag_generator or HashtagGenerator()
        self.card_creator = product_card_creator or ProductCardGenerator()

        self.post_repository = PostRepository(session)
        self.product_repository = product_repository or ProductRepository(session)

        # Track fallbacks used during pipeline execution
        self._fallbacks_used: list[FallbackType] = []

    async def run(
        self,
        category: ProductCategory | str | None = None,
    ) -> PipelineResult:
        """Execute the full daily pipeline.

        Fetches 5 products from Pinduoduo + 5 from Taobao based on daily categories.

        Args:
            category: Optional category override for single-source fetch.

        Returns:
            PipelineResult with execution details.
        """
        start_time = time.monotonic()
        stages: list[StageResult] = []

        # Reset fallbacks tracking for this run
        self._fallbacks_used = []

        # Get today's categories for rotation
        categories = get_daily_categories()

        logger.info(
            "pipeline_starting",
            categories=categories,
            products_per_source=PRODUCTS_PER_SOURCE,
            sources=["pinduoduo", "taobao"],
        )

        try:
            # Stage 1: Fetch products from both Pinduoduo and Taobao
            raw_products, stage = await self._fetch_products_dual(categories)
            stages.append(stage)
            if not stage.success:
                return self._build_failed_result(stages, start_time, stage.error)

            # Stage 2: Get exchange rate and convert prices
            products, stage = await self._convert_prices(raw_products)
            stages.append(stage)
            if not stage.success:
                return self._build_failed_result(stages, start_time, stage.error)

            # Stage 3: Filter products
            filtered_products, stage = self._filter_products(products)
            stages.append(stage)
            if not stage.success:
                return self._build_failed_result(stages, start_time, stage.error)

            # Stage 4: Generate descriptions
            descriptions, stage = await self._generate_content(filtered_products)
            stages.append(stage)
            if not stage.success:
                return self._build_failed_result(stages, start_time, stage.error)

            # Stage 5: Download images
            image_paths, stage = await self._download_images(filtered_products)
            stages.append(stage)
            if not stage.success:
                return self._build_failed_result(stages, start_time, stage.error)

            # Stage 6: Create product cards
            card_paths, stage = self._create_cards(filtered_products, image_paths)
            stages.append(stage)
            if not stage.success:
                return self._build_failed_result(stages, start_time, stage.error)

            # Stage 7: Publish to Telegram
            telegram_id, stage = await self._publish_telegram(
                filtered_products, card_paths, descriptions
            )
            stages.append(stage)
            if not stage.success:
                return self._build_failed_result(stages, start_time, stage.error)

            # Stage 8: Publish to Instagram
            instagram_id, stage = await self._publish_instagram(
                filtered_products, card_paths, descriptions
            )
            stages.append(stage)
            # Instagram failure is non-critical, continue anyway

            # Stage 9: Save to database
            post_id, stage = await self._save_to_db(
                filtered_products, telegram_id, instagram_id
            )
            stages.append(stage)

            # Stage 10: Notify owner
            stage = await self._notify_owner(
                filtered_products, telegram_id, instagram_id, stages
            )
            stages.append(stage)

            total_duration = (time.monotonic() - start_time) * 1000

            # Track Instagram fallback
            if instagram_id is None and telegram_id is not None:
                if FallbackType.INSTAGRAM_SKIPPED not in self._fallbacks_used:
                    self._fallbacks_used.append(FallbackType.INSTAGRAM_SKIPPED)

            logger.info(
                "pipeline_completed",
                total_duration_ms=total_duration,
                products_count=len(filtered_products),
                telegram_id=telegram_id,
                instagram_id=instagram_id,
                fallbacks_used=[f.value for f in self._fallbacks_used],
            )

            # Notify owner about partial failures if fallbacks were used
            if self._fallbacks_used:
                await self._notify_partial_failure(
                    filtered_products, telegram_id, instagram_id
                )

            return PipelineResult(
                success=True,
                total_duration_ms=total_duration,
                stages=stages,
                telegram_message_id=telegram_id,
                instagram_post_id=instagram_id,
                products_count=len(filtered_products),
                fallbacks_used=self._fallbacks_used.copy(),
            )

        except Exception as e:
            logger.exception("pipeline_failed", error=str(e))

            total_duration = (time.monotonic() - start_time) * 1000

            # Notify owner about failure
            await self._notify_error(str(e), stages)

            return PipelineResult(
                success=False,
                total_duration_ms=total_duration,
                stages=stages,
                error=str(e),
                fallbacks_used=self._fallbacks_used.copy(),
            )

    async def _fetch_products(
        self, category: ProductCategory
    ) -> tuple[list[RawProduct], StageResult]:
        """Stage 1: Fetch products from Pinduoduo.

        Falls back to cached products from database if API fails.
        """
        start = time.monotonic()
        api_error: Optional[str] = None

        # Handle both enum and string category values
        category_str = category.value if isinstance(category, ProductCategory) else str(category)

        try:
            result = await self.pinduoduo.fetch_products(category)

            if result.success and result.data:
                duration = (time.monotonic() - start) * 1000

                # Save products to DB for future fallback
                await self.product_repository.save_products(result.data, category_str)

                logger.info(
                    "stage_fetch_products_complete",
                    count=len(result.data),
                    duration_ms=duration,
                    source="api",
                )

                return result.data, StageResult(
                    stage=PipelineStage.FETCH_PRODUCTS,
                    success=True,
                    duration_ms=duration,
                    data=len(result.data),
                )

            api_error = result.error or "No products returned"

        except Exception as e:
            api_error = str(e)
            logger.warning(
                "pinduoduo_api_failed",
                error=api_error,
                category=category_str,
            )

        # Fallback to cached products from database
        try:
            cached_products = await self.product_repository.get_cached_products(
                category_str, limit=100  # Get more products for filtering
            )

            duration = (time.monotonic() - start) * 1000

            if cached_products:
                self._fallbacks_used.append(FallbackType.PINDUODUO_CACHED)

                logger.info(
                    "stage_fetch_products_complete",
                    count=len(cached_products),
                    duration_ms=duration,
                    source="cache",
                    original_error=api_error,
                )

                return cached_products, StageResult(
                    stage=PipelineStage.FETCH_PRODUCTS,
                    success=True,
                    duration_ms=duration,
                    data=len(cached_products),
                )

            # No cached products available
            return [], StageResult(
                stage=PipelineStage.FETCH_PRODUCTS,
                success=False,
                duration_ms=duration,
                error=f"API failed: {api_error}. No cached products available.",
            )

        except Exception as cache_error:
            duration = (time.monotonic() - start) * 1000
            return [], StageResult(
                stage=PipelineStage.FETCH_PRODUCTS,
                success=False,
                duration_ms=duration,
                error=f"API failed: {api_error}. Cache failed: {cache_error}",
            )

    async def _fetch_products_multi(
        self, categories: list[str]
    ) -> tuple[list[RawProduct], StageResult]:
        """Stage 1: Fetch products from multiple categories.

        Fetches products from each category. We fetch more than needed
        to ensure enough products pass filtering (rating >= 4.5).

        Args:
            categories: List of category names to fetch from.

        Returns:
            Tuple of (products list, stage result).
        """
        start = time.monotonic()
        all_products: list[RawProduct] = []
        category_results: dict[str, int] = {}

        # Fetch 10 products per category to ensure enough pass filters
        fetch_per_category = 10

        for i, category in enumerate(categories):
            try:
                # Fetch more products than needed to allow for filtering losses
                result = await self.pinduoduo.fetch_products(category, page_size=fetch_per_category)

                if result.success and result.data:
                    # Take all fetched products - filtering will happen later
                    products = result.data
                    all_products.extend(products)
                    category_results[category] = len(products)

                    # Save to cache for fallback
                    await self.product_repository.save_products(products, category)

                    logger.info(
                        "category_fetch_complete",
                        category=category,
                        fetched=len(products),
                    )
                else:
                    # Try fallback from cache
                    cached = await self.product_repository.get_cached_products(
                        category, limit=fetch_per_category
                    )
                    if cached:
                        all_products.extend(cached)
                        category_results[category] = len(cached)
                        self._fallbacks_used.append(FallbackType.PINDUODUO_CACHED)
                        logger.info(
                            "category_fetch_from_cache",
                            category=category,
                            count=len(cached),
                        )
                    else:
                        category_results[category] = 0
                        logger.warning(
                            "category_fetch_failed",
                            category=category,
                            error=result.error,
                        )

            except Exception as e:
                logger.warning(
                    "category_fetch_exception",
                    category=category,
                    error=str(e),
                )
                category_results[category] = 0

        duration = (time.monotonic() - start) * 1000

        if not all_products:
            return [], StageResult(
                stage=PipelineStage.FETCH_PRODUCTS,
                success=False,
                duration_ms=duration,
                error=f"No products fetched from any category: {category_results}",
            )

        logger.info(
            "stage_fetch_products_multi_complete",
            total=len(all_products),
            by_category=category_results,
            duration_ms=duration,
        )

        return all_products, StageResult(
            stage=PipelineStage.FETCH_PRODUCTS,
            success=True,
            duration_ms=duration,
            data={"total": len(all_products), "by_category": category_results},
        )

    async def _fetch_products_dual(
        self, categories: list[str]
    ) -> tuple[list[RawProduct], StageResult]:
        """Stage 1: Fetch products from Pinduoduo across ALL daily categories.

        Fetches products from each category to ensure variety in the final selection.
        With 3 categories per day, fetches ~10 products per category.

        Args:
            categories: List of category names for keyword search.

        Returns:
            Tuple of (products list, stage result).
        """
        start = time.monotonic()
        all_products: list[RawProduct] = []
        category_results: dict[str, int] = {}

        # Ensure we have categories
        if not categories:
            categories = ["headphones", "bags", "beauty"]

        # Fetch products per category (aim for variety)
        products_per_category = max(10, 30 // len(categories))

        logger.info(
            "fetching_from_multiple_categories",
            categories=categories,
            products_per_category=products_per_category,
        )

        # Fetch from each category
        for category in categories:
            try:
                pdd_result = await self.pinduoduo.fetch_products(
                    category, page_size=products_per_category
                )
                if pdd_result.success and pdd_result.data:
                    all_products.extend(pdd_result.data)
                    category_results[category] = len(pdd_result.data)
                    logger.info(
                        "category_fetch_complete",
                        category=category,
                        count=len(pdd_result.data),
                    )
                else:
                    category_results[category] = 0
                    logger.warning(
                        "category_fetch_empty",
                        category=category,
                    )
            except Exception as e:
                category_results[category] = 0
                logger.warning(
                    "category_fetch_error",
                    category=category,
                    error=str(e),
                )

        # Fetch from Taobao if available (disabled for now)
        if self.taobao:
            try:
                # Pick one category for Taobao to add variety
                taobao_category = random.choice(categories)
                taobao_keyword = taobao_category.replace("_", " ")
                taobao_result = await self.taobao.fetch_products(
                    taobao_keyword, page_size=10
                )
                if taobao_result.success and taobao_result.data:
                    all_products.extend(taobao_result.data)
                    category_results["taobao"] = len(taobao_result.data)
                    logger.info(
                        "taobao_fetch_complete",
                        count=len(taobao_result.data),
                    )
            except Exception as e:
                logger.warning("taobao_fetch_error", error=str(e))

        duration = (time.monotonic() - start) * 1000

        if not all_products:
            return [], StageResult(
                stage=PipelineStage.FETCH_PRODUCTS,
                success=False,
                duration_ms=duration,
                error=f"No products fetched from any category: {category_results}",
            )

        # Shuffle to mix products from all categories
        random.shuffle(all_products)

        logger.info(
            "stage_fetch_products_complete",
            total=len(all_products),
            by_category=category_results,
            duration_ms=duration,
        )

        return all_products, StageResult(
            stage=PipelineStage.FETCH_PRODUCTS,
            success=True,
            duration_ms=duration,
            data={"total": len(all_products), "by_category": category_results},
        )

    async def _convert_prices(
        self, raw_products: list[RawProduct]
    ) -> tuple[list[Product], StageResult]:
        """Stage 2: Convert prices to KGS and generate marketing old_price."""
        start = time.monotonic()

        try:
            # Get exchange rate
            rate_result = await self.currency.get_rate("CNY", "KGS")
            if not rate_result.success or rate_result.data is None:
                duration = (time.monotonic() - start) * 1000
                return [], StageResult(
                    stage=PipelineStage.CONVERT_PRICES,
                    success=False,
                    duration_ms=duration,
                    error=rate_result.error or "Failed to get exchange rate",
                )

            # Convert prices
            products = self.price_converter.convert_products(
                raw_products, rate_result.data
            )

            # Generate marketing old_price and discount for each product
            enhanced_products = []
            for product in products:
                # Generate old_price (30-50% markup)
                markup = Decimal(str(random.uniform(1.3, 1.5)))
                old_price = round(product.price_kgs * markup, -1)  # Round to nearest 10

                # Calculate discount from old_price
                discount = int((1 - float(product.price_kgs / old_price)) * 100)

                # Create new product with old_price_kgs
                enhanced = Product(
                    id=product.id,
                    title=product.title,
                    price_cny=product.price_cny,
                    price_kgs=product.price_kgs,
                    old_price_kgs=old_price,
                    image_url=product.image_url,
                    rating=product.rating,
                    discount=discount,  # Use calculated discount
                    sales_count=product.sales_count,
                )
                enhanced_products.append(enhanced)

            duration = (time.monotonic() - start) * 1000

            logger.info(
                "stage_convert_prices_complete",
                count=len(enhanced_products),
                rate=float(rate_result.data),
                duration_ms=duration,
            )

            return enhanced_products, StageResult(
                stage=PipelineStage.CONVERT_PRICES,
                success=True,
                duration_ms=duration,
                data=float(rate_result.data),
            )

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return [], StageResult(
                stage=PipelineStage.CONVERT_PRICES,
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    def _filter_products(
        self, products: list[Product]
    ) -> tuple[list[Product], StageResult]:
        """Stage 3: Filter and rank products."""
        start = time.monotonic()

        try:
            # Convert Product to RawProduct for filtering
            # Then filter and convert back
            # Actually ProductFilter works with RawProduct, but we already converted
            # We'll filter based on the same criteria

            filtered = [
                p for p in products
                if p.discount >= self.product_filter.min_discount
                and p.rating >= self.product_filter.min_rating
            ]

            # Sort by profitability
            filtered.sort(key=lambda p: p.discount * p.sales_count, reverse=True)

            # Take top N
            filtered = filtered[:self.product_filter.top_limit]

            duration = (time.monotonic() - start) * 1000

            logger.info(
                "stage_filter_products_complete",
                input_count=len(products),
                output_count=len(filtered),
                duration_ms=duration,
            )

            if not filtered:
                return [], StageResult(
                    stage=PipelineStage.FILTER_PRODUCTS,
                    success=False,
                    duration_ms=duration,
                    error="No products passed filters",
                )

            return filtered, StageResult(
                stage=PipelineStage.FILTER_PRODUCTS,
                success=True,
                duration_ms=duration,
                data=len(filtered),
            )

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return [], StageResult(
                stage=PipelineStage.FILTER_PRODUCTS,
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    async def _generate_content(
        self, products: list[Product]
    ) -> tuple[list[str], StageResult]:
        """Stage 4: Generate descriptions for products."""
        start = time.monotonic()

        try:
            results = await self.text_service.generate_descriptions_batch(products)

            descriptions = []
            for i, result in enumerate(results):
                if result.success and result.data:
                    descriptions.append(result.data)
                else:
                    # Use fallback description
                    descriptions.append(
                        f"🔥 {products[i].title}\n💰 Всего {int(products[i].price_kgs)} сом!"
                    )

            duration = (time.monotonic() - start) * 1000

            logger.info(
                "stage_generate_content_complete",
                count=len(descriptions),
                duration_ms=duration,
            )

            return descriptions, StageResult(
                stage=PipelineStage.GENERATE_CONTENT,
                success=True,
                duration_ms=duration,
                data=len(descriptions),
            )

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return [], StageResult(
                stage=PipelineStage.GENERATE_CONTENT,
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    async def _download_images(
        self, products: list[Product]
    ) -> tuple[list[Path], StageResult]:
        """Stage 5: Download product images."""
        start = time.monotonic()

        try:
            image_urls = [p.image_url for p in products]
            results = await self.image.download_batch(image_urls)

            paths = []
            for i, result in enumerate(results):
                if result.success and result.data:
                    paths.append(result.data)
                else:
                    logger.warning(
                        "image_download_failed",
                        product_id=products[i].id,
                        error=result.error,
                    )

            duration = (time.monotonic() - start) * 1000

            if not paths:
                return [], StageResult(
                    stage=PipelineStage.DOWNLOAD_IMAGES,
                    success=False,
                    duration_ms=duration,
                    error="Failed to download any images",
                )

            logger.info(
                "stage_download_images_complete",
                count=len(paths),
                duration_ms=duration,
            )

            return paths, StageResult(
                stage=PipelineStage.DOWNLOAD_IMAGES,
                success=True,
                duration_ms=duration,
                data=len(paths),
            )

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return [], StageResult(
                stage=PipelineStage.DOWNLOAD_IMAGES,
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    def _create_cards(
        self, products: list[Product], image_paths: list[Path]
    ) -> tuple[list[Path], StageResult]:
        """Stage 6: Create product cards with prices."""
        start = time.monotonic()

        try:
            card_paths = []
            min_count = min(len(products), len(image_paths))

            for i in range(min_count):
                product = products[i]
                image_path = image_paths[i]

                try:
                    card_path = self.card_creator.create_card(
                        image_path=image_path,
                        price_kgs=int(product.price_kgs),
                        discount_percent=product.discount,
                        old_price_kgs=int(product.old_price_kgs) if product.old_price_kgs else None,
                        source=product.source,
                    )
                    card_paths.append(card_path)
                except Exception as card_error:
                    logger.warning(
                        "card_creation_failed",
                        product_id=product.id,
                        error=str(card_error),
                    )
                    # Use original image if card creation fails
                    card_paths.append(image_path)

            duration = (time.monotonic() - start) * 1000

            logger.info(
                "stage_create_cards_complete",
                count=len(card_paths),
                duration_ms=duration,
            )

            return card_paths, StageResult(
                stage=PipelineStage.CREATE_CARDS,
                success=True,
                duration_ms=duration,
                data=len(card_paths),
            )

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return [], StageResult(
                stage=PipelineStage.CREATE_CARDS,
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    async def _publish_telegram(
        self,
        products: list[Product],
        card_paths: list[Path],
        descriptions: list[str],
    ) -> tuple[Optional[int], StageResult]:
        """Stage 7: Publish to Telegram.

        Sends an intro message, then a media group (album) where each photo
        has its own caption visible when tapped.
        """
        start = time.monotonic()

        try:
            # Step 1: Send intro message
            intro_text = (
                "🔥 <b>Горячая подборка товаров!</b>\n\n"
                "Нажмите на фото, чтобы увидеть описание и цену 👇"
            )
            intro_result = await self.telegram.send_message(
                text=intro_text,
                parse_mode=ParseMode.HTML,
            )

            if not intro_result.success:
                logger.warning("intro_message_failed", error=intro_result.error)

            # Step 2: Build captions for each photo
            captions = []
            for i, product in enumerate(products[:len(card_paths)]):
                # Use generated description if available
                if i < len(descriptions) and descriptions[i]:
                    description = descriptions[i]
                else:
                    description = f"🔥 {product.title}"

                # Calculate old price for display
                old_price = int(product.old_price_kgs) if product.old_price_kgs > 0 else int(int(product.price_kgs) * 1.4)
                new_price = int(product.price_kgs)
                savings = old_price - new_price

                # Format price block with HTML: strikethrough old price, bold new price
                price_block = (
                    f"\n\n💰 <s>{old_price} сом</s> → <b>{new_price} сом</b>"
                    f"\n🔥 Экономия: {savings} сом!"
                )

                # Combine description + price block
                caption = f"{description}{price_block}"

                # Telegram caption limit is 1024 chars
                if len(caption) > 1024:
                    # Truncate description to fit
                    max_desc_len = 1024 - len(price_block) - 10
                    description = description[:max_desc_len] + "..."
                    caption = f"{description}{price_block}"

                captions.append(caption)

            # Step 3: Send media group (album) - all photos have captions
            # First photo's caption shows in feed, all captions visible when tapped
            result = await self.telegram.send_media_group(
                images=card_paths,
                captions=captions,
                parse_mode=ParseMode.HTML,
            )

            duration = (time.monotonic() - start) * 1000

            if not result.success:
                return None, StageResult(
                    stage=PipelineStage.PUBLISH_TELEGRAM,
                    success=False,
                    duration_ms=duration,
                    error=result.error,
                )

            # result.data is a list of message IDs (one per image in media group)
            message_ids = result.data
            message_id = message_ids[0] if isinstance(message_ids, list) and message_ids else message_ids

            logger.info(
                "stage_publish_telegram_complete",
                message_id=message_id,
                all_message_ids=message_ids,
                duration_ms=duration,
            )

            return message_id, StageResult(
                stage=PipelineStage.PUBLISH_TELEGRAM,
                success=True,
                duration_ms=duration,
                data=message_id,
            )

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return None, StageResult(
                stage=PipelineStage.PUBLISH_TELEGRAM,
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    async def _publish_instagram(
        self,
        products: list[Product],
        card_paths: list[Path],
        descriptions: list[str],
    ) -> tuple[Optional[str], StageResult]:
        """Stage 8: Publish to Instagram."""
        start = time.monotonic()

        # Skip if Instagram service not configured
        if not self.instagram:
            logger.info("instagram_skipped", reason="service_not_configured")
            return None, StageResult(
                stage=PipelineStage.PUBLISH_INSTAGRAM,
                success=True,
                duration_ms=(time.monotonic() - start) * 1000,
                data="skipped",
            )

        try:
            # Generate hashtags
            category = "electronics"  # Default category
            hashtags = self.hashtag_generator.generate(category=category)

            # Convert products to dict format for ContentFormatter
            products_dict = [
                {
                    "name": p.title,
                    "price": int(p.price_kgs),
                    "discount": p.discount,
                }
                for p in products
            ]

            # Format caption with hashtags
            caption = self.content_formatter.build_instagram_post(
                products=products_dict,
                hashtags=hashtags,
            )

            # Convert paths to URLs (Instagram needs public URLs)
            # For now, we'll use the hosted image URLs
            image_urls = [
                f"file://{path.absolute()}" for path in card_paths
            ]

            result = await self.instagram.publish_carousel(
                image_urls=image_urls,
                caption=caption,
            )

            duration = (time.monotonic() - start) * 1000

            if not result.success:
                logger.warning(
                    "instagram_publish_failed",
                    error=result.error,
                )
                return None, StageResult(
                    stage=PipelineStage.PUBLISH_INSTAGRAM,
                    success=False,
                    duration_ms=duration,
                    error=result.error,
                )

            post_id = result.data
            logger.info(
                "stage_publish_instagram_complete",
                post_id=post_id,
                duration_ms=duration,
            )

            return post_id, StageResult(
                stage=PipelineStage.PUBLISH_INSTAGRAM,
                success=True,
                duration_ms=duration,
                data=post_id,
            )

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.warning(
                "instagram_publish_exception",
                error=str(e),
            )
            return None, StageResult(
                stage=PipelineStage.PUBLISH_INSTAGRAM,
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    async def _save_to_db(
        self,
        products: list[Product],
        telegram_id: Optional[int],
        instagram_id: Optional[str],
    ) -> tuple[Optional[int], StageResult]:
        """Stage 9: Save post to database."""
        start = time.monotonic()

        try:
            # Determine status
            if telegram_id and instagram_id:
                status = PostStatus.PUBLISHED
            elif telegram_id:
                if instagram_id is None:
                    status = PostStatus.INSTAGRAM_FAILED
                else:
                    status = PostStatus.TELEGRAM_ONLY
            else:
                status = PostStatus.PENDING

            # Convert products to JSON-serializable format
            products_json = [
                {
                    "id": p.id,
                    "title": p.title,
                    "price_cny": float(p.price_cny),
                    "price_kgs": float(p.price_kgs),
                    "discount": p.discount,
                    "rating": p.rating,
                    "source": p.source,
                }
                for p in products
            ]

            post = await self.post_repository.create_post(
                products_json=products_json,
                telegram_message_id=telegram_id,
                instagram_post_id=instagram_id,
                status=status,
            )

            duration = (time.monotonic() - start) * 1000

            logger.info(
                "stage_save_to_db_complete",
                post_id=post.id,
                status=status.value,
                duration_ms=duration,
            )

            return post.id, StageResult(
                stage=PipelineStage.SAVE_TO_DB,
                success=True,
                duration_ms=duration,
                data=post.id,
            )

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.error(
                "save_to_db_failed",
                error=str(e),
            )
            return None, StageResult(
                stage=PipelineStage.SAVE_TO_DB,
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    async def _notify_owner(
        self,
        products: list[Product],
        telegram_id: Optional[int],
        instagram_id: Optional[str],
        stages: list[StageResult],
    ) -> StageResult:
        """Stage 10: Notify owner about publication."""
        start = time.monotonic()

        try:
            # Calculate total duration from stages
            total_duration = sum(s.duration_ms for s in stages)

            post_info = PostInfo(
                message_id=telegram_id or 0,
                product_count=len(products),
                channel_id="",  # Will be filled by the service
            )

            await self.notification.notify_success(post_info)

            duration = (time.monotonic() - start) * 1000

            logger.info(
                "stage_notify_owner_complete",
                duration_ms=duration,
            )

            return StageResult(
                stage=PipelineStage.NOTIFY_OWNER,
                success=True,
                duration_ms=duration,
            )

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.warning(
                "notify_owner_failed",
                error=str(e),
            )
            return StageResult(
                stage=PipelineStage.NOTIFY_OWNER,
                success=False,
                duration_ms=duration,
                error=str(e),
            )

    async def _notify_error(
        self, error: str, stages: list[StageResult]
    ) -> None:
        """Notify owner about pipeline failure."""
        try:
            failed_stage = None
            for stage in stages:
                if not stage.success:
                    failed_stage = stage.stage.value
                    break

            error_info = ErrorInfo(
                message=error,
                stage=failed_stage or "unknown",
            )

            await self.notification.notify_error(error_info)

        except Exception as e:
            logger.error(
                "error_notification_failed",
                error=str(e),
            )

    async def _notify_partial_failure(
        self,
        products: list[Product],
        telegram_id: Optional[int],
        instagram_id: Optional[str],
    ) -> None:
        """Notify owner about partial failures (fallbacks used).

        Sends a message to the owner describing which fallback strategies
        were used during pipeline execution.
        """
        try:
            fallback_descriptions = {
                FallbackType.PINDUODUO_CACHED: "Pinduoduo API недоступен → использованы кэшированные товары",
                FallbackType.CURRENCY_DB: "Currency API недоступен → использован последний известный курс",
                FallbackType.OPENAI_TEMPLATE: "OpenAI API недоступен → использованы шаблоны текста",
                FallbackType.INSTAGRAM_SKIPPED: "Instagram API недоступен → публикация только в Telegram",
            }

            messages = [
                fallback_descriptions.get(f, f.value)
                for f in self._fallbacks_used
            ]

            error_info = ErrorInfo(
                message=f"⚠️ Частичный сбой при публикации:\n" + "\n".join(f"• {m}" for m in messages),
                stage="fallback",
            )

            await self.notification.notify_error(error_info)

            logger.info(
                "partial_failure_notification_sent",
                fallbacks=[f.value for f in self._fallbacks_used],
            )

        except Exception as e:
            logger.error(
                "partial_failure_notification_failed",
                error=str(e),
            )

    def _build_failed_result(
        self,
        stages: list[StageResult],
        start_time: float,
        error: Optional[str],
    ) -> PipelineResult:
        """Build a failed pipeline result."""
        total_duration = (time.monotonic() - start_time) * 1000

        return PipelineResult(
            success=False,
            total_duration_ms=total_duration,
            stages=stages,
            error=error,
            fallbacks_used=self._fallbacks_used.copy(),
        )
