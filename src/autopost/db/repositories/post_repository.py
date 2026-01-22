"""Post repository for database operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.autopost.db.models import PostDB, PostStatus

logger = structlog.get_logger(__name__)

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100


class PostRepository:
    """Repository for post database operations.

    Provides CRUD operations for post tracking and publication history.

    Attributes:
        session: SQLAlchemy async session for database operations.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize PostRepository with database session.

        Args:
            session: SQLAlchemy async session.
        """
        self.session = session

    async def create_post(
        self,
        products_json: list[dict[str, Any]],
        telegram_message_id: int | None = None,
        instagram_post_id: str | None = None,
        status: PostStatus = PostStatus.PENDING,
    ) -> PostDB:
        """Create a new post record.

        Args:
            products_json: List of products included in the post.
            telegram_message_id: Optional Telegram message ID.
            instagram_post_id: Optional Instagram post ID.
            status: Initial post status.

        Returns:
            Created PostDB instance.
        """
        now = datetime.now(timezone.utc)
        published_at = now if status != PostStatus.PENDING else None

        post = PostDB(
            telegram_message_id=telegram_message_id,
            instagram_post_id=instagram_post_id,
            products_json=products_json,
            status=status.value,
            created_at=now,
            published_at=published_at,
        )

        self.session.add(post)
        await self.session.commit()
        await self.session.refresh(post)

        logger.info(
            "post_created",
            post_id=post.id,
            status=status.value,
            telegram_message_id=telegram_message_id,
            instagram_post_id=instagram_post_id,
        )

        return post

    async def update_instagram_id(
        self,
        post_id: int,
        instagram_post_id: str,
    ) -> PostDB | None:
        """Update post with Instagram post ID and mark as published.

        Args:
            post_id: Post ID to update.
            instagram_post_id: Instagram post ID.

        Returns:
            Updated PostDB instance or None if not found.
        """
        post = await self.get_post_by_id(post_id)
        if not post:
            logger.warning("post_not_found_for_instagram_update", post_id=post_id)
            return None

        post.instagram_post_id = instagram_post_id
        post.status = PostStatus.PUBLISHED.value
        post.published_at = datetime.now(timezone.utc)

        await self.session.commit()
        await self.session.refresh(post)

        logger.info(
            "post_instagram_updated",
            post_id=post_id,
            instagram_post_id=instagram_post_id,
        )

        return post

    async def get_posts(
        self,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        status: PostStatus | None = None,
    ) -> tuple[list[PostDB], int]:
        """Get posts with pagination.

        Args:
            page: Page number (1-indexed).
            page_size: Number of posts per page.
            status: Optional filter by status.

        Returns:
            Tuple of (list of posts, total count).
        """
        # Clamp page_size
        page_size = min(max(1, page_size), MAX_PAGE_SIZE)
        page = max(1, page)
        offset = (page - 1) * page_size

        # Base query
        stmt = select(PostDB).order_by(PostDB.created_at.desc())
        count_stmt = select(func.count(PostDB.id))

        if status:
            stmt = stmt.where(PostDB.status == status.value)
            count_stmt = count_stmt.where(PostDB.status == status.value)

        # Get total count
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar() or 0

        # Get paginated results
        stmt = stmt.offset(offset).limit(page_size)
        result = await self.session.execute(stmt)
        posts = list(result.scalars().all())

        logger.debug(
            "posts_fetched",
            page=page,
            page_size=page_size,
            count=len(posts),
            total=total,
        )

        return posts, total

    async def get_post_by_id(self, post_id: int) -> PostDB | None:
        """Get post by ID.

        Args:
            post_id: Post ID to fetch.

        Returns:
            PostDB instance or None if not found.
        """
        stmt = select(PostDB).where(PostDB.id == post_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_instagram_failed(self, post_id: int) -> PostDB | None:
        """Mark post as Instagram failed.

        Used when Telegram succeeds but Instagram fails.

        Args:
            post_id: Post ID to mark as failed.

        Returns:
            Updated PostDB instance or None if not found.
        """
        post = await self.get_post_by_id(post_id)
        if not post:
            logger.warning("post_not_found_for_instagram_failed", post_id=post_id)
            return None

        post.status = PostStatus.INSTAGRAM_FAILED.value

        await self.session.commit()
        await self.session.refresh(post)

        logger.info(
            "post_marked_instagram_failed",
            post_id=post_id,
        )

        return post

    async def mark_telegram_only(self, post_id: int) -> PostDB | None:
        """Mark post as Telegram only.

        Used when post is published only to Telegram.

        Args:
            post_id: Post ID to mark.

        Returns:
            Updated PostDB instance or None if not found.
        """
        post = await self.get_post_by_id(post_id)
        if not post:
            logger.warning("post_not_found_for_telegram_only", post_id=post_id)
            return None

        post.status = PostStatus.TELEGRAM_ONLY.value
        post.published_at = datetime.now(timezone.utc)

        await self.session.commit()
        await self.session.refresh(post)

        logger.info(
            "post_marked_telegram_only",
            post_id=post_id,
        )

        return post

    async def get_posts_count(self, status: PostStatus | None = None) -> int:
        """Get count of posts.

        Args:
            status: Optional filter by status.

        Returns:
            Number of posts.
        """
        stmt = select(func.count(PostDB.id))
        if status:
            stmt = stmt.where(PostDB.status == status.value)

        result = await self.session.execute(stmt)
        return result.scalar() or 0
