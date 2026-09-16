# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for --checks' nargs='+' swallowing a following FILE argument — check_formatting project
"""Regression tests for a reported first-use footgun.

``--checks`` is ``nargs='+'`` so it greedily consumes any following token
that doesn't look like a flag, including a FILE positional typed right
after it: ``check_formatting --checks shell scripts/status.sh`` fails
with argparse blaming ``scripts/status.sh`` as an "invalid choice" for
``--checks``, which misdirects debugging toward the file path instead of
the actual mistake (argument order). See
``~/AI-papers/check_formatting-checks-flag-swallows-files-feedback.md``
for the full report this codifies.

Deliberately not fixing the swallowing itself (that would mean changing
``--checks``'s documented, tested ``nargs='+'`` syntax — a breaking CLI
change out of scope here). Instead: (1) ``_check_name`` appends a hint to
the error when the rejected value looks like a file path, and (2) accepts
the checker's own display name (``shellcheck``) as an alias for its
internal category name (``shell``), closing the adjacent mismatch noted
in the same report.
"""

from __future__ import annotations

import argparse

import pytest

from check_formatting import cli as check_formatting


def test_check_name_accepts_a_registered_check() -> None:
    assert check_formatting._check_name("shell") == "shell"


def test_check_name_accepts_shellcheck_as_an_alias_for_shell() -> None:
    """'shellcheck' is the checker's own display name shown in the results table."""
    assert check_formatting._check_name("shellcheck") == "shell"


def test_check_name_rejects_unknown_name_without_file_hint() -> None:
    with pytest.raises(argparse.ArgumentTypeError) as exc_info:
        check_formatting._check_name("bogus")

    message = str(exc_info.value)
    assert "invalid choice: 'bogus'" in message
    assert "looks like a file path" not in message


def test_check_name_hints_when_rejected_value_looks_like_a_file_path() -> None:
    with pytest.raises(argparse.ArgumentTypeError) as exc_info:
        check_formatting._check_name("scripts/status.sh")

    message = str(exc_info.value)
    assert "invalid choice: 'scripts/status.sh'" in message
    assert "looks like a file path, not a check name" in message
    assert "--" in message


def test_main_reports_the_file_path_hint_for_the_reported_invocation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """End-to-end repro of the exact command from the feedback report."""
    monkeypatch.setattr("sys.argv", ["check_formatting", "--checks", "shell", "scripts/status.sh"])

    with pytest.raises(SystemExit) as exc_info:
        check_formatting.main()

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "invalid choice: 'scripts/status.sh'" in stderr
    assert "looks like a file path, not a check name" in stderr
