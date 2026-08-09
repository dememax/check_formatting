# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for check_formatting()'s parallel checker dispatch — check_formatting project
"""Tests for check_formatting()'s dispatch loop running every selected
checker concurrently instead of strictly sequentially.

Eleven of the thirteen checkers still stream live via `_run`'s
`sys.stdout.write` per line; the old `--json` capture mechanism
(`contextlib.redirect_stdout` mutating the single process-global
`sys.stdout`) was never thread-safe, which is why this was deferred every
time it came up earlier in this project's history. Dispatch now installs a
thread-local stdout multiplexer for its duration: each checker's thread
gets its own private buffer, and the main thread's own output (banners,
before/after dispatch) falls straight through to the real stdout. Every
checker's full output is captured this way regardless of --json, and
`outputs`/printed banners are built from that same capture uniformly —
`contextlib.redirect_stdout` is no longer used at all.

Results and output are always consumed/printed in the original `checks`
list order, only once every submitted checker has completed — never
completion order, never incrementally. `--fail-fast` no longer stops any
checker from running (dispatch is unconditionally parallel): every future
is still submitted and the enclosing thread pool still waits for all of
them, so a slow checker after a fast failure still finishes in the
background. All --fail-fast now does is truncate the *report* at the
first failure in list order — no summary table, and no output printed for
checkers after it — matching today's "no summary table" contract, but for
a report built from already-known results rather than an early return.
"""

from __future__ import annotations

import contextlib
import sys
import threading
from typing import TYPE_CHECKING

from check_formatting import cli as check_formatting

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    import pytest


def _write_config(root: Path, checks: str) -> None:
    (root / ".check_formatting.toml").write_text(f"checks = [{checks}]\n")


def _stub_checker(label: str, fn: Callable[..., bool]) -> check_formatting.Checker:
    return check_formatting.Checker(
        label,
        fn,
        lambda config, git_auto_detected: {},
        lambda config, git_auto_detected: "no fix command",
    )


def test_check_formatting_runs_checkers_concurrently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A threading.Barrier(2): a sequential dispatch loop deadlocks here
    (only one checker's stub would ever be in flight at a time) rather than
    completing quickly, the same deterministic technique used for this
    project's other concurrency proofs (ruff, kconfig, the prettier
    pipeline).
    """
    _write_config(tmp_path, '"a", "b"')
    barrier = threading.Barrier(2, timeout=5)

    def stub(
        root: Path,
        fix: bool,
        diff: bool,
        verbose: bool,
        ignore_patterns: Sequence[str],
        explicit_files: list[Path] | None,
        quiet: bool = False,
        **kwargs: object,
    ) -> bool:
        barrier.wait()
        return True

    monkeypatch.setattr(
        check_formatting,
        "_CHECKERS",
        {"a": _stub_checker("Checker A", stub), "b": _stub_checker("Checker B", stub)},
    )

    ok = check_formatting.check_formatting(tmp_path, quiet=True)

    assert ok is True


def test_check_formatting_prints_in_checks_list_order_not_completion_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_config(tmp_path, '"slow", "fast"')
    release_slow = threading.Event()

    def slow(
        root: Path,
        fix: bool,
        diff: bool,
        verbose: bool,
        ignore_patterns: Sequence[str],
        explicit_files: list[Path] | None,
        quiet: bool = False,
        **kwargs: object,
    ) -> bool:
        release_slow.wait(timeout=5)
        print("SLOW-OUTPUT")
        return True

    def fast(
        root: Path,
        fix: bool,
        diff: bool,
        verbose: bool,
        ignore_patterns: Sequence[str],
        explicit_files: list[Path] | None,
        quiet: bool = False,
        **kwargs: object,
    ) -> bool:
        print("FAST-OUTPUT")
        release_slow.set()  # let "slow" finish only after "fast" already has
        return True

    monkeypatch.setattr(
        check_formatting,
        "_CHECKERS",
        {"slow": _stub_checker("Slow Checker", slow), "fast": _stub_checker("Fast Checker", fast)},
    )

    ok = check_formatting.check_formatting(tmp_path)

    assert ok is True
    out = capsys.readouterr().out
    assert out.index("SLOW-OUTPUT") < out.index("FAST-OUTPUT")


def test_check_formatting_fail_fast_stops_reporting_but_not_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The redefined --fail-fast: dispatch stays fully parallel regardless,
    every checker always runs to completion — only the *report* stops at
    the first failure in checks-list order.
    """
    _write_config(tmp_path, '"a", "b"')
    b_ran = threading.Event()

    def failing_a(
        root: Path,
        fix: bool,
        diff: bool,
        verbose: bool,
        ignore_patterns: Sequence[str],
        explicit_files: list[Path] | None,
        quiet: bool = False,
        **kwargs: object,
    ) -> bool:
        b_ran.wait(timeout=5)  # prove "b" doesn't need "a" to finish first
        return False

    def stub_b(
        root: Path,
        fix: bool,
        diff: bool,
        verbose: bool,
        ignore_patterns: Sequence[str],
        explicit_files: list[Path] | None,
        quiet: bool = False,
        **kwargs: object,
    ) -> bool:
        b_ran.set()
        print("B-RAN")
        return True

    monkeypatch.setattr(
        check_formatting,
        "_CHECKERS",
        {"a": _stub_checker("Checker A", failing_a), "b": _stub_checker("Checker B", stub_b)},
    )

    ok = check_formatting.check_formatting(tmp_path, fail_fast=True)

    assert ok is False
    out = capsys.readouterr().out
    assert "check_formatting:" not in out  # no summary table/line when fail_fast triggers
    assert "B-RAN" not in out  # b's own output is not part of the (truncated) report...
    assert b_ran.is_set()  # ...even though b actually ran, unaffected by a's failure


def test_check_formatting_json_payload_shape_unchanged_under_new_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    _write_config(tmp_path, '"a"')

    def stub(
        root: Path,
        fix: bool,
        diff: bool,
        verbose: bool,
        ignore_patterns: Sequence[str],
        explicit_files: list[Path] | None,
        quiet: bool = False,
        **kwargs: object,
    ) -> bool:
        print("hello from a")
        return True

    monkeypatch.setattr(check_formatting, "_CHECKERS", {"a": _stub_checker("Checker A", stub)})

    ok = check_formatting.check_formatting(tmp_path, as_json=True)

    assert ok is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"]["a"]["ok"] is True
    assert payload["results"]["a"]["label"] == "Checker A"
    assert "hello from a" in payload["results"]["a"]["output"]


def test_check_formatting_quiet_suppresses_banners_not_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_config(tmp_path, '"a"')

    def stub(
        root: Path,
        fix: bool,
        diff: bool,
        verbose: bool,
        ignore_patterns: Sequence[str],
        explicit_files: list[Path] | None,
        quiet: bool = False,
        **kwargs: object,
    ) -> bool:
        print("a genuine finding")
        return True

    monkeypatch.setattr(check_formatting, "_CHECKERS", {"a": _stub_checker("Checker A", stub)})

    ok = check_formatting.check_formatting(tmp_path, quiet=True)

    assert ok is True
    out = capsys.readouterr().out
    assert "a genuine finding" in out
    assert "Checker A" not in out  # the banner box itself is suppressed


def test_check_formatting_restores_real_stdout_after_returning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(tmp_path, '"a"')
    real_stdout = sys.stdout

    def stub(
        root: Path,
        fix: bool,
        diff: bool,
        verbose: bool,
        ignore_patterns: Sequence[str],
        explicit_files: list[Path] | None,
        quiet: bool = False,
        **kwargs: object,
    ) -> bool:
        return True

    monkeypatch.setattr(check_formatting, "_CHECKERS", {"a": _stub_checker("Checker A", stub)})

    check_formatting.check_formatting(tmp_path, quiet=True)

    assert sys.stdout is real_stdout


def test_check_formatting_restores_real_stdout_even_when_a_checker_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, '"a"')
    real_stdout = sys.stdout

    def boom(
        root: Path,
        fix: bool,
        diff: bool,
        verbose: bool,
        ignore_patterns: Sequence[str],
        explicit_files: list[Path] | None,
        quiet: bool = False,
        **kwargs: object,
    ) -> bool:
        raise RuntimeError("boom")

    monkeypatch.setattr(check_formatting, "_CHECKERS", {"a": _stub_checker("Checker A", boom)})

    with contextlib.suppress(RuntimeError):
        check_formatting.check_formatting(tmp_path, quiet=True)

    assert sys.stdout is real_stdout
