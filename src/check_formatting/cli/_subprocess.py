# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
"""Subprocess/output plumbing shared by every checker: running a formatter
live-streamed or capture-based, printing diffs, and the quiet-aware
``log()`` helper. No checker-specific logic lives here.
"""

from __future__ import annotations

import difflib
import pathlib
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

from check_formatting import cli

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def _run(cmd: list[str], cwd: pathlib.Path) -> int:
    """Run a formatter command, streaming its output to the terminal.

    Returns
    -------
    int
        Exit code of the subprocess.
    """
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError:
        print(f"ERROR: command not found: {cmd[0]!r}")
        return 127  # POSIX "command not found"
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
    proc.wait()
    return proc.returncode


def _fmt_stdout(cmd: list[str], cwd: pathlib.Path, *, input_text: str | None = None) -> tuple[int, str]:
    """Run a formatter capturing stdout; optionally feed *input_text* via stdin.

    Used in diff mode to obtain the formatted content of a file without
    modifying it on disk, and by the Prettier fixer's canonical-equivalence
    validation to format an in-memory candidate using ``--stdin-filepath``.

    Returns
    -------
    tuple[int, str]
        Exit code and captured stdout of the subprocess.
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            input=input_text,
        )
    except FileNotFoundError:
        print(f"ERROR: command not found: {cmd[0]!r}")
        return 127, ""
    if result.stderr:
        sys.stdout.write(result.stderr)
        sys.stdout.flush()
    return result.returncode, result.stdout


def _run_capture_merged(cmd: list[str], cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    """Run *cmd* capturing merged stdout+stderr as one stream, not streamed live
    to the terminal like :func:`_run`, and not kept separate like
    :func:`_fmt_stdout` — used where output must be scanned/filtered
    line-by-line before any of it is shown (the kconfig checker's per-combo
    warning-count scan over west/CMake's combined output). Raises
    ``FileNotFoundError`` the same way ``subprocess.run`` itself does; callers
    that need a missing-binary message of their own catch it directly, the
    same convention :func:`_run`/:func:`_fmt_stdout` each use internally.
    """
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")


def _tool_version_string(
    binary: str | pathlib.Path,
    cwd: pathlib.Path,
    version_args: list[str] | None = None,
) -> str | None:
    """Return *binary*'s version-ish string: the first line of stdout+stderr
    from running ``<binary> --version`` (or *version_args*).

    Returns ``None`` when the subprocess couldn't even be run (missing
    binary, not executable, timed out) — distinct from ``""``, returned when
    the tool ran but printed nothing to either stream. Shared by
    :func:`_print_tool_info`'s verbose-mode banner and the mypy checker's
    version-gated cache invalidation, which both need this same lookup —
    one for display, one for comparison.
    """
    binary_str = str(binary)
    if version_args is None:
        version_args = ["--version"]
    try:
        result = subprocess.run(
            [binary_str, *version_args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except FileNotFoundError, OSError, subprocess.TimeoutExpired:
        return None
    raw = (result.stdout + result.stderr).strip()
    return raw.splitlines()[0] if raw else ""


def _print_tool_info(
    binary: str | pathlib.Path,
    cwd: pathlib.Path,
    version_args: list[str] | None = None,
) -> None:
    """Print the resolved binary path and version string in verbose mode."""
    binary_str = str(binary)
    resolved = binary_str if pathlib.Path(binary_str).is_absolute() else shutil.which(binary_str) or binary_str
    version = cli._tool_version_string(binary, cwd, version_args)
    version_line = "(unavailable)" if version is None else (version or "(unknown)")
    print(f"  Binary:  {resolved}")
    print(f"  Version: {version_line}")


def _make_log(quiet: bool) -> Callable[..., None]:
    """Return a ``print``-like function that is a no-op when *quiet* is True.

    Used by every checker for its own chrome (section banners, "▶ command"
    announcements, "(no files found)"-style scope notices) — never for
    genuine ERROR messages, diff content, or the wrapped tool's real
    output, all of which stay on bare ``print`` and are unaffected by
    --quiet.  Mirrors check_rst's verbosity ladder: --quiet suppresses
    this script's own chrome, not the wrapped tools' findings.
    """

    def log(message: str = "") -> None:
        if not quiet:
            print(message)

    return log


def _log_analysis_only(tool: str, verb: str, fix: bool, diff: bool, log: Callable[..., None]) -> None:
    """Log the "no fix/diff mode of its own" notice shared by every report-only
    checker (mypy, clang-tidy, kconfig, shell): asked to fix or diff, each just
    re-runs its own analysis (*verb*) instead.
    """
    if fix:
        log(f"  ({tool} has no fix mode — running {verb})")
    elif diff:
        log(f"  ({tool} has no diff mode — running {verb})")


def _show_diff(original: str, formatted: str, label: str) -> bool:
    """Print a unified diff of *original* vs *formatted*; return True if they differ."""
    if original == formatted:
        return False
    lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            formatted.splitlines(keepends=True),
            fromfile=label,
            tofile=f"{label} (formatted)",
        )
    )
    sys.stdout.writelines(lines)
    sys.stdout.flush()
    return True


def _diff_files_by_command(
    files: Sequence[pathlib.Path],
    root: pathlib.Path,
    tool_name: str,
    cmd_for_file: Callable[[pathlib.Path], list[str]],
) -> bool:
    """Run ``cmd_for_file(f)`` per file (stdout) and show a unified diff for each
    violation. Shared by every checker whose diff mode is "reformat to stdout,
    diff against the original" — clang-format, cmake-format, and (via
    :func:`_prettier_diff`) prettier's four checkers.

    Returns True if no file would change, False on a violation or a *tool_name*
    invocation failure (exit 127 — command not found).
    """
    any_violation = False
    for f in files:
        rc, formatted = cli._fmt_stdout(cmd_for_file(f), cwd=root)
        if rc == 127:
            return False
        if rc != 0:
            print(f"ERROR: {tool_name} exited {rc} on {f.name}")
            return False
        if cli._show_diff(f.read_text(encoding="utf-8"), formatted, str(f.relative_to(root))):
            any_violation = True
    return not any_violation


def _prettier_diff(files: list[pathlib.Path], root: pathlib.Path) -> bool:
    """Run prettier per-file and show a unified diff for each violation.

    Shared by the web, JSON, INI, and YAML checkers' diff mode (identical loop).
    Returns True if no file would change, False on a violation or a
    prettier invocation failure.
    """
    return _diff_files_by_command(files, root, "prettier", lambda f: ["npx", "--no-install", "prettier", str(f)])
