# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for check_formatting's --quiet verbosity level — check_formatting project
"""Tests for check_formatting's --quiet flag.

Modeled on check_rst's own three-level ladder (--quiet / default / --verbose):
--quiet suppresses this script's own chrome (section banners, the
box-drawing summary table, the config echo, each checker's own
"▶ command" announcement lines, and "(no files found)"-style scope
notices) while never touching the wrapped tool's real output, genuine
ERROR messages, or the final one-line machine-parseable summary.

Critically, --quiet must never change the pass/fail return value or exit
code — it is a display filter only (check_rst's own invariant: "the exit
code stays honest" regardless of verbosity level).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from check_formatting import cli as check_formatting

_MINIMAL_TOML = 'checks = ["ini"]\n\n[ini]\nglobs = ["*.ini"]\n'


def test_quiet_suppresses_banners_and_table_but_keeps_summary_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path
    (root / ".check_formatting.toml").write_text(_MINIMAL_TOML)
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 0)

    ok = check_formatting.check_formatting(root, quiet=True)

    assert ok is True
    out = capsys.readouterr().out
    assert "┌" not in out
    assert "╔" not in out
    assert "config: .check_formatting.toml" not in out
    assert "check_formatting: 1 checker(s) run, 1 passed, 0 failed" in out


def test_quiet_return_value_matches_non_quiet_on_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    (root / ".check_formatting.toml").write_text(_MINIMAL_TOML)
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 0)

    quiet_ok = check_formatting.check_formatting(root, quiet=True)
    loud_ok = check_formatting.check_formatting(root, quiet=False)

    assert quiet_ok is True
    assert loud_ok is True
    assert quiet_ok == loud_ok


def test_quiet_return_value_matches_non_quiet_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    (root / ".check_formatting.toml").write_text(_MINIMAL_TOML)
    (root / "settings.ini").write_text("[section]\nkey = value\n")
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 1)

    quiet_ok = check_formatting.check_formatting(root, quiet=True)
    loud_ok = check_formatting.check_formatting(root, quiet=False)

    assert quiet_ok is False
    assert loud_ok is False
    assert quiet_ok == loud_ok


def test_quiet_still_shows_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A genuine problem (here: prettier exiting nonzero mid-diff) must still surface under --quiet."""
    root = tmp_path
    (root / ".check_formatting.toml").write_text(_MINIMAL_TOML)
    (root / "settings.ini").write_text("[section]\nkey = value\n")
    monkeypatch.setattr(check_formatting, "_fmt_stdout", lambda cmd, cwd: (1, ""))

    ok = check_formatting.check_formatting(root, quiet=True, diff=True)

    assert ok is False
    out = capsys.readouterr().out
    assert "ERROR: prettier exited 1" in out


def test_check_ini_quiet_suppresses_command_announcement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A representative single checker: its own "▶ command" and "(no files found)" chrome
    must be suppressed under quiet=True, without needing every checker tested individually
    (the suppression mechanism — a shared _make_log helper — is identical across all of them)."""
    root = tmp_path

    ok = check_formatting._check_ini(root, quiet=True)

    assert ok is True
    out = capsys.readouterr().out
    assert out == ""


def test_check_ini_default_still_shows_command_announcement(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Confirm quiet=False (the default) is unchanged — chrome still prints normally."""
    root = tmp_path

    ok = check_formatting._check_ini(root)

    assert ok is True
    out = capsys.readouterr().out
    assert "no INI files found" in out
