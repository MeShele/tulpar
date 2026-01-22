"""Autopost module configuration.

Uses AUTOPOST_ prefix for channel-specific settings to avoid
conflicts with main bot configuration.
"""

import os
from typing import Optional


class AutopostSettings:
    """Autopost module settings loaded from environment variables."""

    def __init__(self):
        # Database - shared with main bot, auto-convert for SQLAlchemy async
        db_url = os.getenv("DATABASE_URL", "")
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        # Remove sslmode and channel_binding params (asyncpg handles SSL differently)
        # Keep only basic connection params
        if "?" in db_url:
            base_url = db_url.split("?")[0]
            # For asyncpg with Neon, we need ssl=require in connect_args, not URL
            self.database_url: str = base_url
            self._needs_ssl: bool = "sslmode=require" in db_url
        else:
            self.database_url: str = db_url
            self._needs_ssl: bool = False

        # RapidAPI (Pinduoduo)
        self.rapidapi_key: str = os.getenv("RAPIDAPI_KEY", "")

        # OpenRouter (GPT text generation)
        self.openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")

        # Telegram - shared bot token, separate channel for autopost
        self.telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
        # AUTOPOST_CHANNEL_ID - separate test channel for autoposting
        self.telegram_channel_id: str = os.getenv("AUTOPOST_CHANNEL_ID", "")

        # Owner IDs - use main bot's ADMIN_CHAT_ID
        self.owner_telegram_ids: str = os.getenv("ADMIN_CHAT_ID", "")

        # OpenAI model settings (via OpenRouter)
        self.openai_model: str = os.getenv("AUTOPOST_OPENAI_MODEL", "openai/gpt-4o-mini")
        self.openai_timeout: int = int(os.getenv("AUTOPOST_OPENAI_TIMEOUT", "30"))

        # Instagram (optional, not active for now)
        self.instagram_access_token: str = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
        self.instagram_account_id: str = os.getenv("INSTAGRAM_ACCOUNT_ID", "")

        # Autopost schedule settings
        self.posting_time: str = os.getenv("AUTOPOST_TIME", "19:00")
        self.timezone: str = os.getenv("AUTOPOST_TIMEZONE", "Asia/Bishkek")
        self.max_products: int = int(os.getenv("AUTOPOST_MAX_PRODUCTS", "10"))
        self.contact_username: str = os.getenv("AUTOPOST_CONTACT_USERNAME", "Ruslyandiy")

        # Product filtering settings
        self.min_discount: int = int(os.getenv("AUTOPOST_MIN_DISCOUNT", "0"))
        self.min_rating: float = float(os.getenv("AUTOPOST_MIN_RATING", "0"))
        self.top_products_limit: int = int(os.getenv("AUTOPOST_TOP_LIMIT", "10"))

        # Logging settings (shared with main bot)
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")
        self.log_format: str = os.getenv("LOG_FORMAT", "json")
        self.log_file: Optional[str] = os.getenv("LOG_FILE", "logs/tulpar.log")
        self.log_retention_days: int = int(os.getenv("LOG_RETENTION_DAYS", "30"))

        # Autopost enabled flag
        self.enabled: bool = os.getenv("AUTOPOST_ENABLED", "false").lower() == "true"

    @property
    def owner_ids_list(self) -> list[int]:
        """Get list of all owner Telegram IDs from ADMIN_CHAT_ID."""
        owners = set()
        if self.owner_telegram_ids:
            for id_str in self.owner_telegram_ids.split(","):
                id_str = id_str.strip()
                if id_str.isdigit():
                    owners.add(int(id_str))
        return list(owners)

    def validate_required(self) -> list[str]:
        """Check required fields and return list of missing ones.

        Only validates if autopost is enabled.
        """
        if not self.enabled:
            return []

        missing = []
        if not self.database_url:
            missing.append("DATABASE_URL")
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.telegram_channel_id:
            missing.append("AUTOPOST_CHANNEL_ID")
        if not self.rapidapi_key:
            missing.append("RAPIDAPI_KEY")
        if not self.openrouter_api_key:
            missing.append("OPENROUTER_API_KEY")
        return missing

    def is_configured(self) -> bool:
        """Check if autopost is properly configured and enabled."""
        return self.enabled and len(self.validate_required()) == 0


settings = AutopostSettings()
