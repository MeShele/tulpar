"""Settings service for unified configuration management."""

from __future__ import annotations

import os
from typing import Any, Optional

import structlog
from cachetools import TTLCache
from sqlalchemy.ext.asyncio import AsyncSession

from src.autopost.db.models import SettingValueType
from src.autopost.db.repositories.settings_repository import SettingsRepository

logger = structlog.get_logger(__name__)

# TTL Cache for combined settings: 1 minute
CACHE_TTL_SECONDS = 60
CACHE_MAX_SIZE = 200

# Dynamic settings that can be stored in DB (not secrets)
DYNAMIC_SETTINGS = {
    "posting_time",
    "timezone",
    "max_products",
    "min_discount",
    "min_rating",
    "top_products_limit",
    "log_level",
    "log_format",
}

# Settings that must only come from env (secrets - NFR6)
ENV_ONLY_SETTINGS = {
    "database_url",
    "rapidapi_key",
    "openrouter_api_key",
    "telegram_bot_token",
    "instagram_access_token",
}


class SettingsService:
    """Service for unified configuration management.

    Combines settings from multiple sources with priority:
    1. Environment variables (.env) - highest priority
    2. Database (settings table) - dynamic settings
    3. Default values - fallback

    API keys and secrets are only loaded from environment (NFR6).

    Attributes:
        repository: SettingsRepository for database operations.
    """

    # Class-level cache
    _cache: TTLCache[str, Any] = TTLCache(
        maxsize=CACHE_MAX_SIZE, ttl=CACHE_TTL_SECONDS
    )

    def __init__(self, session: Optional[AsyncSession] = None) -> None:
        """Initialize SettingsService.

        Args:
            session: Optional SQLAlchemy async session for DB access.
        """
        self._session = session
        self._repository: Optional[SettingsRepository] = None

    @property
    def repository(self) -> Optional[SettingsRepository]:
        """Get or create the settings repository."""
        if self._repository is None and self._session is not None:
            self._repository = SettingsRepository(self._session)
        return self._repository

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the in-memory cache."""
        cls._cache.clear()
        logger.info("settings_service_cache_cleared")

    def _get_env_value(self, key: str) -> Optional[str]:
        """Get a setting value from environment variables.

        Args:
            key: The setting key (case-insensitive).

        Returns:
            Environment variable value or None.
        """
        # Try uppercase first (standard convention)
        value = os.environ.get(key.upper())
        if value is not None:
            return value

        # Try lowercase
        return os.environ.get(key.lower())

    def _convert_env_value(self, value: str, expected_type: type) -> Any:
        """Convert environment variable string to expected type.

        Args:
            value: String value from environment.
            expected_type: Expected Python type.

        Returns:
            Converted value.
        """
        if expected_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif expected_type == int:
            return int(value)
        elif expected_type == float:
            return float(value)
        else:
            return value

    async def get(
        self,
        key: str,
        default: Any = None,
        expected_type: Optional[type] = None,
    ) -> Any:
        """Get a setting value with priority: env > db > default.

        Args:
            key: The setting key.
            default: Default value if not found.
            expected_type: Optional type for conversion.

        Returns:
            Setting value or default.
        """
        # Check cache first
        cache_key = f"combined:{key}"
        if cache_key in self._cache:
            logger.debug("setting_from_combined_cache", key=key)
            return self._cache[cache_key]

        # 1. Check environment variables (highest priority)
        env_value = self._get_env_value(key)
        if env_value is not None:
            if expected_type:
                value = self._convert_env_value(env_value, expected_type)
            else:
                value = env_value
            self._cache[cache_key] = value
            logger.debug("setting_from_env", key=key)
            return value

        # 2. Check database (if available and key is dynamic)
        if self.repository and key in DYNAMIC_SETTINGS:
            db_value = await self.repository.get(key)
            if db_value is not None:
                self._cache[cache_key] = db_value
                logger.debug("setting_from_db", key=key)
                return db_value

        # 3. Return default
        if default is not None:
            self._cache[cache_key] = default
        logger.debug("setting_using_default", key=key)
        return default

    async def set(
        self,
        key: str,
        value: Any,
        value_type: Optional[SettingValueType] = None,
        description: Optional[str] = None,
    ) -> bool:
        """Set a dynamic setting in the database.

        Only dynamic settings can be stored in DB. Secrets must be in .env.

        Args:
            key: The setting key.
            value: The value to store.
            value_type: Optional type override.
            description: Optional description.

        Returns:
            True if saved, False if key is not allowed.

        Raises:
            ValueError: If trying to store a secret in DB.
        """
        if key in ENV_ONLY_SETTINGS:
            raise ValueError(
                f"Setting '{key}' must be in environment variables only (NFR6)"
            )

        if key not in DYNAMIC_SETTINGS:
            logger.warning(
                "unknown_dynamic_setting",
                key=key,
                hint="Add to DYNAMIC_SETTINGS if this should be persisted",
            )

        if self.repository is None:
            logger.error("no_db_session", key=key)
            return False

        await self.repository.set(key, value, value_type, description)

        # Invalidate cache
        cache_key = f"combined:{key}"
        if cache_key in self._cache:
            del self._cache[cache_key]

        logger.info("dynamic_setting_saved", key=key)
        return True

    async def get_all_dynamic(self) -> dict[str, Any]:
        """Get all dynamic settings from database.

        Returns:
            Dictionary of all stored settings.
        """
        if self.repository is None:
            return {}
        return await self.repository.get_all()

    def get_env(self, key: str, default: Any = None) -> Any:
        """Get a setting value from environment only.

        Use this for secrets that must not be in database.

        Args:
            key: The setting key.
            default: Default value if not found.

        Returns:
            Environment variable value or default.
        """
        value = self._get_env_value(key)
        return value if value is not None else default

    def is_secret(self, key: str) -> bool:
        """Check if a setting key is a secret.

        Args:
            key: The setting key.

        Returns:
            True if the key should only be in environment.
        """
        return key in ENV_ONLY_SETTINGS

    def is_dynamic(self, key: str) -> bool:
        """Check if a setting can be stored in database.

        Args:
            key: The setting key.

        Returns:
            True if the key can be stored dynamically.
        """
        return key in DYNAMIC_SETTINGS
