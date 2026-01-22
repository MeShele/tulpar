"""Image download service with retry logic for product images."""

from __future__ import annotations

import asyncio
import re
import tempfile
import uuid
from pathlib import Path
from typing import ClassVar

import httpx

from src.autopost.exceptions import ServiceError
from src.autopost.services.base import BaseService, ServiceResult

# Timeout for image download (NFR2: <10 seconds)
IMAGE_DOWNLOAD_TIMEOUT = 15

# Retry settings
MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds between retries

# Supported image formats
SUPPORTED_FORMATS = {"jpeg", "jpg", "png", "webp"}

# Content-Type to extension mapping
CONTENT_TYPE_MAP: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

# Magic bytes for format detection
MAGIC_BYTES: dict[bytes, str] = {
    b"\xff\xd8\xff": "jpg",  # JPEG
    b"\x89PNG": "png",  # PNG
    b"RIFF": "webp",  # WebP (RIFF....WEBP)
}

# Default temp directory for images
DEFAULT_TEMP_DIR = Path(tempfile.gettempdir()) / "tulpar_images"

# Alternative CDN hosts for alicdn (try in order)
ALICDN_ALTERNATIVES = [
    "img.alicdn.com",
    "gw.alicdn.com",
    "cbu01.alicdn.com",
]


class ImageService(BaseService):
    """Service for downloading product images with retry logic.

    Downloads images from URLs with automatic retry on failure,
    CDN fallback for alicdn URLs, and format validation.
    Saves images to a temporary directory for further processing.

    Attributes:
        temp_dir: Directory for storing downloaded images.
        timeout: Download timeout in seconds.
    """

    # Class-level temp directory (shared across instances)
    _temp_dir: ClassVar[Path | None] = None

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        temp_dir: Path | None = None,
        timeout: int = IMAGE_DOWNLOAD_TIMEOUT,
    ) -> None:
        """Initialize ImageService.

        Args:
            client: Optional httpx.AsyncClient for HTTP requests.
            temp_dir: Directory for storing images (default: system temp).
            timeout: Download timeout in seconds (default: 15).
        """
        super().__init__(client)
        self.timeout = timeout

        # Use provided temp_dir or class default
        if temp_dir:
            self._temp_dir = temp_dir
        elif ImageService._temp_dir is None:
            ImageService._temp_dir = DEFAULT_TEMP_DIR

        # Ensure temp directory exists
        self._ensure_temp_dir()

    @property
    def temp_dir(self) -> Path:
        """Get the temporary directory for images."""
        if self._temp_dir is None:
            self._temp_dir = DEFAULT_TEMP_DIR
            self._ensure_temp_dir()
        return self._temp_dir

    def _ensure_temp_dir(self) -> None:
        """Create temp directory if it doesn't exist."""
        if self._temp_dir:
            self._temp_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def set_temp_dir(cls, path: Path) -> None:
        """Set the temporary directory for all instances.

        Args:
            path: Path to temporary directory.
        """
        cls._temp_dir = path
        path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def clear_temp_dir(cls) -> int:
        """Clear all images from temp directory.

        Returns:
            Number of files deleted.
        """
        if cls._temp_dir is None or not cls._temp_dir.exists():
            return 0

        count = 0
        for file in cls._temp_dir.iterdir():
            if file.is_file():
                file.unlink()
                count += 1
        return count

    def _validate_url(self, url: str) -> bool:
        """Validate image URL format.

        Args:
            url: URL to validate.

        Returns:
            True if URL is valid, False otherwise.
        """
        if not url:
            return False

        # Basic URL validation
        if not url.startswith(("http://", "https://")):
            return False

        return True

    def _get_alternative_urls(self, url: str) -> list[str]:
        """Generate alternative CDN URLs for alicdn images.

        Args:
            url: Original image URL.

        Returns:
            List of alternative URLs to try.
        """
        urls = [url]

        # Check if it's an alicdn URL
        if "alicdn.com" not in url:
            return urls

        # Try replacing CDN host (gd1, gd2, gd3, gd4 -> img, gw, cbu01)
        for alt_host in ALICDN_ALTERNATIVES:
            # Replace gd*.alicdn.com or img.alicdn.com with alternatives
            alt_url = re.sub(
                r"(gd\d|img|gw|cbu\d+)\.alicdn\.com",
                alt_host,
                url,
            )
            if alt_url != url and alt_url not in urls:
                urls.append(alt_url)

        return urls

    def _detect_format_from_content_type(self, content_type: str | None) -> str | None:
        """Detect image format from Content-Type header.

        Args:
            content_type: Content-Type header value.

        Returns:
            Image format extension or None if not recognized.
        """
        if not content_type:
            return None

        # Handle content types like "image/jpeg; charset=utf-8"
        content_type = content_type.split(";")[0].strip().lower()
        return CONTENT_TYPE_MAP.get(content_type)

    def _detect_format_from_bytes(self, data: bytes) -> str | None:
        """Detect image format from magic bytes.

        Args:
            data: Image data bytes.

        Returns:
            Image format extension or None if not recognized.
        """
        for magic, fmt in MAGIC_BYTES.items():
            if data.startswith(magic):
                return fmt
        return None

    def _detect_format_from_url(self, url: str) -> str | None:
        """Detect image format from URL extension.

        Args:
            url: Image URL.

        Returns:
            Image format extension or None if not recognized.
        """
        # Remove query parameters
        url_path = url.split("?")[0].lower()

        for fmt in SUPPORTED_FORMATS:
            if url_path.endswith(f".{fmt}"):
                return "jpg" if fmt == "jpeg" else fmt

        return None

    def _generate_filename(self, fmt: str) -> str:
        """Generate unique filename for downloaded image.

        Args:
            fmt: Image format extension.

        Returns:
            Unique filename.
        """
        return f"{uuid.uuid4().hex}.{fmt}"

    async def _download_with_retry(self, url: str) -> tuple[bytes, dict]:
        """Download image with retry logic.

        Retries on failure with exponential backoff.
        Tries alternative CDN URLs for alicdn images.

        Args:
            url: Image URL to download.

        Returns:
            Tuple of (image content bytes, response headers).

        Raises:
            ServiceError: If all retries fail.
        """
        urls_to_try = self._get_alternative_urls(url)
        last_error = None

        timeout = httpx.Timeout(
            connect=5.0,
            read=float(self.timeout),
            write=5.0,
            pool=5.0,
        )

        for try_url in urls_to_try:
            for attempt in range(MAX_RETRIES):
                try:
                    self.logger.debug(
                        "download_attempt",
                        url=try_url[:80],
                        attempt=attempt + 1,
                        max_retries=MAX_RETRIES,
                    )

                    response = await self._get(try_url, timeout=timeout)
                    content = response.content

                    # Validate content size (at least 1KB)
                    if len(content) < 1024:
                        raise ServiceError(
                            message=f"Image too small: {len(content)} bytes",
                            service_name="ImageService",
                        )

                    return content, dict(response.headers)

                except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as e:
                    last_error = e
                    self.logger.warning(
                        "download_retry",
                        url=try_url[:80],
                        attempt=attempt + 1,
                        error=str(e)[:100],
                    )

                    # Wait before retry (exponential backoff)
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1))

                except ServiceError as e:
                    last_error = e
                    # Don't retry on validation errors
                    break

        # All retries exhausted
        raise ServiceError(
            message=f"Failed to download image after {MAX_RETRIES} attempts: {last_error}",
            service_name="ImageService",
        )

    async def download(self, image_url: str) -> ServiceResult[Path]:
        """Download image from URL with retry.

        Downloads image with automatic retry on failure,
        validates format, and saves to temporary directory.

        Args:
            image_url: URL of the image to download.

        Returns:
            ServiceResult containing Path to downloaded image,
            or error message on failure.
        """
        # Validate URL
        if not self._validate_url(image_url):
            self.logger.warning(
                "invalid_image_url",
                url=image_url,
            )
            return ServiceResult.fail(f"Invalid URL: {image_url}")

        self.logger.info(
            "downloading_image",
            url=image_url[:100],
        )

        try:
            # Download with retry
            content, headers = await self._download_with_retry(image_url)

            # Detect format
            fmt = (
                self._detect_format_from_content_type(headers.get("content-type"))
                or self._detect_format_from_bytes(content)
                or self._detect_format_from_url(image_url)
                or "jpg"  # Default to jpg
            )

            # Validate format
            if fmt not in SUPPORTED_FORMATS and fmt != "jpg":
                self.logger.warning(
                    "unsupported_format",
                    url=image_url[:100],
                    format=fmt,
                )
                return ServiceResult.fail(f"Unsupported format: {fmt}")

            # Save to temp file
            filename = self._generate_filename(fmt)
            filepath = self.temp_dir / filename

            filepath.write_bytes(content)

            self.logger.info(
                "image_downloaded",
                url=image_url[:100],
                path=str(filepath),
                size=len(content),
                format=fmt,
            )

            return ServiceResult.ok(filepath)

        except ServiceError as e:
            self.logger.warning(
                "image_service_error",
                url=image_url[:100],
                error=str(e),
            )
            return ServiceResult.fail(str(e))

        except Exception as e:
            self.logger.error(
                "unexpected_download_error",
                url=image_url[:100],
                error=str(e),
                error_type=type(e).__name__,
            )
            return ServiceResult.fail(f"Unexpected error: {e}")

    async def download_batch(
        self, image_urls: list[str]
    ) -> list[ServiceResult[Path]]:
        """Download multiple images in parallel.

        Uses asyncio.gather for parallel downloads with limited concurrency.

        Args:
            image_urls: List of image URLs to download.

        Returns:
            List of ServiceResult for each URL.
        """
        # Download in parallel with limited concurrency
        semaphore = asyncio.Semaphore(5)  # Max 5 concurrent downloads

        async def download_with_semaphore(url: str) -> ServiceResult[Path]:
            async with semaphore:
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.5)
                return await self.download(url)

        tasks = [download_with_semaphore(url) for url in image_urls]
        results = await asyncio.gather(*tasks)
        return list(results)

    async def download_for_product(
        self, product_id: str, image_url: str
    ) -> ServiceResult[Path]:
        """Download image for a specific product.

        Convenience method that logs product ID with the download.

        Args:
            product_id: Product identifier for logging.
            image_url: URL of the product image.

        Returns:
            ServiceResult containing Path to downloaded image.
        """
        self.logger.info(
            "downloading_product_image",
            product_id=product_id,
            url=image_url[:100],
        )
        return await self.download(image_url)
