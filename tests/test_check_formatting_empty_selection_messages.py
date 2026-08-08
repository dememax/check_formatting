# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for the "all N <kind> file(s) excluded" message drift — check_formatting project
"""Pins the "(all N <kind> file(s) excluded by .formatting-ignore)" message shape.

Nine `_check_*` backends independently duplicate the same "no files found" /
"all files excluded" guard pair around their file-selection prologue. Five of
them (cpp, cmake, yaml, clang-tidy, shell) include the excluded count in the
message; four (meson, web, json, ini) silently drop it — a copy-paste drift
caught in code review. These tests pin the corrected, count-including wording
for the four that were missing it, ahead of consolidating all nine call sites
onto one shared helper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from check_formatting import cli as check_formatting

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_check_ini_excluded_count_message_includes_count(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path
    ini_file = root / "settings.ini"
    ini_file.write_text("[section]\nkey = value\n")

    ok = check_formatting._check_ini(root, explicit_files=[ini_file], ignore_patterns=["settings.ini"], globs=["*.ini"])

    assert ok is True
    assert "(all 1 INI file(s) excluded by .formatting-ignore)" in capsys.readouterr().out


def test_check_web_excluded_count_message_includes_count(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path
    web_file = root / "index.html"
    web_file.write_text("<html></html>\n")

    ok = check_formatting._check_web(root, explicit_files=[web_file], ignore_patterns=["index.html"], globs=["*.html"])

    assert ok is True
    assert "(all 1 web file(s) excluded by .formatting-ignore)" in capsys.readouterr().out


def test_check_json_excluded_count_message_includes_count(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path
    json_file = root / "config.json"
    json_file.write_text("{}\n")

    ok = check_formatting._check_json(
        root, explicit_files=[json_file], ignore_patterns=["config.json"], files=["config.json"]
    )

    assert ok is True
    assert "(all 1 JSON file(s) excluded by .formatting-ignore)" in capsys.readouterr().out


def test_check_meson_excluded_count_message_includes_count(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path
    build_file = root / "meson.build"
    build_file.write_text("project('x')\n")

    ok = check_formatting._check_meson(root, explicit_files=[build_file], ignore_patterns=["meson.build"])

    assert ok is True
    assert "(all 1 Meson build file(s) excluded by .formatting-ignore)" in capsys.readouterr().out
