# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for check_formatting's cpp git-scoped fix contract — check_formatting project
"""Tests for the ``cpp`` checker's optional "git-scoped fix" contract.

clang-format is the one non-rst backend with a native line-range mechanism
(``-lines=<start>:<end>``) that could restrict a ``--fix`` to just the lines
that actually changed, mirroring check_rst's own bare-mode hunk scoping (see
``tests/test_check_formatting_rst_scope.py`` and check_rst's guide, "History
protection: bare mode and selective Git scope").  This is documented as an
explicit, OPTIONAL per-checker contract — most other checkers' backends have
no equivalent native mechanism at all (meson format, ruff format, mypy) or
one of unconfirmed reliability outside its primary use case (prettier's
``--range-start``/``--range-end``) — see development-workflow.rst's "Scope
guarantee" table for the full per-checker breakdown.

check and fix (and diff, which previews what fix would do) are scoped
together when ``git_auto_detected`` is True, to avoid a mismatch where
``--fix`` only touches a hunk but ``--check`` still fails forever on
unrelated pre-existing violations elsewhere in the same file — the same
principle rst's own bare mode already applies internally.  Explicit
FILE arguments and ``--all`` keep today's whole-file behavior unchanged,
since those are deliberate, explicit requests (same rst precedent).

``_git_diff_hunk_ranges`` is tested against a real ``tmp_path`` git
repository (not mocked) — git's own diff output format is exactly what is
under test, mirroring ``test_check_formatting_scope.py``'s convention for
``_detect_changed_files``.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from check_formatting import cli as check_formatting


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git("init", "-q", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)


# ---------------------------------------------------------------------------
# _git_diff_hunk_ranges — real git repo, no mocking
# ---------------------------------------------------------------------------


def test_git_diff_hunk_ranges_single_line_change(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    f = tmp_path / "a.cpp"
    f.write_text("line1\nline2\nline3\nline4\nline5\n")
    _git("add", "a.cpp", cwd=tmp_path)
    _git("commit", "-q", "-m", "initial", cwd=tmp_path)

    f.write_text("line1\nline2\nCHANGED\nline4\nline5\n")

    ranges = check_formatting._git_diff_hunk_ranges(tmp_path, f)

    assert ranges == [(3, 3)]


def test_git_diff_hunk_ranges_multiple_hunks(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    f = tmp_path / "a.cpp"
    f.write_text("\n".join(f"line{i}" for i in range(1, 11)) + "\n")
    _git("add", "a.cpp", cwd=tmp_path)
    _git("commit", "-q", "-m", "initial", cwd=tmp_path)

    lines = [f"line{i}" for i in range(1, 11)]
    lines[1] = "CHANGED_TOP"
    lines[8] = "CHANGED_BOTTOM"
    f.write_text("\n".join(lines) + "\n")

    ranges = check_formatting._git_diff_hunk_ranges(tmp_path, f)

    assert ranges == [(2, 2), (9, 9)]


def test_git_diff_hunk_ranges_appended_lines(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    f = tmp_path / "a.cpp"
    f.write_text("line1\nline2\n")
    _git("add", "a.cpp", cwd=tmp_path)
    _git("commit", "-q", "-m", "initial", cwd=tmp_path)

    f.write_text("line1\nline2\nline3\nline4\n")

    ranges = check_formatting._git_diff_hunk_ranges(tmp_path, f)

    assert ranges == [(3, 4)]


def test_git_diff_hunk_ranges_untracked_file_returns_none(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "baseline.cpp").write_text("x\n")
    _git("add", "baseline.cpp", cwd=tmp_path)
    _git("commit", "-q", "-m", "initial", cwd=tmp_path)

    new_file = tmp_path / "new_file.cpp"
    new_file.write_text("brand new content\n")

    ranges = check_formatting._git_diff_hunk_ranges(tmp_path, new_file)

    assert ranges is None


def test_git_diff_hunk_ranges_pure_deletion_returns_none(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    f = tmp_path / "a.cpp"
    f.write_text("line1\nline2\nline3\n")
    _git("add", "a.cpp", cwd=tmp_path)
    _git("commit", "-q", "-m", "initial", cwd=tmp_path)

    f.write_text("line1\nline3\n")

    ranges = check_formatting._git_diff_hunk_ranges(tmp_path, f)

    assert ranges is None


# ---------------------------------------------------------------------------
# _parse_git_diff_hunks_by_relpath — pure parsing, literal diff text, no subprocess
# ---------------------------------------------------------------------------


def test_parse_git_diff_hunks_by_relpath_multiple_files() -> None:
    diff_output = (
        "diff --git a/one.txt b/one.txt\n"
        "index 111..222 100644\n"
        "--- a/one.txt\n"
        "+++ b/one.txt\n"
        "@@ -2 +2 @@ a\n"
        "-b\n"
        "+B\n"
        "diff --git a/two.txt b/two.txt\n"
        "index 333..444 100644\n"
        "--- a/two.txt\n"
        "+++ b/two.txt\n"
        "@@ -3 +3,2 @@ y\n"
        "-z\n"
        "+Z\n"
        "+w\n"
    )

    ranges = check_formatting._parse_git_diff_hunks_by_relpath(diff_output)

    assert ranges == {"one.txt": [(2, 2)], "two.txt": [(3, 4)]}


def test_parse_git_diff_hunks_by_relpath_pure_deletion_hunk_omitted() -> None:
    """A hunk whose new-file line count is zero contributes no range — same
    rule _git_diff_hunk_ranges's own single-file parser already applies."""
    diff_output = "diff --git a/one.txt b/one.txt\n--- a/one.txt\n+++ b/one.txt\n@@ -2 +1,0 @@ a\n-b\n"

    ranges = check_formatting._parse_git_diff_hunks_by_relpath(diff_output)

    assert ranges == {}


def test_parse_git_diff_hunks_by_relpath_whole_file_deletion_omitted() -> None:
    """A file deleted entirely reports "+++ /dev/null" — no new-file side to
    derive ranges for at all, regardless of what its hunks look like."""
    diff_output = "diff --git a/gone.txt b/gone.txt\n--- a/gone.txt\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-x\n-y\n"

    ranges = check_formatting._parse_git_diff_hunks_by_relpath(diff_output)

    assert ranges == {}


# ---------------------------------------------------------------------------
# _batched_git_diff_hunk_ranges — real git repo, no mocking
# ---------------------------------------------------------------------------


def test_batched_git_diff_hunk_ranges_two_files_disjoint_hunks(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    f1 = tmp_path / "a.cpp"
    f1.write_text("line1\nline2\nline3\n")
    f2 = tmp_path / "b.cpp"
    f2.write_text("x\ny\nz\n")
    _git("add", "a.cpp", "b.cpp", cwd=tmp_path)
    _git("commit", "-q", "-m", "initial", cwd=tmp_path)

    f1.write_text("line1\nCHANGED\nline3\n")
    f2.write_text("x\ny\nz\nw\n")

    ranges = check_formatting._batched_git_diff_hunk_ranges(tmp_path, [f1, f2])

    assert ranges == {f1: [(2, 2)], f2: [(4, 4)]}


def test_batched_git_diff_hunk_ranges_empty_file_list_spawns_no_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty `--` pathspec means "no restriction" to git, not "nothing" —
    the empty case must be handled before any subprocess is spawned at all."""

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not spawn git for an empty file list")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    ranges = check_formatting._batched_git_diff_hunk_ranges(tmp_path, [])

    assert ranges == {}


def test_batched_git_diff_hunk_ranges_git_failure_returns_none_for_every_file(tmp_path: Path) -> None:
    """A non-git directory (or any git failure) degrades to whole-file scope
    for every file — same fallback contract as the single-file function."""
    f1 = tmp_path / "a.cpp"
    f1.write_text("x\n")
    f2 = tmp_path / "b.cpp"
    f2.write_text("y\n")

    ranges = check_formatting._batched_git_diff_hunk_ranges(tmp_path, [f1, f2])

    assert ranges == {f1: None, f2: None}


def test_batched_git_diff_hunk_ranges_untracked_file_among_tracked(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    tracked = tmp_path / "a.cpp"
    tracked.write_text("line1\nline2\n")
    _git("add", "a.cpp", cwd=tmp_path)
    _git("commit", "-q", "-m", "initial", cwd=tmp_path)
    tracked.write_text("line1\nCHANGED\n")

    untracked = tmp_path / "new_file.cpp"
    untracked.write_text("brand new content\n")

    ranges = check_formatting._batched_git_diff_hunk_ranges(tmp_path, [tracked, untracked])

    assert ranges == {tracked: [(2, 2)], untracked: None}


# ---------------------------------------------------------------------------
# _check_cpp — git-scoped fix contract (mocked _run/_fmt_stdout/_git_diff_hunk_ranges)
# ---------------------------------------------------------------------------


def test_check_cpp_fix_auto_detected_uses_per_file_lines_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    f = root / "a.cpp"
    f.write_text("int main() { return 0; }\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)
    monkeypatch.setattr(check_formatting, "_git_diff_hunk_ranges", lambda root, file: [(5, 5)])

    ok = check_formatting._check_cpp(root, fix=True, explicit_files=[f], git_auto_detected=True)

    assert ok is True
    assert captured["cmd"] == ["clang-format", "-i", "-lines=5:5", str(f)]


def test_check_cpp_fix_auto_detected_no_ranges_falls_back_to_whole_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An untracked file (no derivable hunk ranges) still gets a whole-file fix —
    exactly today's behavior — rather than being skipped or erroring."""
    root = tmp_path
    f = root / "a.cpp"
    f.write_text("int main() { return 0; }\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)
    monkeypatch.setattr(check_formatting, "_git_diff_hunk_ranges", lambda root, file: None)

    ok = check_formatting._check_cpp(root, fix=True, explicit_files=[f], git_auto_detected=True)

    assert ok is True
    assert captured["cmd"] == ["clang-format", "-i", str(f)]


def test_check_cpp_fix_not_auto_detected_stays_whole_file_batched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without git_auto_detected (explicit FILE args, or --all), today's single
    batched whole-file invocation is unchanged — a deliberate request stays whole-file."""
    root = tmp_path
    f1 = root / "a.cpp"
    f1.write_text("int main() { return 0; }\n")
    f2 = root / "b.cpp"
    f2.write_text("int foo() { return 1; }\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    def fail_if_called(root: Path, file: Path) -> None:
        raise AssertionError("hunk ranges must not be computed when git_auto_detected is False")

    monkeypatch.setattr(check_formatting, "_git_diff_hunk_ranges", fail_if_called)

    ok = check_formatting._check_cpp(root, fix=True, explicit_files=[f1, f2])

    assert ok is True
    assert captured["cmd"] == ["clang-format", "-i", str(f1), str(f2)]


def test_check_cpp_check_mode_auto_detected_uses_lines_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Check mode must scope to the same hunks as fix would, so a routine check
    doesn't fail forever on pre-existing, unrelated violations elsewhere in a
    touched file after --fix only cleaned up the diff."""
    root = tmp_path
    f = root / "a.cpp"
    f.write_text("int main() { return 0; }\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)
    monkeypatch.setattr(check_formatting, "_git_diff_hunk_ranges", lambda root, file: [(5, 5)])

    ok = check_formatting._check_cpp(root, explicit_files=[f], git_auto_detected=True)

    assert ok is True
    assert captured["cmd"] == ["clang-format", "-lines=5:5", "--dry-run", "--Werror", str(f)]


def test_check_cpp_diff_mode_auto_detected_uses_lines_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    f = root / "a.cpp"
    f.write_text("int main(){return 0;}\n")

    captured_cmds: list[list[str]] = []

    def fake_fmt_stdout(cmd: list[str], cwd: Path) -> tuple[int, str]:
        captured_cmds.append(cmd)
        return 0, f.read_text()

    monkeypatch.setattr(check_formatting, "_fmt_stdout", fake_fmt_stdout)
    monkeypatch.setattr(check_formatting, "_git_diff_hunk_ranges", lambda root, file: [(5, 5)])

    ok = check_formatting._check_cpp(root, diff=True, explicit_files=[f], git_auto_detected=True)

    assert ok is True
    assert captured_cmds == [["clang-format", "-lines=5:5", str(f)]]


def test_check_cpp_auto_detected_scope_uses_configured_globs_not_hardcoded_suffixes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    header = tmp_path / "api.h"
    header.write_text("int answer();\n")
    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)
    monkeypatch.setattr(check_formatting, "_git_diff_hunk_ranges", lambda root, file: None)

    ok = check_formatting._check_cpp(
        tmp_path,
        explicit_files=[header],
        globs=["**/*.h"],
        git_auto_detected=True,
    )

    assert ok is True
    assert captured["cmd"] == ["clang-format", "--dry-run", "--Werror", str(header)]
