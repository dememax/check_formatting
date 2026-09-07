# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for _check_python's concurrent read-only modes — check_formatting project
"""Tests for _check_python running `ruff format` and `ruff check` concurrently
in its read-only modes (check/diff/verbose).

Fix mode's ordering (`ruff format` then `ruff check --fix`) is a genuine
data dependency — `--fix` must lint already-reformatted content — so it
stays sequential via `_run` (live-streaming), unchanged. The read-only
modes have no such dependency and now run both commands concurrently via
`_run_capture_merged` (capture-based, not `_run`'s live-streaming, which
would interleave two subprocesses' output if run at the same time),
printing each captured result in the same order as before once both
complete.

The concurrency test below uses a `threading.Barrier(2)`: a fake
`_run_capture_merged` that blocks until BOTH calls have reached the
barrier. A sequential implementation would deadlock here — only one caller
would ever be in flight at a time — so this fails (via the barrier's
timeout) against a sequential implementation and passes quickly against a
genuinely concurrent one. This is a deterministic way to pin actual
parallelism, not just "both commands were called".
"""

from __future__ import annotations

import subprocess
import threading
from typing import TYPE_CHECKING

from check_formatting import cli as check_formatting

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_check_python_check_mode_runs_format_and_check_concurrently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    barrier = threading.Barrier(2, timeout=5)

    def fake_run_capture_merged(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        barrier.wait()
        return subprocess.CompletedProcess(cmd, 0, stdout="")

    monkeypatch.setattr(check_formatting, "_run_capture_merged", fake_run_capture_merged)

    ok = check_formatting._check_python(tmp_path, dirs=["src"])

    assert ok is True


def test_check_python_diff_mode_runs_format_and_check_concurrently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    barrier = threading.Barrier(2, timeout=5)

    def fake_run_capture_merged(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        barrier.wait()
        return subprocess.CompletedProcess(cmd, 0, stdout="")

    monkeypatch.setattr(check_formatting, "_run_capture_merged", fake_run_capture_merged)

    ok = check_formatting._check_python(tmp_path, diff=True, dirs=["src"])

    assert ok is True


def test_check_python_verbose_mode_runs_format_and_check_concurrently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    barrier = threading.Barrier(2, timeout=5)

    def fake_run_capture_merged(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        barrier.wait()
        return subprocess.CompletedProcess(cmd, 0, stdout="")

    monkeypatch.setattr(check_formatting, "_run_capture_merged", fake_run_capture_merged)
    monkeypatch.setattr(check_formatting, "_print_tool_info", lambda *a, **kw: None)

    ok = check_formatting._check_python(tmp_path, verbose=True, dirs=["src"])

    assert ok is True


def test_check_python_check_mode_prints_format_then_check_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Even though both commands run concurrently, the printed output must
    stay in the same (format, then check) order as the sequential version —
    the "check" result finishing first must not make its output appear
    before "format"'s."""

    def fake_run_capture_merged(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if "format" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="FORMAT_OUTPUT\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="CHECK_OUTPUT\n")

    monkeypatch.setattr(check_formatting, "_run_capture_merged", fake_run_capture_merged)

    ok = check_formatting._check_python(tmp_path, dirs=["src"])

    assert ok is True
    out = capsys.readouterr().out
    assert out.index("FORMAT_OUTPUT") < out.index("CHECK_OUTPUT")


def test_check_python_missing_ruff_fails_cleanly_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An optional backend missing from PATH is a normal failed check, not
    an internal error that escapes from either concurrent future."""

    def missing_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "No such file or directory", "ruff")

    monkeypatch.setattr(check_formatting, "_backend_version_error", lambda command, cwd: None)
    monkeypatch.setattr(subprocess, "run", missing_run)

    ok = check_formatting._check_python(tmp_path, dirs=["src"])

    assert ok is False
    assert capsys.readouterr().out.count("ERROR: command not found: 'ruff'") == 2


def test_check_python_fix_mode_stays_sequential_via_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: fix mode must keep using _run (sequential, live-streamed),
    never _run_capture_merged — `ruff check --fix` must only ever see
    already-reformatted content."""
    captured: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured.append(cmd)
        return 0

    def fail_if_called(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        raise AssertionError("fix mode must not use _run_capture_merged")

    monkeypatch.setattr(check_formatting, "_run", fake_run)
    monkeypatch.setattr(check_formatting, "_run_capture_merged", fail_if_called)

    ok = check_formatting._check_python(tmp_path, fix=True, dirs=["src"])

    assert ok is True
    assert captured == [["ruff", "format", "src"], ["ruff", "check", "--fix", "src"]]
