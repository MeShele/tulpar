"""Exception hierarchy for Tulpar Express application."""

from __future__ import annotations


class TulparError(Exception):
    """Base exception for all Tulpar Express errors.

    All application-specific exceptions should inherit from this class.
    """

    def __init__(self, message: str = "An error occurred in Tulpar Express") -> None:
        self.message = message
        super().__init__(self.message)


class ServiceError(TulparError):
    """Exception raised when an external service fails.

    Used for errors from external APIs like Pinduoduo, OpenAI, Telegram, etc.
    """

    def __init__(
        self,
        message: str = "External service error",
        service_name: str = "unknown",
        original_error: Exception | None = None,
    ) -> None:
        self.service_name = service_name
        self.original_error = original_error
        super().__init__(f"[{service_name}] {message}")


class PipelineError(TulparError):
    """Exception raised when the processing pipeline fails.

    Used for errors during the daily content generation and publishing flow.
    """

    def __init__(
        self,
        message: str = "Pipeline processing error",
        stage: str = "unknown",
    ) -> None:
        self.stage = stage
        super().__init__(f"Pipeline failed at stage '{stage}': {message}")
