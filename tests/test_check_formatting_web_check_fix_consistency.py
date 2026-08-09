# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for check_web's check/fix consistency under best-effort git scope — check_formatting project
"""Tests closing a gap in the ``web`` checker's best-effort git-scoped fix.

``_best_effort_prettier_fix`` can write a merge that deliberately retains an
out-of-scope, pre-existing violation (see
``tests/test_check_formatting_web_best_effort_fix.py``'s canonical-equivalence
tests).  Before this fix, ``_check_web``'s check/verbose/diff modes always
compared a file against the unconditional whole-file reformat, never against
what a git-scoped fix would actually produce — so immediately after a
successful ``--fix`` that retained legacy content, running ``--check`` on the
very same file reported a violation, contradicting the fix that had just
"succeeded".  Verified concretely against a real prettier invocation before
writing these tests: a file with one touched line and one separate,
untouched, pre-existing violation gets `fix ok: True` / `"git-scoped merge"`,
then `check ok: False` on the identical resulting file.

The fix: check/verbose/diff, when ``git_auto_detected``, compare each file
against the same target :func:`check_formatting._best_effort_prettier_target`
computes for fix — so a file already at its git-scoped-fixed state now passes
``--check``, even though it still differs from the unconditional whole-file
reformat.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from check_formatting import cli as check_formatting

_ORIGINAL = "one\ntwo\nthree\nfour\nfive\n"
# prettier would fix both changed line 2 and untouched legacy line 4.
_FORMATTED = "one\nTWO_FIXED\nthree\nFOUR_FIXED\nfive\n"
# the scoped candidate retains legacy line 4; canonicalizes to _FORMATTED.
_SCOPED_TARGET = "one\nTWO_FIXED\nthree\nfour\nfive\n"


def _mock_converging_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_fmt_stdout(cmd: list[str], cwd: Path, *, input_text: str | None = None) -> tuple[int, str]:
        calls.append(cmd)
        if len(calls) == 1:
            return 0, _FORMATTED
        return 0, _FORMATTED  # canonical validation: converges

    monkeypatch.setattr(check_formatting, "_fmt_stdout", fake_fmt_stdout)
    monkeypatch.setattr(
        check_formatting, "_batched_git_diff_hunk_ranges", lambda root, files: {f: [(2, 2)] for f in files}
    )


def _mock_diverging_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_fmt_stdout(cmd: list[str], cwd: Path, *, input_text: str | None = None) -> tuple[int, str]:
        calls.append(cmd)
        if len(calls) == 1:
            return 0, _FORMATTED
        return 0, "one\nTWO_FIXED\nthree\nSTILL_DIFFERENT\nfive\n"  # canonical validation: diverges

    monkeypatch.setattr(check_formatting, "_fmt_stdout", fake_fmt_stdout)
    monkeypatch.setattr(
        check_formatting, "_batched_git_diff_hunk_ranges", lambda root, files: {f: [(2, 2)] for f in files}
    )


# ---------------------------------------------------------------------------
# check mode
# ---------------------------------------------------------------------------


def test_check_web_check_auto_detected_passes_when_file_already_at_scoped_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "page.html"
    f.write_text(_SCOPED_TARGET)
    _mock_converging_merge(monkeypatch)

    ok = check_formatting._check_web(tmp_path, explicit_files=[f], git_auto_detected=True)

    assert ok is True


def test_check_web_check_auto_detected_fails_when_file_not_at_scoped_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "page.html"
    f.write_text(_ORIGINAL)
    _mock_converging_merge(monkeypatch)

    def fail_if_called(cmd: list[str], cwd: Path) -> int:
        raise AssertionError("git-scoped check must compare against the target, not shell out to native --check")

    monkeypatch.setattr(check_formatting, "_run", fail_if_called)

    ok = check_formatting._check_web(tmp_path, explicit_files=[f], git_auto_detected=True)

    assert ok is False


def test_check_web_check_auto_detected_falls_back_to_whole_file_target_when_merge_diverges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the scoped candidate does not canonicalize safely, the expected target
    for --check is the plain whole-file reformat, matching what --fix would write."""
    f = tmp_path / "page.html"
    f.write_text(_FORMATTED)  # already at the whole-file fallback target
    _mock_diverging_merge(monkeypatch)

    ok = check_formatting._check_web(tmp_path, explicit_files=[f], git_auto_detected=True)

    assert ok is True


def test_check_web_check_not_auto_detected_still_uses_native_prettier_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: without git_auto_detected, check mode is unchanged — native
    `prettier --check` on the explicit file list, no target computation at all."""
    f = tmp_path / "page.html"
    f.write_text(_ORIGINAL)

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    def fail_if_called(root: Path, files: list[Path]) -> None:
        raise AssertionError("target computation must not run without git_auto_detected")

    monkeypatch.setattr(check_formatting, "_batched_git_diff_hunk_ranges", fail_if_called)

    ok = check_formatting._check_web(tmp_path, explicit_files=[f])

    assert ok is True
    assert captured["cmd"] == ["npx", "--no-install", "prettier", "--check", str(f)]


# ---------------------------------------------------------------------------
# diff mode
# ---------------------------------------------------------------------------


def test_check_web_diff_auto_detected_compares_against_scoped_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "page.html"
    f.write_text(_ORIGINAL)
    _mock_converging_merge(monkeypatch)

    show_diff_calls: list[tuple[str, str]] = []

    def fake_show_diff(original: str, formatted: str, label: str) -> bool:
        show_diff_calls.append((original, formatted))
        return original != formatted

    monkeypatch.setattr(check_formatting, "_show_diff", fake_show_diff)

    ok = check_formatting._check_web(tmp_path, diff=True, explicit_files=[f], git_auto_detected=True)

    assert ok is False
    assert show_diff_calls == [(_ORIGINAL, _SCOPED_TARGET)]


def test_check_web_diff_not_auto_detected_compares_against_whole_file_reformat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: without git_auto_detected, diff mode is unchanged — always the
    unconditional whole-file reformat, via _prettier_diff."""
    f = tmp_path / "page.html"
    f.write_text(_ORIGINAL)

    def fake_fmt_stdout(cmd: list[str], cwd: Path) -> tuple[int, str]:
        return 0, _FORMATTED

    monkeypatch.setattr(check_formatting, "_fmt_stdout", fake_fmt_stdout)

    show_diff_calls: list[tuple[str, str]] = []

    def fake_show_diff(original: str, formatted: str, label: str) -> bool:
        show_diff_calls.append((original, formatted))
        return original != formatted

    monkeypatch.setattr(check_formatting, "_show_diff", fake_show_diff)

    ok = check_formatting._check_web(tmp_path, diff=True, explicit_files=[f])

    assert ok is False
    assert show_diff_calls == [(_ORIGINAL, _FORMATTED)]


# ---------------------------------------------------------------------------
# The consistency proof: fix's own written result must pass an immediate check
# ---------------------------------------------------------------------------


def test_check_web_fix_then_check_agree_on_retained_legacy_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug this closes: --fix reports success and retains legacy content,
    then --check on the identical resulting file must also report success —
    not contradict the fix that just ran."""
    f = tmp_path / "page.html"
    f.write_text(_ORIGINAL)
    _mock_converging_merge(monkeypatch)

    fix_ok = check_formatting._check_web(tmp_path, fix=True, explicit_files=[f], git_auto_detected=True)
    assert fix_ok is True
    assert f.read_text() == _SCOPED_TARGET

    check_ok = check_formatting._check_web(tmp_path, explicit_files=[f], git_auto_detected=True)
    assert check_ok is True
