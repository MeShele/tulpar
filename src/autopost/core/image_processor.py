"""Image processing for social media optimization."""

from __future__ import annotations

import uuid
from pathlib import Path

import structlog
from PIL import Image

logger = structlog.get_logger(__name__)

# Target size for Instagram (square)
TARGET_SIZE = 1080

# JPEG quality (85% for optimal size/quality balance)
JPEG_QUALITY = 85

# Background color for padding (white)
BACKGROUND_COLOR = (255, 255, 255)


class ImageProcessor:
    """Processor for optimizing images for social media.

    Handles:
    - Resizing to 1080×1080 square (Instagram optimal)
    - JPEG compression at 85% quality
    - EXIF metadata removal
    - Color space conversion (CMYK/RGBA → RGB)

    Attributes:
        output_dir: Directory for saving processed images.
        target_size: Target image size (default: 1080).
        quality: JPEG quality (default: 85).
    """

    def __init__(
        self,
        output_dir: Path | None = None,
        target_size: int = TARGET_SIZE,
        quality: int = JPEG_QUALITY,
    ) -> None:
        """Initialize ImageProcessor.

        Args:
            output_dir: Directory for processed images.
                       If None, saves in same directory as input.
            target_size: Target size for square images.
            quality: JPEG quality (1-100).
        """
        self.output_dir = output_dir
        self.target_size = target_size
        self.quality = quality

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)

    def optimize(self, image_path: Path) -> Path:
        """Optimize image for social media.

        Applies all optimizations:
        1. Convert to RGB (from CMYK/RGBA)
        2. Resize to square with padding
        3. Remove EXIF metadata
        4. Save as JPEG with 85% quality

        Args:
            image_path: Path to source image.

        Returns:
            Path to optimized image.

        Raises:
            FileNotFoundError: If image file doesn't exist.
            ValueError: If image format is not supported.
        """
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        logger.info(
            "optimizing_image",
            source=str(image_path),
            target_size=self.target_size,
        )

        # Open image
        with Image.open(image_path) as img:
            # Convert color space
            img = self._convert_to_rgb(img)

            # Resize to square
            img = self._resize_to_square(img)

            # Strip EXIF (by creating new image)
            img = self._strip_exif(img)

            # Generate output path
            output_path = self._get_output_path(image_path)

            # Save with optimization
            img.save(
                output_path,
                format="JPEG",
                quality=self.quality,
                optimize=True,
            )

        logger.info(
            "image_optimized",
            source=str(image_path),
            output=str(output_path),
            size=f"{self.target_size}x{self.target_size}",
        )

        return output_path

    def _convert_to_rgb(self, image: Image.Image) -> Image.Image:
        """Convert image to RGB color space.

        Handles:
        - CMYK → RGB conversion
        - RGBA → RGB (with white background)
        - P (palette) → RGB conversion
        - L (grayscale) → RGB conversion

        Args:
            image: PIL Image object.

        Returns:
            Image in RGB mode.
        """
        original_mode = image.mode

        if image.mode == "RGB":
            return image

        if image.mode == "CMYK":
            logger.debug("converting_cmyk_to_rgb")
            return image.convert("RGB")

        if image.mode == "RGBA":
            logger.debug("converting_rgba_to_rgb")
            # Create white background
            background = Image.new("RGB", image.size, BACKGROUND_COLOR)
            # Paste image with alpha as mask
            background.paste(image, mask=image.split()[3])
            return background

        if image.mode in ("P", "L", "LA"):
            logger.debug(
                "converting_to_rgb",
                from_mode=original_mode,
            )
            # Handle palette with transparency
            if image.mode == "P" and "transparency" in image.info:
                image = image.convert("RGBA")
                background = Image.new("RGB", image.size, BACKGROUND_COLOR)
                background.paste(image, mask=image.split()[3])
                return background
            return image.convert("RGB")

        # Fallback for other modes
        logger.warning(
            "unknown_color_mode",
            mode=image.mode,
        )
        return image.convert("RGB")

    def _resize_to_square(self, image: Image.Image) -> Image.Image:
        """Resize image to square with padding.

        Maintains aspect ratio and centers image on white background.

        Args:
            image: PIL Image object.

        Returns:
            Square image of target_size × target_size.
        """
        # Calculate resize dimensions maintaining aspect ratio
        width, height = image.size
        ratio = min(self.target_size / width, self.target_size / height)

        new_width = int(width * ratio)
        new_height = int(height * ratio)

        # Resize with high-quality resampling
        resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Create square canvas with white background
        canvas = Image.new("RGB", (self.target_size, self.target_size), BACKGROUND_COLOR)

        # Center the image
        x = (self.target_size - new_width) // 2
        y = (self.target_size - new_height) // 2
        canvas.paste(resized, (x, y))

        logger.debug(
            "image_resized",
            original=f"{width}x{height}",
            new=f"{new_width}x{new_height}",
            canvas=f"{self.target_size}x{self.target_size}",
        )

        return canvas

    def _strip_exif(self, image: Image.Image) -> Image.Image:
        """Remove EXIF metadata from image.

        Creates a new image without any metadata.

        Args:
            image: PIL Image object.

        Returns:
            Image without EXIF data.
        """
        # Create new image without EXIF by copying pixel data
        data = list(image.getdata())
        image_without_exif = Image.new(image.mode, image.size)
        image_without_exif.putdata(data)

        logger.debug("exif_stripped")

        return image_without_exif

    def _get_output_path(self, source_path: Path) -> Path:
        """Generate output path for processed image.

        Args:
            source_path: Original image path.

        Returns:
            Path for the processed image.
        """
        # Generate unique filename
        filename = f"{uuid.uuid4().hex}_optimized.jpg"

        if self.output_dir:
            return self.output_dir / filename
        return source_path.parent / filename

    def optimize_batch(self, image_paths: list[Path]) -> list[Path]:
        """Optimize multiple images.

        Args:
            image_paths: List of image paths to process.

        Returns:
            List of paths to optimized images.
        """
        results = []
        for path in image_paths:
            try:
                optimized = self.optimize(path)
                results.append(optimized)
            except Exception as e:
                logger.error(
                    "batch_optimization_error",
                    path=str(path),
                    error=str(e),
                )
        return results

    @staticmethod
    def get_image_info(image_path: Path) -> dict:
        """Get information about an image.

        Args:
            image_path: Path to image file.

        Returns:
            Dictionary with image info (size, mode, format).
        """
        with Image.open(image_path) as img:
            return {
                "width": img.width,
                "height": img.height,
                "mode": img.mode,
                "format": img.format,
                "has_exif": bool(img.getexif()),
            }
