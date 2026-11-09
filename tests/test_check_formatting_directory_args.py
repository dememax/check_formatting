# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for directory FILE arguments passing vacuously — check_formatting project
"""Regression tests for a false pass on a directory FILE argument.

``check_formatting docs`` intersected the directory path itself with each
checker's file targets.  A directory matches no file target, so every checker
reported "no files in selection", passed, and the run exited 0 without checking
anything.  A directory whose name happens to end in a checker's suffix
(``notes.rst/``) instead reached the backend as if it were a file.

check_formatting has no recursive FILE mode: ``--all`` is the full scan.  A
directory FILE argument is therefore a usage error, reported before any checker
runs, in the same spirit as check_rst 0.7.5 rejecting a directory operand that
lacks ``--recursive``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from check_formatting import cli as check_formatting

if TYPE_CHECKING:
    from pathlib import Path


def _project(tmp_path: Path) -> Path:
    (tmp_path / ".check_formatting.toml").write_text('checks = ["rst"]\n', encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.rst").write_text("Title\n=====\n\nText.\n", encoding="utf-8")
    (tmp_path / "notes.rst").mkdir()
    return tmp_path


@pytest.mark.parametrize("directory", ["docs", "notes.rst", "docs/"])
def test_main_rejects_a_directory_file_argument(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    directory: str,
) -> None:
    """A directory FILE argument must be a usage error, never a vacuous pass."""
    monkeypatch.chdir(_project(tmp_path))
    monkeypatch.setattr("sys.argv", ["check_formatting", directory])

    with pytest.raises(SystemExit) as exc_info:
        check_formatting.main()

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "is a directory" in stderr
    assert "--all" in stderr


def test_main_rejects_a_directory_among_regular_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """One directory in the FILE list rejects the whole invocation before any checker runs."""
    monkeypatch.chdir(_project(tmp_path))
    monkeypatch.setattr("sys.argv", ["check_formatting", "docs/index.rst", "docs"])

    with pytest.raises(SystemExit) as exc_info:
        check_formatting.main()

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "'docs' is a directory" in captured.err
    assert "check_rst" not in captured.out
