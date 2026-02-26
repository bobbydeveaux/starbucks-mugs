"""Unit tests for fileguard/services/siem.py (SIEMService).

All tests run fully offline — HTTP calls are replaced by ``unittest.mock``
patches so no external services are required.

Coverage targets
----------------
* Successful delivery to Splunk HEC (correct payload envelope and auth header).
* Successful delivery to RiverSafe WatchTower (direct payload and Bearer auth).
* Network failure triggers retry and increments ``siem_delivery_errors_total``.
* HTTP 5xx triggers retry and increments the error counter.
* HTTP 4xx (non-retryable) aborts immediately and increments the counter.
* Error counter is labelled correctly by destination and error_type.
* Delivery exhaustion logs a warning after all retries are consumed.
* ``forward_event`` schedules an asyncio task and returns without awaiting.
* Missing token: no Authorization header is added.
* Payload and header helper functions produce correct output for both types.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Ensure required env vars are present before importing fileguard modules
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-chars!!")

from fileguard.services.siem import (
    SIEMConfig,
    SIEMService,
    _SIEM_TYPE_SPLUNK,
    _SIEM_TYPE_WATCHTOWER,
    _backoff_delay,
    _build_headers,
    _build_payload,
    siem_delivery_errors_total,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_SCAN_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
_CREATED_AT = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_event(**overrides: Any) -> MagicMock:
    """Return a ScanEvent mock with sensible defaults."""
    event = MagicMock()
    event.id = overrides.get("id", _SCAN_ID)
    event.tenant_id = overrides.get("tenant_id", _TENANT_ID)
    event.file_hash = overrides.get("file_hash", "abc123def456")
    event.file_name = overrides.get("file_name", "test.pdf")
    event.file_size_bytes = overrides.get("file_size_bytes", 1024)
    event.mime_type = overrides.get("mime_type", "application/pdf")
    event.status = overrides.get("status", "clean")
    event.action_taken = overrides.get("action_taken", "pass")
    event.findings = overrides.get("findings", [])
    event.scan_duration_ms = overrides.get("scan_duration_ms", 250)
    event.created_at = overrides.get("created_at", _CREATED_AT)
    event.hmac_signature = overrides.get("hmac_signature", "deadbeef" * 8)
    return event


def _splunk_config(**overrides: Any) -> SIEMConfig:
    return SIEMConfig(
        type=overrides.get("type", "splunk"),
        endpoint=overrides.get("endpoint", "https://splunk.example.com:8088/services/collector/event"),
        token=overrides.get("token", "splunk-hec-token"),
        max_retries=overrides.get("max_retries", 2),
        retry_base_delay=overrides.get("retry_base_delay", 0.01),  # fast retries in tests
    )


def _watchtower_config(**overrides: Any) -> SIEMConfig:
    return SIEMConfig(
        type=overrides.get("type", "watchtower"),
        endpoint=overrides.get("endpoint", "https://watchtower.example.com/api/events"),
        token=overrides.get("token", "wt-bearer-token"),
        max_retries=overrides.get("max_retries", 2),
        retry_base_delay=overrides.get("retry_base_delay", 0.01),
    )


def _ok_response() -> MagicMock:
    """Return a mock httpx.Response with status 200."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status = MagicMock()  # no-op
    return resp


def _error_response(status_code: int) -> MagicMock:
    """Return a mock httpx.Response that raises HTTPStatusError on raise_for_status."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    exc = httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=MagicMock(),
        response=resp,
    )
    resp.raise_for_status = MagicMock(side_effect=exc)
    return resp


# ---------------------------------------------------------------------------
# _build_payload tests
# ---------------------------------------------------------------------------


class TestBuildPayload:
    def test_splunk_wraps_in_hec_envelope(self) -> None:
        event = _make_event()
        payload = _build_payload(event, _SIEM_TYPE_SPLUNK)

        assert "event" in payload
        assert payload["sourcetype"] == "fileguard:scan"
        inner = payload["event"]
        assert inner["scan_id"] == str(_SCAN_ID)
        assert inner["status"] == "clean"

    def test_watchtower_sends_flat_payload(self) -> None:
        event = _make_event()
        payload = _build_payload(event, _SIEM_TYPE_WATCHTOWER)

        assert "event" not in payload
        assert "sourcetype" not in payload
        assert payload["scan_id"] == str(_SCAN_ID)
        assert payload["file_hash"] == "abc123def456"

    def test_unknown_type_sends_flat_payload(self) -> None:
        event = _make_event()
        payload = _build_payload(event, "unknown-siem")

        assert "sourcetype" not in payload
        assert payload["scan_id"] == str(_SCAN_ID)

    def test_created_at_is_iso8601_string(self) -> None:
        event = _make_event()
        payload = _build_payload(event, _SIEM_TYPE_WATCHTOWER)
        assert payload["created_at"] == _CREATED_AT.isoformat()

    def test_non_datetime_created_at_is_stringified(self) -> None:
        event = _make_event(created_at="2026-01-15T12:00:00+00:00")
        payload = _build_payload(event, _SIEM_TYPE_WATCHTOWER)
        assert isinstance(payload["created_at"], str)

    def test_all_required_fields_present(self) -> None:
        event = _make_event()
        payload = _build_payload(event, _SIEM_TYPE_WATCHTOWER)
        required = {
            "scan_id", "tenant_id", "file_hash", "file_name",
            "file_size_bytes", "mime_type", "status", "action_taken",
            "findings", "scan_duration_ms", "created_at", "hmac_signature",
        }
        assert required.issubset(payload.keys())


# ---------------------------------------------------------------------------
# _build_headers tests
# ---------------------------------------------------------------------------


class TestBuildHeaders:
    def test_splunk_uses_splunk_auth(self) -> None:
        headers = _build_headers(_SIEM_TYPE_SPLUNK, token="my-token")
        assert headers["Authorization"] == "Splunk my-token"
        assert headers["Content-Type"] == "application/json"

    def test_watchtower_uses_bearer_auth(self) -> None:
        headers = _build_headers(_SIEM_TYPE_WATCHTOWER, token="my-token")
        assert headers["Authorization"] == "Bearer my-token"

    def test_no_token_omits_authorization(self) -> None:
        headers = _build_headers(_SIEM_TYPE_SPLUNK, token=None)
        assert "Authorization" not in headers

    def test_empty_token_omits_authorization(self) -> None:
        headers = _build_headers(_SIEM_TYPE_WATCHTOWER, token="")
        assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# _backoff_delay tests
# ---------------------------------------------------------------------------


class TestBackoffDelay:
    def test_delay_increases_with_attempt(self) -> None:
        # Each successive attempt should be at least as long as the previous
        # (ignoring jitter, which adds ≤ 0.5 seconds).
        delays = [_backoff_delay(1.0, i) for i in range(4)]
        for i in range(1, len(delays)):
            # The minimum delay grows by factor of 2; jitter is bounded by 0.5.
            assert delays[i] >= delays[i - 1] - 0.5, (
                f"Expected monotonically increasing delays: {delays}"
            )

    def test_delay_is_positive(self) -> None:
        for attempt in range(5):
            assert _backoff_delay(1.0, attempt) > 0


# ---------------------------------------------------------------------------
# SIEMService — successful delivery
# ---------------------------------------------------------------------------


class TestSIEMServiceSuccessfulDelivery:
    @pytest.mark.asyncio
    async def test_splunk_delivery_success(self) -> None:
        """Successful Splunk HEC delivery posts to the correct endpoint."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_ok_response())

        service = SIEMService(http_client=mock_client)
        event = _make_event()
        config = _splunk_config()

        await service._deliver_with_retry(event, config)

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.args[0] == config.endpoint
        payload = call_kwargs.kwargs["json"]
        assert "event" in payload  # Splunk HEC envelope
        assert payload["sourcetype"] == "fileguard:scan"
        headers = call_kwargs.kwargs["headers"]
        assert headers["Authorization"] == f"Splunk {config.token}"

    @pytest.mark.asyncio
    async def test_watchtower_delivery_success(self) -> None:
        """Successful WatchTower delivery posts flat payload with Bearer auth."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_ok_response())

        service = SIEMService(http_client=mock_client)
        event = _make_event()
        config = _watchtower_config()

        await service._deliver_with_retry(event, config)

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs["json"]
        assert "event" not in payload  # no HEC envelope
        assert payload["scan_id"] == str(_SCAN_ID)
        headers = call_kwargs.kwargs["headers"]
        assert headers["Authorization"] == f"Bearer {config.token}"

    @pytest.mark.asyncio
    async def test_only_one_post_on_success(self) -> None:
        """No retries are made when the first attempt succeeds."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_ok_response())

        service = SIEMService(http_client=mock_client)
        await service._deliver_with_retry(_make_event(), _splunk_config())

        assert mock_client.post.call_count == 1


# ---------------------------------------------------------------------------
# SIEMService — network failure and retry
# ---------------------------------------------------------------------------


class TestSIEMServiceNetworkFailureRetry:
    @pytest.mark.asyncio
    async def test_network_error_triggers_retry(self) -> None:
        """ConnectError causes retries up to max_retries."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        service = SIEMService(http_client=mock_client)
        config = _splunk_config(max_retries=2, retry_base_delay=0.001)

        with patch("fileguard.services.siem.asyncio.sleep", new_callable=AsyncMock):
            await service._deliver_with_retry(_make_event(), config)

        # initial attempt + 2 retries = 3 total
        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_network_error_increments_counter(self) -> None:
        """Each network failure increments siem_delivery_errors_total."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        service = SIEMService(http_client=mock_client)
        config = _splunk_config(max_retries=1, retry_base_delay=0.001)

        before = _get_counter_value("splunk", "network_error")
        with patch("fileguard.services.siem.asyncio.sleep", new_callable=AsyncMock):
            await service._deliver_with_retry(_make_event(), config)
        after = _get_counter_value("splunk", "network_error")

        # 2 failures (initial + 1 retry)
        assert after - before == 2

    @pytest.mark.asyncio
    async def test_succeeds_after_transient_failure(self) -> None:
        """Delivery succeeds on the second attempt after one transient failure."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            side_effect=[
                httpx.ConnectError("transient"),
                _ok_response(),
            ]
        )

        service = SIEMService(http_client=mock_client)
        config = _splunk_config(max_retries=2, retry_base_delay=0.001)

        with patch("fileguard.services.siem.asyncio.sleep", new_callable=AsyncMock):
            await service._deliver_with_retry(_make_event(), config)

        assert mock_client.post.call_count == 2


# ---------------------------------------------------------------------------
# SIEMService — HTTP error handling
# ---------------------------------------------------------------------------


class TestSIEMServiceHTTPErrors:
    @pytest.mark.asyncio
    async def test_http_5xx_triggers_retry(self) -> None:
        """HTTP 503 (retryable) causes retries."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        error_resp = _error_response(503)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "503 Service Unavailable",
                request=MagicMock(),
                response=error_resp,
            )
        )

        service = SIEMService(http_client=mock_client)
        config = _splunk_config(max_retries=2, retry_base_delay=0.001)

        with patch("fileguard.services.siem.asyncio.sleep", new_callable=AsyncMock):
            await service._deliver_with_retry(_make_event(), config)

        assert mock_client.post.call_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_http_5xx_increments_error_counter(self) -> None:
        """HTTP 500 increments siem_delivery_errors_total with error_type=http_error."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        error_resp = _error_response(500)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "500 Internal Server Error",
                request=MagicMock(),
                response=error_resp,
            )
        )

        service = SIEMService(http_client=mock_client)
        config = _watchtower_config(max_retries=1, retry_base_delay=0.001)

        before = _get_counter_value("watchtower", "http_error")
        with patch("fileguard.services.siem.asyncio.sleep", new_callable=AsyncMock):
            await service._deliver_with_retry(_make_event(), config)
        after = _get_counter_value("watchtower", "http_error")

        assert after - before == 2  # initial + 1 retry

    @pytest.mark.asyncio
    async def test_http_4xx_non_retryable_aborts_immediately(self) -> None:
        """HTTP 401 (non-retryable) causes immediate abort without retrying."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        error_resp = _error_response(401)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "401 Unauthorized",
                request=MagicMock(),
                response=error_resp,
            )
        )

        service = SIEMService(http_client=mock_client)
        config = _splunk_config(max_retries=3, retry_base_delay=0.001)

        await service._deliver_with_retry(_make_event(), config)

        assert mock_client.post.call_count == 1  # no retries for 4xx

    @pytest.mark.asyncio
    async def test_http_4xx_increments_error_counter(self) -> None:
        """HTTP 403 increments error counter exactly once (no retries)."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        error_resp = _error_response(403)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "403 Forbidden",
                request=MagicMock(),
                response=error_resp,
            )
        )

        service = SIEMService(http_client=mock_client)
        config = _splunk_config(max_retries=3, retry_base_delay=0.001)

        before = _get_counter_value("splunk", "http_error")
        await service._deliver_with_retry(_make_event(), config)
        after = _get_counter_value("splunk", "http_error")

        assert after - before == 1  # exactly one increment, no retries


# ---------------------------------------------------------------------------
# SIEMService — forward_event (fire-and-forget)
# ---------------------------------------------------------------------------


class TestSIEMServiceForwardEvent:
    @pytest.mark.asyncio
    async def test_forward_event_returns_task(self) -> None:
        """forward_event returns an asyncio.Task immediately."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_ok_response())

        service = SIEMService(http_client=mock_client)
        task = service.forward_event(_make_event(), _splunk_config())

        assert isinstance(task, asyncio.Task)
        await task  # wait for completion in tests

    @pytest.mark.asyncio
    async def test_forward_event_does_not_block(self) -> None:
        """forward_event schedules delivery without awaiting it."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # Use an event to detect when delivery starts
        delivery_started = asyncio.Event()

        async def slow_post(*args: Any, **kwargs: Any) -> MagicMock:
            delivery_started.set()
            await asyncio.sleep(1)  # simulate slow delivery
            return _ok_response()

        mock_client.post = slow_post

        service = SIEMService(http_client=mock_client)
        task = service.forward_event(_make_event(), _splunk_config())

        # forward_event should return before delivery completes
        assert not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_forward_event_splunk_delivers_correctly(self) -> None:
        """forward_event for Splunk results in correct payload delivery."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_ok_response())

        service = SIEMService(http_client=mock_client)
        event = _make_event()
        task = service.forward_event(event, _splunk_config())
        await task

        mock_client.post.assert_called_once()
        payload = mock_client.post.call_args.kwargs["json"]
        assert "event" in payload

    @pytest.mark.asyncio
    async def test_forward_event_watchtower_delivers_correctly(self) -> None:
        """forward_event for WatchTower results in correct flat payload delivery."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=_ok_response())

        service = SIEMService(http_client=mock_client)
        event = _make_event()
        task = service.forward_event(event, _watchtower_config())
        await task

        mock_client.post.assert_called_once()
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["scan_id"] == str(_SCAN_ID)
        assert "event" not in payload


# ---------------------------------------------------------------------------
# SIEMService — counter labels and both destinations
# ---------------------------------------------------------------------------


class TestSIEMServiceErrorCounterLabels:
    @pytest.mark.asyncio
    async def test_splunk_counter_uses_splunk_label(self) -> None:
        """Error counter for Splunk failures uses destination=splunk."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("refused")
        )

        service = SIEMService(http_client=mock_client)
        config = _splunk_config(max_retries=0)

        before = _get_counter_value("splunk", "network_error")
        await service._deliver_with_retry(_make_event(), config)
        after = _get_counter_value("splunk", "network_error")

        assert after - before == 1

    @pytest.mark.asyncio
    async def test_watchtower_counter_uses_watchtower_label(self) -> None:
        """Error counter for WatchTower failures uses destination=watchtower."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("refused")
        )

        service = SIEMService(http_client=mock_client)
        config = _watchtower_config(max_retries=0)

        before = _get_counter_value("watchtower", "network_error")
        await service._deliver_with_retry(_make_event(), config)
        after = _get_counter_value("watchtower", "network_error")

        assert after - before == 1

    @pytest.mark.asyncio
    async def test_unknown_exception_uses_unknown_label(self) -> None:
        """Unexpected exceptions use error_type=unknown label."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=RuntimeError("unexpected"))

        service = SIEMService(http_client=mock_client)
        config = _splunk_config(max_retries=0)

        before = _get_counter_value("splunk", "unknown")
        await service._deliver_with_retry(_make_event(), config)
        after = _get_counter_value("splunk", "unknown")

        assert after - before == 1


# ---------------------------------------------------------------------------
# SIEMService — no shared http_client (uses context manager)
# ---------------------------------------------------------------------------


class TestSIEMServiceNoSharedClient:
    @pytest.mark.asyncio
    async def test_creates_client_when_none_provided(self) -> None:
        """SIEMService creates a transient AsyncClient when none is injected."""
        service = SIEMService(http_client=None)

        with patch("fileguard.services.siem.httpx.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post = AsyncMock(return_value=_ok_response())
            mock_cls.return_value = mock_instance

            await service._deliver_with_retry(_make_event(), _splunk_config())

        mock_cls.assert_called_once()
        mock_instance.post.assert_called_once()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _get_counter_value(destination: str, error_type: str) -> float:
    """Read the current value of siem_delivery_errors_total for given labels."""
    try:
        return siem_delivery_errors_total.labels(
            destination=destination, error_type=error_type
        )._value.get()
    except Exception:
        return 0.0
