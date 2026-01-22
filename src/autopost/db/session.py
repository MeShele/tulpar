"""Database session management for async PostgreSQL connections."""

from collections.abc import AsyncGenerator
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine, AsyncEngine
from sqlalchemy.orm import DeclarativeBase

from src.autopost.config import settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


# Lazy initialization of engine and session maker
_engine: Optional[AsyncEngine] = None
_async_session_maker: Optional[async_sessionmaker] = None


def get_engine() -> AsyncEngine:
    """Get or create async engine."""
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not configured")

        # Build connect_args for SSL if needed (Neon.tech requires SSL)
        connect_args = {}
        if getattr(settings, '_needs_ssl', False):
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            connect_args["ssl"] = ssl_context

        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            connect_args=connect_args,
        )
    return _engine


def get_session_maker() -> async_sessionmaker:
    """Get or create async session maker."""
    global _async_session_maker
    if _async_session_maker is None:
        _async_session_maker = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_maker


# For backward compatibility - these will be created on first access
@property
def engine() -> AsyncEngine:
    return get_engine()


@property
def async_session_maker() -> async_sessionmaker:
    return get_session_maker()


# Module-level accessors (lazy)
class _LazyEngine:
    def __getattr__(self, name):
        return getattr(get_engine(), name)

class _LazySessionMaker:
    def __call__(self, *args, **kwargs):
        return get_session_maker()(*args, **kwargs)
    def __getattr__(self, name):
        return getattr(get_session_maker(), name)


engine = _LazyEngine()
async_session_maker = _LazySessionMaker()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session."""
    async with get_session_maker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections."""
    global _engine, _async_session_maker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _async_session_maker = None
