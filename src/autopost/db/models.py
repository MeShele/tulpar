"""SQLAlchemy models for Tulpar Express."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.autopost.db.session import Base


class PostStatus(str, Enum):
    """Status enum for posts.

    Tracks the publication state of posts across platforms.
    """

    PENDING = "pending"  # Post created, waiting for publication
    TELEGRAM_ONLY = "telegram_only"  # Published only in Telegram
    PUBLISHED = "published"  # Published in both Telegram and Instagram
    INSTAGRAM_FAILED = "instagram_failed"  # Telegram OK, Instagram failed


class ProductDB(Base):
    """SQLAlchemy model for cached products from Pinduoduo.

    Stores product data for fallback when API is unavailable.
    Uses pdd_id as unique identifier for upsert operations.
    """

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pdd_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    price_cny: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    image_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    rating: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    discount: Mapped[int] = mapped_column(Integer, nullable=False)
    sales_count: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_products_category_updated", "category", "updated_at"),
    )

    def __repr__(self) -> str:
        """Return string representation of ProductDB."""
        return f"<ProductDB(pdd_id={self.pdd_id}, title={self.title[:30]}...)>"


class CurrencyRateDB(Base):
    """SQLAlchemy model for currency exchange rate history.

    Stores historical exchange rates for fallback when API is unavailable.
    """

    __tablename__ = "currency_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    to_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_currency_rates_pair_date",
            "from_currency",
            "to_currency",
            fetched_at.desc(),
        ),
    )

    def __repr__(self) -> str:
        """Return string representation of CurrencyRateDB."""
        return f"<CurrencyRateDB({self.from_currency}/{self.to_currency}={self.rate})>"


class PostDB(Base):
    """SQLAlchemy model for posts published to Telegram/Instagram.

    Stores publication history and status for tracking.
    """

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    instagram_post_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    products_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PostStatus.PENDING.value,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_posts_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        """Return string representation of PostDB."""
        return f"<PostDB(id={self.id}, status={self.status})>"


class SettingValueType(str, Enum):
    """Type enum for settings values.

    Defines supported types for stored settings.
    """

    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    JSON = "json"


class SettingsDB(Base):
    """SQLAlchemy model for dynamic application settings.

    Stores key-value settings that can be changed without restart.
    API keys and secrets should remain in .env (NFR6).
    """

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(1000), nullable=False)
    value_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=SettingValueType.STRING.value,
    )
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        """Return string representation of SettingsDB."""
        return f"<SettingsDB(key={self.key}, type={self.value_type})>"


class SettingsHistoryDB(Base):
    """SQLAlchemy model for settings change history.

    Tracks all changes to settings for audit and rollback capability.
    Implements FR37 (settings history storage).
    """

    __tablename__ = "settings_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    setting_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    old_value: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    new_value: Mapped[str] = mapped_column(String(1000), nullable=False)
    value_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=SettingValueType.STRING.value,
    )
    changed_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    change_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_settings_history_key_date", "setting_key", "changed_at"),
    )

    def __repr__(self) -> str:
        """Return string representation of SettingsHistoryDB."""
        return f"<SettingsHistoryDB(key={self.setting_key}, changed_at={self.changed_at})>"
