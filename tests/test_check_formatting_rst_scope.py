# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for check_formatting's rst-checker git-scope semantics — check_formatting project
"""Tests for the rst checker's file-selection/scope mapping against check_rst's
documented bare, explicit-file, and recursive modes.

check_rst distinguishes bare invocation (git-diff-scoped: adornment fixes apply only to
changed hunks) from an invocation given explicit filenames (whole-file adornment scope
— "use only when the user explicitly confirms that file should be normalized"). Before
this fix, `_check_rst` collapsed that distinction: `check_formatting`'s own default
scope (auto-detected git-changed files) was always handed to check_rst as explicit
arguments — silently upgrading every routine `--fix` to whole-file scope — while
`explicit_files=None` (used by both `--all` and direct release-gate library
calls) always ran check_rst bare, which is git-diff-scoped and therefore checks nothing
on a clean release tree, contradicting `--all`'s "regardless of git state" contract.

These tests pin the corrected behavior: auto-detected files run check_rst bare (to
preserve hunk-scoping), mutation-only modes use check_rst's matching fast paths,
`explicit_files=None` with a configured `[rst].dir` runs
`check_rst check --recursive <dir>` (a genuine full scan), and genuinely user-typed explicit
files keep today's whole-file behavior.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from check_formatting import cli as check_formatting


def test_check_rst_auto_detected_files_run_bare_not_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Files that came from check_formatting's own git auto-detection must be handed
    to check_rst bare (no file args) — passing them as explicit arguments instead would
    silently upgrade check_rst's fix from hunk-scoped to whole-file scoped."""
    root = tmp_path
    rst_file = root / "guide.rst"
    rst_file.write_text("Guide\n=====\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/check_rst")

    ok = check_formatting._check_rst(root, fix=True, explicit_files=[rst_file], git_auto_detected=True)

    assert ok is True
    assert captured["cmd"] == ["/usr/bin/check_rst", "fix", "--fast"]


def test_check_rst_diff_uses_preview_only_backend_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """check_formatting --diff promises only a mechanical preview, so it must
    not select check_rst's ordinary --diff mode, which additionally runs lint,
    docutils, and Sphinx validation phases."""
    rst_file = tmp_path / "guide.rst"
    rst_file.write_text("Guide\n=====\n")
    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/check_rst")

    ok = check_formatting._check_rst(tmp_path, diff=True, explicit_files=[rst_file])

    assert ok is True
    assert captured["cmd"] == ["/usr/bin/check_rst", "diff", "--fast", str(rst_file)]


def test_check_rst_user_typed_explicit_files_stay_whole_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without git_auto_detected (the default), explicit files are still passed to
    check_rst directly — today's behavior, correct when the user genuinely named the
    file(s) themselves."""
    root = tmp_path
    rst_file = root / "guide.rst"
    rst_file.write_text("Guide\n=====\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/check_rst")

    ok = check_formatting._check_rst(root, fix=True, explicit_files=[rst_file])

    assert ok is True
    assert captured["cmd"] == ["/usr/bin/check_rst", "fix", str(rst_file)]


def test_check_rst_full_scan_uses_recursive_configured_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """explicit_files=None (--all, or a direct library call like release.py's) must run
    check_rst check --recursive <configured dir> for a genuine full-repo scan — not bare mode,
    which is git-diff-scoped and would check nothing on a clean release tree."""
    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/check_rst")

    ok = check_formatting._check_rst(tmp_path, explicit_files=None, recursive_dir="docs")

    assert ok is True
    assert captured["cmd"] == ["/usr/bin/check_rst", "check", "--recursive", "docs"]


def test_check_rst_full_scan_ignores_stray_git_auto_detected_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """git_auto_detected=True must not, by itself, select the unvalidated `fix --fast`
    mutation-only path for a full scan (explicit_files=None) — that combination isn't
    reachable from the CLI (_is_git_auto_detected_scope ties the two together), but a
    direct library caller could still pass it, and a full-repo scan must always get the
    fully-validated `fix`, never a silently weaker mutation-only pass."""
    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/check_rst")

    ok = check_formatting._check_rst(
        tmp_path, fix=True, explicit_files=None, recursive_dir="docs", git_auto_detected=True
    )

    assert ok is True
    assert captured["cmd"] == ["/usr/bin/check_rst", "fix", "--recursive", "docs"]


def test_check_rst_full_scan_without_configured_dir_fails_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A requested full scan must not silently collapse to check_rst's bare,
    Git-changed scope when [rst].dir is absent."""

    def fake_run(cmd: list[str], cwd: Path) -> int:
        raise AssertionError("invalid full-scan configuration must stop before check_rst")

    monkeypatch.setattr(check_formatting, "_run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/check_rst")

    with pytest.raises(SystemExit) as exc_info:
        check_formatting._check_rst(tmp_path, explicit_files=None)

    assert exc_info.value.code == 1
    assert "[rst].dir is required" in capsys.readouterr().out


def test_check_rst_selected_file_fails_when_backend_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rst_file = tmp_path / "guide.rst"
    rst_file.write_text("Guide\n=====\n")
    monkeypatch.setattr(shutil, "which", lambda name: None)

    ok = check_formatting._check_rst(tmp_path, explicit_files=[rst_file])

    assert ok is False
    assert "ERROR: check_rst not found" in capsys.readouterr().out


def test_is_git_auto_detected_scope_true_for_default_invocation(tmp_path: Path) -> None:
    """No FILE args and no --all is exactly check_formatting's own git-auto-detect
    default scope."""
    assert check_formatting._is_git_auto_detected_scope([], False) is True


def test_is_git_auto_detected_scope_false_for_all_flag() -> None:
    assert check_formatting._is_git_auto_detected_scope([], True) is False


def test_is_git_auto_detected_scope_false_for_explicit_file_args() -> None:
    assert check_formatting._is_git_auto_detected_scope(["foo.rst"], False) is False


def test_rst_fix_hint_matches_effective_scope(tmp_path: Path) -> None:
    """The command printed after an RST failure must not reintroduce ordinary
    --fix into the routine Git-scoped workflow."""
    (tmp_path / ".check_formatting.toml").write_text('checks = ["rst"]\n')
    config = check_formatting._load_project_config(tmp_path)

    assert check_formatting._fix_command("rst", config, git_auto_detected=True) == "check_rst fix --fast"
    assert check_formatting._fix_command("rst", config, git_auto_detected=False) == "check_rst fix"


def test_check_formatting_full_scan_hint_ignores_stray_git_auto_detected_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Same misuse as _check_rst's own full-scan test, at the report layer: a
    full-repo scan (explicit_files=None) that also carries a stray
    git_auto_detected=True must still print the fully-validated `check_rst fix`
    remediation hint, not the unvalidated `--fast` one — printing `--fast` here
    would tell a release-gate caller to re-run a mutation-only pass instead of
    the full validation the failure actually needs."""
    (tmp_path / ".check_formatting.toml").write_text('checks = ["rst"]\n\n[rst]\ndir = "docs"\n')
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 1)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/check_rst")

    ok = check_formatting.check_formatting(tmp_path, explicit_files=None, git_auto_detected=True)

    assert ok is False
    out = capsys.readouterr().out
    assert "check_rst fix --fast" not in out
    assert "check_rst fix" in out
