"""Notification service for owner alerts."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from src.autopost.services.base import ServiceResult

if TYPE_CHECKING:
    from src.autopost.services.telegram_service import TelegramService


# Recommendations by pipeline stage
STAGE_RECOMMENDATIONS: dict[str, list[str]] = {
    "pinduoduo": [
        "Проверьте API ключ RapidAPI",
        "Проверьте лимиты запросов (50/день)",
        "Попробуйте повторить через 1 час",
    ],
    "openai": [
        "Проверьте баланс OpenAI аккаунта",
        "Проверьте API ключ",
        "Попробуйте уменьшить размер запроса",
    ],
    "telegram": [
        "Проверьте bot token",
        "Убедитесь что бот добавлен в канал как админ",
        "Проверьте права бота на отправку сообщений",
    ],
    "instagram": [
        "Проверьте access token (истекает каждые 60 дней)",
        "Обновите токен через Facebook Developer",
        "Проверьте привязку Instagram Business аккаунта",
    ],
    "image": [
        "Проверьте наличие файлов изображений",
        "Проверьте права доступа к директории",
        "Убедитесь что формат изображений поддерживается",
    ],
    "currency": [
        "Проверьте доступность API курса валют",
        "Система использует последний известный курс",
    ],
    "database": [
        "Проверьте подключение к PostgreSQL",
        "Проверьте наличие свободного места",
        "Перезапустите сервис базы данных",
    ],
}

# Default recommendations
DEFAULT_RECOMMENDATIONS: list[str] = [
    "Проверьте логи для деталей",
    "Попробуйте перезапустить сервис",
]


@dataclass
class PostInfo:
    """Information about a published post.

    Attributes:
        message_id: Telegram message ID.
        product_count: Number of products in the post.
        channel_id: Channel ID or username.
        published_at: Publication timestamp.
    """

    message_id: int
    product_count: int
    channel_id: str
    published_at: datetime | None = None


@dataclass
class ErrorInfo:
    """Information about an error for notification.

    Attributes:
        message: Error description.
        stage: Pipeline stage where error occurred.
        error_code: Optional error code.
        timestamp: When the error occurred.
        recommendations: Custom recommendations (overrides stage defaults).
    """

    message: str
    stage: str | None = None
    error_code: str | None = None
    timestamp: datetime | None = None
    recommendations: list[str] = field(default_factory=list)


class NotificationService:
    """Service for sending notifications to the owner.

    Handles:
    - Success notifications after publishing
    - Error notifications on failures with recommendations
    - Formatted messages with links and details
    """

    def __init__(self, telegram_service: TelegramService) -> None:
        """Initialize NotificationService.

        Args:
            telegram_service: TelegramService instance for sending messages.
        """
        self.telegram = telegram_service
        self.logger = structlog.get_logger(service="NotificationService")

    @staticmethod
    def build_post_link(channel_id: str, message_id: int) -> str:
        """Build a link to a Telegram post.

        Args:
            channel_id: Channel ID or username (e.g., "@channel" or "-1001234567890").
            message_id: Message ID.

        Returns:
            URL to the post.
        """
        if channel_id.startswith("@"):
            # Public channel with username
            username = channel_id[1:]  # Remove @ prefix
            return f"https://t.me/{username}/{message_id}"
        elif channel_id.startswith("-100"):
            # Private channel with numeric ID
            # Remove -100 prefix for the link
            numeric_id = channel_id[4:]
            return f"https://t.me/c/{numeric_id}/{message_id}"
        else:
            # Fallback for other formats
            return f"https://t.me/c/{channel_id}/{message_id}"

    @staticmethod
    def get_recommendations(stage: str | None) -> list[str]:
        """Get recommendations for a pipeline stage.

        Args:
            stage: Pipeline stage name.

        Returns:
            List of recommendations.
        """
        if not stage:
            return DEFAULT_RECOMMENDATIONS

        # Normalize stage name for lookup
        stage_lower = stage.lower()

        # Try to find matching recommendations
        for key, recommendations in STAGE_RECOMMENDATIONS.items():
            if key in stage_lower:
                return recommendations

        return DEFAULT_RECOMMENDATIONS

    async def notify_success(
        self,
        post_info: PostInfo,
    ) -> ServiceResult[int]:
        """Send success notification to the owner.

        Args:
            post_info: Information about the published post.

        Returns:
            ServiceResult with notification message_id on success.
        """
        self.logger.info(
            "sending_success_notification",
            message_id=post_info.message_id,
            product_count=post_info.product_count,
        )

        # Build link to the post
        post_link = self.build_post_link(
            post_info.channel_id,
            post_info.message_id,
        )

        # Format the notification message
        timestamp = post_info.published_at or datetime.now()
        time_str = timestamp.strftime("%H:%M")

        message = self._format_success_message(
            product_count=post_info.product_count,
            time_str=time_str,
            post_link=post_link,
        )

        # Send via TelegramService
        result = await self.telegram.notify_owner(message)

        if result.success:
            self.logger.info(
                "success_notification_sent",
                notification_id=result.data,
            )
        else:
            self.logger.error(
                "success_notification_failed",
                error=result.error,
            )

        return result

    async def notify_error(
        self,
        error: str | ErrorInfo,
        stage: str | None = None,
    ) -> ServiceResult[int]:
        """Send error notification to the owner.

        Args:
            error: Error description string or ErrorInfo object.
            stage: Pipeline stage (ignored if error is ErrorInfo).

        Returns:
            ServiceResult with notification message_id on success.
        """
        # Convert string to ErrorInfo if needed
        if isinstance(error, str):
            error_info = ErrorInfo(
                message=error,
                stage=stage,
                timestamp=datetime.now(),
            )
        else:
            error_info = error
            if error_info.timestamp is None:
                error_info.timestamp = datetime.now()

        self.logger.error(
            "pipeline_error",
            error_message=error_info.message,
            stage=error_info.stage,
            error_code=error_info.error_code,
            timestamp=error_info.timestamp.isoformat() if error_info.timestamp else None,
        )

        self.logger.info(
            "sending_error_notification",
            error=error_info.message,
            stage=error_info.stage,
        )

        # Get recommendations
        recommendations = (
            error_info.recommendations
            if error_info.recommendations
            else self.get_recommendations(error_info.stage)
        )

        # Format the message
        message = self._format_error_message(
            error_info=error_info,
            recommendations=recommendations,
        )

        # Send via TelegramService
        result = await self.telegram.notify_owner(message)

        if result.success:
            self.logger.info(
                "error_notification_sent",
                notification_id=result.data,
            )
        else:
            self.logger.error(
                "error_notification_failed",
                error=result.error,
            )

        return result

    @staticmethod
    def _format_success_message(
        product_count: int,
        time_str: str,
        post_link: str,
    ) -> str:
        """Format success notification message.

        Args:
            product_count: Number of products published.
            time_str: Formatted time string.
            post_link: URL to the post.

        Returns:
            Formatted HTML message.
        """
        lines = [
            "✅ <b>Пост опубликован!</b>",
            "",
            f"📦 Товаров: {product_count}",
            f"🕐 Время: {time_str}",
            f'🔗 <a href="{post_link}">Открыть пост</a>',
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_error_message(
        error_info: ErrorInfo,
        recommendations: list[str],
    ) -> str:
        """Format error notification message with recommendations.

        Args:
            error_info: Error information.
            recommendations: List of recommendations.

        Returns:
            Formatted HTML message.
        """
        lines = [
            "❌ <b>Ошибка публикации</b>",
            "",
        ]

        if error_info.stage:
            lines.append(f"📍 Этап: {html.escape(error_info.stage)}")

        lines.append(f"⚠️ {html.escape(error_info.message)}")

        if error_info.error_code:
            lines.append(f"🔢 Код: {html.escape(error_info.error_code)}")

        if recommendations:
            lines.append("")
            lines.append("💡 <b>Рекомендации:</b>")
            for rec in recommendations:
                lines.append(f"• {html.escape(rec)}")

        if error_info.timestamp:
            time_str = error_info.timestamp.strftime("%H:%M")
            lines.append("")
            lines.append(f"🕐 Время: {time_str}")

        return "\n".join(lines)
