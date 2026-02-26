"""Unit tests for fileguard/core/av_adapter.py.

Coverage targets:
* AVEngineAdapter is abstract — cannot be instantiated directly.
* Concrete subclasses that implement all abstract methods can be instantiated.
* ScanResult enforces the invariant: is_clean=True with threats is invalid.
* ScanResult(is_clean=False, threats=[...]) is valid.
* ScanResult(is_clean=True, threats=()) is valid.
* AVThreat stores name, severity, and category correctly.
* AVEngineError, AVEngineUnavailableError, AVEngineScanError form a hierarchy.
* is_available() and engine_name() return expected types.
* scan() returns ScanResult with the adapter's engine_name populated.
* Interface is importable with no errors.
"""

from __future__ import annotations

import pytest

from fileguard.core.av_adapter import (
    AVEngineAdapter,
    AVEngineError,
    AVEngineScanError,
    AVEngineUnavailableError,
    AVThreat,
    AVThreatSeverity,
    ScanResult,
)


# ---------------------------------------------------------------------------
# Concrete test adapter implementations
# ---------------------------------------------------------------------------


class _CleanAdapter(AVEngineAdapter):
    """Always reports clean scans and is always available."""

    def scan(self, data: bytes) -> ScanResult:
        return ScanResult(is_clean=True, engine_name=self.engine_name())

    def is_available(self) -> bool:
        return True

    def engine_name(self) -> str:
        return "test-clean"


class _InfectedAdapter(AVEngineAdapter):
    """Always reports a single threat."""

    def scan(self, data: bytes) -> ScanResult:
        threat = AVThreat(
            name="Win.Trojan.EICAR-1",
            severity=AVThreatSeverity.CRITICAL,
            category="Trojan",
        )
        return ScanResult(
            is_clean=False,
            threats=(threat,),
            engine_name=self.engine_name(),
        )

    def is_available(self) -> bool:
        return True

    def engine_name(self) -> str:
        return "test-infected"


class _UnavailableAdapter(AVEngineAdapter):
    """Simulates a daemon that is unreachable."""

    def scan(self, data: bytes) -> ScanResult:
        raise AVEngineUnavailableError("Daemon is down")

    def is_available(self) -> bool:
        return False

    def engine_name(self) -> str:
        return "test-unavailable"


class _ErrorAdapter(AVEngineAdapter):
    """Simulates a daemon that returns an error response."""

    def scan(self, data: bytes) -> ScanResult:
        raise AVEngineScanError("Engine returned ERROR status")

    def is_available(self) -> bool:
        return True

    def engine_name(self) -> str:
        return "test-error"


# ---------------------------------------------------------------------------
# AVEngineAdapter — abstract interface
# ---------------------------------------------------------------------------


class TestAVEngineAdapterAbstract:
    def test_cannot_instantiate_abstract_class(self) -> None:
        with pytest.raises(TypeError):
            AVEngineAdapter()  # type: ignore[abstract]

    def test_concrete_subclass_can_be_instantiated(self) -> None:
        adapter = _CleanAdapter()
        assert isinstance(adapter, AVEngineAdapter)

    def test_partial_implementation_raises_type_error(self) -> None:
        class _Partial(AVEngineAdapter):
            def scan(self, data: bytes) -> ScanResult:  # pragma: no cover
                return ScanResult(is_clean=True)

            # is_available and engine_name not implemented

        with pytest.raises(TypeError):
            _Partial()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# AVEngineAdapter — clean scan path
# ---------------------------------------------------------------------------


class TestCleanScan:
    def setup_method(self) -> None:
        self.adapter = _CleanAdapter()

    def test_is_available_returns_true(self) -> None:
        assert self.adapter.is_available() is True

    def test_engine_name_is_string(self) -> None:
        assert isinstance(self.adapter.engine_name(), str)
        assert self.adapter.engine_name() != ""

    def test_scan_returns_scan_result(self) -> None:
        result = self.adapter.scan(b"clean file content")
        assert isinstance(result, ScanResult)

    def test_scan_clean_result_has_no_threats(self) -> None:
        result = self.adapter.scan(b"clean file content")
        assert result.is_clean is True
        assert result.threats == ()

    def test_scan_result_engine_name_matches_adapter(self) -> None:
        result = self.adapter.scan(b"data")
        assert result.engine_name == self.adapter.engine_name()

    def test_scan_empty_bytes(self) -> None:
        result = self.adapter.scan(b"")
        assert result.is_clean is True


# ---------------------------------------------------------------------------
# AVEngineAdapter — infected scan path
# ---------------------------------------------------------------------------


class TestInfectedScan:
    def setup_method(self) -> None:
        self.adapter = _InfectedAdapter()

    def test_scan_returns_scan_result(self) -> None:
        result = self.adapter.scan(b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE")
        assert isinstance(result, ScanResult)

    def test_scan_infected_result_is_not_clean(self) -> None:
        result = self.adapter.scan(b"malware bytes")
        assert result.is_clean is False

    def test_scan_infected_result_has_threats(self) -> None:
        result = self.adapter.scan(b"malware bytes")
        assert len(result.threats) == 1

    def test_threat_fields_are_populated(self) -> None:
        result = self.adapter.scan(b"malware bytes")
        threat = result.threats[0]
        assert threat.name == "Win.Trojan.EICAR-1"
        assert threat.severity == AVThreatSeverity.CRITICAL
        assert threat.category == "Trojan"


# ---------------------------------------------------------------------------
# AVEngineAdapter — unavailable engine path
# ---------------------------------------------------------------------------


class TestUnavailableEngine:
    def setup_method(self) -> None:
        self.adapter = _UnavailableAdapter()

    def test_is_available_returns_false(self) -> None:
        assert self.adapter.is_available() is False

    def test_scan_raises_av_engine_unavailable_error(self) -> None:
        with pytest.raises(AVEngineUnavailableError):
            self.adapter.scan(b"data")

    def test_av_engine_unavailable_error_is_av_engine_error(self) -> None:
        with pytest.raises(AVEngineError):
            self.adapter.scan(b"data")


# ---------------------------------------------------------------------------
# AVEngineAdapter — engine scan error path
# ---------------------------------------------------------------------------


class TestEngineScanError:
    def setup_method(self) -> None:
        self.adapter = _ErrorAdapter()

    def test_scan_raises_av_engine_scan_error(self) -> None:
        with pytest.raises(AVEngineScanError):
            self.adapter.scan(b"data")

    def test_av_engine_scan_error_is_av_engine_error(self) -> None:
        with pytest.raises(AVEngineError):
            self.adapter.scan(b"data")


# ---------------------------------------------------------------------------
# ScanResult — invariant enforcement
# ---------------------------------------------------------------------------


class TestScanResult:
    def test_clean_result_with_no_threats_is_valid(self) -> None:
        result = ScanResult(is_clean=True)
        assert result.is_clean is True
        assert result.threats == ()

    def test_infected_result_with_threats_is_valid(self) -> None:
        threat = AVThreat(name="EICAR")
        result = ScanResult(is_clean=False, threats=(threat,))
        assert result.is_clean is False
        assert len(result.threats) == 1

    def test_clean_result_with_threats_raises_value_error(self) -> None:
        threat = AVThreat(name="EICAR")
        with pytest.raises(ValueError, match="clean"):
            ScanResult(is_clean=True, threats=(threat,))

    def test_scan_result_is_immutable(self) -> None:
        result = ScanResult(is_clean=True)
        with pytest.raises((AttributeError, TypeError)):
            result.is_clean = False  # type: ignore[misc]

    def test_engine_name_defaults_to_empty_string(self) -> None:
        result = ScanResult(is_clean=True)
        assert result.engine_name == ""

    def test_engine_version_defaults_to_none(self) -> None:
        result = ScanResult(is_clean=True)
        assert result.engine_version is None

    def test_scan_duration_ms_defaults_to_none(self) -> None:
        result = ScanResult(is_clean=True)
        assert result.scan_duration_ms is None

    def test_all_optional_fields_can_be_set(self) -> None:
        result = ScanResult(
            is_clean=True,
            engine_name="clamav",
            engine_version="0.105.2/26955/2026-02-25",
            scan_duration_ms=42,
        )
        assert result.engine_name == "clamav"
        assert result.engine_version == "0.105.2/26955/2026-02-25"
        assert result.scan_duration_ms == 42


# ---------------------------------------------------------------------------
# AVThreat — data class
# ---------------------------------------------------------------------------


class TestAVThreat:
    def test_name_is_required(self) -> None:
        threat = AVThreat(name="Win.Trojan.EICAR-1")
        assert threat.name == "Win.Trojan.EICAR-1"

    def test_severity_defaults_to_high(self) -> None:
        threat = AVThreat(name="EICAR")
        assert threat.severity == AVThreatSeverity.HIGH

    def test_category_defaults_to_none(self) -> None:
        threat = AVThreat(name="EICAR")
        assert threat.category is None

    def test_all_fields_can_be_set(self) -> None:
        threat = AVThreat(
            name="Win.Ransomware.Locky-1",
            severity=AVThreatSeverity.CRITICAL,
            category="Ransomware",
        )
        assert threat.name == "Win.Ransomware.Locky-1"
        assert threat.severity == AVThreatSeverity.CRITICAL
        assert threat.category == "Ransomware"

    def test_threat_is_immutable(self) -> None:
        threat = AVThreat(name="EICAR")
        with pytest.raises((AttributeError, TypeError)):
            threat.name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AVThreatSeverity — enum values
# ---------------------------------------------------------------------------


class TestAVThreatSeverity:
    def test_all_severity_levels_exist(self) -> None:
        assert AVThreatSeverity.LOW == "low"
        assert AVThreatSeverity.MEDIUM == "medium"
        assert AVThreatSeverity.HIGH == "high"
        assert AVThreatSeverity.CRITICAL == "critical"


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    def test_av_engine_unavailable_error_is_av_engine_error(self) -> None:
        assert issubclass(AVEngineUnavailableError, AVEngineError)

    def test_av_engine_scan_error_is_av_engine_error(self) -> None:
        assert issubclass(AVEngineScanError, AVEngineError)

    def test_av_engine_error_is_exception(self) -> None:
        assert issubclass(AVEngineError, Exception)

    def test_exceptions_can_be_instantiated_with_message(self) -> None:
        err = AVEngineError("base error")
        assert str(err) == "base error"

        unavail = AVEngineUnavailableError("daemon down")
        assert str(unavail) == "daemon down"

        scan_err = AVEngineScanError("bad response")
        assert str(scan_err) == "bad response"
