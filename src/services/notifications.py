"""
Tulpar Express - Notification Service
Reusable module for sending notifications with retry and rate limiting
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.models import Client

logger = logging.getLogger(__name__)


@dataclass
class BroadcastResult:
    """Result of broadcast operation (AC 2.1.5)"""
    success_count: int = 0
    failed_list: List[Tuple[str, str]] = field(default_factory=list)  # [(code, error_message), ...]

    @property
    def total_count(self) -> int:
        return self.success_count + len(self.failed_list)

    @property
    def failed_count(self) -> int:
        return len(self.failed_list)


# Retry decorator for Telegram API errors (AC 2.1.3 - NFR9)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(TelegramAPIError),
    reraise=True,
)
async def send_notification(
    bot: Bot,
    chat_id: int,
    message_text: str,
    parse_mode: str = "HTML",
) -> bool:
    """
    Send notification to a single user with retry (AC 2.1.2, AC 2.1.3)

    Args:
        bot: aiogram Bot instance
        chat_id: Telegram chat ID
        message_text: Message text (supports HTML/Markdown)
        parse_mode: Parse mode (default: HTML)

    Returns:
        True if sent successfully, raises exception otherwise
    """
    await bot.send_message(
        chat_id=chat_id,
        text=message_text,
        parse_mode=parse_mode,
    )
    return True


async def broadcast(
    bot: Bot,
    clients: List[Client],
    message_template: str,
    parse_mode: str = "HTML",
    rate_limit_delay: float = 0.035,  # ~28 msg/sec (AC 2.1.4)
) -> BroadcastResult:
    """
    Broadcast message to multiple clients with rate limiting (AC 2.1.4, AC 2.1.5)

    Args:
        bot: aiogram Bot instance
        clients: List of Client objects to send to
        message_template: Message template (can use {code}, {full_name} placeholders)
        parse_mode: Parse mode (default: HTML)
        rate_limit_delay: Delay between messages in seconds

    Returns:
        BroadcastResult with success_count and failed_list
    """
    result = BroadcastResult()

    for client in clients:
        # Format message with client data
        message = message_template.format(
            code=client.code,
            full_name=client.full_name,
            phone=client.phone,
        )

        try:
            logger.info(f"Sending notification to {client.code} (chat_id={client.chat_id})")
            await send_notification(
                bot=bot,
                chat_id=client.chat_id,
                message_text=message,
                parse_mode=parse_mode,
            )
            result.success_count += 1
            logger.info(f"✅ Notification sent to {client.code}")

        except TelegramAPIError as e:
            error_msg = str(e)
            result.failed_list.append((client.code, error_msg))
            logger.warning(f"Failed to notify {client.code}: {error_msg}")

        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            result.failed_list.append((client.code, error_msg))
            logger.error(f"Failed to notify {client.code}: {error_msg}")

        # Rate limiting (AC 2.1.4)
        await asyncio.sleep(rate_limit_delay)

    logger.info(
        f"Broadcast complete: {result.success_count}/{result.total_count} successful"
    )
    return result


async def send_parcel_notification(
    bot: Bot,
    client: Client,
    status_message: str,
    tracking: Optional[str] = None,
    amount: Optional[float] = None,
) -> bool:
    """
    Send parcel status notification to client

    Args:
        bot: aiogram Bot instance
        client: Client to notify
        status_message: Status emoji and text (e.g., "📦 На складе в Китае")
        tracking: Optional tracking number
        amount: Optional payment amount in som

    Returns:
        True if sent, False if failed
    """
    lines = [f"<b>{status_message}</b>"]

    if tracking:
        lines.append(f"\nТрекинг: {tracking}")

    if amount and amount > 0:
        lines.append(f"\n💰 К оплате: <b>{amount:.0f} сом</b>")

    lines.append(f"\nВаш код: {client.code}")

    message = "\n".join(lines)

    try:
        await send_notification(bot, client.chat_id, message)
        return True
    except Exception as e:
        logger.error(f"Failed to send parcel notification to {client.code}: {e}")
        return False
