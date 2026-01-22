"""Health check service for system monitoring."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.autopost.services.scheduler_service import SchedulerService

logger = structlog.get_logger(__name__)


class HealthStatus(str, Enum):
    """Health check status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """Health status for a single component."""

    name: str
    status: HealthStatus
    latency_ms: float
    message: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_healthy(self) -> bool:
        """Check if component is healthy."""
        return self.status == HealthStatus.HEALTHY


@dataclass
class HealthCheckResult:
    """Result of a complete health check."""

    status: HealthStatus
    timestamp: datetime
    components: list[ComponentHealth] = field(default_factory=list)
    version: Optional[str] = None
    uptime_seconds: Optional[float] = None

    @property
    def is_healthy(self) -> bool:
        """Check if overall system is healthy."""
        return self.status == HealthStatus.HEALTHY

    @property
    def healthy_components(self) -> list[ComponentHealth]:
        """Get list of healthy components."""
        return [c for c in self.components if c.is_healthy]

    @property
    def unhealthy_components(self) -> list[ComponentHealth]:
        """Get list of unhealthy components."""
        return [c for c in self.components if not c.is_healthy]


# Health check timeout in seconds
HEALTH_CHECK_TIMEOUT = 5.0

# Components names
COMPONENT_DATABASE = "database"
COMPONENT_SCHEDULER = "scheduler"
COMPONENT_TELEGRAM = "telegram"
COMPONENT_INSTAGRAM = "instagram"
COMPONENT_PINDUODUO = "pinduoduo"
COMPONENT_OPENAI = "openai"
COMPONENT_CURRENCY = "currency"


class HealthService:
    """Service for checking system health.

    Performs health checks on:
    - Database connectivity
    - Scheduler status
    - External API availability (optional)

    Usage:
        health_service = HealthService(session, scheduler)
        result = await health_service.check_health()
        print(f"Status: {result.status.value}")
    """

    def __init__(
        self,
        session: Optional[AsyncSession] = None,
        scheduler: Optional[SchedulerService] = None,
        start_time: Optional[datetime] = None,
        version: Optional[str] = None,
    ) -> None:
        """Initialize the health service.

        Args:
            session: Database session for DB health check.
            scheduler: Scheduler service for scheduler health check.
            start_time: Application start time for uptime calculation.
            version: Application version string.
        """
        self._session = session
        self._scheduler = scheduler
        self._start_time = start_time or datetime.now()
        self._version = version

    @property
    def uptime_seconds(self) -> float:
        """Get application uptime in seconds."""
        return (datetime.now() - self._start_time).total_seconds()

    async def check_health(
        self,
        include_external: bool = False,
        external_checkers: Optional[
            dict[str, Callable[[], Coroutine[Any, Any, bool]]]
        ] = None,
    ) -> HealthCheckResult:
        """Perform a complete health check.

        Args:
            include_external: Whether to check external APIs.
            external_checkers: Optional dict of external service checkers.
                Keys are service names, values are async functions
                returning True if healthy.

        Returns:
            HealthCheckResult with overall and component status.
        """
        components: list[ComponentHealth] = []

        # Check database
        if self._session is not None:
            db_health = await self._check_database()
            components.append(db_health)

        # Check scheduler
        if self._scheduler is not None:
            scheduler_health = self._check_scheduler()
            components.append(scheduler_health)

        # Check external services if requested
        if include_external and external_checkers:
            for name, checker in external_checkers.items():
                try:
                    health = await self._check_external(name, checker)
                    components.append(health)
                except Exception as e:
                    components.append(
                        ComponentHealth(
                            name=name,
                            status=HealthStatus.UNHEALTHY,
                            latency_ms=0,
                            message=str(e),
                        )
                    )

        # Determine overall status
        overall_status = self._calculate_overall_status(components)

        result = HealthCheckResult(
            status=overall_status,
            timestamp=datetime.now(),
            components=components,
            version=self._version,
            uptime_seconds=self.uptime_seconds,
        )

        logger.info(
            "health_check_completed",
            status=overall_status.value,
            healthy=len(result.healthy_components),
            unhealthy=len(result.unhealthy_components),
        )

        return result

    async def _check_database(self) -> ComponentHealth:
        """Check database connectivity.

        Returns:
            ComponentHealth for database.
        """
        start = time.monotonic()

        try:
            if self._session is None:
                return ComponentHealth(
                    name=COMPONENT_DATABASE,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=0,
                    message="No database session",
                )

            # Execute a simple query
            await self._session.execute(text("SELECT 1"))
            latency = (time.monotonic() - start) * 1000

            logger.debug(
                "database_health_check",
                status="healthy",
                latency_ms=latency,
            )

            return ComponentHealth(
                name=COMPONENT_DATABASE,
                status=HealthStatus.HEALTHY,
                latency_ms=latency,
                message="Connected",
            )

        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            logger.warning(
                "database_health_check_failed",
                error=str(e),
                latency_ms=latency,
            )

            return ComponentHealth(
                name=COMPONENT_DATABASE,
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=str(e),
            )

    def _check_scheduler(self) -> ComponentHealth:
        """Check scheduler status.

        Returns:
            ComponentHealth for scheduler.
        """
        start = time.monotonic()

        try:
            if self._scheduler is None:
                return ComponentHealth(
                    name=COMPONENT_SCHEDULER,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=0,
                    message="No scheduler configured",
                )

            is_running = self._scheduler.is_running
            next_run = self._scheduler.get_next_run_time()
            latency = (time.monotonic() - start) * 1000

            if is_running:
                status = HealthStatus.HEALTHY
                message = f"Running, next run: {next_run or 'not scheduled'}"
            else:
                status = HealthStatus.DEGRADED
                message = "Scheduler not running"

            details = {
                "is_running": is_running,
                "next_run": next_run,
                "posting_time": self._scheduler.posting_time,
                "timezone": self._scheduler.timezone,
            }

            logger.debug(
                "scheduler_health_check",
                status=status.value,
                is_running=is_running,
            )

            return ComponentHealth(
                name=COMPONENT_SCHEDULER,
                status=status,
                latency_ms=latency,
                message=message,
                details=details,
            )

        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            logger.warning(
                "scheduler_health_check_failed",
                error=str(e),
            )

            return ComponentHealth(
                name=COMPONENT_SCHEDULER,
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=str(e),
            )

    async def _check_external(
        self,
        name: str,
        checker: Callable[[], Coroutine[Any, Any, bool]],
    ) -> ComponentHealth:
        """Check an external service.

        Args:
            name: Service name.
            checker: Async function returning True if healthy.

        Returns:
            ComponentHealth for the service.
        """
        start = time.monotonic()

        try:
            is_healthy = await checker()
            latency = (time.monotonic() - start) * 1000

            if is_healthy:
                status = HealthStatus.HEALTHY
                message = "Available"
            else:
                status = HealthStatus.UNHEALTHY
                message = "Unavailable"

            logger.debug(
                "external_health_check",
                service=name,
                status=status.value,
                latency_ms=latency,
            )

            return ComponentHealth(
                name=name,
                status=status,
                latency_ms=latency,
                message=message,
            )

        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            logger.warning(
                "external_health_check_failed",
                service=name,
                error=str(e),
            )

            return ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=str(e),
            )

    def _calculate_overall_status(
        self, components: list[ComponentHealth]
    ) -> HealthStatus:
        """Calculate overall health status from components.

        Rules:
        - HEALTHY: All components healthy
        - DEGRADED: Some components degraded, none unhealthy
        - UNHEALTHY: Any critical component unhealthy

        Args:
            components: List of component health results.

        Returns:
            Overall HealthStatus.
        """
        if not components:
            return HealthStatus.HEALTHY

        has_unhealthy = any(
            c.status == HealthStatus.UNHEALTHY for c in components
        )
        has_degraded = any(
            c.status == HealthStatus.DEGRADED for c in components
        )

        if has_unhealthy:
            return HealthStatus.UNHEALTHY
        elif has_degraded:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.HEALTHY

    def format_status_message(self, result: HealthCheckResult) -> str:
        """Format health check result for display.

        Args:
            result: Health check result.

        Returns:
            Formatted status message.
        """
        status_icons = {
            HealthStatus.HEALTHY: "✅",
            HealthStatus.DEGRADED: "⚠️",
            HealthStatus.UNHEALTHY: "❌",
        }

        lines = [
            f"{status_icons[result.status]} System Status: {result.status.value.upper()}",
            "",
        ]

        if result.version:
            lines.append(f"Version: {result.version}")

        if result.uptime_seconds:
            uptime_hours = result.uptime_seconds / 3600
            lines.append(f"Uptime: {uptime_hours:.1f} hours")

        lines.append("")
        lines.append("Components:")

        for component in result.components:
            icon = status_icons[component.status]
            lines.append(
                f"  {icon} {component.name}: {component.message or component.status.value}"
            )
            if component.latency_ms > 0:
                lines.append(f"      Latency: {component.latency_ms:.1f}ms")

        return "\n".join(lines)
