# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Real Nu backend integration tests — check_formatting project
"""Exercise the source package against a real system ``vnu`` executable."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SRC_DIR = Path(__file__).parent.parent / "src"
_VNU = shutil.which("vnu")

pytestmark = pytest.mark.skipif(_VNU is None, reason="vnu is not installed")


def _package_env() -> dict[str, str]:
    """Expose the source-layout package to an isolated CLI subprocess."""
    env = dict(os.environ)
    current_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SRC_DIR)
    if current_pythonpath:
        env["PYTHONPATH"] += os.pathsep + current_pythonpath
    return env


def _write_project(root: Path, files: dict[str, str], *, args: list[str] | None = None) -> None:
    """Write configured Nu targets in a synthetic consuming project."""
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    args_toml = ", ".join(repr(arg) for arg in (args or []))
    (root / ".check_formatting.toml").write_text(
        f'checks = ["vnu"]\n\n[vnu]\nglobs = ["assets/*.html", "assets/*.css", "assets/*.svg"]\nargs = [{args_toml}]\n'
    )


def _run_vnu_check(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the source package's CLI from a synthetic consuming project."""
    return subprocess.run(
        [sys.executable, "-m", "check_formatting", "--all", "--checks", "vnu", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_package_env(),
    )


def test_real_vnu_accepts_clean_html_css_and_svg(tmp_path: Path) -> None:
    _write_project(
        tmp_path,
        {
            "assets/index.html": (
                '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                "<title>Clean document</title></head><body><main><h1>Clean document</h1>"
                "</main></body></html>\n"
            ),
            "assets/styles.css": "body { color: black; }\n",
            "assets/icon.svg": (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                '<title>Square</title><rect width="10" height="10"/></svg>\n'
            ),
        },
    )

    result = _run_vnu_check(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "vnu (HTML/CSS/SVG conformance)" in result.stdout


def test_real_vnu_rejects_invalid_html_content_model(tmp_path: Path) -> None:
    _write_project(
        tmp_path,
        {
            "assets/index.html": (
                '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                "<title>Invalid document</title></head><body><ul><div>invalid</div></ul>"
                "</body></html>\n"
            )
        },
    )

    result = _run_vnu_check(tmp_path)

    assert result.returncode == 1
    assert "not allowed as child" in result.stdout


def test_real_vnu_checks_standalone_css(tmp_path: Path) -> None:
    _write_project(tmp_path, {"assets/styles.css": "body { color: definitely-not-a-color; }\n"})

    result = _run_vnu_check(tmp_path)

    assert result.returncode == 1
    assert "color" in result.stdout.lower()


def test_real_vnu_checks_standalone_svg(tmp_path: Path) -> None:
    _write_project(
        tmp_path,
        {
            "assets/icon.svg": (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><not-an-svg-element/></svg>\n'
            )
        },
    )

    result = _run_vnu_check(tmp_path)

    assert result.returncode == 1
    assert "not-an-svg-element" in result.stdout


def test_real_vnu_warnings_are_failures(tmp_path: Path) -> None:
    _write_project(
        tmp_path,
        {
            "assets/index.html": (
                '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                "<title>Warning document</title></head><body><section>Content</section>"
                "</body></html>\n"
            )
        },
    )

    result = _run_vnu_check(tmp_path)

    assert result.returncode == 1
    assert "lacks heading" in result.stdout


def test_real_vnu_fix_mode_never_modifies_files(tmp_path: Path) -> None:
    target_content = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>Invalid document</title></head><body><ul><div>invalid</div></ul>"
        "</body></html>\n"
    )
    _write_project(tmp_path, {"assets/index.html": target_content})
    target = tmp_path / "assets" / "index.html"
    before = target.read_bytes()

    result = _run_vnu_check(tmp_path, "--fix")

    assert result.returncode == 1
    assert target.read_bytes() == before
