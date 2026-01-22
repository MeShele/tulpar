"""Product card generator with яркий/aggressive price design."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

if TYPE_CHECKING:
    from PIL.ImageFont import FreeTypeFont

logger = structlog.get_logger(__name__)

# Default card size (Instagram optimal)
CARD_SIZE = 1080

# Colors - Яркий/Aggressive стиль
DISCOUNT_BADGE_COLOR = (220, 38, 38)  # Яркий красный
DISCOUNT_TEXT_COLOR = (255, 255, 255)  # Белый
PRICE_TAG_BG = (255, 215, 0)  # Золотисто-жёлтый
PRICE_TAG_BORDER = (255, 140, 0)  # Оранжевый бордер
NEW_PRICE_COLOR = (220, 38, 38)  # Красный для новой цены
OLD_PRICE_COLOR = (100, 100, 100)  # Серый для старой цены
STRIKETHROUGH_COLOR = (220, 38, 38)  # Красная линия зачёркивания
CURRENCY_COLOR = (50, 50, 50)  # Тёмно-серый для "сом"
WATERMARK_COLOR = (255, 255, 255, 160)  # Белый полупрозрачный

# Font sizes - увеличенные для яркости
OLD_PRICE_FONT_SIZE = 56
NEW_PRICE_FONT_SIZE = 96
DISCOUNT_FONT_SIZE = 56
WATERMARK_FONT_SIZE = 28
CURRENCY_FONT_SIZE = 48

# Badge dimensions - больше для заметности
BADGE_PADDING = 20
BADGE_RADIUS = 16
BADGE_MARGIN = 24

# Watermark
WATERMARK_TEXT = "Tulpar Express"
WATERMARK_MARGIN = 20

# Source badge colors
SOURCE_BADGE_BG = {
    "pinduoduo": (255, 87, 34),  # Orange for Pinduoduo
    "taobao": (255, 68, 0),  # Red-orange for Taobao
}
SOURCE_BADGE_TEXT = (255, 255, 255)  # White text
SOURCE_FONT_SIZE = 28
SOURCE_BADGE_PADDING = 12
SOURCE_BADGE_RADIUS = 10

# Price tag dimensions
PRICE_TAG_HEIGHT = 180
PRICE_TAG_MARGIN = 30
PRICE_TAG_RADIUS = 24

# System fonts that support Cyrillic (tried in order)
CYRILLIC_FONTS = [
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/Library/Fonts/Arial.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    # Windows
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _find_font(size: int) -> FreeTypeFont:
    """Find a system font that supports Cyrillic.

    Args:
        size: Font size in pixels.

    Returns:
        PIL ImageFont object.
    """
    for font_path in CYRILLIC_FONTS:
        try:
            if Path(font_path).exists():
                return ImageFont.truetype(font_path, size)
        except (OSError, IOError):
            continue

    # Fallback to default (may not support Cyrillic well)
    logger.warning("no_cyrillic_font_found", fallback="default")
    try:
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


class ProductCardGenerator:
    """Generator for product cards with яркий/aggressive design.

    Creates eye-catching product cards with:
    - Yellow price tag at bottom
    - Crossed-out old price
    - Bold new price in red
    - Big red discount badge
    - Watermark

    Attributes:
        output_dir: Directory for saving generated cards.
        card_size: Output card size (default: 1080).
    """

    def __init__(
        self,
        output_dir: Path | None = None,
        card_size: int = CARD_SIZE,
    ) -> None:
        """Initialize ProductCardGenerator.

        Args:
            output_dir: Directory for generated cards.
                       If None, saves in same directory as input.
            card_size: Target card size in pixels.
        """
        self.output_dir = output_dir
        self.card_size = card_size

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)

        # Load fonts
        self._old_price_font = _find_font(OLD_PRICE_FONT_SIZE)
        self._new_price_font = _find_font(NEW_PRICE_FONT_SIZE)
        self._currency_font = _find_font(CURRENCY_FONT_SIZE)
        self._discount_font = _find_font(DISCOUNT_FONT_SIZE)
        self._watermark_font = _find_font(WATERMARK_FONT_SIZE)
        self._source_font = _find_font(SOURCE_FONT_SIZE)

    def _smart_resize(self, img: Image.Image, target_size: int) -> Image.Image:
        """Smart resize image to square with quality enhancement.

        This preserves image quality better than stretching non-square images.
        Also applies sharpening and enhancement for small/low-quality images.

        Args:
            img: PIL Image object.
            target_size: Target size for square output.

        Returns:
            Resized and enhanced square image.
        """
        width, height = img.size
        original_size = min(width, height)

        # Calculate crop box for center crop to square
        if width > height:
            # Landscape: crop from sides
            left = (width - height) // 2
            top = 0
            right = left + height
            bottom = height
        elif height > width:
            # Portrait: crop from top/bottom
            left = 0
            top = (height - width) // 2
            right = width
            bottom = top + width
        else:
            # Already square
            left, top, right, bottom = 0, 0, width, height

        # Crop to square
        img = img.crop((left, top, right, bottom))

        # Resize to target size using high-quality resampling
        current_size = img.size[0]
        if current_size != target_size:
            # For upscaling (small image to large), use LANCZOS
            # For downscaling (large to small), use LANCZOS too
            img = img.resize((target_size, target_size), Image.Resampling.LANCZOS)

            # If we upscaled significantly, apply sharpening to reduce blur
            if current_size < target_size * 0.7:
                # Apply unsharp mask for better perceived sharpness
                img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=100, threshold=2))

                # Slight contrast boost
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(1.1)

                # Slight color saturation boost
                enhancer = ImageEnhance.Color(img)
                img = enhancer.enhance(1.05)

        return img

    def create_card(
        self,
        image_path: Path,
        price_kgs: int,
        discount_percent: int,
        old_price_kgs: int | None = None,
        source: str | None = None,
    ) -> Path:
        """Create product card with яркий price design.

        Args:
            image_path: Path to the source image.
            price_kgs: Current price in KGS.
            discount_percent: Discount percentage (e.g., 40 for -40%).
            old_price_kgs: Original price before discount.
            source: Product source platform (pinduoduo or taobao).

        Returns:
            Path to the generated card.

        Raises:
            FileNotFoundError: If image file doesn't exist.
            ValueError: If price or discount is invalid.
        """
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        if price_kgs <= 0:
            raise ValueError(f"Price must be positive: {price_kgs}")

        if discount_percent < 0 or discount_percent > 100:
            raise ValueError(f"Discount must be 0-100: {discount_percent}")

        # Generate old price if not provided
        if old_price_kgs is None or old_price_kgs <= price_kgs:
            # Calculate old price based on discount
            if discount_percent > 0 and discount_percent < 100:
                old_price_kgs = int(price_kgs * 100 / (100 - discount_percent))
            elif discount_percent >= 100:
                # Edge case: 100% discount means old price was ~infinite, use 10x
                old_price_kgs = int(price_kgs * 10)
            else:
                old_price_kgs = int(price_kgs * 1.4)  # Default 40% markup
                discount_percent = 30  # Default discount display

        logger.info(
            "creating_product_card",
            image_source=str(image_path),
            price=price_kgs,
            old_price=old_price_kgs,
            discount=discount_percent,
            platform_source=source,
        )

        # Open and prepare image
        with Image.open(image_path) as img:
            # Ensure RGB mode
            if img.mode != "RGB":
                img = img.convert("RGB")

            # Smart resize: crop to square from center, then resize
            # This preserves quality better than stretching
            img = self._smart_resize(img, self.card_size)

            # Create a copy for drawing
            card = img.copy()

            # Source badge removed per user request

            # Add yellow price tag at bottom
            card = self._add_price_tag(card, price_kgs, old_price_kgs)

            # Add big discount badge (top-right corner)
            if discount_percent > 0:
                card = self._add_discount_badge(card, discount_percent)

            # Add watermark
            card = self._add_watermark(card)

            # Save result with high quality
            output_path = self._get_output_path(image_path)
            card.save(output_path, format="JPEG", quality=95, optimize=True, subsampling=0)

        logger.info(
            "product_card_created",
            output=str(output_path),
            price=price_kgs,
            old_price=old_price_kgs,
            discount=discount_percent,
        )

        return output_path

    def _add_price_tag(
        self,
        image: Image.Image,
        price_kgs: int,
        old_price_kgs: int,
    ) -> Image.Image:
        """Add yellow price tag with crossed-out old price.

        Design:
        ╔════════════════════════════════╗
        ║   ~~1 999~~ → 1 299 сом       ║
        ╚════════════════════════════════╝

        Args:
            image: PIL Image object.
            price_kgs: Current price.
            old_price_kgs: Old price (crossed out).

        Returns:
            Image with price tag.
        """
        # Create RGBA image for transparency support
        card = image.convert("RGBA")

        # Create overlay
        overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Price tag dimensions
        tag_width = self.card_size - PRICE_TAG_MARGIN * 2
        tag_height = PRICE_TAG_HEIGHT
        tag_x = PRICE_TAG_MARGIN
        tag_y = self.card_size - tag_height - PRICE_TAG_MARGIN

        # Draw yellow rounded rectangle with border
        # Border first (slightly larger)
        draw.rounded_rectangle(
            [
                (tag_x - 3, tag_y - 3),
                (tag_x + tag_width + 3, tag_y + tag_height + 3),
            ],
            radius=PRICE_TAG_RADIUS + 3,
            fill=PRICE_TAG_BORDER + (255,),
        )

        # Main tag
        draw.rounded_rectangle(
            [
                (tag_x, tag_y),
                (tag_x + tag_width, tag_y + tag_height),
            ],
            radius=PRICE_TAG_RADIUS,
            fill=PRICE_TAG_BG + (255,),
        )

        # Composite overlay onto image
        card = Image.alpha_composite(card, overlay)

        # Now draw text on top
        draw = ImageDraw.Draw(card)

        # Format prices
        old_price_text = f"{old_price_kgs:,}".replace(",", " ")
        new_price_text = f"{new_price_kgs:,}".replace(",", " ") if (new_price_kgs := price_kgs) else ""
        currency_text = "сом"

        # Calculate text dimensions
        old_bbox = draw.textbbox((0, 0), old_price_text, font=self._old_price_font)
        new_bbox = draw.textbbox((0, 0), new_price_text, font=self._new_price_font)
        curr_bbox = draw.textbbox((0, 0), currency_text, font=self._currency_font)

        old_width = old_bbox[2] - old_bbox[0]
        new_width = new_bbox[2] - new_bbox[0]
        curr_width = curr_bbox[2] - curr_bbox[0]

        # Total width: old_price + arrow + new_price + currency
        arrow_width = 40
        gap = 16
        total_width = old_width + arrow_width + new_width + gap + curr_width

        # Center everything horizontally
        start_x = tag_x + (tag_width - total_width) // 2
        center_y = tag_y + tag_height // 2

        # Draw old price (gray, crossed out)
        old_y = center_y - OLD_PRICE_FONT_SIZE // 2
        draw.text(
            (start_x, old_y),
            old_price_text,
            font=self._old_price_font,
            fill=OLD_PRICE_COLOR,
        )

        # Draw strikethrough line
        strikethrough_y = old_y + OLD_PRICE_FONT_SIZE // 2
        draw.line(
            [
                (start_x - 4, strikethrough_y),
                (start_x + old_width + 4, strikethrough_y),
            ],
            fill=STRIKETHROUGH_COLOR,
            width=3,
        )

        # Draw arrow "→"
        arrow_x = start_x + old_width + 8
        arrow_y = center_y - 20
        draw.text(
            (arrow_x, arrow_y),
            "→",
            font=self._old_price_font,
            fill=NEW_PRICE_COLOR,
        )

        # Draw new price (bold red)
        new_x = arrow_x + arrow_width
        new_y = center_y - NEW_PRICE_FONT_SIZE // 2 - 5
        draw.text(
            (new_x, new_y),
            new_price_text,
            font=self._new_price_font,
            fill=NEW_PRICE_COLOR,
        )

        # Draw currency
        curr_x = new_x + new_width + gap
        curr_y = center_y - CURRENCY_FONT_SIZE // 2 + 5
        draw.text(
            (curr_x, curr_y),
            currency_text,
            font=self._currency_font,
            fill=CURRENCY_COLOR,
        )

        return card.convert("RGB")

    def _add_discount_badge(
        self,
        image: Image.Image,
        discount_percent: int,
    ) -> Image.Image:
        """Add big discount badge in top-right corner.

        Args:
            image: PIL Image object.
            discount_percent: Discount percentage.

        Returns:
            Image with discount badge.
        """
        # Create RGBA for transparency
        card = image.convert("RGBA")

        # Create overlay for badge
        overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Badge text
        badge_text = f"-{discount_percent}%"

        # Calculate badge size
        bbox = draw.textbbox((0, 0), badge_text, font=self._discount_font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        badge_width = text_width + BADGE_PADDING * 2
        badge_height = text_height + BADGE_PADDING * 2

        # Badge position (top-right with margin)
        badge_x = self.card_size - badge_width - BADGE_MARGIN
        badge_y = BADGE_MARGIN

        # Draw rounded rectangle badge with shadow effect
        # Shadow
        draw.rounded_rectangle(
            [
                (badge_x + 4, badge_y + 4),
                (badge_x + badge_width + 4, badge_y + badge_height + 4),
            ],
            radius=BADGE_RADIUS,
            fill=(0, 0, 0, 100),
        )

        # Main badge
        draw.rounded_rectangle(
            [
                (badge_x, badge_y),
                (badge_x + badge_width, badge_y + badge_height),
            ],
            radius=BADGE_RADIUS,
            fill=DISCOUNT_BADGE_COLOR + (255,),
        )

        # Draw badge text
        text_x = badge_x + BADGE_PADDING
        text_y = badge_y + BADGE_PADDING - 4
        draw.text(
            (text_x, text_y),
            badge_text,
            font=self._discount_font,
            fill=DISCOUNT_TEXT_COLOR,
        )

        # Composite
        card = Image.alpha_composite(card, overlay)
        return card.convert("RGB")

    def _add_source_badge(
        self,
        image: Image.Image,
        source: str,
    ) -> Image.Image:
        """Add source badge (Pinduoduo/Taobao) in top-left corner.

        Args:
            image: PIL Image object.
            source: Platform source (pinduoduo or taobao).

        Returns:
            Image with source badge.
        """
        # Create RGBA for transparency
        card = image.convert("RGBA")

        # Create overlay for badge
        overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Badge text - short platform name
        source_names = {
            "pinduoduo": "PDD",
            "taobao": "Taobao",
        }
        badge_text = source_names.get(source, source[:6].upper())

        # Get badge background color
        badge_bg = SOURCE_BADGE_BG.get(source, (100, 100, 100))

        # Calculate badge size
        bbox = draw.textbbox((0, 0), badge_text, font=self._source_font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        badge_width = text_width + SOURCE_BADGE_PADDING * 2
        badge_height = text_height + SOURCE_BADGE_PADDING * 2

        # Badge position (top-left with margin)
        badge_x = BADGE_MARGIN
        badge_y = BADGE_MARGIN

        # Draw rounded rectangle badge with shadow effect
        # Shadow
        draw.rounded_rectangle(
            [
                (badge_x + 3, badge_y + 3),
                (badge_x + badge_width + 3, badge_y + badge_height + 3),
            ],
            radius=SOURCE_BADGE_RADIUS,
            fill=(0, 0, 0, 80),
        )

        # Main badge
        draw.rounded_rectangle(
            [
                (badge_x, badge_y),
                (badge_x + badge_width, badge_y + badge_height),
            ],
            radius=SOURCE_BADGE_RADIUS,
            fill=badge_bg + (255,),
        )

        # Draw badge text
        text_x = badge_x + SOURCE_BADGE_PADDING
        text_y = badge_y + SOURCE_BADGE_PADDING - 2
        draw.text(
            (text_x, text_y),
            badge_text,
            font=self._source_font,
            fill=SOURCE_BADGE_TEXT,
        )

        # Composite
        card = Image.alpha_composite(card, overlay)
        return card.convert("RGB")

    def _add_watermark(self, image: Image.Image) -> Image.Image:
        """Add watermark in bottom-left corner.

        Args:
            image: PIL Image object.

        Returns:
            Image with watermark.
        """
        # Create RGBA for transparency
        card = image.convert("RGBA")

        # Create watermark layer
        watermark_layer = Image.new("RGBA", card.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark_layer)

        # Calculate position (above price tag)
        bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=self._watermark_font)
        text_height = bbox[3] - bbox[1]

        x = WATERMARK_MARGIN
        y = self.card_size - PRICE_TAG_HEIGHT - PRICE_TAG_MARGIN - text_height - WATERMARK_MARGIN

        # Draw watermark with semi-transparency
        draw.text(
            (x, y),
            WATERMARK_TEXT,
            font=self._watermark_font,
            fill=WATERMARK_COLOR,
        )

        # Composite
        card = Image.alpha_composite(card, watermark_layer)
        return card.convert("RGB")

    def _get_output_path(self, source_path: Path) -> Path:
        """Generate output path for product card.

        Args:
            source_path: Original image path.

        Returns:
            Path for the generated card.
        """
        filename = f"{uuid.uuid4().hex}_card.jpg"

        if self.output_dir:
            return self.output_dir / filename
        return source_path.parent / filename

    def create_batch(
        self,
        items: list[tuple[Path, int, int, int | None]],
    ) -> list[Path]:
        """Create multiple product cards.

        Args:
            items: List of (image_path, price_kgs, discount_percent, old_price_kgs) tuples.

        Returns:
            List of paths to generated cards.
        """
        results = []
        for item in items:
            try:
                if len(item) == 4:
                    image_path, price_kgs, discount_percent, old_price_kgs = item
                else:
                    image_path, price_kgs, discount_percent = item
                    old_price_kgs = None
                card_path = self.create_card(
                    image_path, price_kgs, discount_percent, old_price_kgs
                )
                results.append(card_path)
            except Exception as e:
                logger.error(
                    "batch_card_error",
                    path=str(item[0]) if item else "unknown",
                    error=str(e),
                )
        return results
