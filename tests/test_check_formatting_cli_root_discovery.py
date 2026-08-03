# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# CLI project-root discovery regression tests — check_formatting project
"""Pins the one behavior change required for check_formatting to work as a
standalone, externally-installed tool (mirroring check_rst's own contract:
"automatic configuration treats the current working directory as the project
root").

Before this fix, ``main()`` computed the project root as
``pathlib.Path(__file__).resolve().parent.parent`` — correct only when the
script happens to live at ``<repo>/scripts/check_formatting``, which was
true in the original source layout but is never true once the tool is
installed once and invoked from many different project directories.  Reproduced directly
against the unfixed script before writing this test: invoking it with
``cwd=<some other project>`` still looked for ``.check_formatting.toml``
relative to the script's own install location, not the caller's directory.

The fix: the project root is the invoking process's current working
directory, full stop — no parent-directory walking, matching check_rst's
own documented discovery contract exactly.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from check_formatting import __version__

_SRC_DIR = Path(__file__).parent.parent / "src"


def _package_env() -> dict[str, str]:
    """Expose the source-layout package to subprocesses without installing it."""
    env = dict(os.environ)
    current_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SRC_DIR)
    if current_pythonpath:
        env["PYTHONPATH"] += os.pathsep + current_pythonpath
    return env


def test_cli_reports_package_version_without_project_config(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "check_formatting", "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_package_env(),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"check_formatting {__version__}\n"


def test_cli_discovers_config_at_invoking_directory_not_script_location(tmp_path: Path) -> None:
    """Running the tool with cwd=<a project directory> must use THAT directory's
    .check_formatting.toml, regardless of where check_formatting itself lives."""
    (tmp_path / ".check_formatting.toml").write_text("checks = []\n")

    result = subprocess.run(
        [sys.executable, "-m", "check_formatting", "--all"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_package_env(),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "not found" not in result.stdout


def test_cli_reports_missing_config_at_invoking_directory(tmp_path: Path) -> None:
    """The hard-error path must also name the CALLER's directory, not the
    script's own install location, when no config is present there."""
    result = subprocess.run(
        [sys.executable, "-m", "check_formatting", "--all"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_package_env(),
    )

    assert result.returncode == 1
    assert str(tmp_path) in result.stdout
