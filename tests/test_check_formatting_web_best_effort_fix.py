# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for check_formatting's Prettier "best-effort" git-scoped fix — check_formatting project
"""Tests for the Prettier checkers' optional "best-effort" git-scoped fix.

Unlike ``cpp``'s native ``clang-format -lines=`` (a tool-guaranteed hunk
scope) or ``rst``'s check_rst bare mode, prettier has no reliably-usable
native line-range mechanism across HTML/CSS/JS, JSON/JSONC, INI, and YAML
(``--range-start``/``--range-end`` exist but are documented mainly for
JS/TS).  The shared implementation instead diffs the whole-file reformat
against the original with ``difflib``, keeps only formatting changes that
overlap git-changed hunks (:func:`check_formatting._git_diff_hunk_ranges`),
then verifies that formatting the merged result produces the same canonical
whole-file result.  This permits retained legacy formatting while proving
the candidate still parses to the expected document; a different canonical
result falls back to today's whole-file ``--write``, never a worse outcome
than before.

``_merge_within_hunk_ranges`` is pure line-diffing logic, tested directly
with no mocking.  ``_best_effort_prettier_fix`` orchestrates it against a
real file on disk with ``_fmt_stdout``/``_git_diff_hunk_ranges`` mocked (no
real prettier invocation).  ``_fix_prettier_files`` centralizes the scoped
versus batched dispatch used by ``web``, ``json``, ``ini``, and ``yaml``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from check_formatting import cli as check_formatting

# ---------------------------------------------------------------------------
# _merge_within_hunk_ranges — pure logic, no mocking
# ---------------------------------------------------------------------------


def test_merge_keeps_in_scope_change_and_reverts_out_of_scope_change() -> None:
    original = "one\ntwo\nthree\nfour\nfive\n"
    # prettier "fixed" both line 2 (in the changed hunk) and line 4 (untouched).
    formatted = "one\nTWO_FIXED\nthree\nFOUR_FIXED\nfive\n"

    merged = check_formatting._merge_within_hunk_ranges(original, formatted, [(2, 2)])

    assert merged == "one\nTWO_FIXED\nthree\nfour\nfive\n"


def test_merge_all_changes_in_scope_matches_formatted() -> None:
    original = "a\nb\nc\n"
    formatted = "A\nB\nc\n"

    merged = check_formatting._merge_within_hunk_ranges(original, formatted, [(1, 2)])

    assert merged == formatted


def test_merge_no_changes_in_scope_matches_original() -> None:
    original = "a\nb\nc\n"
    formatted = "A\nB\nc\n"

    merged = check_formatting._merge_within_hunk_ranges(original, formatted, [(3, 3)])

    assert merged == original


# ---------------------------------------------------------------------------
# _best_effort_prettier_fix — orchestration (_fmt_stdout/_git_diff_hunk_ranges mocked)
# ---------------------------------------------------------------------------


def test_best_effort_fix_writes_scoped_merge_when_it_canonicalizes_to_full_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retained legacy violation is safe when the candidate still canonicalizes
    to the same whole-file result, and validation uses the real file's config path."""
    f = tmp_path / "page.html"
    f.write_text("one\ntwo\nthree\nfour\nfive\n")

    # Prettier fixes both changed line 2 and untouched legacy line 4.  The
    # scoped candidate intentionally retains line 4, but formatting that
    # candidate still produces the same canonical whole-file output.
    formatted = "one\nTWO_FIXED\nthree\nFOUR_FIXED\nfive\n"
    merged = "one\nTWO_FIXED\nthree\nfour\nfive\n"

    calls: list[tuple[list[str], str | None]] = []

    def fake_fmt_stdout(cmd: list[str], cwd: Path, *, input_text: str | None = None) -> tuple[int, str]:
        calls.append((cmd, input_text))
        if len(calls) == 1:
            return 0, formatted
        # Second call validates the scoped candidate.  It is deliberately
        # not a fixed point because line 4 stays legacy-formatted; its
        # canonical form nevertheless matches the expected full result.
        return 0, formatted

    monkeypatch.setattr(check_formatting, "_fmt_stdout", fake_fmt_stdout)

    ok, status = check_formatting._best_effort_prettier_fix(f, tmp_path, [(2, 2)])

    assert ok is True
    assert status == "git-scoped merge"
    assert f.read_text() == merged
    assert calls[1] == (
        ["npx", "--no-install", "prettier", "--stdin-filepath", str(f)],
        merged,
    )


def test_best_effort_fix_falls_back_when_candidate_canonicalizes_differently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "page.html"
    f.write_text("<div>\n<p>one</p>\n<p>two</p>\n</div>\n")

    formatted = "<div>\n  <p>ONE</p>\n  <p>TWO</p>\n</div>\n"

    calls: list[list[str]] = []

    validation_inputs: list[str | None] = []

    def fake_fmt_stdout(cmd: list[str], cwd: Path, *, input_text: str | None = None) -> tuple[int, str]:
        calls.append(cmd)
        validation_inputs.append(input_text)
        if len(calls) == 1:
            return 0, formatted
        # Second call: the scoped candidate canonicalizes to a different
        # document, so the heuristic cannot safely retain it.
        return 0, "<div>\n  <p>ONE</p>\n  <p>STILL DIFFERENT</p>\n</div>\n"

    monkeypatch.setattr(check_formatting, "_fmt_stdout", fake_fmt_stdout)

    ok, status = check_formatting._best_effort_prettier_fix(f, tmp_path, [(2, 2)])

    assert ok is True
    assert status.startswith("whole-file fallback")
    assert f.read_text() == formatted
    assert calls[1] == ["npx", "--no-install", "prettier", "--stdin-filepath", str(f)]
    assert validation_inputs[1] is not None


def test_best_effort_fix_uses_whole_file_when_no_hunk_ranges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "page.html"
    f.write_text("<div>\n<p>one</p>\n</div>\n")
    formatted = "<div>\n  <p>one</p>\n</div>\n"

    monkeypatch.setattr(check_formatting, "_fmt_stdout", lambda cmd, cwd: (0, formatted))

    ok, status = check_formatting._best_effort_prettier_fix(f, tmp_path, None)

    assert ok is True
    assert status == "whole-file fix (no git hunk info)"
    assert f.read_text() == formatted


def test_best_effort_fix_already_compliant_does_not_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "page.html"
    content = "<div>\n  <p>one</p>\n</div>\n"
    f.write_text(content)

    monkeypatch.setattr(check_formatting, "_fmt_stdout", lambda cmd, cwd: (0, content))

    # Hunk ranges are now precomputed once per batch by the caller, not
    # looked up here — the "don't compute ranges you don't need" guarantee
    # this test used to pin at this level now lives one level up, in
    # _fix_prettier_files/_report_prettier_files_git_scoped's own batching.
    ok, status = check_formatting._best_effort_prettier_fix(f, tmp_path, None)

    assert ok is True
    assert status == "already compliant"
    assert f.read_text() == content


def test_best_effort_fix_reports_failure_when_prettier_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "page.html"
    f.write_text("<div></div>\n")

    monkeypatch.setattr(check_formatting, "_fmt_stdout", lambda cmd, cwd: (127, ""))

    ok, _status = check_formatting._best_effort_prettier_fix(f, tmp_path, None)

    assert ok is False


# ---------------------------------------------------------------------------
# Shared Prettier fix dispatch
# ---------------------------------------------------------------------------


def test_fix_prettier_files_git_scope_runs_each_file_and_aggregates_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = [tmp_path / "first.json", tmp_path / "second.json"]
    for f in files:
        f.write_text("{}\n")

    calls: list[Path] = []

    def fake_best_effort(file: Path, root: Path, ranges: list[tuple[int, int]] | None) -> tuple[bool, str]:
        calls.append(file)
        return file == files[0], "git-scoped merge" if file == files[0] else "prettier exited 2"

    monkeypatch.setattr(check_formatting, "_best_effort_prettier_fix", fake_best_effort)
    monkeypatch.setattr(check_formatting, "_batched_git_diff_hunk_ranges", lambda root, files: dict.fromkeys(files))

    def fail_if_batched(cmd: list[str], cwd: Path) -> int:
        raise AssertionError("git-auto-detected scope must not use batched --write")

    monkeypatch.setattr(check_formatting, "_run", fail_if_batched)
    messages: list[str] = []

    ok = check_formatting._fix_prettier_files(
        files,
        tmp_path,
        git_auto_detected=True,
        label="(2 file(s))",
        log=messages.append,
    )

    assert ok is False
    assert calls == files
    assert any("first.json: git-scoped merge" in message for message in messages)
    assert any("second.json: prettier exited 2" in message for message in messages)


def test_fix_prettier_files_non_git_scope_stays_batched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = [tmp_path / "first.yaml", tmp_path / "second.yaml"]
    for f in files:
        f.write_text("key: value\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    def fail_if_called(file: Path, root: Path, ranges: list[tuple[int, int]] | None) -> tuple[bool, str]:
        raise AssertionError("whole-file scope must not run the best-effort merger")

    monkeypatch.setattr(check_formatting, "_best_effort_prettier_fix", fail_if_called)

    ok = check_formatting._fix_prettier_files(
        files,
        tmp_path,
        git_auto_detected=False,
        label="(2 file(s))",
        log=lambda _message: None,
    )

    assert ok is True
    assert captured["cmd"] == ["npx", "--no-install", "prettier", "--write", *[str(f) for f in files]]


def _assert_checker_uses_shared_git_scoped_fix(
    checker_name: str,
    root: Path,
    file: Path,
    monkeypatch: pytest.MonkeyPatch,
    **checker_kwargs: object,
) -> None:
    captured: dict[str, object] = {}

    def fake_fix(
        files: list[Path],
        helper_root: Path,
        *,
        git_auto_detected: bool,
        label: str,
        log: object,
    ) -> bool:
        captured.update(files=files, root=helper_root, git_auto_detected=git_auto_detected, label=label, log=log)
        return True

    monkeypatch.setattr(check_formatting, "_fix_prettier_files", fake_fix, raising=False)
    checker = getattr(check_formatting, checker_name)

    ok = checker(root, fix=True, explicit_files=[file], git_auto_detected=True, **checker_kwargs)

    assert ok is True
    assert captured["files"] == [file]
    assert captured["root"] == root
    assert captured["git_auto_detected"] is True


def test_check_json_git_fix_uses_shared_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "config.json"
    f.write_text("{}\n")

    _assert_checker_uses_shared_git_scoped_fix("_check_json", tmp_path, f, monkeypatch, files=["config.json"])


def test_check_ini_git_fix_uses_shared_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "config.ini"
    f.write_text("[section]\nkey = value\n")

    _assert_checker_uses_shared_git_scoped_fix("_check_ini", tmp_path, f, monkeypatch, globs=["*.ini"])


def test_check_yaml_git_fix_uses_shared_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "config.yaml"
    f.write_text("key: value\n")

    _assert_checker_uses_shared_git_scoped_fix("_check_yaml", tmp_path, f, monkeypatch, globs=["*.yaml"])


# ---------------------------------------------------------------------------
# _check_web fix-mode dispatch (_best_effort_prettier_fix mocked)
# ---------------------------------------------------------------------------


def test_check_web_fix_auto_detected_dispatches_to_best_effort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    f = root / "page.html"
    f.write_text("<div></div>\n")

    calls: list[Path] = []

    def fake_best_effort(file: Path, root: Path, ranges: list[tuple[int, int]] | None) -> tuple[bool, str]:
        calls.append(file)
        return True, "git-scoped merge"

    monkeypatch.setattr(check_formatting, "_best_effort_prettier_fix", fake_best_effort)

    def fail_if_batched(cmd: list[str], cwd: Path) -> int:
        raise AssertionError("must not run the batched whole-file --write when git_auto_detected")

    monkeypatch.setattr(check_formatting, "_run", fail_if_batched)

    ok = check_formatting._check_web(root, fix=True, explicit_files=[f], git_auto_detected=True)

    assert ok is True
    assert calls == [f]


def test_check_web_fix_not_auto_detected_stays_batched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    f = root / "page.html"
    f.write_text("<div></div>\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    def fail_if_called(file: Path, root: Path, ranges: list[tuple[int, int]] | None) -> None:
        raise AssertionError("best-effort merge must not run when git_auto_detected is False")

    monkeypatch.setattr(check_formatting, "_best_effort_prettier_fix", fail_if_called)

    ok = check_formatting._check_web(root, fix=True, explicit_files=[f])

    assert ok is True
    assert captured["cmd"] == ["npx", "--no-install", "prettier", "--write", str(f)]
