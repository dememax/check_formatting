# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for check_formatting's --json machine-readable output — check_formatting project
"""Tests for check_formatting's --json flag.

Modeled on check_rst's own --json contract ("one JSON object on stdout,
nothing else"): unlike check_rst, check_formatting is a thin wrapper
around external tools (ruff, mypy, prettier, clang-format) whose own real
stdout streams through subprocess invocation rather than being generated
by this script — so achieving "nothing else on stdout" requires actually
capturing each checker's output (via contextlib.redirect_stdout) instead
of merely suppressing this script's own chrome the way --quiet does.

The JSON payload embeds each checker's captured output as a string field,
so no information is lost relative to the human-readable run — it is
just relocated into structured data instead of interleaved with our own
banners.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from check_formatting import cli as check_formatting

_MINIMAL_TOML = 'checks = ["ini", "json"]\n\n[ini]\nglobs = ["*.ini"]\n\n[json]\nfiles = ["config.json"]\n'


def test_json_output_is_the_only_thing_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The real (outer) stdout must contain nothing but the JSON object — no banners, no
    config echo, no summary table, no FORMATTING: verdict lines."""
    root = tmp_path
    (root / ".check_formatting.toml").write_text(_MINIMAL_TOML)
    (root / "config.json").write_text("{}\n")
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 0)

    ok = check_formatting.check_formatting(root, as_json=True)

    assert ok is True
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)  # raises if anything else was printed alongside the JSON
    assert payload["overall_ok"] is True


def test_json_payload_has_expected_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path
    (root / ".check_formatting.toml").write_text(_MINIMAL_TOML)
    (root / "config.json").write_text("{}\n")
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 0)

    check_formatting.check_formatting(root, as_json=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["config_source"] == ".check_formatting.toml"
    assert payload["mode"] == "check"
    assert payload["checks"] == ["ini", "json"]
    assert set(payload["results"]) == {"ini", "json"}
    assert payload["results"]["ini"]["ok"] is True
    assert "label" in payload["results"]["ini"]
    assert "output" in payload["results"]["ini"]
    assert payload["summary"] == {"total": 2, "passed": 2, "failed": 0}


def test_json_captures_wrapped_tool_output_per_checker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A wrapped tool's own real stdout (here simulated by _run itself printing, matching
    how the real streaming _run relays subprocess output via sys.stdout.write) must end up
    embedded in the JSON's per-checker "output" field, not loose on the outer stdout."""
    root = tmp_path
    (root / ".check_formatting.toml").write_text('checks = ["ini"]\n\n[ini]\nglobs = ["*.ini"]\n')
    (root / "settings.ini").write_text("[section]\nkey = value\n")

    def fake_run(cmd: list[str], cwd: Path) -> int:
        print("Checking formatting...\nAll matched files use Prettier code style!")
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    check_formatting.check_formatting(root, as_json=True)

    out = capsys.readouterr().out
    payload = json.loads(out)  # would fail to parse if the print above leaked loose onto stdout
    assert "All matched files use Prettier code style!" in payload["results"]["ini"]["output"]


def test_json_return_value_matches_non_json_mode_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    (root / ".check_formatting.toml").write_text('checks = ["ini"]\n\n[ini]\nglobs = ["*.ini"]\n')
    (root / "settings.ini").write_text("[section]\nkey = value\n")
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 1)

    json_ok = check_formatting.check_formatting(root, as_json=True)
    plain_ok = check_formatting.check_formatting(root, as_json=False)

    assert json_ok is False
    assert plain_ok is False
    assert json_ok == plain_ok


def test_json_mode_reports_correct_failure_in_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path
    (root / ".check_formatting.toml").write_text('checks = ["ini"]\n\n[ini]\nglobs = ["*.ini"]\n')
    (root / "settings.ini").write_text("[section]\nkey = value\n")
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 1)

    check_formatting.check_formatting(root, as_json=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["overall_ok"] is False
    assert payload["results"]["ini"]["ok"] is False
    assert payload["summary"] == {"total": 1, "passed": 0, "failed": 1}
