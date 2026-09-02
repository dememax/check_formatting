# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Real ShellCheck backend integration tests — check_formatting project
"""Exercise the source package against a real system ShellCheck executable."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SRC_DIR = Path(__file__).parent.parent / "src"
_SHELLCHECK = shutil.which("shellcheck")

pytestmark = pytest.mark.skipif(_SHELLCHECK is None, reason="shellcheck is not installed")


def _package_env() -> dict[str, str]:
    """Expose the source-layout package to an isolated CLI subprocess."""
    env = dict(os.environ)
    current_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SRC_DIR)
    if current_pythonpath:
        env["PYTHONPATH"] += os.pathsep + current_pythonpath
    return env


def _write_project(root: Path, script_name: str, script: str) -> Path:
    """Write one configured shell target and return its path."""
    scripts = root / "scripts"
    scripts.mkdir()
    target = scripts / script_name
    target.write_text(script)
    (root / ".check_formatting.toml").write_text(f'checks = ["shell"]\n\n[shell]\nglobs = ["scripts/{script_name}"]\n')
    return target


def _run_shell_check(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the source package's CLI from a synthetic consuming project."""
    return subprocess.run(
        [sys.executable, "-m", "check_formatting", "--all", "--checks", "shell", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_package_env(),
    )


def test_real_shellcheck_accepts_clean_script(tmp_path: Path) -> None:
    _write_project(tmp_path, "clean.sh", "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"${1:-ok}\"\n")

    result = _run_shell_check(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "shellcheck (shell scripts)" in result.stdout


def test_real_shellcheck_preserves_violation_code_and_exit_status(tmp_path: Path) -> None:
    _write_project(tmp_path, "bad.sh", "#!/usr/bin/env bash\necho $1\n")

    result = _run_shell_check(tmp_path)

    assert result.returncode == 1
    assert "SC2086" in result.stdout


def test_real_shellcheck_analyzes_extensionless_script(tmp_path: Path) -> None:
    _write_project(tmp_path, "tool", "#!/usr/bin/env bash\necho $1\n")

    result = _run_shell_check(tmp_path)

    assert result.returncode == 1
    assert "SC2086" in result.stdout


def test_real_shellcheck_respects_project_configuration(tmp_path: Path) -> None:
    _write_project(tmp_path, "bad.sh", "#!/usr/bin/env bash\necho $1\n")
    (tmp_path / ".shellcheckrc").write_text("disable=SC2086\n")

    result = _run_shell_check(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_real_shellcheck_fix_mode_never_modifies_script(tmp_path: Path) -> None:
    script = _write_project(tmp_path, "bad.sh", "#!/usr/bin/env bash\necho $1\n")
    before = script.read_bytes()

    result = _run_shell_check(tmp_path, "--fix")

    assert result.returncode == 1
    assert script.read_bytes() == before
