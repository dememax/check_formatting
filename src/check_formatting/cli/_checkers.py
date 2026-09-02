# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
"""The thirteen registered checkers themselves — one `_check_*` function
per backend (clang-format, meson format, prettier, ruff, mypy, check_rst,
clang-tidy, cmake-format, west, shellcheck). See `_registry.py` for how
each is wired into the `_CHECKERS` table with its kwargs/fix-command.
"""

from __future__ import annotations

import concurrent.futures
import pathlib
import shutil
import sys
import tempfile
from typing import TYPE_CHECKING

from check_formatting import cli
from check_formatting.cli._config import _config_error
from check_formatting.cli._prettier import _lines_flags, _report_prettier_files_git_scoped
from check_formatting.cli._selection import (
    CLANG_TIDY_IGNORE_FILE,
    IGNORE_FILE,
    _bare_scoped,
    _file_count_label,
    _filter_configured_targets,
    _filter_files,
    _load_ignore_patterns,
    _report_empty_selection,
    _select_explicit,
    _select_explicit_from_globs,
)
from check_formatting.cli._subprocess import (
    _diff_files_by_command,
    _log_analysis_only,
    _make_log,
    _prettier_diff,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def _check_cpp(
    root: pathlib.Path,
    fix: bool = False,
    diff: bool = False,
    verbose: bool = False,
    ignore_patterns: Sequence[str] = (),
    explicit_files: list[pathlib.Path] | None = None,
    globs: Sequence[str] = (),
    git_auto_detected: bool = False,
    quiet: bool = False,
) -> bool:
    """Run clang-format on all C++ source files.

    Check/verbose mode:  ``--dry-run --Werror`` — exits non-zero if any file
                         differs.  clang-format cannot report rule-level
                         diagnostics.  The only diagnostic code it emits is the
                         generic ``[-Wclang-format-violations]``, meaning "this
                         file would look different after formatting".  It cannot
                         say *which* rule is violated or *why* (e.g. it will not
                         tell you "this line exceeds ColumnLimit" or
                         "indentation is wrong").  ``--verbose`` therefore
                         produces identical output to the plain check.
                         Use ``--diff`` to see the exact changes clang-format
                         would make — that is the only detailed report available.
    Diff mode:           Runs clang-format per-file (stdout) and shows a
                         unified diff.
    Fix mode:            ``-i`` — rewrites files in-place.

    In all modes, files matching :data:`IGNORE_FILE` patterns are excluded
    before any formatter is invoked.

    Optional "git-scoped fix" contract (*git_auto_detected*)
    ----------------------------------------------------------
    clang-format is one of the few wrapped backends with a native line-range
    mechanism (``-lines=<start>:<end>``) — see README.md's
    "Scope guarantee" table for which other checkers do or don't.  When
    *git_auto_detected* is True (the selected files came from
    ``check_formatting``'s own git auto-detection, not a user-typed FILE
    argument or ``--all``), every mode restricts itself per-file to that
    file's actual changed hunks (via :func:`_lines_flags`, computed from
    ``git diff -U0 HEAD``) rather than the whole file — mirroring check_rst's
    own bare-mode hunk scoping and its rationale (see
    :func:`_check_rst`'s docstring and check_rst's guide, "History protection").
    check/verbose/diff are scoped together with fix, not left whole-file,
    specifically so a routine ``--fix`` that only cleans up the diff isn't
    followed by a ``--check`` that fails forever on unrelated, pre-existing
    violations elsewhere in the same touched file.  A file with no derivable
    hunk ranges (untracked, or a pure-deletion diff) falls back to whole-file
    scope for that file only.  User-typed FILE arguments and ``--all`` keep
    today's single batched whole-file invocation, unchanged — a deliberate,
    explicit request is treated as full-file intent, same as check_rst's own
    explicit-files contract.
    """
    log = _make_log(quiet)
    if explicit_files is not None:
        result = _select_explicit_from_globs(
            explicit_files,
            root,
            ignore_patterns,
            globs,
            fallback_extensions=frozenset({".cpp", ".hpp"}),
        )
        if result is None:
            log("  (no C++ files in selection)")
            return True
        files, excluded = result
    else:
        all_files = [f for g in globs for f in sorted(root.glob(g))]
        files, excluded = _filter_files(all_files, root, ignore_patterns)
    if _report_empty_selection(files, excluded, log, "C++"):
        return True
    label = _file_count_label(len(files), excluded)

    if fix:
        if git_auto_detected:
            log(f"▶ clang-format -i (git-scoped)  {label}")
            hunk_ranges = cli._batched_git_diff_hunk_ranges(root, files)
            ok = True
            for f in files:
                cmd = ["clang-format", "-i", *_lines_flags(hunk_ranges[f]), str(f)]
                ok = (cli._run(cmd, cwd=root) == 0) and ok
            return ok
        log(f"▶ clang-format -i  {label}")
        return cli._run(["clang-format", "-i"] + [str(f) for f in files], cwd=root) == 0
    if diff:
        log(f"▶ clang-format (diff{', git-scoped' if git_auto_detected else ''})  {label}")
        hunk_ranges = cli._batched_git_diff_hunk_ranges(root, files) if git_auto_detected else {}
        return _diff_files_by_command(
            files,
            root,
            "clang-format",
            lambda f: ["clang-format", *(_lines_flags(hunk_ranges[f]) if git_auto_detected else []), str(f)],
        )
    # check and verbose: clang-format exposes no extra diagnostic flags
    if verbose:
        cli._print_tool_info("clang-format", cwd=root)
    if git_auto_detected:
        log(f"▶ clang-format --dry-run --Werror (git-scoped)  {label}")
        hunk_ranges = cli._batched_git_diff_hunk_ranges(root, files)
        rc = 0
        for f in files:
            rc |= cli._run(["clang-format", *_lines_flags(hunk_ranges[f]), "--dry-run", "--Werror", str(f)], cwd=root)
        return rc == 0
    log(f"▶ clang-format --dry-run --Werror  {label}")
    return (
        cli._run(
            ["clang-format", "--dry-run", "--Werror"] + [str(f) for f in files],
            cwd=root,
        )
        == 0
    )


def _check_cmake(
    root: pathlib.Path,
    fix: bool = False,
    diff: bool = False,
    verbose: bool = False,
    ignore_patterns: Sequence[str] = (),
    explicit_files: list[pathlib.Path] | None = None,
    quiet: bool = False,
) -> bool:
    """Run cmake-format on all CMakeLists.txt files found recursively.

    Check/verbose mode:  ``--check`` — exits non-zero if any file differs.
                         cmake-format exposes no rule-level diagnostics;
                         use ``--diff`` to see the exact changes it would make.
    Diff mode:           Runs cmake-format per-file (stdout) and shows a
                         unified diff.
    Fix mode:            ``--in-place`` — rewrites files in-place.

    ``CMakeLists.txt`` is a fixed, universal filename (like ``meson.build``
    for the meson checker) — not a project-specific path choice, so this
    checker needs no ``.check_formatting.toml`` section of its own.

    cmake-format is resolved from PATH (bare ``shutil.which``), matching the
    project tool-resolution policy in ``AGENTS.md``.
    """
    log = _make_log(quiet)
    if explicit_files is not None:
        result = _select_explicit(explicit_files, root, ignore_patterns, exact_names=frozenset({"CMakeLists.txt"}))
        if result is None:
            log("  (no CMake files in selection)")
            return True
        files, excluded = result
    else:
        all_files = sorted(root.glob("**/CMakeLists.txt"))
        files, excluded = _filter_files(all_files, root, ignore_patterns)
    if _report_empty_selection(files, excluded, log, "CMakeLists.txt"):
        return True
    label = _file_count_label(len(files), excluded)
    cmake_bin = shutil.which("cmake-format")
    if cmake_bin is None:
        print("  ERROR: cmake-format not found — install it via pip (pip install cmake-format)")
        return False
    if fix:
        log(f"▶ cmake-format --in-place  {label}")
        return cli._run([cmake_bin, "--in-place"] + [str(f) for f in files], cwd=root) == 0
    if diff:
        log(f"▶ cmake-format (diff)  {label}")
        return _diff_files_by_command(files, root, "cmake-format", lambda f: [cmake_bin, str(f)])
    # check and verbose: cmake-format exposes no extra diagnostic flags
    if verbose:
        cli._print_tool_info(cmake_bin, cwd=root)
    log(f"▶ cmake-format --check  {label}")
    return cli._run([cmake_bin, "--check"] + [str(f) for f in files], cwd=root) == 0


def _check_meson(
    root: pathlib.Path,
    fix: bool = False,
    diff: bool = False,
    verbose: bool = False,
    ignore_patterns: Sequence[str] = (),
    explicit_files: list[pathlib.Path] | None = None,
    quiet: bool = False,
) -> bool:
    """Run meson format on all build files recursively.

    Check/verbose mode:  ``--check-only`` — exits non-zero if any file
                         differs.  meson format has no additional diagnostic
                         flags, so verbose output is identical to check output.
                         Note: ``.formatting-ignore`` exclusions are **not**
                         applied in this mode without explicit files, because
                         the tool is invoked with a single recursive command;
                         per-file filtering is only possible in diff, fix, and
                         explicit-file modes.
    Diff mode:           Formats a temp copy of each build file and shows a
                         unified diff.  Ignore patterns are applied.
    Fix mode:            ``-i`` — rewrites files in-place.
                         Ignore patterns are applied.
    """
    log = _make_log(quiet)
    if fix or diff or explicit_files is not None:
        if explicit_files is not None:
            result = _select_explicit(
                explicit_files,
                root,
                ignore_patterns,
                exact_names=frozenset({"meson.build", "meson.options"}),
            )
            if result is None:
                log("  (no Meson files in selection)")
                return True
            build_files, excluded = result
        else:
            all_build_files = sorted(root.rglob("meson.build")) + sorted(root.rglob("meson.options"))
            build_files, excluded = _filter_files(all_build_files, root, ignore_patterns)
        if _report_empty_selection(build_files, excluded, log, "Meson build"):
            return True
    if fix:
        label = _file_count_label(len(build_files), excluded)
        log(f"▶ meson format -i  {label}")
        return (
            cli._run(
                ["meson", "format", "-i"] + [str(f) for f in build_files],
                cwd=root,
            )
            == 0
        )
    if diff:
        label = _file_count_label(len(build_files), excluded)
        log(f"▶ meson format (diff)  {label}")
        any_violation = False
        for f in build_files:
            original = f.read_text(encoding="utf-8")
            with tempfile.NamedTemporaryFile(mode="w", suffix=f.suffix, delete=False, encoding="utf-8") as tmp:
                tmp.write(original)
                tmp_path = pathlib.Path(tmp.name)
            rc = 0
            formatted = original
            try:
                rc, _ = cli._fmt_stdout(
                    ["meson", "format", "-i", "-c", "meson.format", str(tmp_path)],
                    cwd=root,
                )
                formatted = tmp_path.read_text(encoding="utf-8")
            finally:
                tmp_path.unlink(missing_ok=True)
            if rc == 127:
                return False
            if rc != 0:
                print(f"ERROR: meson format exited {rc} on {f.name}")
                return False
            if cli._show_diff(original, formatted, str(f.relative_to(root))):
                any_violation = True
        return not any_violation
    if explicit_files is not None:
        # check/verbose with explicit files: per-file (cannot use -r)
        label = _file_count_label(len(build_files), excluded)
        if verbose:
            cli._print_tool_info("meson", cwd=root)
        log(f"▶ meson format --check-only -c meson.format  {label}")
        rc = 0
        for f in build_files:
            rc |= cli._run(
                ["meson", "format", "--check-only", "-c", "meson.format", str(f)],
                cwd=root,
            )
        return rc == 0
    # check and verbose: single batch command — .formatting-ignore not applied
    if verbose:
        cli._print_tool_info("meson", cwd=root)
    log("▶ meson format --check-only -r -c meson.format")
    return (
        cli._run(
            ["meson", "format", "--check-only", "-r", "-c", "meson.format"],
            cwd=root,
        )
        == 0
    )


# Glob patterns covering every web file passed to prettier (HTML/CSS/JS).
# Used for both file-system discovery (root.glob) and as CLI arguments.
_WEB_GLOBS: tuple[str, ...] = ()


def _check_web(
    root: pathlib.Path,
    fix: bool = False,
    diff: bool = False,
    verbose: bool = False,
    ignore_patterns: Sequence[str] = (),
    explicit_files: list[pathlib.Path] | None = None,
    globs: Sequence[str] = _WEB_GLOBS,
    git_auto_detected: bool = False,
    quiet: bool = False,
) -> bool:
    """Run prettier on all HTML, CSS, and JavaScript files in www/ and docs/_static/.

    The files covered are defined by *globs* (``.check_formatting.toml``'s
    ``[web].globs``; empty by default — a project with no ``[web]`` section
    has nothing to check).

    Check mode:   ``--check`` — exits non-zero if any file differs.  When
                  *git_auto_detected* is True (explicit-file selection only),
                  compares each file against what a best-effort git-scoped
                  fix would write instead (see :func:`_best_effort_prettier_target`
                  via :func:`_report_prettier_files_git_scoped`) — not the
                  unconditional whole-file reformat — so a file already at
                  its git-scoped-fixed state passes even though it still
                  differs from a full reformat.  Comparing against the
                  whole-file reformat unconditionally (as every mode did
                  before this existed) reported a violation on any file
                  whose fix had deliberately retained out-of-scope legacy
                  content, contradicting the ``--fix`` that had just
                  succeeded — see the "Optional git-scoped fix contract"
                  module note above.
    Verbose mode: Same as check, plus ``--log-level log``/tool-info output
                  when not git-scoped; the git-scoped path always logs each
                  file's status regardless of *verbose*.
    Diff mode:    Runs prettier per-file (stdout) and shows a unified diff
                  against the same target check mode now uses when
                  *git_auto_detected*; otherwise the unconditional whole-file
                  reformat via :func:`_prettier_diff`.  Ignore patterns are
                  applied.
    Fix mode:     ``--write`` — rewrites files in-place.  When
                  *git_auto_detected* is True, attempts a "best-effort"
                  git-scoped fix per file first (see
                  :func:`_best_effort_prettier_fix`) rather than clang-format/
                  check_rst's tool-guaranteed hunk scoping — prettier has no
                  reliably-usable native line-range mechanism, so this is a
                  heuristic (diff the whole-file reformat, keep only the
                  changes overlapping the file's git hunks, verify the
                  candidate canonicalizes to the full result) that falls back
                  to today's whole-file ``--write`` when it does not.  Ignore
                  patterns are applied.

    Note: ``.formatting-ignore`` exclusions are applied only in diff,
    fix, and explicit-file modes.  In check and verbose modes without
    explicit files the tool is invoked with glob patterns; use
    ``.prettierignore`` for per-file exclusions in those modes.
    """
    log = _make_log(quiet)
    globs_display = " ".join(f'"{g}"' for g in globs)
    if fix or diff or explicit_files is not None:
        if explicit_files is not None:
            result = _select_explicit_from_globs(
                explicit_files,
                root,
                ignore_patterns,
                globs,
                fallback_extensions=frozenset({".html", ".css", ".js"}),
            )
            if result is None:
                log("  (no web files in selection)")
                return True
            web_files, excluded = result
        else:
            all_web_files = [f for g in globs for f in sorted(root.glob(g))]
            web_files, excluded = _filter_files(all_web_files, root, ignore_patterns)
        if _report_empty_selection(web_files, excluded, log, "web"):
            return True
    if fix:
        label = _file_count_label(len(web_files), excluded)
        return cli._fix_prettier_files(
            web_files,
            root,
            git_auto_detected=git_auto_detected,
            label=label,
            log=log,
        )
    if diff:
        label = _file_count_label(len(web_files), excluded)
        if git_auto_detected:
            log(f"▶ npx prettier (diff, git-scoped)  {label}")
            return _report_prettier_files_git_scoped(web_files, root, show_diff=True, log=log)
        log(f"▶ npx prettier (diff)  {label}")
        return _prettier_diff(web_files, root)
    if explicit_files is not None:
        label = _file_count_label(len(web_files), excluded)
        if git_auto_detected:
            if verbose:
                cli._print_tool_info("npx", cwd=root, version_args=["prettier", "--version"])
            log(f"▶ npx prettier --check (git-scoped)  {label}")
            return _report_prettier_files_git_scoped(web_files, root, show_diff=False, log=log)
        # check/verbose with explicit files: pass paths directly, not globs
        cmd = ["npx", "--no-install", "prettier", "--check"]
        if verbose:
            cli._print_tool_info("npx", cwd=root, version_args=["prettier", "--version"])
            cmd += ["--log-level", "log"]
        log(f"▶ npx prettier --check  {label}")
        return cli._run(cmd + [str(f) for f in web_files], cwd=root) == 0
    if verbose:
        cli._print_tool_info("npx", cwd=root, version_args=["prettier", "--version"])
        log(f"▶ npx prettier --check --log-level log {globs_display}")
        return cli._run(["npx", "--no-install", "prettier", "--check", "--log-level", "log", *globs], cwd=root) == 0
    log(f"▶ npx prettier --check {globs_display}")
    return cli._run(["npx", "--no-install", "prettier", "--check", *globs], cwd=root) == 0


def _resolve_python_targets(
    explicit_files: list[pathlib.Path] | None,
    root: pathlib.Path,
    ignore_patterns: Sequence[str],
    dirs: Sequence[str],
    log: Callable[..., None],
) -> tuple[list[str], str] | None:
    """Resolve the Python file/dir targets shared by ``python`` (ruff) and ``mypy``:
    explicit ``.py`` files intersected with configured *dirs*, or *dirs* themselves
    when no files were named explicitly.

    Returns ``None`` when explicit files were given but none survived extension or
    configured-target filtering — the caller should log nothing further and return
    True ("nothing to do") — otherwise ``(targets, targets_label)``.
    """
    if explicit_files is not None:
        result = _select_explicit(explicit_files, root, ignore_patterns, extensions=frozenset({".py"}))
        if result is None:
            log("  (no Python files in selection)")
            return None
        py_files, excluded = result
        py_files = _filter_configured_targets(py_files, root, dirs)
        if not py_files:
            log("  (no Python files in configured targets after exclusions)")
            return None
        return [str(f) for f in py_files], _file_count_label(len(py_files), excluded)
    return list(dirs), f"({', '.join(dirs)})"


def _run_two_concurrently(
    cmd1: list[str],
    cmd2: list[str],
    cwd: pathlib.Path,
    log: Callable[..., None],
    banner1: str,
    banner2: str,
) -> tuple[int, int]:
    """Run *cmd1* and *cmd2* concurrently, each capturing merged stdout+stderr
    (via :func:`_run_capture_merged`) rather than streaming live like
    :func:`_run` — running two live-streaming subprocesses at once would
    interleave their output unpredictably. Both are submitted before either
    banner is printed, so the actual work overlaps (wall time roughly
    ``max(cmd1, cmd2)`` instead of the sum); each command's own banner and
    captured output are still printed in (*cmd1*, *cmd2*) order once ready,
    exactly the shape a sequential run would have produced.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        future1 = pool.submit(cli._run_capture_merged, cmd1, cwd)
        future2 = pool.submit(cli._run_capture_merged, cmd2, cwd)
        log(banner1)
        result1 = future1.result()
        sys.stdout.write(result1.stdout)
        log()
        log(banner2)
        result2 = future2.result()
        sys.stdout.write(result2.stdout)
    return result1.returncode, result2.returncode


def _check_python(
    root: pathlib.Path,
    fix: bool = False,
    diff: bool = False,
    verbose: bool = False,
    ignore_patterns: Sequence[str] = (),
    explicit_files: list[pathlib.Path] | None = None,
    dirs: Sequence[str] = (),
    quiet: bool = False,
) -> bool:
    """Run ruff on Python source files (*dirs* — ``.check_formatting.toml``'s ``[python].dirs``; empty by default).

    Check mode:   ``ruff format --check`` + ``ruff check`` — no writes.
    Verbose mode: ``ruff format --check`` + ``ruff check --output-format full``
                  — same exit behaviour, but each lint violation is printed
                  with its surrounding source context.
    Diff mode:    ``ruff format --diff`` (native unified diff) + ``ruff check``.
    Fix mode:     ``ruff format`` + ``ruff check --fix`` — rewrites in-place.

    Both sub-commands must exit 0 for the check to pass.  The three
    read-only modes run both sub-commands concurrently (see
    :func:`_run_two_concurrently`) since neither depends on the other's
    output.  Fix mode keeps them sequential, live-streamed via :func:`_run`
    — ``ruff check --fix`` must see the content ``ruff format`` just wrote,
    a genuine data dependency, not just historical ordering.

    Note: ``.formatting-ignore`` exclusions are not applied for ruff when
    operating on directories (``scripts/`` and ``tests/``).  Use
    ``[tool.ruff.exclude]`` in ``pyproject.toml`` for per-file exclusions.
    When explicit files are provided, they are passed directly to ruff and
    ``.formatting-ignore`` patterns are applied beforehand.
    """
    log = _make_log(quiet)
    result = _resolve_python_targets(explicit_files, root, ignore_patterns, dirs, log)
    if result is None:
        return True
    targets, targets_label = result
    if fix:
        log(f"▶ ruff format  {targets_label}")
        fmt_rc = cli._run(["ruff", "format", *targets], cwd=root)
        log()
        log(f"▶ ruff check --fix  {targets_label}")
        lint_rc = cli._run(["ruff", "check", "--fix", *targets], cwd=root)
        return fmt_rc == 0 and lint_rc == 0
    if diff:
        fmt_rc, lint_rc = _run_two_concurrently(
            ["ruff", "format", "--diff", *targets],
            ["ruff", "check", *targets],
            root,
            log,
            f"▶ ruff format --diff  {targets_label}",
            f"▶ ruff check  {targets_label}",
        )
    elif verbose:
        cli._print_tool_info("ruff", cwd=root)
        fmt_rc, lint_rc = _run_two_concurrently(
            ["ruff", "format", "--check", *targets],
            ["ruff", "check", "--output-format", "full", *targets],
            root,
            log,
            f"▶ ruff format --check  {targets_label}",
            f"▶ ruff check --output-format full  {targets_label}",
        )
    else:
        fmt_rc, lint_rc = _run_two_concurrently(
            ["ruff", "format", "--check", *targets],
            ["ruff", "check", *targets],
            root,
            log,
            f"▶ ruff format --check  {targets_label}",
            f"▶ ruff check  {targets_label}",
        )
    return fmt_rc == 0 and lint_rc == 0


def _dispatch_prettier_checker(
    files: list[pathlib.Path],
    root: pathlib.Path,
    *,
    fix: bool,
    diff: bool,
    verbose: bool,
    git_auto_detected: bool,
    label: str,
    log: Callable[..., None],
) -> bool:
    """Run prettier's check/verbose/diff/fix dispatch shared by the checkers whose
    files are always a concrete, already-resolved list regardless of *explicit_files*
    (``json``, ``ini``, ``yaml``) — once each has run its own file-selection
    prologue and produced *files*/*label*.

    ``web`` is not one of these callers: unlike json/ini/yaml, its check/verbose
    modes without explicit files invoke prettier on the configured *globs*
    directly (a single batched command, not a resolved file list), so it keeps
    its own dispatch tail instead of sharing this one.
    """
    if fix:
        return cli._fix_prettier_files(files, root, git_auto_detected=git_auto_detected, label=label, log=log)
    if diff:
        if git_auto_detected:
            log(f"▶ npx prettier (diff, git-scoped)  {label}")
            return _report_prettier_files_git_scoped(files, root, show_diff=True, log=log)
        log(f"▶ npx prettier (diff)  {label}")
        return _prettier_diff(files, root)
    if git_auto_detected:
        if verbose:
            cli._print_tool_info("npx", cwd=root, version_args=["prettier", "--version"])
        log(f"▶ npx prettier --check (git-scoped)  {label}")
        return _report_prettier_files_git_scoped(files, root, show_diff=False, log=log)
    str_files = [str(f) for f in files]
    if verbose:
        cli._print_tool_info("npx", cwd=root, version_args=["prettier", "--version"])
        log(f"▶ npx prettier --check --log-level log  {label}")
        return cli._run(["npx", "--no-install", "prettier", "--check", "--log-level", "log", *str_files], cwd=root) == 0
    log(f"▶ npx prettier --check  {label}")
    return cli._run(["npx", "--no-install", "prettier", "--check", *str_files], cwd=root) == 0


# All JSON / JSONC files in the project (listed explicitly; not a glob).
# Prettier selects the correct parser for each file automatically:
#   - plain JSON files (.prettierrc, package.json, .vscode/tasks.json)
#     use the built-in "json" parser.
#   - JSONC files (.vscode/settings.json, and other project-declared
#     JSONC entries) use the "jsonc" parser with trailingComma:none, both
#     configured via the overrides section of .prettierrc.
# package-lock.json is intentionally excluded — it is machine-generated
# and reformatting it is pointless.
_JSON_FILES: list[str] = []


def _check_json(
    root: pathlib.Path,
    fix: bool = False,
    diff: bool = False,
    verbose: bool = False,
    ignore_patterns: Sequence[str] = (),
    explicit_files: list[pathlib.Path] | None = None,
    files: Sequence[str] = tuple(_JSON_FILES),
    quiet: bool = False,
    *,
    git_auto_detected: bool = False,
) -> bool:
    """Run prettier on JSON and JSONC configuration files.

    Prettier selects the parser automatically based on file extension and
    the ``overrides`` section of ``.prettierrc``:

    - Plain JSON files (``.prettierrc``, ``package.json``,
      ``.vscode/tasks.json``) use the built-in ``json`` parser.
    - JSONC files (e.g. ``.vscode/settings.json``, or any other
      project-declared JSONC entry) use the ``jsonc`` parser with
      ``trailingComma: none`` to preserve their existing style and remain
      compatible with parsers that do not accept trailing commas.

    ``package-lock.json`` is excluded — it is machine-generated.

    Check mode:   ``--check`` — exits non-zero if any file differs.  When
                  *git_auto_detected* is true, compares each file against
                  what a best-effort git-scoped fix would write instead
                  (see :func:`_best_effort_prettier_target` via
                  :func:`_report_prettier_files_git_scoped`), not the
                  unconditional whole-file reformat — keeps this mode
                  consistent with what ``--fix`` actually writes.
    Verbose mode: Same as check, plus ``--check --log-level log`` /
                  tool-info output when not git-scoped.
    Diff mode:    Runs prettier per-file (stdout) and shows a unified diff
                  against the same target check mode uses when
                  *git_auto_detected*; otherwise the unconditional
                  whole-file reformat.
    Fix mode:     ``--write`` — rewrites files in-place; best-effort Git
                  hunk-scoped when *git_auto_detected* is true.

    The checked files are listed by *files* (``.check_formatting.toml``'s
    ``[json].files``; empty by default — a project with no ``[json]``
    section has nothing to check).  Ignore patterns from
    ``.formatting-ignore`` are applied in all modes.
    """
    log = _make_log(quiet)
    json_resolved = frozenset((root / p).resolve() for p in files)
    if explicit_files is not None:
        result = _select_explicit(explicit_files, root, ignore_patterns, exact_paths=json_resolved)
        if result is None:
            log("  (no JSON files in selection)")
            return True
        matched_files, excluded = result
    else:
        all_files = [root / p for p in files if (root / p).exists()]
        matched_files, excluded = _filter_files(all_files, root, ignore_patterns)
    if _report_empty_selection(matched_files, excluded, log, "JSON"):
        return True
    label = _file_count_label(len(matched_files), excluded)
    return _dispatch_prettier_checker(
        matched_files,
        root,
        fix=fix,
        diff=diff,
        verbose=verbose,
        git_auto_detected=git_auto_detected,
        label=label,
        log=log,
    )


def _check_ini(
    root: pathlib.Path,
    fix: bool = False,
    diff: bool = False,
    verbose: bool = False,
    ignore_patterns: Sequence[str] = (),
    explicit_files: list[pathlib.Path] | None = None,
    globs: Sequence[str] = (),
    quiet: bool = False,
    *,
    git_auto_detected: bool = False,
) -> bool:
    """Run prettier on Meson native-file INI configs in build-configs/.

    Uses prettier-plugin-ini (registered in .prettierrc).  The plugin is
    configured via the ``*.ini`` override in .prettierrc:
    ``iniSpaceAroundEquals: true`` preserves the ``key = value`` style of
    the existing files.

    Check mode:   ``--check`` — exits non-zero if any file differs.  When
                  *git_auto_detected* is true, compares each file against
                  what a best-effort git-scoped fix would write instead
                  (see :func:`_best_effort_prettier_target` via
                  :func:`_report_prettier_files_git_scoped`), not the
                  unconditional whole-file reformat — keeps this mode
                  consistent with what ``--fix`` actually writes.
    Verbose mode: Same as check, plus ``--check --log-level log`` /
                  tool-info output when not git-scoped.
    Diff mode:    Runs prettier per-file (stdout) and shows a unified diff
                  against the same target check mode uses when
                  *git_auto_detected*; otherwise the unconditional
                  whole-file reformat.
    Fix mode:     ``--write`` — rewrites files in-place; best-effort Git
                  hunk-scoped when *git_auto_detected* is true.

    The files are discovered via *globs* (``.check_formatting.toml``'s
    ``[ini].globs``; empty by default — a project with no ``[ini]``
    section has nothing to check).  Ignore patterns from
    ``.formatting-ignore`` are applied in all modes.
    """
    log = _make_log(quiet)
    if explicit_files is not None:
        result = _select_explicit_from_globs(
            explicit_files,
            root,
            ignore_patterns,
            globs,
            fallback_extensions=frozenset({".ini"}),
        )
        if result is None:
            log("  (no INI files in selection)")
            return True
        files, excluded = result
    else:
        all_files = [f for g in globs for f in sorted(root.glob(g))]
        files, excluded = _filter_files(all_files, root, ignore_patterns)
    if _report_empty_selection(files, excluded, log, "INI"):
        return True
    label = _file_count_label(len(files), excluded)
    return _dispatch_prettier_checker(
        files,
        root,
        fix=fix,
        diff=diff,
        verbose=verbose,
        git_auto_detected=git_auto_detected,
        label=label,
        log=log,
    )


def _check_yaml(
    root: pathlib.Path,
    fix: bool = False,
    diff: bool = False,
    verbose: bool = False,
    ignore_patterns: Sequence[str] = (),
    explicit_files: list[pathlib.Path] | None = None,
    globs: Sequence[str] = (),
    quiet: bool = False,
    *,
    git_auto_detected: bool = False,
) -> bool:
    """Run prettier on YAML files (*globs*, ``.check_formatting.toml``'s ``[yaml].globs``).

    An exact structural mirror of :func:`_check_ini` — prettier already has
    built-in YAML parser support (confirmed via ``npx prettier --file-info
    test.yaml`` → ``inferredParser: "yaml"``), so no new tool dependency.

    Check mode:   ``--check`` — exits non-zero if any file differs.  When
                  *git_auto_detected* is true, compares each file against
                  what a best-effort git-scoped fix would write instead
                  (see :func:`_best_effort_prettier_target` via
                  :func:`_report_prettier_files_git_scoped`), not the
                  unconditional whole-file reformat — keeps this mode
                  consistent with what ``--fix`` actually writes.
    Verbose mode: Same as check, plus ``--check --log-level log`` /
                  tool-info output when not git-scoped.
    Diff mode:    Runs prettier per-file (stdout) and shows a unified diff
                  against the same target check mode uses when
                  *git_auto_detected*; otherwise the unconditional
                  whole-file reformat.
    Fix mode:     ``--write`` — rewrites files in-place; best-effort Git
                  hunk-scoped when *git_auto_detected* is true.

    A project with no ``[yaml]`` section (*globs* empty) has nothing to
    check and passes vacuously, without requiring prettier.
    """
    log = _make_log(quiet)
    if explicit_files is not None:
        result = _select_explicit_from_globs(
            explicit_files,
            root,
            ignore_patterns,
            globs,
            fallback_extensions=frozenset({".yaml", ".yml"}),
        )
        if result is None:
            log("  (no YAML files in selection)")
            return True
        files, excluded = result
    else:
        all_files = [f for g in globs for f in sorted(root.glob(g))]
        files, excluded = _filter_files(all_files, root, ignore_patterns)
    if _report_empty_selection(files, excluded, log, "YAML"):
        return True
    label = _file_count_label(len(files), excluded)
    return _dispatch_prettier_checker(
        files,
        root,
        fix=fix,
        diff=diff,
        verbose=verbose,
        git_auto_detected=git_auto_detected,
        label=label,
        log=log,
    )


# Lives inside .mypy_cache/ itself, not alongside it — so mypy's own cache
# clearing, or a user's `rm -rf .mypy_cache`, naturally clears this marker
# too, and there is no separate piece of state that can go stale on its own.
_MYPY_CACHE_VERSION_MARKER = ".check_formatting_mypy_version"


def _invalidate_mypy_cache_if_version_changed(root: pathlib.Path, mypy_bin: pathlib.Path) -> None:
    """Wipe ``.mypy_cache/`` only when the resolved mypy's version differs
    from the version recorded there last time — not on every invocation.

    mypy's incremental cache format is version-dependent: reusing a cache
    written by a different mypy version than the one about to run could
    silently produce wrong (missing or spurious) results instead of a clean
    full recheck — the one guarantee wiping the cache exists to preserve.
    No marker present (first run, or a cache that predates this check) is
    treated as a mismatch: wipe once, the safe default.

    The marker is (re)written here, before mypy actually runs, so it always
    reflects the version about to run rather than the version that last
    completed — a crash mid-run can never leave a stale marker claiming a
    clean, matching cache for a run that never finished. A failed marker
    write (e.g. a read-only root) is swallowed: the check still runs, it
    just forfeits this optimization for the next invocation.
    """
    cache_dir = root / ".mypy_cache"
    marker = cache_dir / _MYPY_CACHE_VERSION_MARKER
    current_version = cli._tool_version_string(mypy_bin, root) or "(unknown)"
    previous_version = None
    if marker.is_file():
        try:
            previous_version = marker.read_text(encoding="utf-8")
        except OSError:
            previous_version = None
    if cache_dir.exists() and previous_version != current_version:
        shutil.rmtree(cache_dir)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(current_version, encoding="utf-8")
    except OSError:
        pass


def _check_mypy(
    root: pathlib.Path,
    fix: bool = False,
    diff: bool = False,
    verbose: bool = False,
    ignore_patterns: Sequence[str] = (),
    explicit_files: list[pathlib.Path] | None = None,
    dirs: Sequence[str] = (),
    quiet: bool = False,
) -> bool:
    """Run mypy strict type-checker on Python source files.

    *dirs* comes from ``[mypy].dirs`` when declared, otherwise from the
    ``[python].dirs`` compatibility fallback.

    mypy has no fix or diff mode; the same type-check is performed in all modes.
    Check mode:   ``mypy scripts tests``
    Verbose mode: ``mypy --show-error-context scripts tests``
    Fix/diff mode: identical to check (mypy cannot modify files).

    mypy is resolved from ``PATH`` according to the project tool-resolution
    policy in ``AGENTS.md``. Configuration is read from ``[tool.mypy]`` in
    ``pyproject.toml``.
    """
    log = _make_log(quiet)
    result = _resolve_python_targets(explicit_files, root, ignore_patterns, dirs, log)
    if result is None:
        return True
    targets, targets_label = result
    _log_analysis_only("mypy", "type-check", fix, diff, log)
    found = shutil.which("mypy")
    mypy_bin = pathlib.Path(found) if found else None
    if mypy_bin is None:
        print("  ERROR: mypy not found on PATH — install it via the system package manager (e.g. apt install mypy)")
        return False
    _invalidate_mypy_cache_if_version_changed(root, mypy_bin)
    cmd = [str(mypy_bin)]
    if verbose:
        cli._print_tool_info(mypy_bin, cwd=root)
        cmd += ["--show-error-context"]
    cmd += targets
    log(f"▶ mypy  {targets_label}")
    return cli._run(cmd, cwd=root) == 0


def _check_clang_tidy(
    root: pathlib.Path,
    fix: bool = False,
    diff: bool = False,
    verbose: bool = False,
    ignore_patterns: Sequence[str] = (),
    explicit_files: list[pathlib.Path] | None = None,
    cpp_globs: Sequence[str] = (),
    build_dir: pathlib.Path | None = None,
    quiet: bool = False,
) -> bool:
    """Run clang-tidy on C++ source files using the Meson compile_commands.json.

    Not run by default — must be requested explicitly via ``--checks clang-tidy``.

    *build_dir* (``.check_formatting.toml``'s ``[clang_tidy].build_dir``) must
    hold an up-to-date ``compile_commands.json`` (generated automatically by
    Meson).  A project with no ``[clang_tidy]`` section (*build_dir* ``None``)
    has nothing to analyze and passes vacuously, without requiring
    ``clang-tidy`` on ``PATH`` — matching every other optional checker's
    "not configured for this project" behavior (see ``_check_kconfig``,
    ``_check_shell``, ``_check_yaml``).  ``None`` rather than an empty path is
    the sentinel here because ``pathlib.Path("")`` normalizes to ``Path(".")``,
    which would otherwise silently collapse "unconfigured" into "configured
    as the current directory".  Rebuild if the database is missing or
    stale::

        meson compile -C <configured build_dir>

    Checks are driven by ``.clang-tidy`` at the project root.

    Files listed in :data:`CLANG_TIDY_IGNORE_FILE` (``.clang-tidy-ignore``) are
    excluded in addition to the global :data:`IGNORE_FILE` patterns.  Use
    ``.clang-tidy-ignore`` for files that clang-tidy cannot parse (e.g. TUs
    that include GCC-specific reflection headers) but that remain valid
    targets for clang-format and other checkers.

    clang-tidy has no fix or diff mode; the same analysis is run in all modes.
    """
    log = _make_log(quiet)
    if build_dir is None:
        log("  (no [clang_tidy].build_dir configured)")
        return True

    _log_analysis_only("clang-tidy", "analysis", fix, diff, log)

    clang_tidy_patterns = list(ignore_patterns) + _load_ignore_patterns(root, filename=CLANG_TIDY_IGNORE_FILE)

    compile_commands = build_dir / "compile_commands.json"
    if not compile_commands.exists():
        print(f"  ERROR: {compile_commands} not found.")
        print("  Rebuild to regenerate it:")
        print(f"    meson compile -C {build_dir}")
        return False

    # clang-tidy must receive translation units (.cpp) only; headers are
    # analysed through the .cpp files that include them.
    _CPP_ONLY = frozenset({".cpp"})
    if explicit_files is not None:
        result = _select_explicit(explicit_files, root, clang_tidy_patterns, extensions=_CPP_ONLY)
        if result is None:
            log("  (no .cpp files in selection)")
            return True
        files, excluded = result
    else:
        all_files = sorted(f for g in cpp_globs for f in root.glob(g) if f.suffix == ".cpp")
        files, excluded = _filter_files(all_files, root, clang_tidy_patterns)

    if _report_empty_selection(files, excluded, log, ".cpp", ignore_file=f"{IGNORE_FILE} / {CLANG_TIDY_IGNORE_FILE}"):
        return True

    label = _file_count_label(len(files), excluded)
    clang_tidy_bin = shutil.which("clang-tidy")
    if clang_tidy_bin is None:
        print("  ERROR: clang-tidy not found — install LLVM:")
        print("    sudo apt install clang-tidy")
        return False

    if verbose:
        cli._print_tool_info("clang-tidy", cwd=root)

    log(f"▶ clang-tidy -p {build_dir}  {label}")
    return (
        cli._run(
            [clang_tidy_bin, "-p", str(build_dir)] + [str(f) for f in files],
            cwd=root,
        )
        == 0
    )


def _check_kconfig(
    root: pathlib.Path,
    fix: bool = False,
    diff: bool = False,
    verbose: bool = False,
    ignore_patterns: Sequence[str] = (),
    explicit_files: list[pathlib.Path] | None = None,
    build_combos: Sequence[dict[str, object]] = (),
    quiet: bool = False,
) -> bool:
    """Validate Kconfig/prj.conf overlays via ``west build --cmake-only --pristine``.

    Always runs with ``--pristine`` to guarantee a fresh Kconfig evaluation
    regardless of cached build state — without it, the cached ``.config``
    is reused and ignored assignments are not re-reported.

    Kconfig processes all ``.conf`` files for a given board and reports two
    classes of problem, both surfaced as a ``warning:`` line by kconfiglib:
    undefined symbols (``CONFIG_FOO=y`` where ``FOO`` is not declared in any
    ``Kconfig`` file) and ignored assignments (``CONFIG_FOO=y`` where
    ``FOO``'s dependencies are not satisfied).

    *build_combos* (``.check_formatting.toml``'s ``[kconfig].build_combos``)
    is a list of ``{"label": str, "args": list[str]}`` — one ``west build``
    invocation per board/source combination the project cares about (e.g. a
    main app on two boards, plus a unit-test app). This is the one piece
    that must be project-specific. Board names are declared in config, not
    hardcoded or guessed by the utility.

    Check mode:   Captures output; prints the Kconfig-relevant lines
                  (warnings, "Merged configuration") while suppressing CMake
                  toolchain-detection noise.  Every combo's build runs
                  concurrently (see :func:`_run_capture_merged`) — output is
                  captured, not streamed, so concurrent combos never
                  interleave; banners and warning lines are only ever
                  printed in *build_combos*'s original order, once each
                  combo's build has finished.
    Verbose mode: Streams all west/CMake/Kconfig output to the terminal, one
                  combo at a time, sequentially (warning-counting is skipped
                  — the human reading the stream sees it directly).  Kept
                  sequential deliberately: parallelizing live-streamed
                  output from multiple combos would interleave it,
                  defeating the point of watching it in real time.
    Diff/fix mode: Identical to check (Kconfig has neither).

    When explicit files are given, the check runs only if at least one has
    a ``.conf`` suffix (``west`` always validates every ``.conf`` file
    together — individual file selection is not supported).

    ``west`` is resolved from PATH (bare ``shutil.which``), matching this
    project's PATH-only tool-resolution policy.

    Concurrent combos and build-directory isolation
    ------------------------------------------------
    Since combos now build concurrently, any combo relying on ``west``'s
    default build directory will race with every other combo doing the
    same.  Give each combo its own ``-d``/``--build-dir`` in *args* if it
    needs isolated build state — ``west build`` already supports this flag
    directly through *args*, no ``check_formatting``-specific configuration
    exists or is needed for it.
    """
    log = _make_log(quiet)
    if explicit_files is not None and not any(f.suffix == ".conf" for f in explicit_files):
        log("  (no .conf files in selection)")
        return True

    if not build_combos:
        log("  (no [kconfig].build_combos configured)")
        return True

    _log_analysis_only("Kconfig", "validation", fix, diff, log)

    west_bin = shutil.which("west")
    if west_bin is None:
        print("  ERROR: west not found — activate the project's Zephyr workspace first")
        return False
    if verbose:
        cli._print_tool_info(west_bin, cwd=root)

    noise_phrases = (
        "looks like a fresh build",
        "to silence the above",
        "Configuration saved",
        "Kconfig header saved",
        "Loading Zephyr",
        "Parsing ",
        "No change to configuration",
        "No change to Kconfig header",
    )
    cmake_error_phrases = ("FATAL ERROR:", "CMake Error", "error:")

    commands = [[west_bin, "build", "--cmake-only", "--pristine", *combo["args"]] for combo in build_combos]  # type: ignore[misc]

    if verbose:
        # Sequential and live-streamed, deliberately — see docstring.
        all_ok = True
        for combo, cmd in zip(build_combos, commands, strict=True):
            log(f"▶ {' '.join(cmd)}  ({combo['label']})")
            all_ok = all_ok and (cli._run(cmd, cwd=root) == 0)
        return all_ok

    # Non-verbose: every combo's build runs concurrently, captured rather
    # than streamed — submitted all at once so the actual work overlaps,
    # then consumed/printed below in build_combos's original order once
    # each future resolves, exactly the shape a sequential run would have
    # produced.
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(build_combos)) as pool:
        futures = [pool.submit(cli._run_capture_merged, cmd, root) for cmd in commands]

        all_ok = True
        for combo, cmd, future in zip(build_combos, commands, futures, strict=True):
            label = combo["label"]
            log(f"▶ {' '.join(cmd)}  ({label})")
            result = future.result()

            kconfig_warnings = 0
            for line in result.stdout.splitlines():
                if line.strip().startswith("-- "):
                    if any(kw in line for kw in cmake_error_phrases):
                        print(line)
                elif not any(phrase in line for phrase in noise_phrases):
                    print(line)
                    if line.strip().lower().startswith("warning:"):
                        kconfig_warnings += 1

            if kconfig_warnings:
                print(f"  [{label}] {kconfig_warnings} Kconfig warning(s) — correct the .conf overlays")
            all_ok = all_ok and result.returncode == 0 and kconfig_warnings == 0

    return all_ok


def _check_shell(
    root: pathlib.Path,
    fix: bool = False,
    diff: bool = False,
    verbose: bool = False,
    ignore_patterns: Sequence[str] = (),
    explicit_files: list[pathlib.Path] | None = None,
    globs: Sequence[str] = (),
    quiet: bool = False,
) -> bool:
    """Run shellcheck on shell scripts (*globs*, ``.check_formatting.toml``'s ``[shell].globs``).

    shellcheck is lint-only — it has no fix or diff mode; the same lint pass
    runs in every mode.

    Check mode:   ``shellcheck <files>``
    Verbose mode: identical to check — shellcheck's default output already
                  includes source context per finding; there is no deeper
                  diagnostic flag beyond that.
    Fix/diff mode: identical to check (shellcheck cannot modify files).

    A project with no ``[shell]`` section (*globs* empty) has nothing to
    lint and passes vacuously, without requiring shellcheck on ``PATH`` —
    matching every other glob-based checker's "no files found" behavior.

    shellcheck is resolved from PATH (bare ``shutil.which``), matching the
    project tool-resolution policy in ``AGENTS.md``.
    """
    log = _make_log(quiet)
    if explicit_files is not None:
        result = _select_explicit_from_globs(
            explicit_files,
            root,
            ignore_patterns,
            globs,
            fallback_extensions=frozenset({".sh"}),
        )
        if result is None:
            log("  (no shell files in selection)")
            return True
        files, excluded = result
    else:
        all_files = sorted({file for glob in globs for file in root.glob(glob)})
        files, excluded = _filter_files(all_files, root, ignore_patterns)
    if _report_empty_selection(files, excluded, log, "shell"):
        return True
    label = _file_count_label(len(files), excluded)
    _log_analysis_only("shellcheck", "lint", fix, diff, log)
    shellcheck_bin = shutil.which("shellcheck")
    if shellcheck_bin is None:
        print("  ERROR: shellcheck not found — install it via the system package manager (e.g. apt install shellcheck)")
        return False
    if verbose:
        cli._print_tool_info(shellcheck_bin, cwd=root)
    log(f"▶ shellcheck  {label}")
    return cli._run([shellcheck_bin] + [str(f) for f in files], cwd=root) == 0


def _check_rst(
    root: pathlib.Path,
    fix: bool = False,
    diff: bool = False,
    verbose: bool = False,
    ignore_patterns: Sequence[str] = (),
    explicit_files: list[pathlib.Path] | None = None,
    recursive_dir: str = "",
    git_auto_detected: bool = False,
    quiet: bool = False,
) -> bool:
    """Run check_rst on RST documentation files.

    Uses the installed ``check_rst`` console entry point from PATH, on its
    current verb-based CLI (``check``/``fix``/``diff``, global options such
    as ``--sphinx-src``/``--config`` given *before* the verb, git-style —
    see check_rst's guide, "Global option position").  The Sphinx facts
    (``--sphinx-src docs``, the incremental build cache) come from
    ``.check_rst.toml`` at the repository root — a committed, tool-echoed,
    CLI-overridable declaration — so no flags are passed here; check_rst
    discovers it from ``cwd`` (``root``) on its own.

    check_rst distinguishes bare invocation (no file arguments — git-diff-scoped:
    adornment fixes apply only to changed hunks) from being given explicit
    filenames (whole-file adornment scope — see check_rst's guide, "History
    protection: bare mode and selective Git scope").  Three distinct scopes
    map onto that distinction:

    - *explicit_files* is a list AND *git_auto_detected* is True — these files
      came from ``check_formatting``'s own git auto-detection (the default
      CLI scope, no FILE args and no ``--all``), which is exactly the same
      changed/untracked set check_rst's own bare mode would select on its
      own.  Run check_rst **bare** rather than handing it that same list as
      explicit arguments — doing the latter would silently upgrade every
      routine ``--fix`` from hunk-scoped to whole-file scoped, and risk
      renormalizing pre-existing, deliberately non-standard adornments
      (historical entries, or externally-adopted documents with their
      own style) elsewhere in a touched file.  Fix mode uses ``fix --fast``
      here (mutate without the validation phases — check_rst's guide, the
      "three-step loop": mutate fast, then a separate ``check`` confirms).
    - *explicit_files* is a list and *git_auto_detected* is False — the user
      (or a caller) genuinely named these files.  Pass them to check_rst
      directly: whole-file scope is the correct, explicitly-requested
      behavior here (see check_rst's guide: "Fix a specific file in full only
      when the user explicitly confirms that file should be normalized").
      Fix mode uses ordinary ``fix`` (not ``--fast``), which mutates and then
      runs the same full validation pipeline as ``check`` in one pass.
    - *explicit_files* is ``None`` — a real full-repo scan is wanted (``--all``
      on the CLI, or a direct release-gate library call). Bare mode does NOT
      mean this: it is git-diff-scoped by design and checks nothing on a clean
      tree — exactly the release gate's ``--all`` contract ("regardless of git
      state"). Use
      ``check_rst check --recursive <recursive_dir>`` (``.check_formatting.toml``'s
      ``[rst].dir``) for a genuine unconditional scan.  A project with no
      ``[rst].dir`` fails clearly: silently falling back to bare mode would
      violate ``--all``'s scope contract.

    Diff mode always selects ``diff --fast`` regardless of scope — the fast,
    parser-free preview (no lint/docutils/Sphinx phases), matching this
    wrapper's own "mechanical preview only" ``--diff`` promise.  Note this is
    the one check_rst mode whose exit code means "a change would be made"
    rather than "an ERROR was found" (check_rst's guide, "Fast mechanical
    mutation and previews") — for this wrapper's purposes both count as "not
    clean", which is the right outcome for ``--diff``.

    ``.formatting-ignore`` and the wrapper's ``--exclude`` are not consulted.
    Run check_rst's recursive mode directly when an RST tree audit needs its
    native ``--exclude`` option.
    """
    log = _make_log(quiet)
    if explicit_files is not None:
        # ignore_patterns=() — .formatting-ignore is deliberately not consulted for rst (see docstring).
        result = _select_explicit(explicit_files, root, (), extensions=frozenset({".rst"}))
        if result is None:
            log("  (no RST files in selection)")
            return True
        rst_files, _ = result

    if explicit_files is None and not recursive_dir:
        _config_error("[rst].dir is required when the rst checker is selected for a full scan (--all)")

    rst_tool = shutil.which("check_rst")
    if rst_tool is None:
        print("  ERROR: check_rst not found on PATH — install it or remove 'rst' from the configured checks")
        return False

    if explicit_files is not None:
        if git_auto_detected:
            label = _file_count_label(len(rst_files), 0) + " — bare, hunk-scoped"
            base = [rst_tool]
        else:
            label = _file_count_label(len(rst_files), 0)
            base = [rst_tool, *[str(f) for f in rst_files]]
    else:
        # explicit_files is None implies recursive_dir here: the guard above
        # (_config_error on "explicit_files is None and not recursive_dir") already
        # exited otherwise.
        label = f"(recursive: {recursive_dir})"
        base = [rst_tool, "--recursive", recursive_dir]

    if fix:
        verb = ["fix", "--fast"] if _bare_scoped(explicit_files, git_auto_detected) else ["fix"]
        log(f"▶ check_rst {' '.join(verb)}  {label}")
        return cli._run([base[0], *verb, *base[1:]], cwd=root) == 0
    if diff:
        log(f"▶ check_rst diff --fast  {label}")
        return cli._run([base[0], "diff", "--fast", *base[1:]], cwd=root) == 0
    verb = ["check", "--verbose"] if verbose else ["check"]
    if verbose:
        log(f"  {rst_tool}")
    log(f"▶ check_rst check  {label}")
    return cli._run([base[0], *verb, *base[1:]], cwd=root) == 0
