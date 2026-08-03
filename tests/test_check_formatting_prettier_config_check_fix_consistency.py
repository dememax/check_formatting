# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for json/ini/yaml check/fix consistency under best-effort scope — check_formatting project
"""Extends ``web``'s check/fix consistency fix
(``tests/test_check_formatting_web_check_fix_consistency.py``) to the other
three Prettier-backed checkers: ``json``, ``ini``, and ``yaml``.

Before this fix, only ``web``'s check/verbose/diff modes compared a file
against what a git-scoped ``--fix`` would actually write
(:func:`check_formatting._best_effort_prettier_target`); ``json``/``ini``/
``yaml`` still compared against the unconditional whole-file reformat in
check/diff mode, even though their ``--fix`` (via the shared
``_fix_prettier_files``) already used the same best-effort merge as ``web``.
So the exact same contradiction ``web`` had — ``--fix`` succeeds and
deliberately retains legacy content, then ``--check`` on the identical file
fails — could still happen for these three.

Parametrized over the three checkers since ``_check_ini``/``_check_yaml``
are documented as an "exact structural mirror" of each other and ``_check_json``
matches the same check/diff shape; the merge/validation logic itself
(``_merge_within_hunk_ranges``, ``_best_effort_prettier_target``) is already
file-type-agnostic pure text diffing, so mocked prettier output doesn't need
to be valid JSON/INI/YAML.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from check_formatting import cli as check_formatting

if TYPE_CHECKING:
    from pathlib import Path

_ORIGINAL = "one\ntwo\nthree\nfour\nfive\n"
# prettier would fix both changed line 2 and untouched legacy line 4.
_FORMATTED = "one\nTWO_FIXED\nthree\nFOUR_FIXED\nfive\n"
# the scoped candidate retains legacy line 4; canonicalizes to _FORMATTED.
_SCOPED_TARGET = "one\nTWO_FIXED\nthree\nfour\nfive\n"

_CASES = [
    ("_check_json", "config.json", {"files": ["config.json"]}),
    ("_check_ini", "config.ini", {"globs": ["*.ini"]}),
    ("_check_yaml", "config.yaml", {"globs": ["*.yaml"]}),
]


def _mock_converging_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_fmt_stdout(cmd: list[str], cwd: Path, *, input_text: str | None = None) -> tuple[int, str]:
        calls.append(cmd)
        return 0, _FORMATTED  # both calls: whole-file reformat, then converging validation

    monkeypatch.setattr(check_formatting, "_fmt_stdout", fake_fmt_stdout)
    monkeypatch.setattr(check_formatting, "_git_diff_hunk_ranges", lambda root, file: [(2, 2)])


@pytest.mark.parametrize(("checker_name", "filename", "extra_kwargs"), _CASES)
def test_check_prettier_config_passes_when_file_already_at_scoped_target(
    checker_name: str,
    filename: str,
    extra_kwargs: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = tmp_path / filename
    f.write_text(_SCOPED_TARGET)
    _mock_converging_merge(monkeypatch)
    checker = getattr(check_formatting, checker_name)

    ok = checker(tmp_path, explicit_files=[f], git_auto_detected=True, **extra_kwargs)

    assert ok is True


@pytest.mark.parametrize(("checker_name", "filename", "extra_kwargs"), _CASES)
def test_check_prettier_config_fails_when_file_not_at_scoped_target(
    checker_name: str,
    filename: str,
    extra_kwargs: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = tmp_path / filename
    f.write_text(_ORIGINAL)
    _mock_converging_merge(monkeypatch)

    def fail_if_called(cmd: list[str], cwd: Path) -> int:
        raise AssertionError("git-scoped check must compare against the target, not shell out to native --check")

    monkeypatch.setattr(check_formatting, "_run", fail_if_called)
    checker = getattr(check_formatting, checker_name)

    ok = checker(tmp_path, explicit_files=[f], git_auto_detected=True, **extra_kwargs)

    assert ok is False


@pytest.mark.parametrize(("checker_name", "filename", "extra_kwargs"), _CASES)
def test_check_prettier_config_not_auto_detected_stays_native_check(
    checker_name: str,
    filename: str,
    extra_kwargs: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: without git_auto_detected, check mode is unchanged — native
    `prettier --check`, no target computation at all."""
    f = tmp_path / filename
    f.write_text(_ORIGINAL)

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    def fail_if_called(root: Path, file: Path) -> None:
        raise AssertionError("target computation must not run without git_auto_detected")

    monkeypatch.setattr(check_formatting, "_git_diff_hunk_ranges", fail_if_called)
    checker = getattr(check_formatting, checker_name)

    ok = checker(tmp_path, explicit_files=[f], **extra_kwargs)

    assert ok is True
    assert captured["cmd"] == ["npx", "--no-install", "prettier", "--check", str(f)]


@pytest.mark.parametrize(("checker_name", "filename", "extra_kwargs"), _CASES)
def test_check_prettier_config_diff_auto_detected_compares_against_scoped_target(
    checker_name: str,
    filename: str,
    extra_kwargs: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = tmp_path / filename
    f.write_text(_ORIGINAL)
    _mock_converging_merge(monkeypatch)

    show_diff_calls: list[tuple[str, str]] = []

    def fake_show_diff(original: str, formatted: str, label: str) -> bool:
        show_diff_calls.append((original, formatted))
        return original != formatted

    monkeypatch.setattr(check_formatting, "_show_diff", fake_show_diff)
    checker = getattr(check_formatting, checker_name)

    ok = checker(tmp_path, diff=True, explicit_files=[f], git_auto_detected=True, **extra_kwargs)

    assert ok is False
    assert show_diff_calls == [(_ORIGINAL, _SCOPED_TARGET)]


@pytest.mark.parametrize(("checker_name", "filename", "extra_kwargs"), _CASES)
def test_check_prettier_config_fix_then_check_agree_on_retained_legacy_content(
    checker_name: str,
    filename: str,
    extra_kwargs: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug this closes: --fix reports success and retains legacy content,
    then --check on the identical resulting file must also report success."""
    f = tmp_path / filename
    f.write_text(_ORIGINAL)
    _mock_converging_merge(monkeypatch)
    checker = getattr(check_formatting, checker_name)

    fix_ok = checker(tmp_path, fix=True, explicit_files=[f], git_auto_detected=True, **extra_kwargs)
    assert fix_ok is True
    assert f.read_text() == _SCOPED_TARGET

    check_ok = checker(tmp_path, explicit_files=[f], git_auto_detected=True, **extra_kwargs)
    assert check_ok is True
