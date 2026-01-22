"""Bot command and callback handlers for the owner bot."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable

import structlog
from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import BaseFilter, Command
from aiogram.types import CallbackQuery, Message

from src.autopost.bot.keyboards import (
    BTN_POSTS,
    BTN_RUN,
    BTN_STATUS,
    CALLBACK_ADMIN_BACK,
    CALLBACK_ADMIN_POSTS,
    CALLBACK_ADMIN_RUN,
    CALLBACK_ADMIN_STATUS,
    CALLBACK_POST_VIEW,
    CALLBACK_POSTS_PAGE,
    CALLBACK_PRODUCT_LINK,
    POSTS_PAGE_SIZE,
    build_admin_menu_keyboard,
    build_back_to_menu_keyboard,
    build_main_menu_reply_keyboard,
    build_post_detail_keyboard,
    build_posts_keyboard,
    format_post_detail_message,
    format_posts_list_message,
    format_product_link_message,
)
from src.autopost.db.repositories.post_repository import PostRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# Router for owner commands
owner_router = Router(name="owner")


class OwnerFilter(BaseFilter):
    """Filter to check if user is an owner/admin."""

    def __init__(self, owner_ids: list[int]) -> None:
        """Initialize with list of owner IDs.

        Args:
            owner_ids: List of Telegram IDs of owners/admins.
        """
        self.owner_ids = set(owner_ids)

    async def __call__(self, message: Message | CallbackQuery) -> bool:
        """Check if the message/callback is from an owner.

        Args:
            message: Message or CallbackQuery to check.

        Returns:
            True if from any owner, False otherwise.
        """
        user_id = message.from_user.id if message.from_user else None
        return user_id in self.owner_ids


def setup_owner_router(
    owner_ids: list[int],
    session_factory: Callable[[], AsyncSession],
) -> Router:
    """Set up the owner router with handlers.

    Args:
        owner_ids: List of Telegram IDs of owners/admins.
        session_factory: Factory to create database sessions.

    Returns:
        Configured Router instance.
    """
    router = Router(name="owner")
    owner_filter = OwnerFilter(owner_ids)

    @router.message(Command("posts"), owner_filter)
    async def handle_posts_command(message: Message) -> None:
        """Handle /posts command - show list of posts.

        Args:
            message: Incoming message with /posts command.
        """
        logger.info(
            "posts_command_received",
            user_id=message.from_user.id if message.from_user else None,
        )

        async with session_factory() as session:
            repo = PostRepository(session)
            posts, total = await repo.get_posts(page=1, page_size=POSTS_PAGE_SIZE)
            total_pages = max(1, math.ceil(total / POSTS_PAGE_SIZE))

            text = format_posts_list_message(posts, 1, total_pages, total)
            keyboard = build_posts_keyboard(posts, 1, total_pages)

            await message.answer(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )

    @router.callback_query(F.data.startswith(CALLBACK_POSTS_PAGE), owner_filter)
    async def handle_posts_page(callback: CallbackQuery) -> None:
        """Handle pagination callback for posts list.

        Args:
            callback: Callback query with page number.
        """
        if not callback.data:
            await callback.answer()
            return

        try:
            page = int(callback.data.split(":")[-1])
        except ValueError:
            await callback.answer("Ошибка пагинации")
            return

        logger.info(
            "posts_page_callback",
            user_id=callback.from_user.id if callback.from_user else None,
            page=page,
        )

        async with session_factory() as session:
            repo = PostRepository(session)
            posts, total = await repo.get_posts(page=page, page_size=POSTS_PAGE_SIZE)
            total_pages = max(1, math.ceil(total / POSTS_PAGE_SIZE))

            text = format_posts_list_message(posts, page, total_pages, total)
            keyboard = build_posts_keyboard(posts, page, total_pages)

            if callback.message:
                await callback.message.edit_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )

        await callback.answer()

    @router.callback_query(F.data.startswith(CALLBACK_POST_VIEW), owner_filter)
    async def handle_post_view(callback: CallbackQuery) -> None:
        """Handle post view callback - show post details.

        Args:
            callback: Callback query with post ID.
        """
        if not callback.data:
            await callback.answer()
            return

        try:
            post_id = int(callback.data.split(":")[-1])
        except ValueError:
            await callback.answer("Ошибка: неверный ID поста")
            return

        logger.info(
            "post_view_callback",
            user_id=callback.from_user.id if callback.from_user else None,
            post_id=post_id,
        )

        async with session_factory() as session:
            repo = PostRepository(session)
            post = await repo.get_post_by_id(post_id)

            if not post:
                await callback.answer("Пост не найден")
                return

            text = format_post_detail_message(post)
            keyboard = build_post_detail_keyboard(post)

            if callback.message:
                await callback.message.edit_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )

        await callback.answer()

    @router.callback_query(F.data.startswith(CALLBACK_PRODUCT_LINK), owner_filter)
    async def handle_product_link(callback: CallbackQuery) -> None:
        """Handle product link callback - send Pinduoduo link.

        Args:
            callback: Callback query with post_id and product_index.
        """
        if not callback.data:
            await callback.answer()
            return

        try:
            # Parse callback data: product:link:post_id:product_index
            parts = callback.data.split(":")
            post_id = int(parts[2])
            product_index = int(parts[3])
        except (ValueError, IndexError):
            await callback.answer("Ошибка: неверный формат данных")
            return

        logger.info(
            "product_link_callback",
            user_id=callback.from_user.id if callback.from_user else None,
            post_id=post_id,
            product_index=product_index,
        )

        async with session_factory() as session:
            repo = PostRepository(session)
            post = await repo.get_post_by_id(post_id)

            if not post:
                await callback.answer("Пост не найден")
                return

            products = post.products_json if post.products_json else []

            if product_index < 0 or product_index >= len(products):
                await callback.answer("Товар не найден")
                return

            product = products[product_index]
            text = format_product_link_message(product, product_index)

            # Send as new message (not edit) so link is clickable
            if callback.message:
                await callback.message.answer(
                    text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False,
                )

        await callback.answer()

    @router.callback_query(F.data == "noop", owner_filter)
    async def handle_noop(callback: CallbackQuery) -> None:
        """Handle noop callback (page indicator button).

        Args:
            callback: Callback query.
        """
        await callback.answer()

    @router.message(Command("status"), owner_filter)
    async def handle_status_command(message: Message) -> None:
        """Handle /status command - show system health status.

        Args:
            message: Incoming message with /status command.
        """
        from datetime import datetime

        from src.autopost.services.health_service import HealthService
        from src.autopost.services.scheduler_service import SchedulerService

        logger.info(
            "status_command_received",
            user_id=message.from_user.id if message.from_user else None,
        )

        await message.answer("⏳ Проверяю статус системы...")

        async with session_factory() as session:
            # Create health service
            health_service = HealthService(
                session=session,
                version="1.0.0",
                start_time=datetime.now(),  # Will be replaced with actual start time
            )

            # Run health check
            result = await health_service.check_health()

            # Format message
            text = health_service.format_status_message(result)

            await message.answer(text, parse_mode=ParseMode.HTML)

    @router.message(Command("run"), owner_filter)
    async def handle_run_command(message: Message) -> None:
        """Handle /run command - manually trigger the pipeline.

        Args:
            message: Incoming message with /run command.
        """
        logger.info(
            "run_command_received",
            user_id=message.from_user.id if message.from_user else None,
        )

        await message.answer(
            "🚀 <b>Запускаю пайплайн...</b>\n\n"
            "Это может занять несколько минут.\n"
            "Вы получите уведомление о результате.",
            parse_mode=ParseMode.HTML,
        )

        # Import here to avoid circular imports
        from src.autopost.main import execute_pipeline

        async with session_factory() as session:
            try:
                await execute_pipeline(session)
                await message.answer(
                    "✅ <b>Пайплайн завершён успешно!</b>\n\n"
                    "Используйте /posts для просмотра публикации.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.exception("manual_pipeline_error", error=str(e))
                await message.answer(
                    f"❌ <b>Ошибка при выполнении пайплайна:</b>\n\n"
                    f"<code>{str(e)[:200]}</code>",
                    parse_mode=ParseMode.HTML,
                )

    @router.message(Command("start"), owner_filter)
    async def handle_start_command(message: Message) -> None:
        """Handle /start command - show main menu with reply keyboard.

        Args:
            message: Incoming message with /start command.
        """
        text = (
            "👋 <b>Тулпар Экспресс</b>\n\n"
            "Используйте кнопки внизу для управления:"
        )

        await message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_menu_reply_keyboard(),
        )

    # Reply keyboard button handlers
    @router.message(F.text == BTN_RUN, owner_filter)
    async def handle_run_button(message: Message) -> None:
        """Handle Run button press."""
        await handle_run_command(message)

    @router.message(F.text == BTN_POSTS, owner_filter)
    async def handle_posts_button(message: Message) -> None:
        """Handle Posts button press."""
        await handle_posts_command(message)

    @router.message(F.text == BTN_STATUS, owner_filter)
    async def handle_status_button(message: Message) -> None:
        """Handle Status button press."""
        await handle_status_command(message)

    @router.message(Command("help"), owner_filter)
    async def handle_help_command(message: Message) -> None:
        """Handle /help command.

        Args:
            message: Incoming message with /help command.
        """
        text = (
            "📖 <b>Справка по боту Тулпар Экспресс</b>\n\n"
            "<b>Команды:</b>\n"
            "/posts - Показать список опубликованных постов\n"
            "/status - Проверить статус системы\n"
            "/run - Запустить пайплайн вручную\n"
            "/help - Показать эту справку\n\n"
            "<b>В списке постов:</b>\n"
            "• Нажмите на пост для просмотра товаров\n"
            "• Используйте кнопки ← → для навигации\n\n"
            "<b>Статусы постов:</b>\n"
            "✅ Опубликован - TG + Instagram\n"
            "📱 Только TG - только Telegram\n"
            "⚠️ IG ошибка - Instagram не опубликован\n"
            "⏳ Ожидает - ещё не опубликован\n\n"
            "<b>Автопубликация:</b>\n"
            "Бот автоматически публикует товары каждый день в 19:00 (Бишкек)"
        )

        await message.answer(text, parse_mode=ParseMode.HTML)

    # Admin menu callback handlers
    @router.callback_query(F.data == CALLBACK_ADMIN_RUN, owner_filter)
    async def handle_admin_run(callback: CallbackQuery) -> None:
        """Handle admin run button - trigger pipeline.

        Args:
            callback: Callback query from admin menu.
        """
        logger.info(
            "admin_run_callback",
            user_id=callback.from_user.id if callback.from_user else None,
        )

        await callback.answer()

        if callback.message:
            await callback.message.edit_text(
                "🚀 <b>Запускаю пайплайн...</b>\n\n"
                "Это может занять несколько минут.\n"
                "Вы получите уведомление о результате.",
                parse_mode=ParseMode.HTML,
            )

        # Import here to avoid circular imports
        from src.autopost.main import execute_pipeline

        async with session_factory() as session:
            try:
                await execute_pipeline(session)
                if callback.message:
                    await callback.message.answer(
                        "✅ <b>Пайплайн завершён успешно!</b>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=build_admin_menu_keyboard(),
                    )
            except Exception as e:
                logger.exception("admin_run_error", error=str(e))
                if callback.message:
                    await callback.message.answer(
                        f"❌ <b>Ошибка:</b>\n<code>{str(e)[:200]}</code>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=build_admin_menu_keyboard(),
                    )

    @router.callback_query(F.data == CALLBACK_ADMIN_POSTS, owner_filter)
    async def handle_admin_posts(callback: CallbackQuery) -> None:
        """Handle admin posts button - show posts list.

        Args:
            callback: Callback query from admin menu.
        """
        logger.info(
            "admin_posts_callback",
            user_id=callback.from_user.id if callback.from_user else None,
        )

        async with session_factory() as session:
            repo = PostRepository(session)
            posts, total = await repo.get_posts(page=1, page_size=POSTS_PAGE_SIZE)
            total_pages = max(1, math.ceil(total / POSTS_PAGE_SIZE))

            text = format_posts_list_message(posts, 1, total_pages, total)
            keyboard = build_posts_keyboard(posts, 1, total_pages)

            if callback.message:
                await callback.message.edit_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )

        await callback.answer()

    @router.callback_query(F.data == CALLBACK_ADMIN_STATUS, owner_filter)
    async def handle_admin_status(callback: CallbackQuery) -> None:
        """Handle admin status button - show system health.

        Args:
            callback: Callback query from admin menu.
        """
        from datetime import datetime

        from src.autopost.services.health_service import HealthService

        logger.info(
            "admin_status_callback",
            user_id=callback.from_user.id if callback.from_user else None,
        )

        await callback.answer("⏳ Проверяю...")

        async with session_factory() as session:
            health_service = HealthService(
                session=session,
                version="1.0.0",
                start_time=datetime.now(),
            )
            result = await health_service.check_health()
            text = health_service.format_status_message(result)

            if callback.message:
                await callback.message.edit_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=build_back_to_menu_keyboard(),
                )

    @router.callback_query(F.data == CALLBACK_ADMIN_BACK, owner_filter)
    async def handle_admin_back(callback: CallbackQuery) -> None:
        """Handle back to menu button.

        Args:
            callback: Callback query.
        """
        text = (
            "👋 <b>Тулпар Экспресс</b>\n\n"
            "Выберите действие:"
        )

        if callback.message:
            await callback.message.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=build_admin_menu_keyboard(),
            )

        await callback.answer()

    return router
