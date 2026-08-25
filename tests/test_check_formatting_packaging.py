# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Wheel-build regression tests — check_formatting project
"""Black-box tests for wheel contents produced from a reused source tree."""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_wheel_prunes_deleted_module_left_in_build_tree(tmp_path: Path) -> None:
    """A deleted source module must not survive in a later wheel merely
    because setuptools' reusable ``build/lib`` tree still contains it."""
    project = tmp_path / "project"
    project.mkdir()
    for filename in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(_PROJECT_ROOT / filename, project / filename)
    setup_py = _PROJECT_ROOT / "setup.py"
    if setup_py.is_file():
        shutil.copy2(setup_py, project / setup_py.name)
    shutil.copytree(
        _PROJECT_ROOT / "src",
        project / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )

    stale_module = project / "build" / "lib" / "check_formatting" / "cli.py"
    stale_module.parent.mkdir(parents=True)
    stale_module.write_text("raise AssertionError('deleted module packaged')\n", encoding="utf-8")
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-build-isolation",
            "--no-deps",
            "--wheel-dir",
            str(wheel_dir),
            str(project),
        ],
        cwd=project,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as wheel:
        members = set(wheel.namelist())
    assert "check_formatting/cli/__init__.py" in members
    assert "check_formatting/cli.py" not in members
