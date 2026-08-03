# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for check_formatting's yaml checker — check_formatting project
"""Tests for check_formatting's yaml checker.

The checker covers YAML files without adding a tool dependency:
``npx prettier --file-info test.yaml`` reports the built-in
``inferredParser: "yaml"`` parser.

`_check_yaml` is an exact structural mirror of `_check_ini` (same
check/verbose/diff/fix modes via prettier, same `_prettier_diff` helper
reused for diff mode) — the only differences are the config section name
(`[yaml].globs`), the file extensions recognised for explicit-file
selection (`.yaml`/`.yml`), and the human-readable label ("YAML" instead
of "INI").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from check_formatting import cli as check_formatting

if TYPE_CHECKING:
    from pathlib import Path


def test_check_yaml_uses_configured_globs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    custom_dir = root / "config"
    custom_dir.mkdir()
    yaml_file = custom_dir / "zitadel.yaml"
    yaml_file.write_text("key: value\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_yaml(root, globs=["config/*.yaml"])

    assert ok is True
    assert str(yaml_file) in captured["cmd"]


def test_check_yaml_no_globs_configured_passes_without_requiring_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project with no `[yaml]` section (globs=()) has nothing to check — must vacuously pass."""
    root = tmp_path

    def fail_if_called(cmd: list[str], cwd: Path) -> int:
        raise AssertionError("prettier should not run when there is nothing to check")

    monkeypatch.setattr(check_formatting, "_run", fail_if_called)

    ok = check_formatting._check_yaml(root, globs=[])

    assert ok is True


def test_check_yaml_fix_mode_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    (root / "sample.yaml").write_text("key: value\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_yaml(root, globs=["*.yaml"], fix=True)

    assert ok is True
    assert "--write" in captured["cmd"]


def test_check_yaml_diff_mode_shows_diff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    yaml_file = root / "sample.yaml"
    yaml_file.write_text("key: value\n")

    monkeypatch.setattr(check_formatting, "_fmt_stdout", lambda cmd, cwd: (0, "key: value\n"))

    ok = check_formatting._check_yaml(root, globs=["*.yaml"], diff=True)

    assert ok is True


def test_check_yaml_recognizes_yml_extension_in_explicit_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path
    yml_file = root / "testcase.yml"
    yml_file.write_text("key: value\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_yaml(root, explicit_files=[yml_file])

    assert ok is True
    assert str(yml_file) in captured["cmd"]


def test_check_yaml_no_yaml_in_explicit_selection_skips(tmp_path: Path) -> None:
    root = tmp_path

    ok = check_formatting._check_yaml(root, explicit_files=[root / "foo.py"], globs=["*.yaml"])

    assert ok is True


def test_check_yaml_quiet_suppresses_chrome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path

    ok = check_formatting._check_yaml(root, globs=[], quiet=True)

    assert ok is True
    out = capsys.readouterr().out
    assert out == ""


_VALID_YAML_TOML = 'checks = ["yaml"]\n\n[yaml]\nglobs = ["**/*.yaml", "**/*.yml"]\n'


def test_yaml_globs_loaded_from_config(tmp_path: Path) -> None:
    (tmp_path / ".check_formatting.toml").write_text(_VALID_YAML_TOML)
    config = check_formatting._load_project_config(tmp_path)
    assert config.yaml_globs == ["**/*.yaml", "**/*.yml"]


def test_yaml_globs_wrong_type_is_hard_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad_toml = 'checks = []\n\n[yaml]\nglobs = "**/*.yaml"\n'
    (tmp_path / ".check_formatting.toml").write_text(bad_toml)
    with pytest.raises(SystemExit) as exc_info:
        check_formatting._load_project_config(tmp_path)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "yaml" in out
