"""Scheduler service for daily automated pipeline execution."""

from __future__ import annotations

import re
from typing import Awaitable, Callable, Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = structlog.get_logger(__name__)

# Job ID for the daily pipeline
DAILY_PIPELINE_JOB_ID = "daily_pipeline"

# Default posting time
DEFAULT_POSTING_TIME = "19:00"

# Default timezone
DEFAULT_TIMEZONE = "Asia/Bishkek"

# Time format regex (HH:MM)
TIME_FORMAT_REGEX = re.compile(r"^([01]?[0-9]|2[0-3]):([0-5][0-9])$")


class SchedulerService:
    """Service for scheduling daily pipeline execution.

    Uses APScheduler with CronTrigger for daily automated runs.
    Configured for Bishkek timezone (UTC+6) by default.
    """

    def __init__(
        self,
        posting_time: str = DEFAULT_POSTING_TIME,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> None:
        """Initialize the scheduler service.

        Args:
            posting_time: Time for daily execution in HH:MM format.
            timezone: Timezone for scheduling (e.g., "Asia/Bishkek").

        Raises:
            ValueError: If posting_time format is invalid.
        """
        self._posting_time = posting_time
        self._timezone = timezone
        self._hour, self._minute = self._parse_time(posting_time)

        self._scheduler: Optional[AsyncIOScheduler] = None
        self._pipeline_callback: Optional[Callable[[], Awaitable[None]]] = None
        self._is_running = False

        logger.info(
            "scheduler_service_initialized",
            posting_time=posting_time,
            timezone=timezone,
            hour=self._hour,
            minute=self._minute,
        )

    @staticmethod
    def _parse_time(time_str: str) -> tuple[int, int]:
        """Parse time string in HH:MM format.

        Args:
            time_str: Time string in HH:MM format.

        Returns:
            Tuple of (hour, minute).

        Raises:
            ValueError: If time format is invalid.
        """
        match = TIME_FORMAT_REGEX.match(time_str)
        if not match:
            raise ValueError(
                f"Invalid time format: '{time_str}'. Expected HH:MM (e.g., '19:00')"
            )

        hour = int(match.group(1))
        minute = int(match.group(2))

        return hour, minute

    @property
    def posting_time(self) -> str:
        """Get the configured posting time."""
        return self._posting_time

    @property
    def timezone(self) -> str:
        """Get the configured timezone."""
        return self._timezone

    @property
    def hour(self) -> int:
        """Get the hour component of posting time."""
        return self._hour

    @property
    def minute(self) -> int:
        """Get the minute component of posting time."""
        return self._minute

    @property
    def is_running(self) -> bool:
        """Check if the scheduler is running."""
        return self._is_running

    def set_pipeline_callback(
        self, callback: Callable[[], Awaitable[None]]
    ) -> None:
        """Set the callback function for the daily pipeline.

        Args:
            callback: Async function to call for daily pipeline execution.
        """
        self._pipeline_callback = callback
        logger.info("pipeline_callback_set")

    async def _run_pipeline(self) -> None:
        """Execute the pipeline callback with logging."""
        logger.info(
            "daily_pipeline_starting",
            posting_time=self._posting_time,
            timezone=self._timezone,
        )

        if self._pipeline_callback is None:
            logger.warning("pipeline_callback_not_set")
            return

        try:
            await self._pipeline_callback()
            logger.info("daily_pipeline_completed")
        except Exception:
            logger.exception("daily_pipeline_failed")
            raise

    def start(self) -> None:
        """Start the scheduler.

        Creates the APScheduler instance and adds the daily job.
        Uses coalesce=True to prevent duplicate runs after downtime.
        Uses max_instances=1 to prevent concurrent executions.
        """
        if self._is_running:
            logger.warning("scheduler_already_running")
            return

        self._scheduler = AsyncIOScheduler(timezone=self._timezone)

        # Create CronTrigger for daily execution
        trigger = CronTrigger(
            hour=self._hour,
            minute=self._minute,
            timezone=self._timezone,
        )

        # Add the daily pipeline job
        self._scheduler.add_job(
            self._run_pipeline,
            trigger=trigger,
            id=DAILY_PIPELINE_JOB_ID,
            name="Daily Pipeline",
            coalesce=True,  # Prevent duplicate runs after downtime
            max_instances=1,  # Prevent concurrent executions
            replace_existing=True,
        )

        self._scheduler.start()
        self._is_running = True

        logger.info(
            "scheduler_started",
            job_id=DAILY_PIPELINE_JOB_ID,
            hour=self._hour,
            minute=self._minute,
            timezone=self._timezone,
        )

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the scheduler.

        Args:
            wait: Whether to wait for running jobs to complete.
        """
        if not self._is_running or self._scheduler is None:
            logger.warning("scheduler_not_running")
            return

        self._scheduler.shutdown(wait=wait)
        self._is_running = False
        self._scheduler = None

        logger.info("scheduler_stopped", wait=wait)

    def get_next_run_time(self) -> Optional[str]:
        """Get the next scheduled run time.

        Returns:
            ISO format string of next run time, or None if not scheduled.
        """
        if self._scheduler is None:
            return None

        job = self._scheduler.get_job(DAILY_PIPELINE_JOB_ID)
        if job is None or job.next_run_time is None:
            return None

        return job.next_run_time.isoformat()
