# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for check_formatting's .check_formatting.toml config loader — check_formatting project
"""Tests for check_formatting's per-repo config loader and its
consumption by the individual checker functions.

The loader follows `.check_rst.toml`'s contract: a committed, hand-authored
TOML declaration of project facts (never auto-detected), discovered at the
working directory only (no parent-directory walking), with unknown keys and
wrong-typed values failing loudly rather than being silently ignored.

The checker-consumption tests prove each `_check_*` function follows a
config-sourced value (a custom glob/dir/file list) rather than its old
hardcoded module-level constant, one checker at a time.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
from pathlib import Path

import pytest

from check_formatting import cli as check_formatting

_VALID_TOML = """\
checks = ["cpp", "meson", "web", "python", "json", "ini", "mypy", "rst"]

[cpp]
globs = ["src/**/*.cpp", "src/**/*.hpp"]

[web]
globs = ["www/**/*.html", "www/**/*.css", "www/**/*.js", "docs/_static/*.js"]

[python]
dirs = ["scripts", "tests"]

[json]
files = [".prettierrc", "package.json"]

[ini]
globs = ["build-configs/*.ini"]

[clang_tidy]
build_dir = "/tmp/vscode-build/example-project"

[rst]
dir = "docs"
"""


def test_config_sections_known_keys_match_expected_schema() -> None:
    """Characterization test, not a bug fix: pins `_CONFIG_SECTIONS`'s
    schema so a refactor of how it's built (e.g. deriving it from shared
    section/key constants instead of hand-listing each frozenset) can't
    silently drop or rename a checker's known config key.
    """
    assert {
        "cpp": frozenset({"globs"}),
        "web": frozenset({"globs"}),
        "python": frozenset({"dirs"}),
        "mypy": frozenset({"dirs"}),
        "json": frozenset({"files"}),
        "ini": frozenset({"globs"}),
        "clang_tidy": frozenset({"build_dir"}),
        "kconfig": frozenset({"build_combos"}),
        "shell": frozenset({"globs"}),
        "yaml": frozenset({"globs"}),
        "rst": frozenset({"dir"}),
    } == check_formatting._CONFIG_SECTIONS


def test_missing_config_file_is_hard_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        check_formatting._load_project_config(tmp_path)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert ".check_formatting.toml" in out


def test_unknown_top_level_key_is_hard_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".check_formatting.toml").write_text(_VALID_TOML + '\n[bogus]\nfoo = "bar"\n')
    with pytest.raises(SystemExit) as exc_info:
        check_formatting._load_project_config(tmp_path)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "bogus" in out


def test_unknown_section_key_is_hard_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad_toml = _VALID_TOML.replace('globs = ["src/**/*.cpp", "src/**/*.hpp"]', 'glob = ["src/**/*.cpp"]')
    (tmp_path / ".check_formatting.toml").write_text(bad_toml)
    with pytest.raises(SystemExit) as exc_info:
        check_formatting._load_project_config(tmp_path)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "glob" in out


def test_wrong_type_value_is_hard_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad_toml = _VALID_TOML.replace('globs = ["src/**/*.cpp", "src/**/*.hpp"]', 'globs = "src/**/*.cpp"')
    (tmp_path / ".check_formatting.toml").write_text(bad_toml)
    with pytest.raises(SystemExit) as exc_info:
        check_formatting._load_project_config(tmp_path)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "cpp" in out


def test_wrong_type_section_is_hard_error_without_traceback(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".check_formatting.toml").write_text("checks = []\ncpp = 42\n")

    with pytest.raises(SystemExit) as exc_info:
        check_formatting._load_project_config(tmp_path)

    assert exc_info.value.code == 1
    assert "[cpp] must be a table" in capsys.readouterr().out


def test_invalid_toml_is_hard_error_without_traceback(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".check_formatting.toml").write_text('checks = ["python"\n')

    with pytest.raises(SystemExit) as exc_info:
        check_formatting._load_project_config(tmp_path)

    assert exc_info.value.code == 1
    assert "invalid .check_formatting.toml" in capsys.readouterr().out


def test_unknown_checker_name_is_hard_error_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".check_formatting.toml").write_text('checks = ["bogus"]\n')

    with pytest.raises(SystemExit) as exc_info:
        check_formatting._load_project_config(tmp_path)

    assert exc_info.value.code == 1
    assert "unknown checker" in capsys.readouterr().out


def test_duplicate_checker_name_is_hard_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Duplicate entries would submit the same checker more than once and
    can race two mutating ``--fix`` runs against the same files."""
    (tmp_path / ".check_formatting.toml").write_text('checks = ["python", "python"]\n')

    with pytest.raises(SystemExit) as exc_info:
        check_formatting._load_project_config(tmp_path)

    assert exc_info.value.code == 1
    assert "duplicate checker(s): python" in capsys.readouterr().out


def test_valid_config_loads_correctly(tmp_path: Path) -> None:
    (tmp_path / ".check_formatting.toml").write_text(_VALID_TOML)
    config = check_formatting._load_project_config(tmp_path)
    assert config.checks == ["cpp", "meson", "web", "python", "json", "ini", "mypy", "rst"]
    assert config.cpp_globs == ["src/**/*.cpp", "src/**/*.hpp"]
    assert config.web_globs == ["www/**/*.html", "www/**/*.css", "www/**/*.js", "docs/_static/*.js"]
    assert config.python_dirs == ["scripts", "tests"]
    assert config.mypy_dirs == ["scripts", "tests"]
    assert config.json_files == [".prettierrc", "package.json"]
    assert config.ini_globs == ["build-configs/*.ini"]
    assert config.clang_tidy_build_dir == "/tmp/vscode-build/example-project"
    assert config.rst_dir == "docs"


def test_applied_config_is_echoed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".check_formatting.toml").write_text(_VALID_TOML)
    config = check_formatting._load_project_config(tmp_path)
    check_formatting._echo_project_config(".check_formatting.toml", config)
    out = capsys.readouterr().out
    assert out.startswith("config: .check_formatting.toml")
    assert "checks=" in out


def test_omitted_section_defaults_to_empty_not_an_error(tmp_path: Path) -> None:
    """A project without targets for some checkers may omit their sections
    rather than declaring empty globs it never uses."""
    minimal_toml = 'checks = ["python", "mypy", "rst"]\n\n[python]\ndirs = ["bin", "tests"]\n'
    (tmp_path / ".check_formatting.toml").write_text(minimal_toml)
    config = check_formatting._load_project_config(tmp_path)
    assert config.checks == ["python", "mypy", "rst"]
    assert config.python_dirs == ["bin", "tests"]
    assert config.mypy_dirs == ["bin", "tests"]
    assert config.cpp_globs == []
    assert config.web_globs == []
    assert config.json_files == []
    assert config.ini_globs == []
    assert config.clang_tidy_build_dir == ""
    assert config.rst_dir == ""


def test_check_ini_uses_configured_globs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_check_ini must follow a config-sourced glob list, not the old hardcoded _INI_GLOB."""
    root = tmp_path
    custom_dir = root / "custom-inis"
    custom_dir.mkdir()
    ini_file = custom_dir / "settings.ini"
    ini_file.write_text("[section]\nkey = value\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_ini(root, globs=["custom-inis/*.ini"])

    assert ok is True
    assert str(ini_file) in captured["cmd"]


def test_check_json_uses_configured_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_check_json must follow a config-sourced file list, not the old hardcoded _JSON_FILES."""
    root = tmp_path
    custom_file = root / "custom-config.json"
    custom_file.write_text("{}\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_json(root, files=["custom-config.json"])

    assert ok is True
    assert str(custom_file) in captured["cmd"]


def test_check_web_uses_configured_globs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_check_web must follow a config-sourced glob list, not the old hardcoded _WEB_GLOBS."""
    root = tmp_path
    custom_dir = root / "static-assets"
    custom_dir.mkdir()
    html_file = custom_dir / "page.html"
    html_file.write_text("<html></html>\n")

    captured_cmds: list[list[str]] = []

    def fake_fmt_stdout(cmd: list[str], cwd: Path) -> tuple[int, str]:
        captured_cmds.append(cmd)
        return 0, html_file.read_text()

    monkeypatch.setattr(check_formatting, "_fmt_stdout", fake_fmt_stdout)

    ok = check_formatting._check_web(root, diff=True, globs=["static-assets/*.html"])

    assert ok is True
    assert any(str(html_file) in cmd for cmd in captured_cmds)


def test_check_web_explicit_scope_uses_configured_globs_not_hardcoded_suffixes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    typescript_file = web_dir / "app.ts"
    typescript_file.write_text("const answer: number = 42;\n")
    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_web(
        tmp_path,
        explicit_files=[typescript_file],
        globs=["web/*.ts"],
    )

    assert ok is True
    assert str(typescript_file) in captured["cmd"]


def test_check_cpp_uses_configured_globs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_check_cpp must follow a config-sourced glob list, not the hardcoded src/**/*.cpp."""
    root = tmp_path
    custom_dir = root / "firmware"
    custom_dir.mkdir()
    cpp_file = custom_dir / "main.cpp"
    cpp_file.write_text("int main() { return 0; }\n")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_cpp(root, globs=["firmware/*.cpp"])

    assert ok is True
    assert str(cpp_file) in captured["cmd"]


def test_check_clang_tidy_uses_configured_cpp_globs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_check_clang_tidy's own independent cpp-glob copy must also follow config, not its old
    hardcoded src/**/*.cpp — closing the duplicate-hardcode bug versus _check_cpp."""
    root = tmp_path
    (root / "compile_commands.json").write_text("[]")

    custom_dir = root / "firmware"
    custom_dir.mkdir()
    cpp_file = custom_dir / "main.cpp"
    cpp_file.write_text("int main() { return 0; }\n")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/clang-tidy")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_clang_tidy(root, cpp_globs=["firmware/*.cpp"], build_dir=root)

    assert ok is True
    assert str(cpp_file) in captured["cmd"]


def test_check_python_uses_configured_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_check_python must follow a config-sourced dirs list, not the hardcoded ["scripts", "tests"]."""
    captured_cmds: list[list[str]] = []

    def fake_run_capture_merged(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        captured_cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="")

    monkeypatch.setattr(check_formatting, "_run_capture_merged", fake_run_capture_merged)

    ok = check_formatting._check_python(tmp_path, dirs=["source", "spec"])

    assert ok is True
    assert any("source" in cmd and "spec" in cmd for cmd in captured_cmds)


def test_check_mypy_uses_configured_dirs_matching_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_check_mypy must share the same config-sourced dirs list as _check_python — this is the
    fix for the pre-existing bug where the two checkers independently hardcoded
    ["scripts", "tests"] and could silently drift apart."""
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/mypy")
    monkeypatch.setattr(shutil, "rmtree", lambda path: None)
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: False)

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_mypy(tmp_path, dirs=["source", "spec"])

    assert ok is True
    assert "source" in captured["cmd"]
    assert "spec" in captured["cmd"]


def test_checker_kwargs_use_mypy_specific_dirs_when_configured(tmp_path: Path) -> None:
    """Mypy may intentionally cover a narrower source set than Ruff."""
    (tmp_path / ".check_formatting.toml").write_text(
        'checks = ["python", "mypy"]\n\n[python]\ndirs = ["bin", "tests"]\n\n[mypy]\ndirs = ["bin/std.py", "tests"]\n'
    )

    config = check_formatting._load_project_config(tmp_path)

    assert check_formatting._checker_kwargs("python", config) == {"dirs": ["bin", "tests"]}
    assert check_formatting._checker_kwargs("mypy", config) == {"dirs": ["bin/std.py", "tests"]}


def test_every_registered_checker_has_kwargs_and_fix_command_coverage(tmp_path: Path) -> None:
    """Every name in _CHECKERS must resolve both a kwargs dict and a fix
    command without error — guards against a future checker being added to
    _CHECKERS but forgotten in its own kwargs/fix-command wiring. Today's
    suite otherwise has no direct _checker_kwargs/_fix_command coverage at
    all for cpp, meson, cmake, kconfig, or shell — this closes that gap."""
    (tmp_path / ".check_formatting.toml").write_text('checks = ["cpp"]\n')
    config = check_formatting._load_project_config(tmp_path)

    for name in check_formatting._CHECKERS:
        kwargs = check_formatting._checker_kwargs(name, config, git_auto_detected=True)
        assert isinstance(kwargs, dict)
        command = check_formatting._fix_command(name, config, git_auto_detected=True)
        assert isinstance(command, str)
        assert command


@pytest.mark.parametrize("checker", ["python", "mypy"])
def test_python_checkers_restrict_explicit_files_to_configured_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker: str
) -> None:
    """Changed-file and explicit-file scopes must retain configured target
    boundaries instead of accepting every selected .py file."""
    included = tmp_path / "tests" / "test_std.py"
    included.parent.mkdir()
    included.write_text("def test_std() -> None:\n    pass\n")
    excluded = tmp_path / "bin" / "legacy_migration.py"
    excluded.parent.mkdir()
    excluded.write_text("value = 1\n")
    captured: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured.append(cmd)
        return 0

    def fake_run_capture_merged(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="")

    monkeypatch.setattr(check_formatting, "_run", fake_run)
    monkeypatch.setattr(check_formatting, "_run_capture_merged", fake_run_capture_merged)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: False)

    check = check_formatting._check_python if checker == "python" else check_formatting._check_mypy
    ok = check(tmp_path, explicit_files=[included, excluded], dirs=["bin/std.py", "tests"])

    assert ok is True
    assert captured
    assert all(str(included) in cmd for cmd in captured)
    assert all(str(excluded) not in cmd for cmd in captured)


def test_check_clang_tidy_uses_configured_build_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_check_clang_tidy must follow a config-sourced build_dir, not the hardcoded _CLANG_TIDY_DB."""
    root = tmp_path
    custom_build_dir = root / "custom-build"
    custom_build_dir.mkdir()
    (custom_build_dir / "compile_commands.json").write_text("[]")

    cpp_file = root / "main.cpp"
    cpp_file.write_text("int main() { return 0; }\n")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/clang-tidy")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_clang_tidy(root, cpp_globs=["*.cpp"], build_dir=custom_build_dir)

    assert ok is True
    assert str(custom_build_dir) in captured["cmd"]


def test_check_clang_tidy_unconfigured_build_dir_passes_without_requiring_clang_tidy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project with no `[clang_tidy]` section (build_dir=None) has nothing to analyze —
    this must vacuously pass, not fall back to the old hardcoded _CLANG_TIDY_DB path and
    fail because that source-project-specific directory doesn't exist here."""
    root = tmp_path
    monkeypatch.setattr(shutil, "which", lambda name: None)

    ok = check_formatting._check_clang_tidy(root, build_dir=None)

    assert ok is True


def test_check_clang_tidy_empty_string_build_dir_from_config_becomes_none(tmp_path: Path) -> None:
    """`_checker_kwargs` must translate an unset `[clang_tidy].build_dir` (empty string in
    ProjectConfig) into the `None` sentinel `_check_clang_tidy` expects — not
    `pathlib.Path("")`, which silently normalizes to `Path(".")` and would defeat the
    unconfigured-project skip above."""
    minimal_toml = 'checks = ["python"]\n\n[python]\ndirs = ["scripts"]\n'
    (tmp_path / ".check_formatting.toml").write_text(minimal_toml)
    config = check_formatting._load_project_config(tmp_path)

    kwargs = check_formatting._checker_kwargs("clang-tidy", config)

    assert kwargs["build_dir"] is None


@pytest.mark.parametrize("checker_name", ["web", "json", "ini", "yaml"])
def test_checker_kwargs_threads_git_scope_to_every_prettier_fixer(tmp_path: Path, checker_name: str) -> None:
    """Every Prettier-backed fixer must receive the CLI's auto-detected-scope fact."""
    (tmp_path / ".check_formatting.toml").write_text(_VALID_TOML)
    config = check_formatting._load_project_config(tmp_path)

    kwargs = check_formatting._checker_kwargs(checker_name, config, git_auto_detected=True)

    assert kwargs["git_auto_detected"] is True


def test_check_formatting_wires_config_into_checkers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The top-level check_formatting() must load .check_formatting.toml and thread its
    values into each checker — not just the config loader existing in isolation."""
    root = tmp_path
    custom_dir = root / "custom-inis"
    custom_dir.mkdir()
    ini_file = custom_dir / "settings.ini"
    ini_file.write_text("[section]\nkey = value\n")

    (root / ".check_formatting.toml").write_text('checks = ["ini"]\n\n[ini]\nglobs = ["custom-inis/*.ini"]\n')

    captured_cmds: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: pathlib.Path) -> int:
        captured_cmds.append(cmd)
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting.check_formatting(root)

    assert ok is True
    assert any(str(ini_file) in cmd for cmd in captured_cmds)


def test_check_formatting_explicit_checks_overrides_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An explicit checks= argument (mirroring --checks) must override the config's default list,
    while still threading that checker's own config-sourced values (here [json].files)."""
    root = tmp_path
    (root / "config.json").write_text("{}\n")
    (root / ".check_formatting.toml").write_text(
        'checks = ["ini"]\n\n[ini]\nglobs = ["*.ini"]\n\n[json]\nfiles = ["config.json"]\n'
    )

    captured_cmds: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: pathlib.Path) -> int:
        captured_cmds.append(cmd)
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting.check_formatting(root, checks=["json"])

    assert ok is True
    out = capsys.readouterr().out
    assert "prettier (JSON/JSONC)" in out
    assert "prettier-plugin-ini (INI)" not in out
    assert any(str(root / "config.json") in cmd for cmd in captured_cmds)


def test_check_formatting_prints_machine_parseable_summary_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A single stable, grep-able summary line must appear regardless of the box-drawing table
    formatting, modeled on check_rst's own 'check_rst: N file(s) checked, ...' precedent."""
    root = tmp_path
    (root / ".check_formatting.toml").write_text('checks = ["ini", "json"]\n\n[ini]\nglobs = ["*.ini"]\n')

    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 0)

    ok = check_formatting.check_formatting(root)

    assert ok is True
    out = capsys.readouterr().out
    assert "check_formatting: 2 checker(s) run, 2 passed, 0 failed" in out
