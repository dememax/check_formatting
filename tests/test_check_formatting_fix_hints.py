# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for truthful automatic-fix remediation hints — check_formatting project
"""Ensure analysis-only failures are never presented as automatically fixable."""

from __future__ import annotations

from typing import TYPE_CHECKING

from check_formatting import cli as check_formatting

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _fail(*args: object, **kwargs: object) -> bool:
    return False


def test_analysis_only_failure_does_not_recommend_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".check_formatting.toml").write_text('checks = ["shell"]\n')
    shell = check_formatting._CHECKERS["shell"]._replace(fn=_fail)
    monkeypatch.setattr(check_formatting, "_CHECKERS", {"shell": shell})

    ok = check_formatting.check_formatting(tmp_path)

    assert ok is False
    output = capsys.readouterr().out
    assert "shellcheck has no automatic fix" in output
    assert "re-run with --fix" not in output


def test_mixed_failures_describe_fix_as_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".check_formatting.toml").write_text('checks = ["cpp", "shell"]\n')
    cpp = check_formatting._CHECKERS["cpp"]._replace(fn=_fail)
    shell = check_formatting._CHECKERS["shell"]._replace(fn=_fail)
    monkeypatch.setattr(check_formatting, "_CHECKERS", {"cpp": cpp, "shell": shell})

    ok = check_formatting.check_formatting(tmp_path)

    assert ok is False
    output = capsys.readouterr().out
    assert "automatic fixes where available" in output
    assert "manual fixes will remain" in output
    assert "apply all fixes at once" not in output


def test_fixable_only_failure_retains_apply_all_fix_advice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The truthful distinction must preserve the useful existing fix shortcut."""
    (tmp_path / ".check_formatting.toml").write_text('checks = ["cpp"]\n')
    cpp = check_formatting._CHECKERS["cpp"]._replace(fn=_fail)
    monkeypatch.setattr(check_formatting, "_CHECKERS", {"cpp": cpp})

    ok = check_formatting.check_formatting(tmp_path)

    assert ok is False
    assert "re-run with --fix to apply all fixes at once" in capsys.readouterr().out
