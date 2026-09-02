# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for check_formatting's shell checker — check_formatting project
"""Tests for check_formatting's shell (shellcheck) checker.

This checker supports projects with shell scripts, including extensionless
scripts selected through configured globs. It is exercised entirely via
mocked tool invocation here (matching the
mocking pattern already used for mypy/clang-tidy/cmake) — never registered
in this project's `.check_formatting.toml` `checks` list (this project has no
shell scripts), only in `_CHECKERS` so `--checks shell` works when
explicitly requested.

shellcheck is lint-only (no formatter, no ``--fix``/``--diff`` mode) —
`_check_shell` mirrors `_check_mypy`'s shape for that reason (fix/diff modes
both just run the same lint), combined with `_check_ini`'s glob-based file
selection (`[shell].globs` in `.check_formatting.toml`, a plain string-list
section like `cpp`/`web`/`ini` — no new config shape needed here).
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from check_formatting import cli as check_formatting

if TYPE_CHECKING:
    from pathlib import Path


def test_check_shell_finds_files_via_globs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    (root / "scripts").mkdir()
    (root / "scripts" / "build.sh").write_text("#!/bin/sh\necho hi\n")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/shellcheck")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_shell(root, globs=["scripts/*.sh"])

    assert ok is True
    assert str(root / "scripts" / "build.sh") in captured["cmd"]


def test_check_shell_tool_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    (root / "build.sh").write_text("#!/bin/sh\necho hi\n")

    monkeypatch.setattr(shutil, "which", lambda name: None)

    ok = check_formatting._check_shell(root, globs=["*.sh"])

    assert ok is False


def test_check_shell_no_globs_configured_passes_without_requiring_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project with no `[shell]` section (globs=()) has nothing to lint —
    this must vacuously pass, not fail because shellcheck happens to be missing."""
    root = tmp_path
    monkeypatch.setattr(shutil, "which", lambda name: None)

    ok = check_formatting._check_shell(root, globs=[])

    assert ok is True


def test_check_shell_fix_mode_runs_lint_not_a_fix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """shellcheck has no fix mode — --fix must still run the same lint, not silently no-op."""
    root = tmp_path
    (root / "build.sh").write_text("#!/bin/sh\necho hi\n")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/shellcheck")
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 1)

    ok = check_formatting._check_shell(root, globs=["*.sh"], fix=True)

    assert ok is False


def test_check_shell_quiet_suppresses_chrome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/shellcheck")

    ok = check_formatting._check_shell(root, globs=[], quiet=True)

    assert ok is True
    out = capsys.readouterr().out
    assert out == ""


def test_check_shell_no_sh_in_explicit_selection_skips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/shellcheck")

    ok = check_formatting._check_shell(root, explicit_files=[root / "foo.py"], globs=["*.sh"])

    assert ok is True


def test_check_shell_explicit_selection_uses_configured_glob_for_extensionless_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "scripts" / "build"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\necho hi\n")
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/shellcheck")

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_shell(root=tmp_path, explicit_files=[script], globs=["scripts/*"])

    assert ok is True
    assert captured["cmd"] == ["/usr/bin/shellcheck", str(script)]


def test_check_shell_deduplicates_files_selected_by_overlapping_globs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One physical script must produce one ShellCheck input and one set of diagnostics."""
    script = tmp_path / "scripts" / "build.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\necho hi\n")
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/shellcheck")

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_shell(root=tmp_path, globs=["scripts/*.sh", "scripts/**/*.sh"])

    assert ok is True
    assert captured["cmd"] == ["/usr/bin/shellcheck", str(script)]


def test_check_shell_verbose_reports_real_tool_information(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verbose mode must identify ShellCheck before running the ordinary lint pass."""
    script = tmp_path / "build.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    tool_info_calls: list[tuple[str, Path]] = []

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/shellcheck")
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 0)
    monkeypatch.setattr(
        check_formatting,
        "_print_tool_info",
        lambda tool, cwd: tool_info_calls.append((tool, cwd)),
    )

    ok = check_formatting._check_shell(root=tmp_path, globs=["*.sh"], verbose=True)

    assert ok is True
    assert tool_info_calls == [("/usr/bin/shellcheck", tmp_path)]


_VALID_SHELL_TOML = 'checks = ["shell"]\n\n[shell]\nglobs = ["scripts/*.sh"]\n'


def test_shell_globs_loaded_from_config(tmp_path: Path) -> None:
    (tmp_path / ".check_formatting.toml").write_text(_VALID_SHELL_TOML)
    config = check_formatting._load_project_config(tmp_path)
    assert config.shell_globs == ["scripts/*.sh"]


def test_shell_globs_wrong_type_is_hard_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad_toml = 'checks = []\n\n[shell]\nglobs = "scripts/*.sh"\n'
    (tmp_path / ".check_formatting.toml").write_text(bad_toml)
    with pytest.raises(SystemExit) as exc_info:
        check_formatting._load_project_config(tmp_path)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "shell" in out
