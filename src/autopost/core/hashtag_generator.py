"""Hashtag generator for Instagram posts."""

from __future__ import annotations

import re
import random

import structlog

logger = structlog.get_logger(__name__)

# Minimum and maximum number of hashtags
MIN_HASHTAGS = 10
MAX_HASHTAGS = 15

# Base hashtags (always included)
BASE_HASHTAGS = [
    "бишкек",
    "кыргызстан",
    "доставкаизкитая",
    "тулпарэкспресс",
    "китай",
    "карго",
]

# Category-specific hashtags
CATEGORY_HASHTAGS: dict[str, list[str]] = {
    "electronics": [
        "техника",
        "гаджеты",
        "электроника",
        "смартфон",
        "наушники",
        "аксессуары",
        "гаджетыизкитая",
        "техникаизкитая",
    ],
    "clothing": [
        "одежда",
        "мода",
        "стиль",
        "fashion",
        "одеждаизкитая",
        "модабишкек",
        "стильнаяодежда",
        "тренды",
    ],
    "home": [
        "дом",
        "интерьер",
        "уют",
        "декор",
        "товарыдлядома",
        "домашнийуют",
        "длядома",
        "домизкитая",
    ],
    "beauty": [
        "красота",
        "косметика",
        "уход",
        "beauty",
        "косметикаизкитая",
        "уходзасобой",
        "бьютибишкек",
        "макияж",
    ],
    "kids": [
        "дети",
        "детскиетовары",
        "игрушки",
        "детям",
        "мама",
        "длядетей",
        "детскоеизкитая",
        "родителям",
    ],
    "auto": [
        "авто",
        "автотовары",
        "машина",
        "автоаксессуары",
        "тюнинг",
        "автобишкек",
        "длямашины",
        "автоизкитая",
    ],
}

# Generic hashtags for unknown categories
GENERIC_HASHTAGS = [
    "товарыизкитая",
    "выгодно",
    "скидки",
    "распродажа",
    "акция",
    "дешево",
    "качество",
    "хит",
]

# Category name mappings (Russian -> English key)
CATEGORY_MAPPING: dict[str, str] = {
    # Russian names
    "электроника": "electronics",
    "техника": "electronics",
    "гаджеты": "electronics",
    "одежда": "clothing",
    "мода": "clothing",
    "дом": "home",
    "интерьер": "home",
    "красота": "beauty",
    "косметика": "beauty",
    "дети": "kids",
    "детское": "kids",
    "игрушки": "kids",
    "авто": "auto",
    "автомобиль": "auto",
    # English names
    "electronics": "electronics",
    "clothing": "clothing",
    "clothes": "clothing",
    "home": "home",
    "beauty": "beauty",
    "kids": "kids",
    "children": "kids",
    "auto": "auto",
    "car": "auto",
}


class HashtagGenerator:
    """Generator for Instagram hashtags.

    Creates relevant hashtags based on product category and title.
    Always includes base hashtags and adds category-specific ones.

    Attributes:
        min_hashtags: Minimum number of hashtags to generate.
        max_hashtags: Maximum number of hashtags to generate.
    """

    def __init__(
        self,
        min_hashtags: int = MIN_HASHTAGS,
        max_hashtags: int = MAX_HASHTAGS,
    ) -> None:
        """Initialize HashtagGenerator.

        Args:
            min_hashtags: Minimum hashtags to return (default: 10).
            max_hashtags: Maximum hashtags to return (default: 15).
        """
        self.min_hashtags = min_hashtags
        self.max_hashtags = max_hashtags

    def generate(
        self,
        category: str | None = None,
        title: str | None = None,
    ) -> list[str]:
        """Generate hashtags for a product.

        Args:
            category: Product category (e.g., "electronics", "clothing").
            title: Product title for keyword extraction.

        Returns:
            List of 10-15 hashtags with # prefix.
        """
        logger.debug(
            "generating_hashtags",
            category=category,
            title=title[:50] if title else None,
        )

        # Start with base hashtags (always included)
        hashtags: list[str] = list(BASE_HASHTAGS)
        seen: set[str] = set(BASE_HASHTAGS)

        # Add category-specific hashtags
        if category:
            category_tags = self._get_category_hashtags(category)
            for tag in category_tags:
                if tag not in seen:
                    hashtags.append(tag)
                    seen.add(tag)

        # Extract keywords from title
        if title:
            title_tags = self._extract_title_hashtags(title)
            for tag in title_tags:
                if tag not in seen:
                    hashtags.append(tag)
                    seen.add(tag)

        # Add generic hashtags if needed
        if len(hashtags) < self.min_hashtags:
            for tag in GENERIC_HASHTAGS:
                if tag not in seen:
                    hashtags.append(tag)
                    seen.add(tag)
                if len(hashtags) >= self.max_hashtags:
                    break

        # Trim to max if exceeded
        if len(hashtags) > self.max_hashtags:
            # Keep base hashtags, randomly select from the rest
            base_count = len(BASE_HASHTAGS)
            extra = hashtags[base_count:]
            random.shuffle(extra)
            remaining_slots = self.max_hashtags - base_count
            hashtags = hashtags[:base_count] + extra[:remaining_slots]

        # Add # prefix
        result = [f"#{tag}" for tag in hashtags]

        logger.info(
            "hashtags_generated",
            count=len(result),
            category=category,
        )

        return result

    def _get_category_hashtags(self, category: str) -> list[str]:
        """Get hashtags for a specific category.

        Args:
            category: Category name (Russian or English).

        Returns:
            List of category-specific hashtags.
        """
        # Normalize category name
        category_lower = category.lower().strip()

        # Try direct mapping
        category_key = CATEGORY_MAPPING.get(category_lower)

        if not category_key:
            # Try to find partial match
            for name, key in CATEGORY_MAPPING.items():
                if name in category_lower or category_lower in name:
                    category_key = key
                    break

        if category_key and category_key in CATEGORY_HASHTAGS:
            return CATEGORY_HASHTAGS[category_key]

        logger.debug("unknown_category", category=category)
        return []

    def _extract_title_hashtags(self, title: str) -> list[str]:
        """Extract potential hashtags from product title.

        Args:
            title: Product title.

        Returns:
            List of extracted hashtags.
        """
        # Normalize title
        title_lower = title.lower()

        # Remove special characters, keep only letters and spaces
        cleaned = re.sub(r"[^a-zа-яё\s]", " ", title_lower)

        # Split into words
        words = cleaned.split()

        # Filter: only words 4-20 chars, no stop words
        stop_words = {
            "для", "или", "это", "как", "что", "при", "под", "над",
            "без", "про", "через", "после", "перед", "между",
            "the", "and", "for", "with", "from", "this", "that",
        }

        hashtags = []
        for word in words:
            word = word.strip()
            if (
                len(word) >= 4
                and len(word) <= 20
                and word not in stop_words
                and word not in BASE_HASHTAGS
            ):
                hashtags.append(word)

        # Return unique, limited number
        seen: set[str] = set()
        unique = []
        for tag in hashtags:
            if tag not in seen:
                unique.append(tag)
                seen.add(tag)
            if len(unique) >= 5:  # Max 5 from title
                break

        return unique

    def format_for_post(self, hashtags: list[str]) -> str:
        """Format hashtags as a string for Instagram post.

        Args:
            hashtags: List of hashtags with # prefix.

        Returns:
            Space-separated string of hashtags.
        """
        return " ".join(hashtags)

    @staticmethod
    def get_base_hashtags() -> list[str]:
        """Get base hashtags (always included).

        Returns:
            List of base hashtags without # prefix.
        """
        return list(BASE_HASHTAGS)

    @staticmethod
    def get_supported_categories() -> list[str]:
        """Get list of supported category keys.

        Returns:
            List of supported category names.
        """
        return list(CATEGORY_HASHTAGS.keys())
