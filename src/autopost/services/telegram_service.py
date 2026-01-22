"""Telegram service for publishing to channels."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import FSInputFile, InputMediaPhoto
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.autopost.services.base import ServiceResult

if TYPE_CHECKING:
    from aiogram.types import Message

logger = structlog.get_logger(__name__)

# Timeout for Telegram API requests (5 seconds per NFR4)
TELEGRAM_TIMEOUT = 5.0

# Maximum caption length for photos
MAX_CAPTION_LENGTH = 1024

# Maximum message length
MAX_MESSAGE_LENGTH = 4096

# Maximum number of media items in a group (Telegram limit)
MAX_MEDIA_GROUP_SIZE = 10


class TelegramService:
    """Service for publishing content to Telegram channels.

    Handles:
    - Sending text messages to channels
    - Sending photos with captions
    - Retry logic for failed requests
    - Rate limit handling

    Attributes:
        bot: aiogram Bot instance.
        channel_id: Target channel ID or username.
        owner_ids: List of owner Telegram IDs for notifications.
    """

    def __init__(
        self,
        bot_token: str,
        channel_id: str,
        owner_id: int | None = None,
        owner_ids: list[int] | None = None,
    ) -> None:
        """Initialize TelegramService.

        Args:
            bot_token: Telegram Bot API token.
            channel_id: Channel ID (e.g., "@channel" or "-1001234567890").
            owner_id: Single owner's Telegram ID (legacy, for backward compatibility).
            owner_ids: List of owner Telegram IDs for notifications.
        """
        self.bot = Bot(token=bot_token)
        self.channel_id = channel_id
        # Support both single owner_id and list of owner_ids
        self._owner_ids: list[int] = []
        if owner_ids:
            self._owner_ids = list(owner_ids)
        if owner_id and owner_id not in self._owner_ids:
            self._owner_ids.append(owner_id)
        self.logger = structlog.get_logger(service="TelegramService")

    @property
    def owner_id(self) -> int | None:
        """Get first owner ID for backward compatibility."""
        return self._owner_ids[0] if self._owner_ids else None

    @property
    def owner_ids(self) -> list[int]:
        """Get all owner IDs."""
        return self._owner_ids

    async def close(self) -> None:
        """Close the bot session."""
        await self.bot.session.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((TelegramAPIError,)),
        reraise=True,
    )
    async def send_message(
        self,
        text: str,
        parse_mode: ParseMode = ParseMode.HTML,
    ) -> ServiceResult[int]:
        """Send a text message to the channel.

        Args:
            text: Message text (max 4096 characters).
            parse_mode: Parse mode for formatting (HTML or Markdown).

        Returns:
            ServiceResult with message_id on success.
        """
        if len(text) > MAX_MESSAGE_LENGTH:
            text = text[:MAX_MESSAGE_LENGTH - 3] + "..."

        self.logger.info(
            "sending_message",
            channel=self.channel_id,
            text_length=len(text),
        )

        start_time = time.time()

        try:
            message = await self.bot.send_message(
                chat_id=self.channel_id,
                text=text,
                parse_mode=parse_mode,
            )

            elapsed = time.time() - start_time

            self.logger.info(
                "message_sent",
                channel=self.channel_id,
                message_id=message.message_id,
                elapsed_seconds=round(elapsed, 2),
            )

            return ServiceResult.ok(message.message_id)

        except TelegramRetryAfter as e:
            self.logger.warning(
                "rate_limited",
                retry_after=e.retry_after,
            )
            raise

        except TelegramAPIError as e:
            self.logger.error(
                "telegram_api_error",
                error=str(e),
                channel=self.channel_id,
            )
            raise

        except Exception as e:
            self.logger.error(
                "send_message_error",
                error=str(e),
                channel=self.channel_id,
            )
            return ServiceResult.fail(f"Failed to send message: {e}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((TelegramAPIError,)),
        reraise=True,
    )
    async def send_photo(
        self,
        photo_path: Path,
        caption: str | None = None,
        parse_mode: ParseMode = ParseMode.HTML,
    ) -> ServiceResult[int]:
        """Send a photo to the channel.

        Args:
            photo_path: Path to the image file.
            caption: Optional caption (max 1024 characters).
            parse_mode: Parse mode for caption formatting.

        Returns:
            ServiceResult with message_id on success.
        """
        if not photo_path.exists():
            return ServiceResult.fail(f"Photo not found: {photo_path}")

        if caption and len(caption) > MAX_CAPTION_LENGTH:
            caption = caption[:MAX_CAPTION_LENGTH - 3] + "..."

        self.logger.info(
            "sending_photo",
            channel=self.channel_id,
            photo=str(photo_path),
            caption_length=len(caption) if caption else 0,
        )

        start_time = time.time()

        try:
            photo = FSInputFile(photo_path)

            message = await self.bot.send_photo(
                chat_id=self.channel_id,
                photo=photo,
                caption=caption,
                parse_mode=parse_mode,
            )

            elapsed = time.time() - start_time

            self.logger.info(
                "photo_sent",
                channel=self.channel_id,
                message_id=message.message_id,
                elapsed_seconds=round(elapsed, 2),
            )

            return ServiceResult.ok(message.message_id)

        except TelegramRetryAfter as e:
            self.logger.warning(
                "rate_limited",
                retry_after=e.retry_after,
            )
            raise

        except TelegramAPIError as e:
            self.logger.error(
                "telegram_api_error",
                error=str(e),
                channel=self.channel_id,
            )
            raise

        except Exception as e:
            self.logger.error(
                "send_photo_error",
                error=str(e),
                photo=str(photo_path),
            )
            return ServiceResult.fail(f"Failed to send photo: {e}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((TelegramAPIError,)),
        reraise=True,
    )
    async def send_media_group(
        self,
        images: list[Path],
        captions: list[str] | None = None,
        main_caption: str | None = None,
        parse_mode: ParseMode = ParseMode.HTML,
    ) -> ServiceResult[list[int]]:
        """Send a media group (carousel) to the channel.

        Args:
            images: List of image paths (max 10).
            captions: Individual captions for each image.
            main_caption: Caption for the first image (visible as post text).
            parse_mode: Parse mode for caption formatting.

        Returns:
            ServiceResult with list of message_ids on success.
        """
        if not images:
            return ServiceResult.fail("No images provided for media group")

        if len(images) > MAX_MEDIA_GROUP_SIZE:
            return ServiceResult.fail(
                f"Too many images: {len(images)}. Maximum is {MAX_MEDIA_GROUP_SIZE}"
            )

        # Validate all files exist
        for img_path in images:
            if not img_path.exists():
                return ServiceResult.fail(f"Image not found: {img_path}")

        self.logger.info(
            "sending_media_group",
            channel=self.channel_id,
            image_count=len(images),
        )

        start_time = time.time()

        try:
            media_group: list[InputMediaPhoto] = []

            for i, img_path in enumerate(images):
                photo = FSInputFile(img_path)

                # Determine caption for this image
                caption = None
                if i == 0 and main_caption:
                    # First image gets the main caption (legacy behavior)
                    caption = main_caption
                    if len(caption) > MAX_CAPTION_LENGTH:
                        caption = caption[: MAX_CAPTION_LENGTH - 3] + "..."
                elif captions and i < len(captions) and captions[i]:
                    # Each image gets its individual caption
                    caption = captions[i]
                    if len(caption) > MAX_CAPTION_LENGTH:
                        caption = caption[: MAX_CAPTION_LENGTH - 3] + "..."

                media_group.append(
                    InputMediaPhoto(
                        media=photo,
                        caption=caption,
                        parse_mode=parse_mode if caption else None,
                    )
                )

            messages = await self.bot.send_media_group(
                chat_id=self.channel_id,
                media=media_group,
            )

            elapsed = time.time() - start_time
            message_ids = [msg.message_id for msg in messages]

            self.logger.info(
                "media_group_sent",
                channel=self.channel_id,
                message_ids=message_ids,
                elapsed_seconds=round(elapsed, 2),
            )

            return ServiceResult.ok(message_ids)

        except TelegramRetryAfter as e:
            self.logger.warning(
                "rate_limited",
                retry_after=e.retry_after,
            )
            raise

        except TelegramAPIError as e:
            self.logger.error(
                "telegram_api_error",
                error=str(e),
                channel=self.channel_id,
            )
            raise

        except Exception as e:
            self.logger.error(
                "send_media_group_error",
                error=str(e),
                channel=self.channel_id,
            )
            return ServiceResult.fail(f"Failed to send media group: {e}")

    async def notify_owner(
        self,
        text: str,
        parse_mode: ParseMode = ParseMode.HTML,
    ) -> ServiceResult[int]:
        """Send a notification to all owners.

        Args:
            text: Notification text.
            parse_mode: Parse mode for formatting.

        Returns:
            ServiceResult with first message_id on success.
        """
        if not self._owner_ids:
            return ServiceResult.fail("No owner IDs configured")

        self.logger.info(
            "notifying_owners",
            owner_count=len(self._owner_ids),
        )

        first_message_id = None
        errors = []

        for owner_id in self._owner_ids:
            try:
                message = await self.bot.send_message(
                    chat_id=owner_id,
                    text=text,
                    parse_mode=parse_mode,
                )
                if first_message_id is None:
                    first_message_id = message.message_id
                self.logger.debug("owner_notified", owner_id=owner_id)
            except Exception as e:
                self.logger.error(
                    "notify_owner_error",
                    owner_id=owner_id,
                    error=str(e),
                )
                errors.append(f"owner {owner_id}: {e}")

        if first_message_id is not None:
            return ServiceResult.ok(first_message_id)
        else:
            return ServiceResult.fail(f"Failed to notify all owners: {'; '.join(errors)}")

    async def get_channel_info(self) -> ServiceResult[dict]:
        """Get information about the channel.

        Returns:
            ServiceResult with channel info dict.
        """
        try:
            chat = await self.bot.get_chat(self.channel_id)

            info = {
                "id": chat.id,
                "title": chat.title,
                "username": chat.username,
                "type": chat.type,
            }

            return ServiceResult.ok(info)

        except Exception as e:
            self.logger.error(
                "get_channel_info_error",
                error=str(e),
            )
            return ServiceResult.fail(f"Failed to get channel info: {e}")

    @staticmethod
    def format_post_text(
        title: str,
        products: list[dict],
        footer: str | None = None,
    ) -> str:
        """Format a post with multiple products.

        Args:
            title: Post title.
            products: List of product dicts with name, price, discount.
            footer: Optional footer text.

        Returns:
            Formatted HTML text.
        """
        lines = [f"<b>{title}</b>", ""]

        for i, product in enumerate(products, 1):
            name = product.get("name", "Товар")
            price = product.get("price", 0)
            discount = product.get("discount", 0)

            line = f"{i}. {name}"
            if discount > 0:
                line += f" <b>-{discount}%</b>"
            line += f"\n   💰 <b>{price:,} сом</b>".replace(",", " ")

            lines.append(line)
            lines.append("")

        if footer:
            lines.append(footer)

        return "\n".join(lines)
