"""Unit tests for the AVEngineAdapter abstract interface and ClamAVAdapter.

All tests are fully offline — the ClamAV daemon socket is replaced by
``unittest.mock`` patches so no external services are required.

Test coverage:
- :class:`~fileguard.engines.base.Finding` immutability and equality
- :class:`~fileguard.engines.base.AVEngineAdapter` abstract enforcement
- :class:`~fileguard.engines.clamav.ClamAVAdapter` happy path (clean file,
  single threat, multiple threats, ``None`` result)
- :class:`~fileguard.engines.clamav.ClamAVAdapter` error handling
  (``ConnectionError``, missing file, unexpected daemon error)
- :class:`~fileguard.engines.clamav.ClamAVAdapter` ``ping`` liveness check
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fileguard.engines import (
    AVEngineAdapter,
    AVEngineError,
    ClamAVAdapter,
    Finding,
    FindingSeverity,
    FindingType,
)


# ---------------------------------------------------------------------------
# Finding dataclass
# ---------------------------------------------------------------------------


class TestFinding:
    def test_finding_is_immutable(self) -> None:
        finding = Finding(
            type=FindingType.AV_THREAT,
            category="EICAR-Test-Signature",
            severity=FindingSeverity.CRITICAL,
            offset=0,
            match="EICAR-Test-Signature",
        )
        with pytest.raises((AttributeError, TypeError)):
            finding.category = "other"  # type: ignore[misc]

    def test_findings_with_same_fields_are_equal(self) -> None:
        f1 = Finding(FindingType.AV_THREAT, "EICAR", FindingSeverity.CRITICAL, 0, "EICAR")
        f2 = Finding(FindingType.AV_THREAT, "EICAR", FindingSeverity.CRITICAL, 0, "EICAR")
        assert f1 == f2

    def test_findings_with_different_fields_are_not_equal(self) -> None:
        f1 = Finding(FindingType.AV_THREAT, "EICAR", FindingSeverity.CRITICAL, 0, "EICAR")
        f2 = Finding(FindingType.AV_THREAT, "Trojan.X", FindingSeverity.HIGH, 0, "Trojan.X")
        assert f1 != f2

    def test_finding_pii_type_stores_offset(self) -> None:
        f = Finding(
            type=FindingType.PII,
            category="NHS_NUMBER",
            severity=FindingSeverity.HIGH,
            offset=42,
            match="[REDACTED]",
        )
        assert f.type == FindingType.PII
        assert f.offset == 42
        assert f.match == "[REDACTED]"

    def test_finding_type_enum_values(self) -> None:
        assert FindingType.AV_THREAT == "av_threat"
        assert FindingType.PII == "pii"

    def test_finding_severity_enum_values(self) -> None:
        assert FindingSeverity.LOW == "low"
        assert FindingSeverity.MEDIUM == "medium"
        assert FindingSeverity.HIGH == "high"
        assert FindingSeverity.CRITICAL == "critical"


# ---------------------------------------------------------------------------
# AVEngineAdapter abstract interface enforcement
# ---------------------------------------------------------------------------


class TestAVEngineAdapterIsAbstract:
    def test_cannot_instantiate_base_class_directly(self) -> None:
        with pytest.raises(TypeError):
            AVEngineAdapter()  # type: ignore[abstract]

    def test_subclass_missing_scan_cannot_be_instantiated(self) -> None:
        class IncompleteAdapter(AVEngineAdapter):
            def ping(self) -> bool:
                return True

        with pytest.raises(TypeError):
            IncompleteAdapter()  # type: ignore[abstract]

    def test_subclass_missing_ping_cannot_be_instantiated(self) -> None:
        class IncompleteAdapter(AVEngineAdapter):
            def scan(self, file_path: Path) -> list[Finding]:
                return []

        with pytest.raises(TypeError):
            IncompleteAdapter()  # type: ignore[abstract]

    def test_concrete_subclass_implementing_both_methods_can_be_instantiated(self) -> None:
        class MinimalAdapter(AVEngineAdapter):
            def scan(self, file_path: Path) -> list[Finding]:
                return []

            def ping(self) -> bool:
                return True

        adapter = MinimalAdapter()
        assert adapter.ping() is True
        assert adapter.scan(Path("/dev/null")) == []

    def test_adapter_is_usable_via_base_type_annotation(self) -> None:
        """Verify that the adapter can be used through its abstract type."""

        def _run(engine: AVEngineAdapter, path: Path) -> list[Finding]:
            return engine.scan(path)

        class FakeAdapter(AVEngineAdapter):
            def scan(self, file_path: Path) -> list[Finding]:
                return [
                    Finding(FindingType.AV_THREAT, "Fake.Virus", FindingSeverity.HIGH, 0, "Fake.Virus")
                ]

            def ping(self) -> bool:
                return True

        result = _run(FakeAdapter(), Path("/dev/null"))
        assert len(result) == 1
        assert result[0].category == "Fake.Virus"


# ---------------------------------------------------------------------------
# ClamAVAdapter — initialisation
# ---------------------------------------------------------------------------


class TestClamAVAdapterInit:
    def test_default_host_and_port(self) -> None:
        adapter = ClamAVAdapter()
        assert adapter._host == "clamav"
        assert adapter._port == 3310

    def test_custom_host_and_port(self) -> None:
        adapter = ClamAVAdapter(host="127.0.0.1", port=9999)
        assert adapter._host == "127.0.0.1"
        assert adapter._port == 9999

    def test_adapter_is_instance_of_base(self) -> None:
        assert isinstance(ClamAVAdapter(), AVEngineAdapter)


# ---------------------------------------------------------------------------
# ClamAVAdapter — scan: clean file
# ---------------------------------------------------------------------------


class TestClamAVAdapterCleanFile:
    def _make_adapter_with_temp_file(self, scan_result: dict | None) -> tuple[ClamAVAdapter, Path]:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        tmp.write(b"clean content")
        tmp.close()
        path = Path(tmp.name)

        adapter = ClamAVAdapter(host="localhost", port=3310)
        mock_client = MagicMock()
        mock_client.scan.return_value = scan_result
        adapter._client = mock_client
        return adapter, path

    def test_ok_status_returns_empty_list(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            path = Path(f.name)
            f.write(b"clean")
        adapter = ClamAVAdapter(host="localhost", port=3310)
        mock_client = MagicMock()
        mock_client.scan.return_value = {str(path): ("OK", None)}
        adapter._client = mock_client

        findings = adapter.scan(path)
        assert findings == []

    def test_none_result_returns_empty_list(self) -> None:
        adapter, path = self._make_adapter_with_temp_file(None)
        findings = adapter.scan(path)
        assert findings == []

    def test_scan_calls_client_with_string_path(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            path = Path(f.name)
            f.write(b"data")
        adapter = ClamAVAdapter(host="localhost", port=3310)
        mock_client = MagicMock()
        mock_client.scan.return_value = {str(path): ("OK", None)}
        adapter._client = mock_client

        adapter.scan(path)
        mock_client.scan.assert_called_once_with(str(path))


# ---------------------------------------------------------------------------
# ClamAVAdapter — scan: threat detected
# ---------------------------------------------------------------------------


class TestClamAVAdapterThreatDetected:
    def test_single_threat_returns_one_finding(self) -> None:
        adapter = ClamAVAdapter(host="localhost", port=3310)
        mock_client = MagicMock()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)
        mock_client.scan.return_value = {str(path): ("FOUND", "Eicar-Test-Signature")}
        adapter._client = mock_client

        findings = adapter.scan(path)

        assert len(findings) == 1
        assert findings[0].type == FindingType.AV_THREAT
        assert findings[0].category == "Eicar-Test-Signature"
        assert findings[0].severity == FindingSeverity.CRITICAL
        assert findings[0].match == "Eicar-Test-Signature"
        assert findings[0].offset == 0

    def test_threat_with_none_virus_name_uses_unknown(self) -> None:
        adapter = ClamAVAdapter(host="localhost", port=3310)
        mock_client = MagicMock()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)
        mock_client.scan.return_value = {str(path): ("FOUND", None)}
        adapter._client = mock_client

        findings = adapter.scan(path)

        assert len(findings) == 1
        assert findings[0].category == "UNKNOWN"

    def test_multiple_threats_returns_multiple_findings(self) -> None:
        adapter = ClamAVAdapter(host="localhost", port=3310)
        mock_client = MagicMock()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)
        mock_client.scan.return_value = {
            str(path): ("FOUND", "Virus.Alpha"),
            str(path) + ".extra": ("FOUND", "Virus.Beta"),
        }
        adapter._client = mock_client

        findings = adapter.scan(path)

        assert len(findings) == 2
        categories = {f.category for f in findings}
        assert categories == {"Virus.Alpha", "Virus.Beta"}

    def test_mixed_ok_and_found_only_returns_threat_findings(self) -> None:
        adapter = ClamAVAdapter(host="localhost", port=3310)
        mock_client = MagicMock()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)
        mock_client.scan.return_value = {
            str(path): ("FOUND", "Trojan.Evil"),
            "/other/clean.txt": ("OK", None),
        }
        adapter._client = mock_client

        findings = adapter.scan(path)

        assert len(findings) == 1
        assert findings[0].category == "Trojan.Evil"


# ---------------------------------------------------------------------------
# ClamAVAdapter — scan: error handling
# ---------------------------------------------------------------------------


class TestClamAVAdapterScanErrors:
    def test_connection_error_raises_av_engine_error(self) -> None:
        import clamd as _clamd

        adapter = ClamAVAdapter(host="localhost", port=3310)
        mock_client = MagicMock()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)
        mock_client.scan.side_effect = _clamd.ConnectionError("connection refused")
        adapter._client = mock_client

        with pytest.raises(AVEngineError, match="unreachable"):
            adapter.scan(path)

    def test_connection_error_message_contains_host_and_port(self) -> None:
        import clamd as _clamd

        adapter = ClamAVAdapter(host="192.168.1.10", port=9999)
        mock_client = MagicMock()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)
        mock_client.scan.side_effect = _clamd.ConnectionError("refused")
        adapter._client = mock_client

        with pytest.raises(AVEngineError, match="192.168.1.10"):
            adapter.scan(path)

    def test_missing_file_raises_file_not_found_error(self) -> None:
        adapter = ClamAVAdapter(host="localhost", port=3310)
        with pytest.raises(FileNotFoundError):
            adapter.scan(Path("/nonexistent/path/that/does/not/exist.bin"))

    def test_unexpected_daemon_error_raises_av_engine_error(self) -> None:
        adapter = ClamAVAdapter(host="localhost", port=3310)
        mock_client = MagicMock()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)
        mock_client.scan.side_effect = RuntimeError("unexpected clamd error")
        adapter._client = mock_client

        with pytest.raises(AVEngineError):
            adapter.scan(path)

    def test_av_engine_error_wraps_original_exception(self) -> None:
        import clamd as _clamd

        adapter = ClamAVAdapter(host="localhost", port=3310)
        original = _clamd.ConnectionError("root cause")
        mock_client = MagicMock()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)
        mock_client.scan.side_effect = original
        adapter._client = mock_client

        with pytest.raises(AVEngineError) as exc_info:
            adapter.scan(path)

        assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# ClamAVAdapter — ping liveness check
# ---------------------------------------------------------------------------


class TestClamAVAdapterPing:
    def test_ping_returns_true_when_daemon_responds(self) -> None:
        adapter = ClamAVAdapter(host="localhost", port=3310)
        mock_client = MagicMock()
        mock_client.ping.return_value = "PONG"
        adapter._client = mock_client

        assert adapter.ping() is True

    def test_ping_returns_false_on_connection_error(self) -> None:
        import clamd as _clamd

        adapter = ClamAVAdapter(host="localhost", port=3310)
        mock_client = MagicMock()
        mock_client.ping.side_effect = _clamd.ConnectionError("refused")
        adapter._client = mock_client

        assert adapter.ping() is False

    def test_ping_returns_false_on_os_error(self) -> None:
        adapter = ClamAVAdapter(host="localhost", port=3310)
        mock_client = MagicMock()
        mock_client.ping.side_effect = OSError("network unreachable")
        adapter._client = mock_client

        assert adapter.ping() is False

    def test_ping_never_raises(self) -> None:
        adapter = ClamAVAdapter(host="localhost", port=3310)
        mock_client = MagicMock()
        mock_client.ping.side_effect = Exception("unexpected error")
        adapter._client = mock_client

        # Must not raise — just return False
        result = adapter.ping()
        assert result is False


# ---------------------------------------------------------------------------
# AVEngineError
# ---------------------------------------------------------------------------


class TestAVEngineError:
    def test_is_exception_subclass(self) -> None:
        assert issubclass(AVEngineError, Exception)

    def test_can_be_raised_with_message(self) -> None:
        with pytest.raises(AVEngineError, match="daemon down"):
            raise AVEngineError("daemon down")

    def test_can_chain_cause(self) -> None:
        cause = ConnectionRefusedError("port 3310")
        with pytest.raises(AVEngineError) as exc_info:
            try:
                raise cause
            except ConnectionRefusedError as exc:
                raise AVEngineError("AV engine unavailable") from exc

        assert exc_info.value.__cause__ is cause
