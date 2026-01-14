"""
Tulpar Express Bot - Main Entry Point
"""
import asyncio
import logging
import sys
import traceback

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update, ErrorEvent

from src.config import config
from src.handlers import client_router, admin_router, excel_router, payment_router
from src.services.database import db_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def error_handler(event: ErrorEvent, bot: Bot):
    """Global error handler for all unhandled exceptions (Story 5.4)"""
    exception = event.exception
    update = event.update

    # Log error with full traceback
    logger.error(
        f"Exception while handling update: {exception}\n"
        f"Update: {update}\n"
        f"Traceback: {traceback.format_exc()}"
    )

    # Try to notify user about error
    try:
        if update and update.message:
            await update.message.answer(
                "❌ Произошла ошибка при обработке запроса.\n"
                "Попробуйте позже или обратитесь к администратору."
            )
    except Exception as notify_error:
        logger.error(f"Failed to notify user about error: {notify_error}")

    # Notify admin about error
    for admin_id in config.admin_chat_ids:
        try:
            user_info = ""
            if update and update.message and update.message.from_user:
                user_info = f"\nUser: {update.message.from_user.id}"

            await bot.send_message(
                admin_id,
                f"⚠️ <b>Ошибка в боте</b>\n\n"
                f"<code>{str(exception)[:500]}</code>{user_info}",
                parse_mode="HTML"
            )
        except Exception:
            pass


async def main():
    """Initialize and run the bot"""
    # Validate configuration
    try:
        config.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    logger.info("Starting Tulpar Express Bot...")

    # Initialize PostgreSQL connection
    if config.database_url:
        try:
            await db_service.connect()
            logger.info("PostgreSQL connected")
        except Exception as e:
            logger.error(f"PostgreSQL connection failed: {e}")
            logger.warning("Continuing with Google Sheets only")

    # Initialize bot and dispatcher
    bot = Bot(
        token=config.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Use memory storage for FSM (in production, consider Redis)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Register global error handler (Story 5.4)
    dp.errors.register(error_handler)

    # Register routers
    dp.include_router(admin_router)  # Admin router first for priority
    dp.include_router(excel_router)  # Excel handler for file uploads
    dp.include_router(payment_router)  # Payment handlers
    dp.include_router(client_router)

    # Log startup info
    bot_info = await bot.get_me()
    logger.info(f"Bot started: @{bot_info.username}")
    logger.info(f"Admin IDs: {config.admin_chat_ids}")

    # Notify admin about startup
    for admin_id in config.admin_chat_ids:
        try:
            await bot.send_message(
                admin_id,
                f"🚀 <b>Tulpar Express Bot запущен!</b>\n\n"
                f"Версия: 1.0.0\n"
                f"Bot: @{bot_info.username}",
            )
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id}: {e}")

    # Start polling
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        if config.database_url:
            await db_service.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
