"""Settings repository for database operations."""

from __future__ import annotations

import json
from typing import Any, Optional

import structlog
from cachetools import TTLCache
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.autopost.db.models import SettingsDB, SettingsHistoryDB, SettingValueType

logger = structlog.get_logger(__name__)

# TTL Cache: 5 minutes, max 100 entries
CACHE_TTL_SECONDS = 300
CACHE_MAX_SIZE = 100


class SettingsRepository:
    """Repository for settings database operations.

    Provides CRUD operations for dynamic settings with in-memory TTLCache
    for improved performance. Settings are stored as key-value pairs with
    type information for proper serialization.

    Attributes:
        session: SQLAlchemy async session for database operations.
    """

    # Class-level cache shared across instances
    _cache: TTLCache[str, Any] = TTLCache(
        maxsize=CACHE_MAX_SIZE, ttl=CACHE_TTL_SECONDS
    )

    def __init__(self, session: AsyncSession) -> None:
        """Initialize SettingsRepository with database session.

        Args:
            session: SQLAlchemy async session.
        """
        self.session = session

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the in-memory cache.

        Useful for testing or when cache invalidation is needed.
        """
        cls._cache.clear()
        logger.info("settings_cache_cleared")

    @staticmethod
    def _serialize_value(value: Any, value_type: SettingValueType) -> str:
        """Serialize a value to string based on its type.

        Args:
            value: The value to serialize.
            value_type: The type of the value.

        Returns:
            String representation of the value.
        """
        if value_type == SettingValueType.JSON:
            return json.dumps(value)
        elif value_type == SettingValueType.BOOL:
            return "true" if value else "false"
        else:
            return str(value)

    @staticmethod
    def _deserialize_value(value: str, value_type: str) -> Any:
        """Deserialize a string value based on its type.

        Args:
            value: The string value to deserialize.
            value_type: The type of the value.

        Returns:
            Deserialized value.
        """
        if value_type == SettingValueType.INT.value:
            return int(value)
        elif value_type == SettingValueType.FLOAT.value:
            return float(value)
        elif value_type == SettingValueType.BOOL.value:
            return value.lower() in ("true", "1", "yes")
        elif value_type == SettingValueType.JSON.value:
            return json.loads(value)
        else:  # STRING
            return value

    @staticmethod
    def _detect_value_type(value: Any) -> SettingValueType:
        """Detect the type of a value.

        Args:
            value: The value to check.

        Returns:
            Detected SettingValueType.
        """
        if isinstance(value, bool):
            return SettingValueType.BOOL
        elif isinstance(value, int):
            return SettingValueType.INT
        elif isinstance(value, float):
            return SettingValueType.FLOAT
        elif isinstance(value, (dict, list)):
            return SettingValueType.JSON
        else:
            return SettingValueType.STRING

    async def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value by key.

        Checks cache first, then database.

        Args:
            key: The setting key.
            default: Default value if not found.

        Returns:
            The setting value or default.
        """
        # Check cache first
        cache_key = f"setting:{key}"
        if cache_key in self._cache:
            logger.debug("setting_from_cache", key=key)
            return self._cache[cache_key]

        # Fetch from database
        stmt = select(SettingsDB).where(SettingsDB.key == key)
        result = await self.session.execute(stmt)
        setting = result.scalar_one_or_none()

        if setting is None:
            logger.debug("setting_not_found", key=key)
            return default

        # Deserialize and cache
        value = self._deserialize_value(setting.value, setting.value_type)
        self._cache[cache_key] = value

        logger.debug("setting_from_db", key=key, type=setting.value_type)
        return value

    async def set(
        self,
        key: str,
        value: Any,
        value_type: Optional[SettingValueType] = None,
        description: Optional[str] = None,
        changed_by: Optional[str] = None,
        change_reason: Optional[str] = None,
    ) -> None:
        """Set a setting value with history tracking.

        Uses upsert to handle both insert and update.
        Automatically records change in settings_history table (FR37).

        Args:
            key: The setting key.
            value: The value to store.
            value_type: Optional type override (auto-detected if not provided).
            description: Optional description.
            changed_by: Who made the change (user ID, system, etc.).
            change_reason: Why the change was made.
        """
        if value_type is None:
            value_type = self._detect_value_type(value)

        serialized = self._serialize_value(value, value_type)

        # Get old value for history
        old_value = await self._get_raw_value(key)

        stmt = insert(SettingsDB).values(
            key=key,
            value=serialized,
            value_type=value_type.value,
            description=description,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={
                "value": serialized,
                "value_type": value_type.value,
                "description": description if description else SettingsDB.description,
            },
        )

        await self.session.execute(stmt)

        # Record change in history (FR37 - settings history storage)
        history_entry = SettingsHistoryDB(
            setting_key=key,
            old_value=old_value,
            new_value=serialized,
            value_type=value_type.value,
            changed_by=changed_by,
            change_reason=change_reason,
        )
        self.session.add(history_entry)

        await self.session.commit()

        # Update cache
        cache_key = f"setting:{key}"
        self._cache[cache_key] = value

        logger.info(
            "setting_saved",
            key=key,
            type=value_type.value,
            changed_by=changed_by,
        )

    async def _get_raw_value(self, key: str) -> Optional[str]:
        """Get raw string value from database for history tracking.

        Args:
            key: The setting key.

        Returns:
            Raw string value or None if not found.
        """
        stmt = select(SettingsDB.value).where(SettingsDB.key == key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete(self, key: str) -> bool:
        """Delete a setting by key.

        Args:
            key: The setting key to delete.

        Returns:
            True if deleted, False if not found.
        """
        stmt = delete(SettingsDB).where(SettingsDB.key == key)
        result = await self.session.execute(stmt)
        await self.session.commit()

        # Remove from cache
        cache_key = f"setting:{key}"
        if cache_key in self._cache:
            del self._cache[cache_key]

        deleted = result.rowcount > 0
        if deleted:
            logger.info("setting_deleted", key=key)
        else:
            logger.debug("setting_not_found_for_delete", key=key)

        return deleted

    async def get_all(self) -> dict[str, Any]:
        """Get all settings as a dictionary.

        Returns:
            Dictionary of all settings (key -> value).
        """
        stmt = select(SettingsDB)
        result = await self.session.execute(stmt)
        settings = result.scalars().all()

        return {
            s.key: self._deserialize_value(s.value, s.value_type)
            for s in settings
        }

    async def get_by_prefix(self, prefix: str) -> dict[str, Any]:
        """Get all settings with a specific key prefix.

        Args:
            prefix: The prefix to filter by.

        Returns:
            Dictionary of matching settings.
        """
        stmt = select(SettingsDB).where(SettingsDB.key.startswith(prefix))
        result = await self.session.execute(stmt)
        settings = result.scalars().all()

        return {
            s.key: self._deserialize_value(s.value, s.value_type)
            for s in settings
        }

    async def exists(self, key: str) -> bool:
        """Check if a setting exists.

        Args:
            key: The setting key.

        Returns:
            True if exists, False otherwise.
        """
        # Check cache first
        cache_key = f"setting:{key}"
        if cache_key in self._cache:
            return True

        stmt = select(SettingsDB.id).where(SettingsDB.key == key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_history(
        self,
        key: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get settings change history (FR37).

        Args:
            key: Optional setting key to filter by.
            limit: Maximum number of records to return.

        Returns:
            List of history entries as dictionaries.
        """
        stmt = select(SettingsHistoryDB).order_by(SettingsHistoryDB.changed_at.desc())

        if key:
            stmt = stmt.where(SettingsHistoryDB.setting_key == key)

        stmt = stmt.limit(limit)

        result = await self.session.execute(stmt)
        entries = result.scalars().all()

        return [
            {
                "id": e.id,
                "key": e.setting_key,
                "old_value": e.old_value,
                "new_value": e.new_value,
                "value_type": e.value_type,
                "changed_by": e.changed_by,
                "change_reason": e.change_reason,
                "changed_at": e.changed_at.isoformat() if e.changed_at else None,
            }
            for e in entries
        ]

    async def rollback_setting(self, history_id: int) -> bool:
        """Rollback a setting to a previous value from history.

        Args:
            history_id: ID of the history entry to rollback to.

        Returns:
            True if rollback successful, False if history entry not found.
        """
        # Get history entry
        stmt = select(SettingsHistoryDB).where(SettingsHistoryDB.id == history_id)
        result = await self.session.execute(stmt)
        entry = result.scalar_one_or_none()

        if not entry:
            logger.warning("history_entry_not_found", history_id=history_id)
            return False

        # Restore old value (if it existed)
        if entry.old_value is not None:
            await self.set(
                key=entry.setting_key,
                value=self._deserialize_value(entry.old_value, entry.value_type),
                changed_by="system:rollback",
                change_reason=f"Rollback to history entry {history_id}",
            )
        else:
            # Setting didn't exist before, delete it
            await self.delete(entry.setting_key)

        logger.info(
            "setting_rolled_back",
            key=entry.setting_key,
            history_id=history_id,
        )

        return True
