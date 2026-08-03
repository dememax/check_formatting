# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for check_formatting's checker-internals bugs — check_formatting project
"""Tests for check_formatting checker internals.

These target four specific defects found during a technical review of the
script: a silent-failure path in the meson diff-mode checker, two checkers
that discard the excluded-file count in explicit-file mode, and the rst
checker's hand-rolled file filter bypassing the shared ``_select_explicit``
helper. Each test isolates the checker under test from the real formatter
binaries by monkeypatching ``_run``/``_fmt_stdout`` (or, for the meson
silent-failure case, the file-selection/temp-file plumbing only), so they
run hermetically without requiring meson/ruff/mypy/check_rst to actually be
invoked.
"""

from __future__ import annotations

import shutil
import tempfile
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from check_formatting import cli as check_formatting


def test_check_meson_diff_mode_reports_nonzero_meson_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A meson format failure (nonzero rc, not just 127) must fail the check, not pass silently."""
    root = tmp_path
    bad_file = root / "meson.build"
    bad_file.write_text("foo(\n")

    def fake_fmt_stdout(cmd: list[str], cwd: Path) -> tuple[int, str]:
        # Simulate meson format erroring out and leaving the temp file untouched —
        # exactly what a real syntax error produces (confirmed manually: rc=1).
        return 1, bad_file.read_text()

    monkeypatch.setattr(check_formatting, "_fmt_stdout", fake_fmt_stdout)

    ok = check_formatting._check_meson(root, diff=True, explicit_files=[bad_file])

    assert ok is False


def test_check_meson_diff_mode_temp_file_outside_project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The scratch copy used to compute the diff must not be created inside the project root."""
    root = tmp_path
    good_file = root / "meson.build"
    good_file.write_text("project('x')\n")

    captured_kwargs: dict[str, Any] = {}
    real_ntf = tempfile.NamedTemporaryFile

    def fake_ntf(**kwargs: Any) -> Any:  # noqa: ANN401
        captured_kwargs.update(kwargs)
        return real_ntf(**kwargs)

    monkeypatch.setattr(check_formatting, "_fmt_stdout", lambda cmd, cwd: (0, good_file.read_text()))
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", fake_ntf)

    check_formatting._check_meson(root, diff=True, explicit_files=[good_file])

    assert captured_kwargs.get("dir") != root


def test_check_python_explicit_mode_reports_excluded_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An ignored file among the explicit selection must show up in the printed file-count label."""
    root = tmp_path
    kept = root / "a.py"
    kept.write_text("x = 1\n")
    excluded = root / "b.py"
    excluded.write_text("y = 2\n")

    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 0)

    ok = check_formatting._check_python(
        root,
        ignore_patterns=["b.py"],
        explicit_files=[kept, excluded],
    )

    assert ok is True
    out = capsys.readouterr().out
    assert "1 excluded" in out


def test_check_mypy_explicit_mode_reports_excluded_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Same excluded-count bug as ruff, in the mypy checker's explicit-file path."""
    root = tmp_path
    kept = root / "a.py"
    kept.write_text("x = 1\n")
    excluded = root / "b.py"
    excluded.write_text("y = 2\n")

    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 0)

    ok = check_formatting._check_mypy(
        root,
        ignore_patterns=["b.py"],
        explicit_files=[kept, excluded],
    )

    assert ok is True
    out = capsys.readouterr().out
    assert "1 excluded" in out


def test_check_rst_sorts_explicit_files_like_other_checkers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """rst's file selection must go through _select_explicit, which sorts (like every other checker)."""
    root = tmp_path
    file_b = root / "b.rst"
    file_b.write_text("B\n=\n")
    file_a = root / "a.rst"
    file_a.write_text("A\n=\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/check_rst")

    ok = check_formatting._check_rst(root, explicit_files=[file_b, file_a])

    assert ok is True
    file_args = captured["cmd"][1:]
    assert file_args == [str(file_a), str(file_b)]
