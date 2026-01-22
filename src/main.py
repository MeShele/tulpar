"""
Tulpar Express Bot - Main Entry Point
Includes CRM functionality and Autopost module
"""
import asyncio
import logging
import sys
import traceback
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update, ErrorEvent

from src.config import config
from src.handlers import client_router, admin_router, excel_router, payment_router
from src.services.database import db_service

# Autopost imports (conditional)
try:
    from src.autopost.config import settings as autopost_settings
    AUTOPOST_AVAILABLE = True
except ImportError:
    AUTOPOST_AVAILABLE = False
    autopost_settings = None

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


async def setup_autopost_scheduler(bot: Bot) -> Optional["SchedulerService"]:
    """Initialize and start the autopost scheduler if enabled.

    Returns:
        SchedulerService instance if autopost is enabled and configured, None otherwise.
    """
    if not AUTOPOST_AVAILABLE or not autopost_settings:
        logger.info("Autopost module not available")
        return None

    if not autopost_settings.is_configured():
        missing = autopost_settings.validate_required()
        if missing:
            logger.info(f"Autopost disabled - missing config: {', '.join(missing)}")
        else:
            logger.info("Autopost disabled (AUTOPOST_ENABLED=false)")
        return None

    try:
        # Import autopost components
        from src.autopost.services.scheduler_service import SchedulerService
        from src.autopost.db.session import get_session_maker, get_engine, init_db
        # Import models to register them with Base.metadata
        from src.autopost.db.models import ProductDB, PostDB, CurrencyRateDB, SettingsDB  # noqa: F401
        from sqlalchemy import text

        # Test database connection for autopost
        async with get_engine().begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Autopost database connected")

        # Create autopost tables if they don't exist
        await init_db()
        logger.info("Autopost database tables initialized")

        # Create scheduler
        scheduler = SchedulerService(
            posting_time=autopost_settings.posting_time,
            timezone=autopost_settings.timezone,
        )

        # Define pipeline callback
        async def run_autopost_pipeline():
            """Execute the daily autopost pipeline."""
            logger.info("Running autopost pipeline...")
            try:
                from src.autopost.pipeline.daily_pipeline import DailyPipeline
                from src.autopost.services.pinduoduo import PinduoduoService
                from src.autopost.services.currency import CurrencyService
                from src.autopost.services.openai_service import OpenAIService
                from src.autopost.services.image_service import ImageService
                from src.autopost.services.telegram_service import TelegramService
                from src.autopost.services.notification_service import NotificationService
                from src.autopost.core.product_filter import ProductFilter
                from src.autopost.db.repositories import CurrencyRepository
                import httpx

                async with httpx.AsyncClient(timeout=30.0) as http_client:
                    async with get_session_maker()() as session:
                        currency_repo = CurrencyRepository(session)

                        pinduoduo = PinduoduoService(client=http_client)
                        currency = CurrencyService(client=http_client, repository=currency_repo)
                        text_service = OpenAIService(client=http_client)
                        image = ImageService(client=http_client)

                        telegram = TelegramService(
                            bot_token=autopost_settings.telegram_bot_token,
                            channel_id=autopost_settings.telegram_channel_id,
                            owner_ids=autopost_settings.owner_ids_list,
                        )

                        notification = NotificationService(telegram_service=telegram)

                        product_filter = ProductFilter(
                            min_discount=autopost_settings.min_discount,
                            min_rating=autopost_settings.min_rating,
                            top_limit=autopost_settings.top_products_limit,
                        )

                        pipeline = DailyPipeline(
                            pinduoduo_service=pinduoduo,
                            currency_service=currency,
                            taobao_service=None,
                            text_service=text_service,
                            image_service=image,
                            telegram_service=telegram,
                            instagram_service=None,  # Instagram disabled for now
                            notification_service=notification,
                            session=session,
                            product_filter=product_filter,
                        )

                        result = await pipeline.run()

                        if result.success:
                            logger.info(
                                f"Autopost completed: {result.products_count} products, "
                                f"telegram_id={result.telegram_message_id}"
                            )
                        else:
                            logger.error(f"Autopost failed: {result.error}")

            except Exception as e:
                logger.exception(f"Autopost pipeline error: {e}")

        scheduler.set_pipeline_callback(run_autopost_pipeline)
        scheduler.start()

        logger.info(
            f"Autopost scheduler started: time={autopost_settings.posting_time}, "
            f"channel={autopost_settings.telegram_channel_id}, "
            f"next_run={scheduler.get_next_run_time()}"
        )

        return scheduler

    except Exception as e:
        logger.error(f"Failed to setup autopost scheduler: {e}")
        return None


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

    # Initialize autopost scheduler (if enabled)
    autopost_scheduler = await setup_autopost_scheduler(bot)

    # Log startup info
    bot_info = await bot.get_me()
    logger.info(f"Bot started: @{bot_info.username}")
    logger.info(f"Admin IDs: {config.admin_chat_ids}")

    # Prepare startup message
    startup_msg = (
        f"🚀 <b>Tulpar Express Bot запущен!</b>\n\n"
        f"Версия: 1.0.0\n"
        f"Bot: @{bot_info.username}"
    )

    # Add autopost status to startup message
    if autopost_scheduler:
        startup_msg += (
            f"\n\n📢 <b>Автопостинг включён</b>\n"
            f"Канал: {autopost_settings.telegram_channel_id}\n"
            f"Время: {autopost_settings.posting_time}\n"
            f"След. запуск: {autopost_scheduler.get_next_run_time() or 'не запланирован'}"
        )
    else:
        startup_msg += "\n\n📢 Автопостинг выключен"

    # Notify admin about startup
    for admin_id in config.admin_chat_ids:
        try:
            await bot.send_message(admin_id, startup_msg)
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id}: {e}")

    # Start polling
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        # Cleanup
        if autopost_scheduler:
            autopost_scheduler.shutdown(wait=False)
        await bot.session.close()
        if config.database_url:
            await db_service.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
