# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Standalone installation and release-artifact tests — check_formatting project
"""Black-box contracts for building and installing the standalone utility."""

from __future__ import annotations

import hashlib
import os
import runpy
import shutil
import subprocess
import sys
import types
import zipfile
from email.parser import BytesParser
from email.policy import default
from pathlib import Path

import pytest

from check_formatting import __version__

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(*command: str | Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(argument) for argument in command],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _committed_project_copy(destination: Path) -> Path:
    project = destination / "project"
    shutil.copytree(
        _PROJECT_ROOT,
        project,
        ignore=shutil.ignore_patterns(
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "__pycache__",
            "*.egg-info",
            "*.pyc",
            "build",
            "dist",
            "_build",
        ),
    )
    assert _run("git", "init", "-q", project, cwd=destination).returncode == 0
    assert _run("git", "-C", project, "add", ".").returncode == 0
    commit = _run(
        "git",
        "-C",
        project,
        "-c",
        "user.name=Packaging test",
        "-c",
        "user.email=packaging-test@example.invalid",
        "commit",
        "-qm",
        "test fixture",
    )
    assert commit.returncode == 0, commit.stdout + commit.stderr
    return project


@pytest.fixture(scope="module")
def release_artifacts(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    root = tmp_path_factory.mktemp("standalone-release")
    project = _committed_project_copy(root)
    first = root / "first"
    second = root / "second"

    for output_dir in (first, second):
        result = _run(
            sys.executable,
            project / "tools" / "build_wheel.py",
            "--output-dir",
            output_dir,
            cwd=project,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    wheels = list(first.glob("check_formatting-*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0]
    checksum = wheel.with_suffix(f"{wheel.suffix}.sha256")
    assert checksum.is_file()
    assert wheel.read_bytes() == (second / wheel.name).read_bytes()
    return project, wheel, checksum


def test_release_builder_produces_verified_wheel_and_checksum(
    release_artifacts: tuple[Path, Path, Path],
) -> None:
    _project, wheel, checksum = release_artifacts
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert checksum.read_text(encoding="utf-8") == f"{digest}  {wheel.name}\n"

    with zipfile.ZipFile(wheel) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert "check_formatting/__init__.py" in names
        assert not any(name.startswith("docs/") for name in names)

        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser(policy=default).parsebytes(archive.read(metadata_name))

    project_urls = set(metadata.get_all("Project-URL", []))
    assert "Documentation, https://github.com/dememax/check_formatting/blob/main/docs/guide.rst" in project_urls
    assert "Issues, https://github.com/dememax/check_formatting/issues" in project_urls


def test_release_builder_rejects_a_dirty_checkout(tmp_path: Path) -> None:
    project = _committed_project_copy(tmp_path)
    with (project / "README.md").open("a", encoding="utf-8") as stream:
        stream.write("\nnot committed\n")

    result = _run(
        sys.executable,
        project / "tools" / "build_wheel.py",
        "--output-dir",
        tmp_path / "artifacts",
        cwd=project,
    )

    assert result.returncode == 1
    assert "worktree is not clean" in result.stderr


def test_standalone_installer_replaces_system_site_environment_and_manages_launcher(
    release_artifacts: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    project, wheel, _checksum = release_artifacts
    prefix = tmp_path / "prefix"
    environment = prefix / "check_formatting"
    environment.parent.mkdir(parents=True)
    create = _run(sys.executable, "-m", "venv", "--system-site-packages", environment)
    assert create.returncode == 0, create.stdout + create.stderr

    installer = project / "tools" / "install_standalone.py"
    refused = _run(sys.executable, installer, "install", wheel, "--prefix", prefix)
    assert refused.returncode == 1
    assert "--recreate" in refused.stderr

    installed = _run(sys.executable, installer, "install", wheel, "--prefix", prefix, "--recreate")
    assert installed.returncode == 0, installed.stdout + installed.stderr
    configuration = (environment / "pyvenv.cfg").read_text(encoding="utf-8")
    assert "include-system-site-packages = false" in configuration

    launcher = prefix / "bin" / "check_formatting"
    assert launcher.is_file()
    assert os.access(launcher, os.X_OK)
    version = _run(launcher, "--version")
    assert version.returncode == 0, version.stdout + version.stderr
    assert version.stdout.splitlines()[0] == f"check_formatting {__version__}"

    uninstalled = _run(sys.executable, installer, "uninstall", "--prefix", prefix)
    assert uninstalled.returncode == 0, uninstalled.stdout + uninstalled.stderr
    assert not environment.exists()
    assert not launcher.exists()


def test_sphinx_release_comes_from_package_version(monkeypatch: pytest.MonkeyPatch) -> None:
    package = types.ModuleType("check_formatting")
    package.__version__ = "9.8.7"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "check_formatting", package)

    configuration = runpy.run_path(str(_PROJECT_ROOT / "docs" / "conf.py"))

    assert configuration["version"] == "9.8.7"
    assert configuration["release"] == "9.8.7"
