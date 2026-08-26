# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for check_formatting's cmake and kconfig checkers — check_formatting project
"""Tests for check_formatting's cmake and kconfig checkers.

Both are checker categories required by CMake/west consuming projects, where
Kconfig/prj.conf validation complements the formatter-oriented checker set.

This project has no CMakeLists.txt/Kconfig files or `west` workspace, so these
checkers are exercised entirely via mocked tool invocation here
(matching the same mocking pattern already used for mypy/clang-tidy/meson)
— absent from this project's `.check_formatting.toml` `checks` list, but
registered in `_CHECKERS` so `--checks cmake`/`--checks kconfig` work when
explicitly requested. There is no separate "OPTIONAL_CHECKS" concept: any
checker registered in `_CHECKERS` but absent from a project's own `checks`
list is implicitly opt-in for that project — "optional" is project-relative
(a CMake/west project can include `cmake`/`kconfig` in its default checks),
not a fixed Python-level list.

`_check_cmake` mirrors `_check_cpp`'s exact shape (cmake-format supports
--check/--in-place/diff, same as clang-format). `_check_kconfig` is
generalizes project-specific board/source combinations by loading them from
`.check_formatting.toml`'s `[kconfig].build_combos` — a
config shape (a list of {label, args} tables) requiring a new validator
beyond the existing flat-string-list/string validators.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from check_formatting import cli as check_formatting

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# cmake checker
# ---------------------------------------------------------------------------


def test_check_cmake_finds_cmakelists_recursively(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    subdir = root / "sub"
    subdir.mkdir()
    (subdir / "CMakeLists.txt").write_text("project(x)\n")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/cmake-format")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_cmake(root)

    assert ok is True
    assert str(subdir / "CMakeLists.txt") in captured["cmd"]


def test_check_cmake_tool_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    (root / "CMakeLists.txt").write_text("project(x)\n")

    monkeypatch.setattr(shutil, "which", lambda name: None)

    ok = check_formatting._check_cmake(root)

    assert ok is False


def test_check_cmake_diff_mode_shows_diff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    cmake_file = root / "CMakeLists.txt"
    cmake_file.write_text("project(x)\n")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/cmake-format")
    monkeypatch.setattr(check_formatting, "_fmt_stdout", lambda cmd, cwd: (0, "project(x)\n"))

    ok = check_formatting._check_cmake(root, diff=True)

    assert ok is True


def test_check_cmake_quiet_suppresses_chrome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/cmake-format")

    ok = check_formatting._check_cmake(root, quiet=True)

    assert ok is True
    out = capsys.readouterr().out
    assert out == ""


# ---------------------------------------------------------------------------
# kconfig checker
# ---------------------------------------------------------------------------

_VALID_KCONFIG_TOML = """\
checks = ["kconfig"]

[kconfig]
build_combos = [
    { label = "main/board_a", args = [] },
    { label = "main/native_sim", args = ["-b", "native_sim/native/64"] },
]
"""


def test_kconfig_build_combos_loaded_from_config(tmp_path: Path) -> None:
    (tmp_path / ".check_formatting.toml").write_text(_VALID_KCONFIG_TOML)
    config = check_formatting._load_project_config(tmp_path)
    assert config.kconfig_build_combos == [
        {"label": "main/board_a", "args": []},
        {"label": "main/native_sim", "args": ["-b", "native_sim/native/64"]},
    ]


def test_kconfig_build_combos_missing_label_is_hard_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad_toml = "checks = []\n\n[kconfig]\nbuild_combos = [{ args = [] }]\n"
    (tmp_path / ".check_formatting.toml").write_text(bad_toml)
    with pytest.raises(SystemExit) as exc_info:
        check_formatting._load_project_config(tmp_path)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "kconfig" in out


def test_check_kconfig_passes_when_no_warnings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/west")

    class _FakeResult:
        returncode = 0
        stdout = "-- Cache files will be written to: /tmp/x\nKconfig header saved\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _FakeResult())

    combos: list[dict[str, object]] = [{"label": "main/board_a", "args": []}]
    ok = check_formatting._check_kconfig(root, build_combos=combos)

    assert ok is True


def test_check_kconfig_fails_on_warning_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/west")

    class _FakeResult:
        returncode = 0
        stdout = "warning: FOO was assigned the value 'y' but got the value 'n'.\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _FakeResult())

    combos: list[dict[str, object]] = [{"label": "main/board_a", "args": []}]
    ok = check_formatting._check_kconfig(root, build_combos=combos)

    assert ok is False


def test_check_kconfig_missing_west_binary_fails_cleanly_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`west` can vanish between the initial `shutil.which` probe and actual
    execution (TOCTOU). `_run_capture_merged` already turns that into a
    normal exit-127 result (see test_check_formatting_python_parallel.py's
    equivalent ruff case) rather than raising — this must surface as a
    normal failed check, not an internal traceback out of the worker future."""
    root = tmp_path
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/west")

    def missing_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "No such file or directory", "west")

    monkeypatch.setattr(subprocess, "run", missing_run)

    combos: list[dict[str, object]] = [{"label": "main/board_a", "args": []}]
    ok = check_formatting._check_kconfig(root, build_combos=combos)

    assert ok is False
    assert "ERROR: command not found: '/usr/bin/west'" in capsys.readouterr().out


def test_check_kconfig_tool_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    monkeypatch.setattr(shutil, "which", lambda name: None)

    ok = check_formatting._check_kconfig(root, build_combos=[{"label": "x", "args": []}])

    assert ok is False


def test_check_kconfig_empty_build_combos_passes_without_requiring_west(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project with no `[kconfig]` section (build_combos=()) has nothing to validate —
    this must vacuously pass, not fail because `west` happens to be missing from PATH."""
    root = tmp_path
    monkeypatch.setattr(shutil, "which", lambda name: None)

    ok = check_formatting._check_kconfig(root, build_combos=[])

    assert ok is True


def test_check_kconfig_no_conf_in_explicit_selection_skips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/west")

    ok = check_formatting._check_kconfig(
        root, explicit_files=[root / "foo.py"], build_combos=[{"label": "x", "args": []}]
    )

    assert ok is True
