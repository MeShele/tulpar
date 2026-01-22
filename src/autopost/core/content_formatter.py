"""Content formatter for Telegram and Instagram posts."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass


# Default post title with emoji
DEFAULT_TITLE = "🔥 ТОП-10 ТОВАРОВ ДНЯ"

# Default call-to-action footer for Telegram
DEFAULT_CTA = """📦 Доставка 7-14 дней
📱 Заказать: @tulpar_express
🌐 te.kg"""

# Instagram-specific constants
MAX_INSTAGRAM_CAPTION_LENGTH = 2200
DEFAULT_INSTAGRAM_CONTACT = """📲 Заказ: @tulpar_express или te.kg
📦 Доставка 7-14 дней"""

# Index emoji numbers for Instagram (no HTML support)
INDEX_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


@dataclass
class ProductInfo:
    """Product information for formatting.

    Attributes:
        name: Product name.
        price: Current price in KGS.
        old_price: Original price before discount (optional).
        discount: Discount percentage (optional).
    """

    name: str
    price: int
    old_price: int | None = None
    discount: int | None = None


class ContentFormatter:
    """Formatter for Telegram post content.

    Creates beautifully formatted posts with:
    - Title with emoji
    - Product list with prices
    - Strikethrough old prices
    - Bold current prices
    - Call-to-action footer
    """

    @staticmethod
    def escape_html(text: str) -> str:
        """Escape HTML special characters.

        Args:
            text: Text to escape.

        Returns:
            Escaped text safe for HTML.
        """
        return html.escape(text)

    @staticmethod
    def format_price(price: int) -> str:
        """Format price with thousand separators.

        Args:
            price: Price in KGS.

        Returns:
            Formatted price string (e.g., "1 299 сом").
        """
        return f"{price:,} сом".replace(",", " ")

    @classmethod
    def format_product_line(
        cls,
        index: int,
        product: ProductInfo,
    ) -> str:
        """Format a single product line.

        Args:
            index: Product number (1-based).
            product: Product information.

        Returns:
            Formatted product line with HTML markup.
        """
        name = cls.escape_html(product.name)
        current_price = cls.format_price(product.price)

        lines = [f"{index}. {name}"]

        if product.old_price and product.old_price > product.price:
            old_price_str = cls.format_price(product.old_price)
            discount_str = ""
            if product.discount and product.discount > 0:
                discount_str = f" (-{product.discount}%)"
            lines.append(
                f"   <s>{old_price_str}</s> → <b>{current_price}</b>{discount_str}"
            )
        else:
            lines.append(f"   💰 <b>{current_price}</b>")

        return "\n".join(lines)

    @classmethod
    def format_telegram_post(
        cls,
        products: list[ProductInfo] | list[dict],
        title: str | None = None,
        footer: str | None = None,
    ) -> str:
        """Format a complete Telegram post.

        Args:
            products: List of ProductInfo or dicts with product data.
            title: Post title (default: "🔥 ТОП-10 ТОВАРОВ ДНЯ").
            footer: Call-to-action footer (default: delivery/contact info).

        Returns:
            Formatted HTML text for Telegram.
        """
        if title is None:
            title = DEFAULT_TITLE
        if footer is None:
            footer = DEFAULT_CTA

        sections = [f"<b>{cls.escape_html(title)}</b>", ""]

        for i, product in enumerate(products, 1):
            if isinstance(product, dict):
                product = ProductInfo(
                    name=product.get("name", "Товар"),
                    price=product.get("price", 0),
                    old_price=product.get("old_price"),
                    discount=product.get("discount"),
                )
            sections.append(cls.format_product_line(i, product))
            sections.append("")

        if footer:
            sections.append(footer)

        return "\n".join(sections)

    @classmethod
    def format_product_caption(
        cls,
        product: ProductInfo | dict,
        index: int | None = None,
    ) -> str:
        """Format a short caption for a single product image.

        Args:
            product: Product information.
            index: Optional product number.

        Returns:
            Short caption for image.
        """
        if isinstance(product, dict):
            product = ProductInfo(
                name=product.get("name", "Товар"),
                price=product.get("price", 0),
                old_price=product.get("old_price"),
                discount=product.get("discount"),
            )

        name = cls.escape_html(product.name)
        price = cls.format_price(product.price)

        prefix = f"{index}. " if index else ""

        if product.discount and product.discount > 0:
            return f"{prefix}{name}\n<b>{price}</b> (-{product.discount}%)"

        return f"{prefix}{name}\n<b>{price}</b>"

    @classmethod
    def format_success_notification(
        cls,
        post_count: int,
        channel_link: str | None = None,
    ) -> str:
        """Format success notification message.

        Args:
            post_count: Number of products published.
            channel_link: Optional link to the post.

        Returns:
            Formatted success message.
        """
        lines = [
            "✅ <b>Пост опубликован!</b>",
            "",
            f"📦 Товаров: {post_count}",
        ]

        if channel_link:
            lines.append(f"🔗 <a href=\"{channel_link}\">Открыть пост</a>")

        return "\n".join(lines)

    @classmethod
    def format_error_notification(
        cls,
        error_message: str,
        stage: str | None = None,
    ) -> str:
        """Format error notification message.

        Args:
            error_message: Error description.
            stage: Pipeline stage where error occurred.

        Returns:
            Formatted error message.
        """
        lines = [
            "❌ <b>Ошибка публикации</b>",
            "",
        ]

        if stage:
            lines.append(f"📍 Этап: {cls.escape_html(stage)}")

        lines.append(f"⚠️ {cls.escape_html(error_message)}")
        lines.append("")
        lines.append("💡 Проверьте логи для диагностики")

        return "\n".join(lines)

    # =========================================================================
    # Instagram Formatting Methods
    # =========================================================================

    @staticmethod
    def strip_html_tags(text: str) -> str:
        """Remove HTML tags from text.

        Args:
            text: Text with HTML tags.

        Returns:
            Plain text without HTML tags.
        """
        # Remove HTML tags
        clean = re.sub(r"<[^>]+>", "", text)
        # Decode HTML entities
        clean = html.unescape(clean)
        return clean

    @classmethod
    def format_instagram_product_line(
        cls,
        index: int,
        product: ProductInfo,
    ) -> str:
        """Format a single product line for Instagram (no HTML).

        Args:
            index: Product number (1-based).
            product: Product information.

        Returns:
            Formatted product line without HTML markup.
        """
        # Use emoji number if available, otherwise plain number
        if 1 <= index <= len(INDEX_EMOJIS):
            index_str = INDEX_EMOJIS[index - 1]
        else:
            index_str = f"{index}."

        name = product.name
        current_price = cls.format_price(product.price)

        if product.old_price and product.old_price > product.price:
            old_price_str = cls.format_price(product.old_price)
            discount_str = ""
            if product.discount and product.discount > 0:
                discount_str = f" (-{product.discount}%)"
            return f"{index_str} {name} — {current_price} (было {old_price_str}){discount_str}"
        else:
            return f"{index_str} {name} — {current_price}"

    @classmethod
    def format_instagram_caption(
        cls,
        products: list[ProductInfo] | list[dict],
        title: str | None = None,
        contact: str | None = None,
    ) -> str:
        """Format Instagram post caption (without HTML, with emojis).

        Args:
            products: List of ProductInfo or dicts with product data.
            title: Post title (default: "🔥 ТОП-10 ТОВАРОВ ДНЯ").
            contact: Contact information (default: @tulpar_express).

        Returns:
            Plain text caption for Instagram.
        """
        if title is None:
            title = DEFAULT_TITLE
        if contact is None:
            contact = DEFAULT_INSTAGRAM_CONTACT

        sections = [
            f"{title} от Тулпар Экспресс!",
            "",
            "Лучшие скидки из Китая с доставкой в Бишкек 🚀",
            "",
        ]

        for i, product in enumerate(products, 1):
            if isinstance(product, dict):
                product = ProductInfo(
                    name=product.get("name", "Товар"),
                    price=product.get("price", 0),
                    old_price=product.get("old_price"),
                    discount=product.get("discount"),
                )
            sections.append(cls.format_instagram_product_line(i, product))

        sections.append("")
        if contact:
            sections.append(contact)

        return "\n".join(sections)

    @classmethod
    def build_instagram_post(
        cls,
        products: list[ProductInfo] | list[dict],
        hashtags: list[str],
        title: str | None = None,
        contact: str | None = None,
    ) -> str:
        """Build complete Instagram post with caption and hashtags.

        Args:
            products: List of ProductInfo or dicts with product data.
            hashtags: List of hashtags (with # prefix).
            title: Post title.
            contact: Contact information.

        Returns:
            Complete Instagram post text (caption + hashtags).

        Note:
            If the post exceeds 2200 characters, hashtags will be trimmed.
        """
        caption = cls.format_instagram_caption(
            products=products,
            title=title,
            contact=contact,
        )

        # Format hashtags as single line
        hashtag_text = " ".join(hashtags)

        # Combine caption and hashtags
        full_post = f"{caption}\n\n{hashtag_text}"

        # Check length and trim if needed
        if len(full_post) > MAX_INSTAGRAM_CAPTION_LENGTH:
            # Calculate how much space we have for hashtags
            caption_with_spacing = f"{caption}\n\n"
            available_for_hashtags = MAX_INSTAGRAM_CAPTION_LENGTH - len(caption_with_spacing)

            if available_for_hashtags > 20:  # At least some space for hashtags
                # Trim hashtags to fit
                trimmed_hashtags = []
                current_length = 0
                for tag in hashtags:
                    tag_with_space = f"{tag} "
                    if current_length + len(tag_with_space) <= available_for_hashtags:
                        trimmed_hashtags.append(tag)
                        current_length += len(tag_with_space)
                    else:
                        break

                hashtag_text = " ".join(trimmed_hashtags)
                full_post = f"{caption}\n\n{hashtag_text}"
            else:
                # No space for hashtags, return caption only
                full_post = caption[:MAX_INSTAGRAM_CAPTION_LENGTH]

        return full_post

    @classmethod
    def format_instagram_product_caption(
        cls,
        product: ProductInfo | dict,
        index: int | None = None,
    ) -> str:
        """Format a short caption for Instagram carousel item.

        Args:
            product: Product information.
            index: Optional product number.

        Returns:
            Short caption without HTML for carousel item.
        """
        if isinstance(product, dict):
            product = ProductInfo(
                name=product.get("name", "Товар"),
                price=product.get("price", 0),
                old_price=product.get("old_price"),
                discount=product.get("discount"),
            )

        name = product.name
        price = cls.format_price(product.price)

        if index and 1 <= index <= len(INDEX_EMOJIS):
            prefix = f"{INDEX_EMOJIS[index - 1]} "
        elif index:
            prefix = f"{index}. "
        else:
            prefix = ""

        if product.discount and product.discount > 0:
            return f"{prefix}{name}\n💰 {price} (-{product.discount}%)"

        return f"{prefix}{name}\n💰 {price}"
