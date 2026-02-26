"""SIEMService — async SIEM event forwarding for FileGuard.

Forwards :class:`~fileguard.models.scan_event.ScanEvent` records to external
SIEM platforms (Splunk HEC and RiverSafe WatchTower) completely asynchronously
so that SIEM delivery never blocks the scan critical path.

Delivery is **fire-and-forget**: callers invoke :meth:`SIEMService.forward_event`
and return immediately.  The actual HTTP delivery happens in the background via
:func:`asyncio.create_task`.

Retry policy
------------
On a transient failure (network error or HTTP 5xx) the service retries up to
``max_retries`` times using exponential back-off with jitter::

    delay = base_delay * (2 ** attempt) + random_jitter(0, 0.5)

Each failed delivery attempt (including retries) increments the Prometheus
counter ``siem_delivery_errors_total`` so that operators can alert on
sustained failures.

Supported destinations
----------------------
``"splunk"``
    Sends a Splunk HTTP Event Collector (HEC) payload wrapped in
    ``{"event": {...}, "sourcetype": "fileguard:scan"}``.  The ``token``
    field is sent as ``Authorization: Splunk <token>``.

``"watchtower"``
    Sends the event payload directly as a JSON body to the RiverSafe
    WatchTower REST API.  The ``token`` field is sent as
    ``Authorization: Bearer <token>``.

Usage::

    from fileguard.services.siem import SIEMService, SIEMConfig

    siem = SIEMService()

    config = SIEMConfig(
        type="splunk",
        endpoint="https://splunk.example.com:8088/services/collector/event",
        token="your-hec-token",
    )

    # Fire-and-forget — returns immediately
    siem.forward_event(scan_event, config)
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from prometheus_client import Counter

from fileguard.models.scan_event import ScanEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

#: Incremented for every failed SIEM delivery attempt (including retries).
#: Labels: ``destination`` ("splunk" | "watchtower") and ``error_type``
#: ("http_error" | "network_error" | "unknown").
siem_delivery_errors_total = Counter(
    "siem_delivery_errors_total",
    "Total number of failed SIEM event delivery attempts",
    ["destination", "error_type"],
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SIEM_TYPE_SPLUNK = "splunk"
_SIEM_TYPE_WATCHTOWER = "watchtower"

#: Maximum seconds to wait for a single HTTP request to a SIEM endpoint.
_HTTP_TIMEOUT = 10.0

#: HTTP status codes that are considered transient and should trigger a retry.
_RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})

# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------


@dataclass
class SIEMConfig:
    """Runtime configuration for a single SIEM destination.

    Args:
        type: Destination type — ``"splunk"`` or ``"watchtower"``.
        endpoint: Full URL of the SIEM ingest endpoint (e.g. Splunk HEC URL
            or WatchTower events URL).
        token: Optional authentication token.  For Splunk this is the HEC
            token; for WatchTower this is the Bearer token.
        max_retries: Number of additional delivery attempts after the first
            failure.  Defaults to 3.
        retry_base_delay: Base delay in seconds for exponential back-off.
            The actual delay is ``base * 2**attempt + jitter``.  Defaults
            to 1.0 second.
    """

    type: str
    endpoint: str
    token: str | None = None
    max_retries: int = 3
    retry_base_delay: float = field(default=1.0)


# ---------------------------------------------------------------------------
# SIEMService
# ---------------------------------------------------------------------------


class SIEMService:
    """Async SIEM forwarding service.

    Provides fire-and-forget delivery of :class:`~fileguard.models.scan_event.ScanEvent`
    records to Splunk HEC and RiverSafe WatchTower, fully decoupled from the
    scan critical path.

    Args:
        http_client: Optional shared :class:`httpx.AsyncClient`.  When
            provided the client is reused across requests (recommended in
            production for connection pooling).  When ``None`` a new client
            is created for each delivery attempt.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http_client = http_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def forward_event(self, event: ScanEvent, config: SIEMConfig) -> asyncio.Task[None]:
        """Schedule asynchronous SIEM delivery for *event*.

        This method is **non-blocking**: it creates an :mod:`asyncio` task and
        returns immediately.  Callers on the scan critical path must use this
        method (not ``await``\-ing the result) to preserve response latency.

        Args:
            event: The :class:`~fileguard.models.scan_event.ScanEvent` to
                forward.  The object is read at scheduling time, not at
                delivery time, so there is no race condition with later
                mutations.
            config: :class:`SIEMConfig` describing the destination and
                delivery parameters.

        Returns:
            The :class:`asyncio.Task` wrapping the delivery coroutine.
            In production code callers typically discard this value; it is
            returned to facilitate testing and optional cancellation.
        """
        coro = self._deliver_with_retry(event, config)
        return asyncio.create_task(coro)

    # ------------------------------------------------------------------
    # Internal delivery helpers
    # ------------------------------------------------------------------

    async def _deliver_with_retry(
        self,
        event: ScanEvent,
        config: SIEMConfig,
    ) -> None:
        """Attempt delivery with exponential back-off retry.

        Each failed attempt increments ``siem_delivery_errors_total``.  After
        all attempts are exhausted the error is logged at WARNING level and
        suppressed — SIEM failures must never propagate to the caller.
        """
        destination = config.type.lower()
        payload = _build_payload(event, destination)
        headers = _build_headers(destination, config.token)

        for attempt in range(config.max_retries + 1):
            try:
                await self._post(config.endpoint, payload, headers)
                logger.info(
                    "SIEM event delivered: scan_id=%s destination=%s attempt=%d",
                    event.id,
                    destination,
                    attempt,
                )
                return  # Success — no further retries needed
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code not in _RETRYABLE_HTTP_STATUSES:
                    # Non-retryable HTTP error (e.g. 400, 401, 403) — give up immediately.
                    siem_delivery_errors_total.labels(
                        destination=destination, error_type="http_error"
                    ).inc()
                    logger.warning(
                        "SIEM delivery failed (HTTP %d, non-retryable) "
                        "for scan_id=%s destination=%s: %s",
                        status_code,
                        event.id,
                        destination,
                        exc,
                    )
                    return

                siem_delivery_errors_total.labels(
                    destination=destination, error_type="http_error"
                ).inc()
                logger.warning(
                    "SIEM delivery failed (HTTP %d) for scan_id=%s destination=%s "
                    "attempt=%d/%d: %s",
                    status_code,
                    event.id,
                    destination,
                    attempt + 1,
                    config.max_retries + 1,
                    exc,
                )
            except httpx.RequestError as exc:
                siem_delivery_errors_total.labels(
                    destination=destination, error_type="network_error"
                ).inc()
                logger.warning(
                    "SIEM network error for scan_id=%s destination=%s attempt=%d/%d: %s",
                    event.id,
                    destination,
                    attempt + 1,
                    config.max_retries + 1,
                    exc,
                )
            except Exception as exc:  # noqa: BLE001
                siem_delivery_errors_total.labels(
                    destination=destination, error_type="unknown"
                ).inc()
                logger.warning(
                    "Unexpected SIEM error for scan_id=%s destination=%s attempt=%d/%d: %s",
                    event.id,
                    destination,
                    attempt + 1,
                    config.max_retries + 1,
                    exc,
                )

            if attempt < config.max_retries:
                delay = _backoff_delay(config.retry_base_delay, attempt)
                logger.debug(
                    "Retrying SIEM delivery for scan_id=%s in %.2fs (attempt %d/%d)",
                    event.id,
                    delay,
                    attempt + 2,
                    config.max_retries + 1,
                )
                await asyncio.sleep(delay)

        logger.warning(
            "SIEM delivery exhausted all %d attempts for scan_id=%s destination=%s",
            config.max_retries + 1,
            event.id,
            destination,
        )

    async def _post(
        self,
        endpoint: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Execute a single HTTP POST to the SIEM endpoint.

        Raises :class:`httpx.HTTPStatusError` on a non-2xx response and
        :class:`httpx.RequestError` on a network-level failure.
        """
        if self._http_client is not None:
            response = await self._http_client.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=_HTTP_TIMEOUT,
            )
            response.raise_for_status()
        else:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()


# ---------------------------------------------------------------------------
# Module-level payload / header helpers
# ---------------------------------------------------------------------------


def _build_payload(event: ScanEvent, destination: str) -> dict[str, Any]:
    """Construct the SIEM-specific request payload for *event*.

    For Splunk the payload is wrapped in the HEC envelope::

        {"event": {...}, "sourcetype": "fileguard:scan"}

    For WatchTower (and any unknown type) the event dict is sent directly.
    """
    created_at = event.created_at
    created_at_str = (
        created_at.isoformat() if isinstance(created_at, datetime) else str(created_at)
    )

    base: dict[str, Any] = {
        "scan_id": str(event.id),
        "tenant_id": str(event.tenant_id),
        "file_hash": event.file_hash,
        "file_name": event.file_name,
        "file_size_bytes": event.file_size_bytes,
        "mime_type": event.mime_type,
        "status": event.status,
        "action_taken": event.action_taken,
        "findings": event.findings,
        "scan_duration_ms": event.scan_duration_ms,
        "created_at": created_at_str,
        "hmac_signature": event.hmac_signature,
    }

    if destination == _SIEM_TYPE_SPLUNK:
        return {"event": base, "sourcetype": "fileguard:scan"}

    return base


def _build_headers(destination: str, token: str | None) -> dict[str, str]:
    """Return HTTP headers appropriate for *destination*.

    Splunk uses ``Authorization: Splunk <token>``; all others use
    ``Authorization: Bearer <token>``.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        if destination == _SIEM_TYPE_SPLUNK:
            headers["Authorization"] = f"Splunk {token}"
        else:
            headers["Authorization"] = f"Bearer {token}"
    return headers


def _backoff_delay(base: float, attempt: int) -> float:
    """Return the sleep duration for *attempt* using exponential back-off with jitter.

    Formula: ``base * 2**attempt + uniform(0, 0.5)``
    """
    return base * (2**attempt) + random.uniform(0, 0.5)  # noqa: S311
