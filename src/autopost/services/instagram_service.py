"""Instagram Graph API service for publishing content."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.autopost.services.base import ServiceResult


# Instagram Graph API base URL
GRAPH_API_URL = "https://graph.facebook.com/v18.0"

# Default timeout for API requests (30 seconds per NFR5)
INSTAGRAM_TIMEOUT = 30.0

# Token expiration warning threshold (7 days)
TOKEN_EXPIRY_WARNING_DAYS = 7

# Carousel limits
MIN_CAROUSEL_ITEMS = 2
MAX_CAROUSEL_ITEMS = 10

# Container status check interval (seconds)
CONTAINER_CHECK_INTERVAL = 1.0
MAX_CONTAINER_CHECKS = 30


@dataclass
class TokenInfo:
    """Information about an access token.

    Attributes:
        is_valid: Whether the token is valid.
        expires_at: Token expiration datetime.
        scopes: List of granted permissions.
        app_id: Facebook App ID.
        user_id: Facebook User ID.
    """

    is_valid: bool
    expires_at: datetime | None = None
    scopes: list[str] | None = None
    app_id: str | None = None
    user_id: str | None = None

    @property
    def is_expiring_soon(self) -> bool:
        """Check if token expires within warning threshold."""
        if not self.expires_at:
            return False
        warning_date = datetime.now() + timedelta(days=TOKEN_EXPIRY_WARNING_DAYS)
        return self.expires_at < warning_date

    @property
    def days_until_expiry(self) -> int | None:
        """Get number of days until token expires."""
        if not self.expires_at:
            return None
        delta = self.expires_at - datetime.now()
        return max(0, delta.days)


@dataclass
class InstagramAccount:
    """Instagram Business Account information.

    Attributes:
        id: Instagram Business Account ID.
        username: Instagram username.
        name: Account display name.
        followers_count: Number of followers.
        media_count: Number of media posts.
    """

    id: str
    username: str | None = None
    name: str | None = None
    followers_count: int | None = None
    media_count: int | None = None


class InstagramAPIError(Exception):
    """Exception for Instagram API errors."""

    def __init__(
        self,
        message: str,
        error_code: int | None = None,
        error_subcode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.error_subcode = error_subcode


class InstagramService:
    """Service for Instagram Graph API integration.

    Handles:
    - Authentication with Facebook Graph API
    - Getting Instagram Business Account info
    - Token validation and expiration checks
    - Publishing content (in future stories)
    """

    def __init__(
        self,
        access_token: str,
        timeout: float = INSTAGRAM_TIMEOUT,
    ) -> None:
        """Initialize InstagramService.

        Args:
            access_token: Facebook Page Access Token with Instagram permissions.
            timeout: Request timeout in seconds.
        """
        self.access_token = access_token
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._instagram_account_id: str | None = None
        self.logger = structlog.get_logger(service="InstagramService")

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"User-Agent": "TulparExpress/1.0"},
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _build_url(self, endpoint: str) -> str:
        """Build full API URL."""
        return f"{GRAPH_API_URL}/{endpoint.lstrip('/')}"

    def _handle_api_error(self, response_data: dict[str, Any]) -> None:
        """Handle API error response."""
        if "error" in response_data:
            error = response_data["error"]
            raise InstagramAPIError(
                message=error.get("message", "Unknown error"),
                error_code=error.get("code"),
                error_subcode=error.get("error_subcode"),
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPError,)),
        reraise=True,
    )
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an API request with retry logic.

        Args:
            method: HTTP method (GET, POST).
            endpoint: API endpoint.
            params: Query parameters.
            json_data: JSON body data.

        Returns:
            Response data as dict.

        Raises:
            InstagramAPIError: On API error response.
            httpx.HTTPError: On network error.
        """
        client = await self._get_client()
        url = self._build_url(endpoint)

        # Add access token to params
        if params is None:
            params = {}
        params["access_token"] = self.access_token

        self.logger.debug(
            "instagram_api_request",
            method=method,
            endpoint=endpoint,
        )

        if method.upper() == "GET":
            response = await client.get(url, params=params)
        elif method.upper() == "POST":
            response = await client.post(url, params=params, json=json_data)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
        data = response.json()

        self._handle_api_error(data)

        return data

    async def get_token_info(self) -> ServiceResult[TokenInfo]:
        """Get information about the access token.

        Returns:
            ServiceResult with TokenInfo on success.
        """
        self.logger.info("checking_token_info")

        try:
            data = await self._make_request(
                "GET",
                "debug_token",
                params={"input_token": self.access_token},
            )

            token_data = data.get("data", {})

            expires_at = None
            if "expires_at" in token_data and token_data["expires_at"]:
                expires_at = datetime.fromtimestamp(token_data["expires_at"])

            token_info = TokenInfo(
                is_valid=token_data.get("is_valid", False),
                expires_at=expires_at,
                scopes=token_data.get("scopes"),
                app_id=token_data.get("app_id"),
                user_id=token_data.get("user_id"),
            )

            if token_info.is_expiring_soon:
                self.logger.warning(
                    "token_expiring_soon",
                    days_until_expiry=token_info.days_until_expiry,
                    expires_at=token_info.expires_at.isoformat() if token_info.expires_at else None,
                )

            return ServiceResult.ok(token_info)

        except InstagramAPIError as e:
            self.logger.error(
                "token_info_error",
                error=str(e),
                error_code=e.error_code,
            )
            return ServiceResult.fail(f"Failed to get token info: {e}")

        except Exception as e:
            self.logger.error("token_info_error", error=str(e))
            return ServiceResult.fail(f"Failed to get token info: {e}")

    async def validate_token(self) -> ServiceResult[bool]:
        """Validate the access token.

        Returns:
            ServiceResult with True if token is valid.
        """
        result = await self.get_token_info()

        if not result.success:
            return ServiceResult.fail(result.error)

        token_info = result.data

        if not token_info.is_valid:
            self.logger.error("token_invalid")
            return ServiceResult.fail("Access token is invalid")

        # Check required scopes
        required_scopes = ["instagram_basic", "instagram_content_publish"]
        if token_info.scopes:
            missing_scopes = [s for s in required_scopes if s not in token_info.scopes]
            if missing_scopes:
                self.logger.warning(
                    "missing_scopes",
                    missing=missing_scopes,
                    granted=token_info.scopes,
                )

        return ServiceResult.ok(True)

    async def get_instagram_account_id(self) -> ServiceResult[str]:
        """Get the Instagram Business Account ID.

        Returns:
            ServiceResult with Instagram Account ID.
        """
        if self._instagram_account_id:
            return ServiceResult.ok(self._instagram_account_id)

        self.logger.info("getting_instagram_account_id")

        try:
            # Get pages linked to the user
            data = await self._make_request(
                "GET",
                "me/accounts",
                params={"fields": "instagram_business_account,name,access_token"},
            )

            pages = data.get("data", [])

            if not pages:
                return ServiceResult.fail("No Facebook Pages found")

            # Find first page with Instagram business account
            for page in pages:
                ig_account = page.get("instagram_business_account")
                if ig_account:
                    self._instagram_account_id = ig_account["id"]
                    self.logger.info(
                        "instagram_account_found",
                        account_id=self._instagram_account_id,
                        page_name=page.get("name"),
                    )
                    return ServiceResult.ok(self._instagram_account_id)

            return ServiceResult.fail(
                "No Instagram Business Account linked to any Facebook Page"
            )

        except InstagramAPIError as e:
            self.logger.error(
                "get_account_id_error",
                error=str(e),
                error_code=e.error_code,
            )
            return ServiceResult.fail(f"Failed to get Instagram account: {e}")

        except Exception as e:
            self.logger.error("get_account_id_error", error=str(e))
            return ServiceResult.fail(f"Failed to get Instagram account: {e}")

    async def get_account_info(self) -> ServiceResult[InstagramAccount]:
        """Get Instagram Business Account information.

        Returns:
            ServiceResult with InstagramAccount info.
        """
        # First get the account ID
        account_id_result = await self.get_instagram_account_id()
        if not account_id_result.success:
            return ServiceResult.fail(account_id_result.error)

        account_id = account_id_result.data

        self.logger.info("getting_account_info", account_id=account_id)

        try:
            data = await self._make_request(
                "GET",
                account_id,
                params={"fields": "id,username,name,followers_count,media_count"},
            )

            account = InstagramAccount(
                id=data.get("id", account_id),
                username=data.get("username"),
                name=data.get("name"),
                followers_count=data.get("followers_count"),
                media_count=data.get("media_count"),
            )

            self.logger.info(
                "account_info_retrieved",
                username=account.username,
                followers=account.followers_count,
            )

            return ServiceResult.ok(account)

        except InstagramAPIError as e:
            self.logger.error(
                "get_account_info_error",
                error=str(e),
                error_code=e.error_code,
            )
            return ServiceResult.fail(f"Failed to get account info: {e}")

        except Exception as e:
            self.logger.error("get_account_info_error", error=str(e))
            return ServiceResult.fail(f"Failed to get account info: {e}")

    async def _create_image_container(
        self,
        image_url: str,
        account_id: str,
    ) -> ServiceResult[str]:
        """Create a media container for a single image.

        Args:
            image_url: Public URL of the image.
            account_id: Instagram Business Account ID.

        Returns:
            ServiceResult with container creation ID.
        """
        self.logger.debug("creating_image_container", image_url=image_url[:50])

        try:
            data = await self._make_request(
                "POST",
                f"{account_id}/media",
                params={
                    "image_url": image_url,
                    "is_carousel_item": "true",
                },
            )

            container_id = data.get("id")
            if not container_id:
                return ServiceResult.fail("No container ID in response")

            self.logger.debug("image_container_created", container_id=container_id)
            return ServiceResult.ok(container_id)

        except InstagramAPIError as e:
            self.logger.error(
                "create_image_container_error",
                error=str(e),
                error_code=e.error_code,
            )
            return ServiceResult.fail(f"Failed to create image container: {e}")

        except Exception as e:
            self.logger.error("create_image_container_error", error=str(e))
            return ServiceResult.fail(f"Failed to create image container: {e}")

    async def _create_carousel_container(
        self,
        children_ids: list[str],
        caption: str,
        account_id: str,
    ) -> ServiceResult[str]:
        """Create a carousel container with children media items.

        Args:
            children_ids: List of media container IDs.
            caption: Caption text for the carousel.
            account_id: Instagram Business Account ID.

        Returns:
            ServiceResult with carousel container creation ID.
        """
        self.logger.info(
            "creating_carousel_container",
            children_count=len(children_ids),
        )

        try:
            data = await self._make_request(
                "POST",
                f"{account_id}/media",
                params={
                    "media_type": "CAROUSEL",
                    "children": ",".join(children_ids),
                    "caption": caption,
                },
            )

            container_id = data.get("id")
            if not container_id:
                return ServiceResult.fail("No carousel container ID in response")

            self.logger.info("carousel_container_created", container_id=container_id)
            return ServiceResult.ok(container_id)

        except InstagramAPIError as e:
            self.logger.error(
                "create_carousel_container_error",
                error=str(e),
                error_code=e.error_code,
            )
            return ServiceResult.fail(f"Failed to create carousel container: {e}")

        except Exception as e:
            self.logger.error("create_carousel_container_error", error=str(e))
            return ServiceResult.fail(f"Failed to create carousel container: {e}")

    async def _check_container_status(
        self,
        container_id: str,
    ) -> ServiceResult[str]:
        """Check the status of a media container.

        Args:
            container_id: Media container ID to check.

        Returns:
            ServiceResult with status code (FINISHED, IN_PROGRESS, ERROR).
        """
        try:
            data = await self._make_request(
                "GET",
                container_id,
                params={"fields": "status_code"},
            )

            status = data.get("status_code", "UNKNOWN")
            return ServiceResult.ok(status)

        except Exception as e:
            self.logger.error("check_container_status_error", error=str(e))
            return ServiceResult.fail(f"Failed to check container status: {e}")

    async def _wait_for_container(
        self,
        container_id: str,
    ) -> ServiceResult[bool]:
        """Wait for a media container to be ready for publishing.

        Args:
            container_id: Media container ID to wait for.

        Returns:
            ServiceResult with True if container is ready.
        """
        self.logger.debug("waiting_for_container", container_id=container_id)

        for _ in range(MAX_CONTAINER_CHECKS):
            status_result = await self._check_container_status(container_id)

            if not status_result.success:
                return ServiceResult.fail(status_result.error)

            status = status_result.data

            if status == "FINISHED":
                self.logger.debug("container_ready", container_id=container_id)
                return ServiceResult.ok(True)

            if status == "ERROR":
                return ServiceResult.fail("Container processing failed")

            # Still processing, wait and retry
            await asyncio.sleep(CONTAINER_CHECK_INTERVAL)

        return ServiceResult.fail("Container processing timeout")

    async def _publish_container(
        self,
        container_id: str,
        account_id: str,
    ) -> ServiceResult[str]:
        """Publish a media container.

        Args:
            container_id: Media container ID to publish.
            account_id: Instagram Business Account ID.

        Returns:
            ServiceResult with published post ID.
        """
        self.logger.info("publishing_container", container_id=container_id)

        try:
            data = await self._make_request(
                "POST",
                f"{account_id}/media_publish",
                params={"creation_id": container_id},
            )

            post_id = data.get("id")
            if not post_id:
                return ServiceResult.fail("No post ID in publish response")

            self.logger.info("container_published", post_id=post_id)
            return ServiceResult.ok(post_id)

        except InstagramAPIError as e:
            self.logger.error(
                "publish_container_error",
                error=str(e),
                error_code=e.error_code,
            )
            return ServiceResult.fail(f"Failed to publish container: {e}")

        except Exception as e:
            self.logger.error("publish_container_error", error=str(e))
            return ServiceResult.fail(f"Failed to publish container: {e}")

    async def publish_carousel(
        self,
        image_urls: list[str],
        caption: str,
    ) -> ServiceResult[str]:
        """Publish a carousel of images to Instagram.

        Args:
            image_urls: List of public image URLs (2-10 images).
            caption: Caption text for the carousel post.

        Returns:
            ServiceResult with Instagram post ID on success.
        """
        # Validate carousel limits
        if len(image_urls) < MIN_CAROUSEL_ITEMS:
            return ServiceResult.fail(
                f"Carousel requires at least {MIN_CAROUSEL_ITEMS} images, "
                f"got {len(image_urls)}"
            )

        if len(image_urls) > MAX_CAROUSEL_ITEMS:
            return ServiceResult.fail(
                f"Carousel allows maximum {MAX_CAROUSEL_ITEMS} images, "
                f"got {len(image_urls)}"
            )

        self.logger.info(
            "publishing_carousel",
            image_count=len(image_urls),
            caption_length=len(caption),
        )

        # Get Instagram account ID
        account_id_result = await self.get_instagram_account_id()
        if not account_id_result.success:
            return ServiceResult.fail(account_id_result.error)

        account_id = account_id_result.data

        # Step 1: Create individual media containers for each image
        children_ids: list[str] = []
        for i, image_url in enumerate(image_urls):
            self.logger.debug(
                "creating_child_container",
                index=i + 1,
                total=len(image_urls),
            )

            container_result = await self._create_image_container(
                image_url=image_url,
                account_id=account_id,
            )

            if not container_result.success:
                return ServiceResult.fail(
                    f"Failed to create container for image {i + 1}: "
                    f"{container_result.error}"
                )

            children_ids.append(container_result.data)

        # Step 2: Create carousel container
        carousel_result = await self._create_carousel_container(
            children_ids=children_ids,
            caption=caption,
            account_id=account_id,
        )

        if not carousel_result.success:
            return ServiceResult.fail(carousel_result.error)

        carousel_id = carousel_result.data

        # Step 3: Wait for carousel to be ready
        wait_result = await self._wait_for_container(carousel_id)
        if not wait_result.success:
            return ServiceResult.fail(wait_result.error)

        # Step 4: Publish the carousel
        publish_result = await self._publish_container(
            container_id=carousel_id,
            account_id=account_id,
        )

        if not publish_result.success:
            return ServiceResult.fail(publish_result.error)

        post_id = publish_result.data

        self.logger.info(
            "carousel_published_successfully",
            post_id=post_id,
            image_count=len(image_urls),
        )

        return ServiceResult.ok(post_id)
