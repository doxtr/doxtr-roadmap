"""Unit tests for doxtr_roadmap.plantuml_version and _check_plantuml_version.

All tests are hermetic — no real plantuml binary is invoked.  subprocess is
monkeypatched at the doxtr_roadmap module level so the actual import tree is
exercised without any I/O.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from doxtr_roadmap.plantuml_version import (
    MIN_PLANTUML_VERSION,
    MIN_PLANTUML_VERSION_STR,
    is_version_sufficient,
    parse_plantuml_version,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MIN = MIN_PLANTUML_VERSION  # (1, 2026, 7)


def _make_subprocess_mock(stdout: str, stderr: str = "") -> MagicMock:
    """Return a mock 'subprocess' module whose .run() yields a fake result."""
    fake_result = MagicMock()
    fake_result.stdout = stdout
    fake_result.stderr = stderr
    fake_sub = MagicMock()
    fake_sub.run.return_value = fake_result
    return fake_sub


class _FakeConfig:
    """Minimal Sphinx config stub for _check_plantuml_version tests."""
    plantuml: str = "plantuml"
    doxtr_roadmap_require_plantuml_version: object = "error"


class _FakeApp:
    def __init__(self, require: object = "error") -> None:
        self.config = _FakeConfig()
        self.config.doxtr_roadmap_require_plantuml_version = require


# ---------------------------------------------------------------------------
# Autouse fixture — reset module-level dedup flag between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_version_flag():
    """Reset doxtr_roadmap._version_check_done before and after every test."""
    import doxtr_roadmap
    doxtr_roadmap._version_check_done = False
    yield
    doxtr_roadmap._version_check_done = False


# ---------------------------------------------------------------------------
# parse_plantuml_version
# ---------------------------------------------------------------------------

def test_parse_real_sample_line():
    """The canonical -version sample line is parsed correctly."""
    text = "PlantUML version 1.2023.7 (Fri May 12 19:23:42 CEST 2023)"
    assert parse_plantuml_version(text) == (1, 2023, 7)


def test_parse_min_version_line():
    """The minimum required version line is parsed correctly."""
    text = "PlantUML version 1.2026.7 (Mon Aug 25 09:35:51 UTC 2026)"
    assert parse_plantuml_version(text) == (1, 2026, 7)


def test_parse_version_embedded_in_multi_line_output():
    """Version is found even when surrounded by other output lines."""
    text = (
        "Some header\n"
        "PlantUML version 1.2025.3 (Thu Jan 01 00:00:00 UTC 2025)\n"
        "Installation seems OK.\n"
    )
    assert parse_plantuml_version(text) == (1, 2025, 3)


def test_parse_garbage_returns_none():
    assert parse_plantuml_version("some random text with no version") is None


def test_parse_empty_string_returns_none():
    assert parse_plantuml_version("") is None


def test_parse_partial_version_returns_none():
    """Two-component version string must not match."""
    assert parse_plantuml_version("PlantUML version 1.2026") is None


# ---------------------------------------------------------------------------
# is_version_sufficient
# ---------------------------------------------------------------------------

def test_exact_min_is_sufficient():
    assert is_version_sufficient((1, 2026, 7), _MIN) is True


def test_above_min_release_same_year_is_sufficient():
    assert is_version_sufficient((1, 2026, 8), _MIN) is True


def test_below_min_year_is_not_sufficient():
    assert is_version_sufficient((1, 2023, 7), _MIN) is False


def test_below_min_release_same_year_is_not_sufficient():
    assert is_version_sufficient((1, 2026, 6), _MIN) is False


def test_higher_major_is_sufficient():
    assert is_version_sufficient((2, 0, 0), _MIN) is True


def test_higher_year_is_sufficient():
    assert is_version_sufficient((1, 2027, 0), _MIN) is True


# ---------------------------------------------------------------------------
# _check_plantuml_version — integration tests with monkeypatched subprocess
# ---------------------------------------------------------------------------

def test_check_error_raises_when_below_min(monkeypatch):
    """require='error' + below-min version raises ExtensionError."""
    import doxtr_roadmap
    fake_sub = _make_subprocess_mock("PlantUML version 1.2023.7 (old build)\n")
    monkeypatch.setattr(doxtr_roadmap, "subprocess", fake_sub)

    from sphinx.errors import ExtensionError
    app = _FakeApp(require="error")
    with pytest.raises(ExtensionError) as exc_info:
        doxtr_roadmap._check_plantuml_version(app)

    assert "1.2023.7" in str(exc_info.value)
    assert MIN_PLANTUML_VERSION_STR in str(exc_info.value)


def test_check_warn_logs_warning_when_below_min(monkeypatch, caplog):
    """require='warn' + below-min version logs a WARNING-level message."""
    import doxtr_roadmap
    fake_sub = _make_subprocess_mock("PlantUML version 1.2023.7 (old build)\n")
    monkeypatch.setattr(doxtr_roadmap, "subprocess", fake_sub)

    app = _FakeApp(require="warn")
    with caplog.at_level(logging.WARNING):
        doxtr_roadmap._check_plantuml_version(app)

    warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("1.2023.7" in m for m in warning_messages), (
        f"Expected '1.2023.7' in warnings; got: {warning_messages}"
    )
    assert any(MIN_PLANTUML_VERSION_STR in m for m in warning_messages), (
        f"Expected '{MIN_PLANTUML_VERSION_STR}' in warnings; got: {warning_messages}"
    )


def test_check_off_string_does_not_invoke_subprocess(monkeypatch):
    """require='off' must not call subprocess.run at all."""
    import doxtr_roadmap
    fake_sub = MagicMock()
    monkeypatch.setattr(doxtr_roadmap, "subprocess", fake_sub)

    app = _FakeApp(require="off")
    doxtr_roadmap._check_plantuml_version(app)

    fake_sub.run.assert_not_called()


def test_check_false_does_not_invoke_subprocess(monkeypatch):
    """require=False (boolean) also skips the check entirely."""
    import doxtr_roadmap
    fake_sub = MagicMock()
    monkeypatch.setattr(doxtr_roadmap, "subprocess", fake_sub)

    app = _FakeApp(require=False)
    doxtr_roadmap._check_plantuml_version(app)

    fake_sub.run.assert_not_called()


def test_check_sufficient_version_no_warning(monkeypatch, caplog):
    """Sufficient version does not produce a warning or error."""
    import doxtr_roadmap
    fake_sub = _make_subprocess_mock("PlantUML version 1.2026.7 (current)\n")
    monkeypatch.setattr(doxtr_roadmap, "subprocess", fake_sub)

    app = _FakeApp(require="warn")
    with caplog.at_level(logging.WARNING):
        doxtr_roadmap._check_plantuml_version(app)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, f"Unexpected warnings for sufficient version: {warnings}"


def test_check_above_min_version_no_warning(monkeypatch, caplog):
    """A version strictly above the minimum also produces no warning."""
    import doxtr_roadmap
    fake_sub = _make_subprocess_mock("PlantUML version 1.2026.8 (newer)\n")
    monkeypatch.setattr(doxtr_roadmap, "subprocess", fake_sub)

    app = _FakeApp(require="warn")
    with caplog.at_level(logging.WARNING):
        doxtr_roadmap._check_plantuml_version(app)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings


def test_check_undetermined_version_logs_info_not_warning(monkeypatch, caplog):
    """Unrecognised plantuml output: emits INFO, not WARNING; build continues."""
    import doxtr_roadmap
    fake_sub = _make_subprocess_mock("something completely unexpected\n")
    monkeypatch.setattr(doxtr_roadmap, "subprocess", fake_sub)

    app = _FakeApp(require="warn")
    with caplog.at_level(logging.DEBUG):
        doxtr_roadmap._check_plantuml_version(app)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, f"Unexpected warnings for undetermined version: {warnings}"

    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert infos, "Expected at least one INFO log for undetermined version"
    assert any(MIN_PLANTUML_VERSION_STR in r.message for r in infos)


def test_check_file_not_found_logs_info_not_warning(monkeypatch, caplog):
    """FileNotFoundError from subprocess: emits INFO, not WARNING; build continues."""
    import doxtr_roadmap
    fake_sub = MagicMock()
    fake_sub.run.side_effect = FileNotFoundError("plantuml: command not found")
    monkeypatch.setattr(doxtr_roadmap, "subprocess", fake_sub)

    app = _FakeApp(require="warn")
    with caplog.at_level(logging.DEBUG):
        doxtr_roadmap._check_plantuml_version(app)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, f"Unexpected warnings on FileNotFoundError: {warnings}"

    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert infos, "Expected at least one INFO log on FileNotFoundError"


def test_check_deduplication(monkeypatch):
    """The version check runs at most once per build (module-level flag)."""
    import doxtr_roadmap
    fake_sub = _make_subprocess_mock("PlantUML version 1.2026.7 (current)\n")
    monkeypatch.setattr(doxtr_roadmap, "subprocess", fake_sub)

    app = _FakeApp(require="warn")
    doxtr_roadmap._check_plantuml_version(app)
    doxtr_roadmap._check_plantuml_version(app)
    doxtr_roadmap._check_plantuml_version(app)

    assert fake_sub.run.call_count == 1, (
        f"subprocess.run was called {fake_sub.run.call_count} times; expected 1"
    )


def test_check_message_contains_doxtr_roadmap_prefix(monkeypatch, caplog):
    """Warning messages are prefixed with '[doxtr-roadmap]' for easy filtering."""
    import doxtr_roadmap
    fake_sub = _make_subprocess_mock("PlantUML version 1.2025.1 (old)\n")
    monkeypatch.setattr(doxtr_roadmap, "subprocess", fake_sub)

    app = _FakeApp(require="warn")
    with caplog.at_level(logging.WARNING):
        doxtr_roadmap._check_plantuml_version(app)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("[doxtr-roadmap]" in r.message for r in warnings)


def test_check_default_mode_is_error_raises_on_old_version(monkeypatch):
    """Default require mode is 'error': below-min version raises ExtensionError.

    Mirrors the registered default in setup() — projects on PlantUML < v1.2026.7
    get a hard build failure rather than a warning unless they opt out.
    """
    import doxtr_roadmap
    fake_sub = _make_subprocess_mock("PlantUML version 1.2023.7 (old build)\n")
    monkeypatch.setattr(doxtr_roadmap, "subprocess", fake_sub)

    from sphinx.errors import ExtensionError
    app = _FakeApp()  # default require="error" — no explicit override
    with pytest.raises(ExtensionError) as exc_info:
        doxtr_roadmap._check_plantuml_version(app)

    assert "1.2023.7" in str(exc_info.value)
    assert MIN_PLANTUML_VERSION_STR in str(exc_info.value)


def test_check_default_mode_is_error_no_raise_on_sufficient_version(monkeypatch, caplog):
    """Default require='error' does NOT raise when the installed version is sufficient."""
    import doxtr_roadmap
    fake_sub = _make_subprocess_mock("PlantUML version 1.2026.7 (current)\n")
    monkeypatch.setattr(doxtr_roadmap, "subprocess", fake_sub)

    app = _FakeApp()  # default require="error"
    with caplog.at_level(logging.WARNING):
        doxtr_roadmap._check_plantuml_version(app)  # must not raise

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, f"Unexpected warnings for sufficient version: {warnings}"


# ---------------------------------------------------------------------------
# S-2 test: version-check timeout branch (T-27)
# ---------------------------------------------------------------------------

def test_check_timeout_logs_info_not_warning(monkeypatch, caplog):
    """subprocess.TimeoutExpired → emits INFO, not WARNING; build continues."""
    import doxtr_roadmap
    import subprocess as _subprocess
    fake_sub = MagicMock()
    fake_sub.run.side_effect = _subprocess.TimeoutExpired(cmd=["plantuml", "-version"], timeout=15)
    fake_sub.TimeoutExpired = _subprocess.TimeoutExpired
    monkeypatch.setattr(doxtr_roadmap, "subprocess", fake_sub)

    app = _FakeApp(require="warn")
    with caplog.at_level(logging.DEBUG):
        doxtr_roadmap._check_plantuml_version(app)   # must NOT raise

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, f"Unexpected warnings on TimeoutExpired: {warnings}"

    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert infos, "Expected at least one INFO log on TimeoutExpired"
    assert any("timed out" in r.message.lower() or "timeout" in r.message.lower()
               for r in infos), f"Expected timeout mention in info: {[r.message for r in infos]}"


def test_check_timeout_does_not_raise_on_error_mode(monkeypatch):
    """TimeoutExpired with require='error' must NOT crash the build."""
    import doxtr_roadmap
    import subprocess as _subprocess
    fake_sub = MagicMock()
    fake_sub.run.side_effect = _subprocess.TimeoutExpired(cmd=["plantuml", "-version"], timeout=15)
    fake_sub.TimeoutExpired = _subprocess.TimeoutExpired
    monkeypatch.setattr(doxtr_roadmap, "subprocess", fake_sub)

    app = _FakeApp(require="error")
    # Should NOT raise ExtensionError — undetermined version must not abort build
    doxtr_roadmap._check_plantuml_version(app)
