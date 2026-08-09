# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for _check_kconfig's concurrent per-combo builds — check_formatting project
"""Tests for _check_kconfig running each configured build combo's
`west build` concurrently in non-verbose mode.

Verbose mode stays sequential and unchanged — its own docstring frames it
as "the human reading the stream sees it directly" real-time feedback via
live-streaming `_run`, which parallelizing would defeat by interleaving
multiple combos' live output. Non-verbose mode already captures merged
output via `_run_capture_merged` rather than streaming it, so there is no
interleaving risk there: banners and warning lines are only ever printed
in the main thread, in `build_combos`' original order, after each future
resolves.

`west build`'s `-d`/`--build-dir` flag already works today via a combo's
own `args` list — no schema change. Parallelizing combos that don't supply
distinct build directories will race; this is now documented on
`_check_kconfig` and the project's own docs, matching this ecosystem's
existing "declare, don't guess" convention (the config, not the checker,
owns build-directory isolation).

The concurrency test below uses a `threading.Barrier(N)`, the same
deterministic technique used for _check_python's concurrent ruff calls: a
fake `_run_capture_merged` that blocks until all N combos have reached the
barrier. A sequential implementation deadlocks here (only one combo would
ever be in flight at a time) rather than completing quickly.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from typing import TYPE_CHECKING

from check_formatting import cli as check_formatting

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_check_kconfig_runs_combos_concurrently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/west")
    barrier = threading.Barrier(3, timeout=5)

    def fake_run_capture_merged(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        barrier.wait()
        return subprocess.CompletedProcess(cmd, 0, stdout="")

    monkeypatch.setattr(check_formatting, "_run_capture_merged", fake_run_capture_merged)

    combos: list[dict[str, object]] = [
        {"label": "main/board_a", "args": []},
        {"label": "main/board_b", "args": []},
        {"label": "main/board_c", "args": []},
    ]

    ok = check_formatting._check_kconfig(tmp_path, build_combos=combos)

    assert ok is True


def test_check_kconfig_two_combos_aggregate_one_warning_one_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No existing test exercised the multi-combo execution/aggregation path
    at all (every prior test used 0-1 combos) — pin it directly: one combo
    with a warning must fail the overall result, and both combos' labels
    must appear in the output regardless of concurrent execution order."""
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/west")

    def fake_run_capture_merged(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if "board_a" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="warning: FOO was assigned 'y' but got 'n'.\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="Kconfig header saved\n")

    monkeypatch.setattr(check_formatting, "_run_capture_merged", fake_run_capture_merged)

    combos: list[dict[str, object]] = [
        {"label": "main/board_a", "args": ["-d", "build/board_a", "-b", "board_a"]},
        {"label": "main/board_b", "args": ["-d", "build/board_b", "-b", "board_b"]},
    ]

    ok = check_formatting._check_kconfig(tmp_path, build_combos=combos)

    assert ok is False
    out = capsys.readouterr().out
    assert "main/board_a" in out
    assert "main/board_b" in out


def test_check_kconfig_verbose_mode_stays_sequential_via_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: verbose mode must keep streaming each combo's build live
    via _run, one at a time — parallelizing it would interleave multiple
    combos' live output, defeating the whole point of verbose mode."""
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/west")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: Path) -> int:
        calls.append(cmd)
        return 0

    def fail_if_called(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        raise AssertionError("verbose mode must not use _run_capture_merged")

    monkeypatch.setattr(check_formatting, "_run", fake_run)
    monkeypatch.setattr(check_formatting, "_run_capture_merged", fail_if_called)

    combos: list[dict[str, object]] = [
        {"label": "main/board_a", "args": []},
        {"label": "main/board_b", "args": []},
    ]

    ok = check_formatting._check_kconfig(tmp_path, verbose=True, build_combos=combos)

    assert ok is True
    assert len(calls) == 2
