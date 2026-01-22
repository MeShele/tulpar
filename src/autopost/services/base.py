"""Base service classes for external API integrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.autopost.exceptions import ServiceError

T = TypeVar("T")

# Default timeout for HTTP requests (30 seconds as per NFR20)
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


@dataclass
class ServiceResult(Generic[T]):
    """Result wrapper for service operations.

    Provides a consistent interface for service responses,
    distinguishing between success and failure cases.

    Attributes:
        success: Whether the operation succeeded.
        data: The result data if successful, None otherwise.
        error: Error message if failed, None otherwise.
    """

    success: bool
    data: T | None = None
    error: str | None = None

    @classmethod
    def ok(cls, data: T) -> "ServiceResult[T]":
        """Create a successful result.

        Args:
            data: The successful result data.

        Returns:
            ServiceResult with success=True and the data.
        """
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error: str) -> "ServiceResult[T]":
        """Create a failed result.

        Args:
            error: Error message describing the failure.

        Returns:
            ServiceResult with success=False and the error message.
        """
        return cls(success=False, error=error)


class BaseService:
    """Base class for external service integrations.

    Provides common functionality for HTTP-based API clients:
    - Shared httpx.AsyncClient with connection pooling
    - Retry logic with exponential backoff
    - Structured logging
    - Timeout configuration

    All service classes should inherit from this base.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        """Initialize the base service.

        Args:
            client: Optional httpx.AsyncClient. If not provided,
                    a new client will be created with default settings.
        """
        self.client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        self.logger = structlog.get_logger(service=self.__class__.__name__)
        self._owns_client = client is None

    async def close(self) -> None:
        """Close the HTTP client if owned by this service.

        Should be called when the service is no longer needed.
        """
        if self._owns_client and self.client:
            await self.client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
        reraise=True,
    )
    async def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an HTTP request with retry logic.

        Automatically retries on 5xx errors and connection issues
        with exponential backoff (2-30 seconds, 3 attempts).

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            **kwargs: Additional arguments passed to httpx.request()

        Returns:
            httpx.Response object

        Raises:
            httpx.HTTPStatusError: If request fails after all retries
            httpx.TimeoutException: If request times out
            ServiceError: For other request failures
        """
        self.logger.debug(
            "http_request",
            method=method,
            url=url,
        )

        try:
            response = await self.client.request(method, url, **kwargs)
            response.raise_for_status()

            self.logger.debug(
                "http_response",
                method=method,
                url=url,
                status_code=response.status_code,
            )

            return response

        except httpx.TimeoutException as e:
            self.logger.error(
                "request_timeout",
                method=method,
                url=url,
                error=str(e),
            )
            raise ServiceError(
                message=f"Request timeout: {url}",
                service_name=self.__class__.__name__,
                original_error=e,
            ) from e

        except httpx.HTTPStatusError as e:
            self.logger.warning(
                "http_error",
                method=method,
                url=url,
                status_code=e.response.status_code,
                error=str(e),
            )
            # Let tenacity handle retry for 5xx errors
            if e.response.status_code >= 500:
                raise
            # For 4xx errors, wrap in ServiceError
            raise ServiceError(
                message=f"HTTP {e.response.status_code}: {url}",
                service_name=self.__class__.__name__,
                original_error=e,
            ) from e

    async def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make a GET request with retry logic.

        Args:
            url: Request URL
            **kwargs: Additional arguments passed to httpx.request()

        Returns:
            httpx.Response object
        """
        return await self._request("GET", url, **kwargs)

    async def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make a POST request with retry logic.

        Args:
            url: Request URL
            **kwargs: Additional arguments passed to httpx.request()

        Returns:
            httpx.Response object
        """
        return await self._request("POST", url, **kwargs)
