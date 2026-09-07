# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for check_formatting's Nu web-conformance checker — check_formatting project
"""Tests for the analysis-only ``vnu`` HTML/CSS/SVG checker."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from check_formatting import cli as check_formatting

if TYPE_CHECKING:
    from pathlib import Path


def _write_targets(root: Path) -> list[Path]:
    """Create one target for every document type handled by Nu."""
    targets = [root / "index.html", root / "styles.css", root / "icon.svg"]
    for target in targets:
        target.write_text("content\n")
    return sorted(targets)


def test_check_vnu_enables_strict_html_css_and_svg_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    targets = _write_targets(tmp_path)
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(shutil, "which", lambda name: "/home/max/opt/bin/vnu")

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_vnu(
        tmp_path,
        globs=["*.html", "*.css", "*.svg"],
        args=["--filterfile", ".vnu-filter"],
    )

    assert ok is True
    assert captured["cmd"] == [
        "/home/max/opt/bin/vnu",
        "--Werror",
        "--also-check-css",
        "--also-check-svg",
        "--filterfile",
        ".vnu-filter",
        *(str(target) for target in targets),
    ]


def test_check_vnu_deduplicates_overlapping_globs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "index.html"
    target.write_text("content\n")
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/vnu")

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_vnu(tmp_path, globs=["*.html", "**/*.html"])

    assert ok is True
    assert captured["cmd"].count(str(target)) == 1


@pytest.mark.parametrize("suffix", [".html", ".htm", ".xhtml", ".xht", ".css", ".svg"])
def test_check_vnu_explicit_selection_recognizes_every_supported_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    target = tmp_path / f"target{suffix}"
    target.write_text("content\n")
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/vnu")

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_vnu(tmp_path, explicit_files=[target])

    assert ok is True
    assert str(target) in captured["cmd"]


def test_check_vnu_explicit_selection_still_respects_configured_globs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    included = tmp_path / "published" / "index.html"
    included.parent.mkdir()
    included.write_text("content\n")
    outside = tmp_path / "templates" / "fragment.html"
    outside.parent.mkdir()
    outside.write_text("content\n")
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/vnu")

    def fake_run(cmd: list[str], cwd: Path) -> int:
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_vnu(
        tmp_path,
        explicit_files=[included, outside],
        globs=["published/*.html"],
    )

    assert ok is True
    assert str(included) in captured["cmd"]
    assert str(outside) not in captured["cmd"]


def test_check_vnu_missing_backend_fails_when_files_are_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "index.html").write_text("content\n")
    monkeypatch.setattr(shutil, "which", lambda name: None)

    ok = check_formatting._check_vnu(tmp_path, globs=["*.html"])

    assert ok is False
    assert "vnu not found" in capsys.readouterr().out


def test_check_vnu_empty_scope_passes_without_requiring_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    assert check_formatting._check_vnu(tmp_path, globs=[]) is True


@pytest.mark.parametrize("mode", ["fix", "diff"])
def test_check_vnu_fix_and_diff_modes_run_analysis_without_modifying_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    target = tmp_path / "index.html"
    target.write_text("content\n")
    before = target.read_bytes()

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/vnu")
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 1)

    ok = check_formatting._check_vnu(
        tmp_path,
        globs=["*.html"],
        fix=mode == "fix",
        diff=mode == "diff",
    )

    assert ok is False
    assert target.read_bytes() == before


def test_check_vnu_verbose_reports_resolved_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "index.html"
    target.write_text("content\n")
    tool_info_calls: list[tuple[str, Path]] = []

    monkeypatch.setattr(shutil, "which", lambda name: "/home/max/opt/bin/vnu")
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 0)
    monkeypatch.setattr(
        check_formatting,
        "_print_tool_info",
        lambda tool, cwd: tool_info_calls.append((tool, cwd)),
    )

    ok = check_formatting._check_vnu(tmp_path, globs=["*.html"], verbose=True)

    assert ok is True
    assert tool_info_calls == [("/home/max/opt/bin/vnu", tmp_path)]


def test_vnu_config_is_independent_from_prettier_web_scope(tmp_path: Path) -> None:
    (tmp_path / ".check_formatting.toml").write_text(
        """checks = ["web", "vnu"]

[web]
globs = ["sources/*.html", "sources/*.js"]

[vnu]
globs = ["published/*.html", "published/*.css", "published/*.svg"]
args = ["--filterfile", ".vnu-filter"]
"""
    )

    config = check_formatting._load_project_config(tmp_path)

    assert config.web_globs == ["sources/*.html", "sources/*.js"]
    assert config.vnu_globs == [
        "published/*.html",
        "published/*.css",
        "published/*.svg",
    ]
    assert config.vnu_args == ["--filterfile", ".vnu-filter"]
    assert check_formatting._checker_kwargs("vnu", config) == {
        "globs": config.vnu_globs,
        "args": config.vnu_args,
    }


def test_vnu_native_args_are_optional(tmp_path: Path) -> None:
    (tmp_path / ".check_formatting.toml").write_text('checks = ["vnu"]\n\n[vnu]\nglobs = ["public/**/*.html"]\n')

    config = check_formatting._load_project_config(tmp_path)

    assert config.vnu_args == []


@pytest.mark.parametrize("forbidden_arg", ["--errors-only", "--exit-zero-always", "--css", "--svg"])
def test_vnu_args_reject_validation_weakening_options(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], forbidden_arg: str
) -> None:
    """See docs/roadmap/vnu-message-suppression-ergonomics.rst, Finding 3:
    ``--errors-only``/``--exit-zero-always`` bypass ``--Werror``'s exit-code
    guarantee outright, and ``--css``/``--svg`` force every selected file to
    be parsed as CSS/SVG regardless of its real type — both silently weaken
    the adapter's advertised strict HTML/CSS/SVG validation contract instead
    of narrowing one specific finding.
    """
    (tmp_path / ".check_formatting.toml").write_text(
        f'checks = ["vnu"]\n\n[vnu]\nglobs = ["*.html"]\nargs = ["{forbidden_arg}"]\n'
    )

    with pytest.raises(SystemExit) as exc_info:
        check_formatting._load_project_config(tmp_path)

    assert exc_info.value.code == 1
    assert forbidden_arg in capsys.readouterr().out


def test_vnu_args_allow_safe_native_options(tmp_path: Path) -> None:
    (tmp_path / ".check_formatting.toml").write_text(
        'checks = ["vnu"]\n\n[vnu]\nglobs = ["*.html"]\n'
        'args = ["--filterpattern", ".*Trailing slash.*", "--asciiquotes"]\n'
    )

    config = check_formatting._load_project_config(tmp_path)

    assert config.vnu_args == ["--filterpattern", ".*Trailing slash.*", "--asciiquotes"]


@pytest.mark.parametrize(
    ("key", "value"),
    [("globs", '"*.html"'), ("args", '"--errors-only"')],
)
def test_vnu_config_lists_reject_wrong_types(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    key: str,
    value: str,
) -> None:
    globs = value if key == "globs" else '["*.html"]'
    args = value if key == "args" else "[]"
    (tmp_path / ".check_formatting.toml").write_text(f"checks = []\n\n[vnu]\nglobs = {globs}\nargs = {args}\n")

    with pytest.raises(SystemExit) as exc_info:
        check_formatting._load_project_config(tmp_path)

    assert exc_info.value.code == 1
    assert key in capsys.readouterr().out


def test_vnu_is_registered_as_analysis_only() -> None:
    checker = check_formatting._CHECKERS["vnu"]

    assert checker.label == "vnu (HTML/CSS/SVG conformance)"
    assert checker.auto_fix is False
    assert "no automatic fix" in checker.fix_command_fn(None, False)  # type: ignore[arg-type]


def test_check_vnu_skip_info_messages_hint_appears_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """See docs/roadmap/vnu-message-suppression-ergonomics.rst, Finding 1: a
    filtered-out info message still fails ``--Werror`` with no visible
    output, so ``check_formatting`` must explain why itself.
    """
    (tmp_path / "index.html").write_text("content\n")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/vnu")
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 1)

    ok = check_formatting._check_vnu(tmp_path, globs=["*.html"], args=["--skip-info-messages"])

    assert ok is False
    out = capsys.readouterr().out
    assert "--skip-info-messages" in out
    assert "vnu exited with status 1" in out


def test_check_vnu_no_hint_when_skip_info_messages_not_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "index.html").write_text("content\n")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/vnu")
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 1)

    ok = check_formatting._check_vnu(tmp_path, globs=["*.html"], args=["--filterfile", ".vnu-filter"])

    assert ok is False
    assert "--skip-info-messages" not in capsys.readouterr().out


def test_check_vnu_no_hint_on_success_even_with_skip_info_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "index.html").write_text("content\n")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/vnu")
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 0)

    ok = check_formatting._check_vnu(tmp_path, globs=["*.html"], args=["--skip-info-messages"])

    assert ok is True
    assert "vnu exited with status" not in capsys.readouterr().out


def test_check_vnu_skip_info_messages_hint_survives_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Never suppressed by ``--quiet``, matching this project's convention
    that ``--quiet`` hides chrome, never a finding or failure explanation.
    """
    (tmp_path / "index.html").write_text("content\n")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/vnu")
    monkeypatch.setattr(check_formatting, "_run", lambda cmd, cwd: 1)

    ok = check_formatting._check_vnu(tmp_path, globs=["*.html"], args=["--skip-info-messages"], quiet=True)

    assert ok is False
    assert "--skip-info-messages" in capsys.readouterr().out
