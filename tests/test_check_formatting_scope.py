# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for check_formatting's git-based changed-file auto-detection — check_formatting project
"""Tests for check_formatting's default file-selection scope.

Mirrors check_rst's own default (auto-detect changed/untracked files via
git, rather than a full-repo scan) — motivated by this project's own
actual usage pattern (every interactive invocation this session scoped to
just-touched files via `-- $(git diff --name-only HEAD)`, never the bare
full-repo form except as a final regression gate).

This also closes a real bug: `main()` used to collapse an *explicitly
empty* file selection (`-- $(git diff --name-only HEAD)` expanding to
nothing) into `None` via `[...] or None`, which silently reran the full
repo instead of doing nothing. `explicit_files=[]` and `explicit_files=None`
are now distinct, meaningful states:

- `None`      — full-repo scan (used by release-gate library callers and
                requested by `--all` on the CLI).
- `[]`        — explicitly nothing to check; check_formatting() reports
                this and returns True without running any checker.
- non-empty   — scope to exactly those files (unchanged).

`_resolve_explicit_files` is the CLI-layer helper that decides which of
these three states main() should pass, given the FILE positional args and
the new `--all` flag. `_detect_changed_files` is the git-based auto-detect
itself, tested against a real tmp_path git repository (not mocked — git's
own output format is exactly what's under test here).
"""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from check_formatting import cli as check_formatting


def test_check_formatting_preserves_existing_positional_parameter_order() -> None:
    """Adding git scope must not silently shift quiet/JSON/exclude callers."""
    root = Path("/project")
    explicit_files = [root / "changed.cpp"]
    exclude_patterns = ("vendor/",)

    bound = inspect.signature(check_formatting.check_formatting).bind(
        root,
        ["cpp"],
        True,
        False,
        True,
        False,
        explicit_files,
        True,
        False,
        exclude_patterns,
    )

    assert bound.arguments["explicit_files"] == explicit_files
    assert bound.arguments["quiet"] is True
    assert bound.arguments["as_json"] is False
    assert bound.arguments["exclude_patterns"] == exclude_patterns
    assert "git_auto_detected" not in bound.arguments


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git("init", "-q", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)


# ---------------------------------------------------------------------------
# _detect_changed_files — real git repo, no mocking
# ---------------------------------------------------------------------------


def test_detect_changed_files_finds_modified_tracked_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    tracked = tmp_path / "tracked.py"
    tracked.write_text("x = 1\n")
    _git("add", "tracked.py", cwd=tmp_path)
    _git("commit", "-q", "-m", "initial", cwd=tmp_path)

    tracked.write_text("x = 2\n")

    files = check_formatting._detect_changed_files(tmp_path)

    assert tracked.resolve() in files


def test_detect_changed_files_finds_untracked_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "baseline.py").write_text("x = 1\n")
    _git("add", "baseline.py", cwd=tmp_path)
    _git("commit", "-q", "-m", "initial", cwd=tmp_path)

    new_file = tmp_path / "new_file.py"
    new_file.write_text("y = 1\n")

    files = check_formatting._detect_changed_files(tmp_path)

    assert new_file.resolve() in files


def test_detect_changed_files_excludes_unchanged_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    changed = tmp_path / "changed.py"
    unchanged = tmp_path / "unchanged.py"
    changed.write_text("x = 1\n")
    unchanged.write_text("x = 1\n")
    _git("add", "changed.py", "unchanged.py", cwd=tmp_path)
    _git("commit", "-q", "-m", "initial", cwd=tmp_path)

    changed.write_text("x = 2\n")

    files = check_formatting._detect_changed_files(tmp_path)

    assert changed.resolve() in files
    assert unchanged.resolve() not in files


def test_detect_changed_files_excludes_deleted_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    doomed = tmp_path / "doomed.py"
    doomed.write_text("x = 1\n")
    _git("add", "doomed.py", cwd=tmp_path)
    _git("commit", "-q", "-m", "initial", cwd=tmp_path)

    doomed.unlink()

    files = check_formatting._detect_changed_files(tmp_path)

    assert doomed.resolve() not in files


def test_detect_changed_files_returns_empty_when_nothing_changed(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "settled.py").write_text("x = 1\n")
    _git("add", "settled.py", cwd=tmp_path)
    _git("commit", "-q", "-m", "initial", cwd=tmp_path)

    files = check_formatting._detect_changed_files(tmp_path)

    assert files == []


# ---------------------------------------------------------------------------
# check_formatting() — explicit_files=[] is a distinct "nothing to do" state
# ---------------------------------------------------------------------------


def test_check_formatting_empty_explicit_files_reports_nothing_to_do_without_running_checkers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path
    (root / ".check_formatting.toml").write_text('checks = ["ini"]\n\n[ini]\nglobs = ["*.ini"]\n')

    def fail_if_called(*args: object, **kwargs: object) -> bool:
        raise AssertionError("no checker should run when explicit_files is an empty list")

    monkeypatch.setattr(check_formatting, "_CHECKERS", {"ini": ("prettier-plugin-ini (INI)", fail_if_called)})

    ok = check_formatting.check_formatting(root, explicit_files=[])

    assert ok is True
    out = capsys.readouterr().out
    assert "nothing to do" in out


def test_check_formatting_empty_explicit_files_json_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    root = tmp_path
    (root / ".check_formatting.toml").write_text('checks = ["ini"]\n\n[ini]\nglobs = ["*.ini"]\n')

    def fail_if_called(*args: object, **kwargs: object) -> bool:
        raise AssertionError("no checker should run when explicit_files is an empty list")

    monkeypatch.setattr(check_formatting, "_CHECKERS", {"ini": ("prettier-plugin-ini (INI)", fail_if_called)})

    ok = check_formatting.check_formatting(root, explicit_files=[], as_json=True)

    assert ok is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["overall_ok"] is True
    assert payload["summary"] == {"total": 0, "passed": 0, "failed": 0}


def test_check_formatting_empty_explicit_files_still_validates_config(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        check_formatting.check_formatting(tmp_path, explicit_files=[])

    assert exc_info.value.code == 1


def test_check_formatting_none_explicit_files_still_full_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: None must keep meaning "full repo" for library callers."""
    root = tmp_path
    (root / ".check_formatting.toml").write_text('checks = ["ini"]\n\n[ini]\nglobs = ["*.ini"]\n')
    (root / "settings.ini").write_text("[section]\nkey = value\n")
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 0)

    ok = check_formatting.check_formatting(root, explicit_files=None)

    assert ok is True


# ---------------------------------------------------------------------------
# _resolve_explicit_files — the CLI-layer decision (--all / FILE args / auto-detect)
# ---------------------------------------------------------------------------


def test_resolve_explicit_files_all_flag_forces_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(root: Path) -> list[Path]:
        raise AssertionError("--all must not trigger git auto-detection")

    monkeypatch.setattr(check_formatting, "_detect_changed_files", fail_if_called)

    result = check_formatting._resolve_explicit_files([], True, tmp_path)

    assert result is None


def test_resolve_explicit_files_explicit_paths_used_verbatim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(root: Path) -> list[Path]:
        raise AssertionError("explicit FILE args must not trigger git auto-detection")

    monkeypatch.setattr(check_formatting, "_detect_changed_files", fail_if_called)

    result = check_formatting._resolve_explicit_files(["foo.py", "bar.cpp"], False, tmp_path)

    assert result == [(tmp_path / "foo.py").resolve(), (tmp_path / "bar.cpp").resolve()]


def test_resolve_explicit_files_no_args_triggers_autodetect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    detected = [tmp_path / "changed.py"]
    monkeypatch.setattr(check_formatting, "_detect_changed_files", lambda root: detected)

    result = check_formatting._resolve_explicit_files([], False, tmp_path)

    assert result is detected


def test_resolve_explicit_files_no_args_autodetect_empty_stays_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug this replaces: an empty result must stay `[]`, never collapse to `None`."""
    monkeypatch.setattr(check_formatting, "_detect_changed_files", lambda root: [])

    result = check_formatting._resolve_explicit_files([], False, tmp_path)

    assert result == []
    assert result is not None


# ---------------------------------------------------------------------------
# --exclude — ad hoc, single-invocation exclusion (composes with .formatting-ignore)
# ---------------------------------------------------------------------------


def test_check_formatting_exclude_patterns_filter_out_matching_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path
    (root / ".check_formatting.toml").write_text('checks = ["ini"]\n\n[ini]\nglobs = ["*.ini"]\n')
    (root / "keep.ini").write_text("[section]\nkey = value\n")
    (root / "skip_me.ini").write_text("[section]\nkey = value\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting.check_formatting(root, exclude_patterns=["skip_me.ini"])

    assert ok is True
    assert str(root / "keep.ini") in captured["cmd"]
    assert str(root / "skip_me.ini") not in captured["cmd"]


def test_check_formatting_exclude_combines_with_formatting_ignore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--exclude adds to .formatting-ignore's exclusions for this run; it doesn't replace them."""
    root = tmp_path
    (root / ".check_formatting.toml").write_text('checks = ["ini"]\n\n[ini]\nglobs = ["*.ini"]\n')
    (root / ".formatting-ignore").write_text("ignored_by_file.ini\n")
    (root / "keep.ini").write_text("[section]\nkey = value\n")
    (root / "ignored_by_file.ini").write_text("[section]\nkey = value\n")
    (root / "ignored_by_flag.ini").write_text("[section]\nkey = value\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting.check_formatting(root, exclude_patterns=["ignored_by_flag.ini"])

    assert ok is True
    assert str(root / "keep.ini") in captured["cmd"]
    assert str(root / "ignored_by_file.ini") not in captured["cmd"]
    assert str(root / "ignored_by_flag.ini") not in captured["cmd"]
