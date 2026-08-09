# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Import-sanity and no-cycle tests for the cli package split — check_formatting project
"""`check_formatting.cli` used to be a single flat `cli.py`; it is now a
package (`_config`, `_selection`, `_subprocess`, `_prettier`, `_checkers`,
`_registry`, plus `__init__.py`'s dispatch loop/CLI entry point/re-exports).

Cross-submodule calls to the handful of names tests monkeypatch on the
package itself (e.g. `monkeypatch.setattr(check_formatting, "_run", ...)`)
go through `from check_formatting import cli` + a deferred `cli.<name>(...)`
attribute lookup rather than a plain `from ._x import name` — the latter
binds at import time and would silently stop observing a patch applied to
the package later. That pattern only works if importing `check_formatting
import cli` from inside a submodule doesn't itself deadlock/fail while the
package is still mid-initialization — these tests pin that down directly,
each importing in a cold interpreter (no `sys.modules` cache from a prior
import in the same process) rather than relying on pytest's collection
having already warmed the cache in some other order.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

from check_formatting import cli as check_formatting
from check_formatting.cli import _checkers, _config, _prettier, _registry, _selection, _subprocess

_SUBMODULES = ("_checkers", "_config", "_prettier", "_registry", "_selection", "_subprocess")

# This project has no editable install; pytest itself resolves `check_formatting`
# via its own `pythonpath = ["src"]` setting (pyproject.toml), which a spawned
# subprocess does not inherit — set it explicitly so the cold interpreter can
# find the package the same way pytest's own process does.
_SRC_DIR = str(pathlib.Path(__file__).resolve().parent.parent / "src")


def _run_cold_import(statement: str) -> subprocess.CompletedProcess[str]:
    """Run *statement* in a brand-new interpreter with no warmed sys.modules cache."""
    env = dict(os.environ, PYTHONPATH=_SRC_DIR)
    return subprocess.run(
        [sys.executable, "-c", statement],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def test_cli_package_imports_cold_with_no_cycle_error() -> None:
    result = _run_cold_import("import check_formatting.cli")
    assert result.returncode == 0, result.stderr


def test_each_cli_submodule_imports_cold_as_the_first_import() -> None:
    """Import each submodule directly, as the *first* thing the interpreter
    does — this is what forces Python to initialize the still-empty parent
    `check_formatting.cli` package as a side effect, exactly the partial-
    initialization scenario a submodule's own `from check_formatting import
    cli` must survive regardless of which submodule happens to trigger it.
    """
    for name in _SUBMODULES:
        result = _run_cold_import(f"import check_formatting.cli.{name}")
        assert result.returncode == 0, f"{name}: {result.stderr}"


def test_cli_submodules_expose_their_expected_public_surface() -> None:
    """Characterization test pinning each submodule's own top-level
    definitions — a safety net against a future move accidentally leaving a
    function orphaned or misfiled.
    """
    assert hasattr(_config, "ProjectConfig")
    assert hasattr(_config, "_load_project_config")
    assert hasattr(_selection, "_detect_changed_files")
    assert hasattr(_selection, "_batched_git_diff_hunk_ranges")
    assert hasattr(_subprocess, "_run")
    assert hasattr(_subprocess, "_make_log")
    assert hasattr(_prettier, "_best_effort_prettier_fix")
    assert hasattr(_checkers, "_check_cpp")
    assert hasattr(_checkers, "_check_rst")
    assert hasattr(_registry, "_CHECKERS")
    assert hasattr(_registry, "Checker")


def test_cli_package_reexports_everything_the_test_suite_patches_directly() -> None:
    """Every name the wider test suite monkeypatches or reads off
    `check_formatting.cli` directly must resolve there — this is the
    contract the whole split is built to preserve unchanged.
    """
    reexported = (
        "_CHECKERS",
        "_CONFIG_SECTIONS",
        "_MYPY_CACHE_VERSION_MARKER",
        "_batched_git_diff_hunk_ranges",
        "_best_effort_prettier_fix",
        "_best_effort_prettier_target",
        "_check_clang_tidy",
        "_check_cmake",
        "_check_cpp",
        "_check_ini",
        "_check_json",
        "_check_kconfig",
        "_check_meson",
        "_check_mypy",
        "_check_python",
        "_check_rst",
        "_check_shell",
        "_check_web",
        "_check_yaml",
        "_checker_kwargs",
        "_detect_changed_files",
        "_echo_project_config",
        "_file_matches_any_glob",
        "_fix_command",
        "_fix_prettier_files",
        "_git_diff_hunk_ranges",
        "_invalidate_mypy_cache_if_version_changed",
        "_is_git_auto_detected_scope",
        "_load_project_config",
        "_merge_within_hunk_ranges",
        "_parse_git_diff_hunks_by_relpath",
        "_report_prettier_files_git_scoped",
        "_resolve_explicit_files",
        "_run",
        "_run_capture_merged",
        "_show_diff",
        "_tool_version_string",
    )
    missing = [name for name in reexported if not hasattr(check_formatting, name)]
    assert missing == []
