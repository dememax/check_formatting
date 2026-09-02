#!/usr/bin/env python3.14
# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Check source file formatting against project coding standards — check_formatting project
"""
Check (or fix) source file formatting against project coding standards.

Each checker below is a plugin over an external formatter/linter backend
(clang-format, meson format, prettier, ruff, mypy, check_rst, clang-tidy,
cmake-format, west, shellcheck).  Which checkers are active by default and
which globs/directories/files each one scans are declared in
``.check_formatting.toml`` at the repository root — never hardcoded in
this script.  The per-checker command lines shown below describe *behavior*
(what each mode does) using this project's own current
``.check_formatting.toml`` values as the illustrative file set; a project
with a different config sees the same modes applied to its own declared
files instead.  Thirteen checkers are registered in total —
``cpp``, ``meson``, ``web``, ``python``, ``json``, ``ini``, ``mypy``,
``rst``, ``clang-tidy``, ``cmake``, ``kconfig``, ``shell``, ``yaml`` — but
none is active unless a project's own ``.check_formatting.toml`` lists it
in ``checks``.  "Active by default" is entirely project-relative: a
Meson/prettier/ruff project might default to ``cpp``/``meson``/``web``/
``python``/``mypy``, while a CMake/Zephyr project would default to
``cmake``/``kconfig`` instead — neither is a fixed property of the tool.
Any registered checker not in a given project's default ``checks`` list is
still reachable via ``--checks`` once its own config section (or, for
``clang-tidy``, a built compile database) is in place.  See this module's
own ``_CHECKERS`` dict for the authoritative, currently-registered checker
list at any given time.

Optional "git-scoped fix" contract
-------------------------------------
Some checkers' backends support restricting a ``--fix`` — and, to keep
check and fix consistent, ``--check``/``--diff`` too, for the *native*
tier below — to just the lines a file actually changed, instead of the
whole file.  This protects pre-existing content elsewhere in a touched
file from being silently renormalized when the file came from
``check_formatting``'s own git auto-detection (see
:func:`_is_git_auto_detected_scope`).  This is an explicit, OPTIONAL
per-checker contract, gated on the backend actually exposing (or, for the
best-effort tier, this script reconstructing) a working line/hunk-range
mechanism — not every checker can offer it, and it comes in two tiers:

Native tier — tool-guaranteed, applies to check/verbose/diff/fix alike
    - ``rst``  — check_rst's own bare-mode git integration (native,
      first-party; see :func:`_check_rst` and check_rst's guide, "History
      protection: bare mode and selective Git scope").
    - ``cpp``  — clang-format's native ``-lines=<start>:<end>``, computed
      per file from ``git diff -U0 HEAD`` via :func:`_git_diff_hunk_ranges`
      (see :func:`_check_cpp`).

Best-effort tier — heuristic
    - ``web``, ``json``, ``ini``, ``yaml`` — prettier has no reliably-usable
      native line-range mechanism across all of these parsers
      (``--range-start``/``--range-end`` exist but are documented mainly for
      JS/TS — see the "Scope guarantee" table in README.md),
      so :func:`_best_effort_prettier_target` reconstructs the effect
      instead: diff the whole-file reformat against the original with
      ``difflib`` (:func:`_merge_within_hunk_ranges`), keep only the
      reformatting that overlaps the file's changed hunks, then verify that
      formatting the merge produces the same canonical whole-file result as
      formatting the original.  Validation uses stdin plus
      ``--stdin-filepath`` so prettier resolves the real file's parser,
      plugins, and path-based configuration.  If the candidate does not
      parse or canonicalizes differently, this falls back to the plain
      whole-file reformat, exactly what ``--fix`` did before this existed:
      never a worse outcome, only sometimes a better one.  All four
      checkers' check/verbose/diff modes compare each file against this
      same target (:func:`_report_prettier_files_git_scoped`) rather than
      the unconditional whole-file reformat — comparing against the
      latter reported a violation on any file whose fix had deliberately
      retained out-of-scope legacy content, contradicting the ``--fix``
      that had just succeeded on the identical file.

Every other checker's backend has no equivalent mechanism at all —
native or reconstructable (meson format, cmake-format, ruff format,
``ruff check --fix``, mypy, west, shellcheck) — so ``--fix`` is
necessarily whole-file for them, and always has been.  This is a
materially lower risk for them than it was for ``rst``: clang-format,
prettier, and ``ruff format`` are convergent, idempotent formatters —
re-running one over already-compliant, untouched lines is a no-op —
whereas check_rst's adornment-hierarchy remap can rewrite headings that
are valid RST but intentionally non-standard for this project
(pandoc-imported docs, historical entries) purely because they don't
match this project's convention, which is exactly what made whole-file
scope dangerous there in the first place.

Four mutually exclusive operating modes are supported:

check (default)
    Each formatter is run in check mode — no files are modified.
    Output is minimal: pass/fail per checker plus a summary table.

    cpp    — clang-format --dry-run --Werror on [cpp].globs; per-file
             -lines= git-scoped when the selection is auto-detected (see
             "Optional git-scoped fix contract" above)
    meson  — meson format --check-only -r -c meson.format
    web    — npx prettier --check on [web].globs
    python — ruff format --check + ruff check on [python].dirs
    json   — npx prettier --check on [json].files (parser selected
             automatically; JSONC files use jsonc parser with
             trailingComma:none via overrides in .prettierrc)
    ini    — npx prettier --check on [ini].globs
             (prettier-plugin-ini; iniSpaceAroundEquals configured via
             overrides in .prettierrc)
    mypy   — mypy strict type-checker on [mypy].dirs, falling back to
             [python].dirs; configuration from [tool.mypy] in pyproject.toml
    rst    — check_rst check; three distinct scopes depending on how files
             were selected (see _check_rst's docstring and check_rst's guide,
             "History protection" for the full rationale): the default
             git-auto-detected scope runs check_rst check bare (hunk-scoped —
             preserves check_rst's own "fix only what you changed"
             contract), a user-typed FILE argument runs check_rst check with
             that file explicitly (whole-file scope — the user asked for
             it), and explicit_files=None (--all, or a direct library
             call) runs check_rst check --recursive on [rst].dir (a genuine
             full-repo scan; missing [rst].dir is an error).
             Sphinx facts come from .check_rst.toml at the repository root.
    clang-tidy, cmake, kconfig, shell, yaml — not necessarily in a given
             project's default ``checks`` list; see the module-level note above and
             ``--checks <name> --help``-style docstrings on each
             ``_check_*`` function for their own config keys and behavior

verbose (``--verbose``)
    Same as check, but each tool is asked for its maximum native
    diagnostic output — warnings, hints, and source context included.
    No files are modified.

    cpp    — clang-format --dry-run --Werror  (identical to check mode,
             including git-scoping;
             clang-format cannot report rule-level diagnostics — the only
             diagnostic it emits is the generic ``[-Wclang-format-violations]``
             code, which means "this file would look different after formatting".
             It cannot tell you *which* rule is violated or *why*.
             Use ``--diff`` to see the exact changes clang-format would make.)
    meson  — meson format --check-only -r     (no extra flags available)
    web    — npx prettier --check --log-level log
    python — ruff format --check + ruff check --output-format full
    json   — npx prettier --check --log-level log (same files as check mode)
    ini    — npx prettier --check --log-level log (same files as check mode)
    mypy   — mypy --show-error-context [mypy].dirs (or [python].dirs fallback)
    rst    — check_rst check --verbose (adds context lines to each finding)
    clang-tidy, cmake, kconfig, shell, yaml — same file selection as check
             mode; most expose no extra diagnostic flags (see each
             ``_check_*`` function's docstring)

diff (``--diff``)
    Each formatter is run in a mode that shows a unified diff of what
    would change.  No files are modified.  The diff is produced by
    comparing the formatter's output against the original source:

    cpp    — clang-format <file> (stdout) vs original, via difflib;
             git-scoped like check/fix when auto-detected
    meson  — meson format -i on a temp copy vs original, via difflib
    web    — npx prettier <file> (stdout) vs original, via difflib
    python — ruff format --diff (native) + ruff check
    json   — npx prettier <file> (stdout) vs original, via difflib
    ini    — npx prettier <file> (stdout) vs original, via difflib
    mypy   — same as check (mypy has no diff mode)
    rst    — check_rst diff --fast (native mechanical preview without validation)
    cmake  — cmake-format <file> (stdout) vs original, via difflib
    yaml   — npx prettier <file> (stdout) vs original, via difflib
    clang-tidy, kconfig, shell — same as check (none of the three
             underlying tools has a diff mode)

fix (``--fix``)
    Each formatter is run in write/inplace mode.  Files are modified.
    clang-tidy, mypy, kconfig, and shell have no fix mode of their own —
    they run their check-mode analysis instead and report violations for
    manual resolution.  ``cpp`` and ``rst`` restrict the write to just the
    changed hunks of an auto-detected file rather than the whole file
    (tool-guaranteed); every Prettier-backed checker (``web``, ``json``,
    ``ini``, ``yaml``) attempts the same as a best-effort heuristic and falls
    back to whole-file if the candidate does not canonicalize to the expected
    full result — see "Optional git-scoped fix contract" above.

Ignore file (``.formatting-ignore``)
    A ``.formatting-ignore`` file at the project root lists files and
    directories excluded from wrapper-selected checks, except ``rst`` (whose
    native scope remains authoritative).  Its syntax is a subset of
    ``.gitignore``:

    - Blank lines and lines starting with ``#`` are ignored.
    - Patterns are relative to the project root and use forward slashes.
    - A trailing ``/`` (e.g. ``src/base/``) excludes every file under
      that directory.
    - ``/**`` at the end of a path (e.g. ``src/base/**``) is treated
      identically to a trailing ``/``.
    - Patterns containing a ``/`` (but no trailing ``/`` or ``/**``) are
      matched against the full relative path with :func:`fnmatch.fnmatch`.
    - Patterns with no ``/`` are matched against the file basename only
      (e.g. ``StaticJSON.hpp`` excludes that file wherever it appears).

    Note: for the ``meson`` and ``web`` checkers in **check** and
    **verbose** modes *without explicit files*, the underlying tools are
    invoked with a single batch command (``meson format -r``,
    ``npx prettier "www/**"``) that cannot filter individual files.
    Per-file exclusions from ``.formatting-ignore`` are applied only in
    **diff** and **fix** modes for those two checkers (and in all modes
    for ``cpp``), or in any mode when explicit files are supplied.  Use
    the tools' own ignore mechanisms for finer control:
    ``.prettierignore`` for prettier, ``[tool.ruff.exclude]`` in
    ``pyproject.toml`` for ruff.  The ``rst`` checker never consults this file
    or the wrapper's ``--exclude`` option.  Run ``check_rst check --recursive
    ... --exclude ...`` directly when an RST tree audit needs exclusions.

Prerequisites
-------------

clang-format
    Part of the LLVM toolchain.  Install via the system package manager::

        sudo apt install clang-format        # Debian/Ubuntu
        brew install llvm                    # macOS

meson format
    Provided by Meson itself (≥ 1.5.0 required for ``--check-only``).
    Install via pip or the system package manager::

        pip install meson

prettier (``web``, ``json``, ``ini``, and ``yaml`` checkers)
    prettier is a Node.js tool and is **not** available as a standalone
    system binary.  It requires:

    1. **Node.js** (≥ 18 recommended) and **npm**::

           sudo apt install nodejs npm       # Debian/Ubuntu
           brew install node                # macOS

    2. **Project dependencies** installed from ``package.json`` at the
       repository root (this installs prettier into ``node_modules/``)::

           npm install

    The script invokes prettier via ``npx prettier``, which resolves the
    locally installed version from ``node_modules/.bin/prettier``.
    Running ``npx prettier`` without ``node_modules/`` present will
    attempt a one-off network download, which may fail in offline
    environments or produce a version mismatch.

ruff
    Python linter and formatter.  Install via pip::

        pip install ruff

mypy
    Python static type-checker, resolved from ``PATH`` according to the
    project tool-resolution policy in ``AGENTS.md``.  Install via the system
    package manager or pip::

        sudo apt install mypy      # Debian/Ubuntu
        pip install mypy

check_rst (``rst`` checker)
    RST/Sphinx linter and fixer installed as the standalone ``check_rst``
    package and resolved from ``PATH``.  A missing executable fails the
    selected checker.  A full-repo scan (``--all``, or a direct library call
    with no ``explicit_files``) additionally needs
    ``.check_formatting.toml``'s ``[rst].dir`` set to the project's RST root
    (matching ``.check_rst.toml``'s ``sphinx-src``).  Without it, the selected
    full scan fails rather than silently checking only Git-changed files.

clang-tidy (``clang-tidy`` checker — optional, project-dependent)
    Part of the LLVM toolchain, same install as clang-format above.
    Additionally requires an up-to-date ``compile_commands.json`` in the
    build directory named by ``.check_formatting.toml``'s
    ``[clang_tidy].build_dir`` (generated automatically by Meson on
    ``meson compile``).  A project with no ``[clang_tidy]`` section skips
    this checker cleanly without requiring clang-tidy on ``PATH`` at all.

cmake-format (``cmake`` checker — optional; only relevant to CMake-based
projects, not Meson-based ones)
    Install via pip::

        pip install cmake-format

west (``kconfig`` checker — optional; only relevant to projects with a
Kconfig/west workspace)
    Part of a Zephyr-style West workspace.  Requires at least one entry in
    ``.check_formatting.toml``'s ``[kconfig].build_combos``; a project with
    none skips this checker cleanly without requiring ``west`` on ``PATH``.

shellcheck (``shell`` checker — optional; only relevant to projects with
shell scripts)
    Install via the system package manager::

        sudo apt install shellcheck        # Debian/Ubuntu
        brew install shellcheck            # macOS

A per-checker summary is printed at the end.
Exits 0 only if every checker reports no violations.

Usage (standalone)::

    check_formatting
    check_formatting --all
    check_formatting --verbose
    check_formatting --diff
    check_formatting --fix
    check_formatting --checks mypy
    check_formatting --checks cpp meson
    check_formatting --checks cpp meson --fix
    check_formatting --fail-fast
    check_formatting src/Foo.cpp www/index.html
    check_formatting --fix src/Foo.cpp docs/conf.py

File-selection scope
---------------------

With no FILE arguments and no ``--all``, the default scope is files
changed since HEAD plus untracked files, auto-detected via git (mirrors
check_rst's own default) — not a full-repo scan.  If nothing is changed,
the script reports "nothing to do" and exits 0 without running any
checker.  Pass ``--all`` for the unconditional full-repo scan instead,
including from release-gate callers.  Explicit FILE arguments
restrict each checker to only those listed files that match its type
and, for configuration-driven checkers, its declared globs/files.  Thus a
configured C++ ``*.h`` file, TypeScript file, or extensionless shell script
remains in scope instead of being discarded by a built-in suffix list.
Checkers with no matching files pass vacuously.
``.formatting-ignore`` is still applied after the type filter, in every
scope mode.

Scope guarantee: file-level only, not line-level
--------------------------------------------------

The scopes above are all **file**-level by default: a file is either
checked/fixed in full, or not looked at at all.  ``cpp`` and ``rst``
guarantee **line**-level scoping (native tier) when the file selection is
git auto-detected (see "Optional git-scoped fix contract" above): a
modified tracked file is only checked/fixed on the lines that actually
changed, never renormalizing pre-existing content elsewhere in the same
file.  Every Prettier-backed checker reconstructs the same effect on a
best-effort basis (``--fix`` only), falling back to whole-file if the
candidate does not canonicalize to the expected full result.  Every other
checker remains file-level only, because it is a thin wrapper around an
independently-maintained external tool with no equivalent native mechanism.
Concretely, per checker:

======================  ===========================  ============================================
Checker                 Tool                          Line-range restriction available?
======================  ===========================  ============================================
``cpp``                 clang-format                  Yes — native ``-lines=<start>:<end>``,
                                                        exploited by ``_check_cpp`` when the
                                                        selection is git auto-detected
``clang-tidy``           clang-tidy                    Yes — native ``-line-filter=<json>`` — but
                                                        unexploited: this checker never writes
                                                        files in check_formatting (report-only
                                                        in every mode), so there is no mutation to
                                                        scope, only potential reporting noise
``web``/``json``/       prettier                       No reliable native mechanism across every
``ini``/``yaml``                                        parser — but ``_fix_prettier_files`` shares
                                                        a best-effort equivalent for ``--fix``:
                                                        diff the whole-file reformat, keep changes
                                                        overlapping git hunks, verify canonical
                                                        equivalence, and fall back if it fails
``meson``               meson format                   No — whole-file only
``cmake``               cmake-format                   No — whole-file only
``python`` (format)     ruff format                    No — whole-file only (same gap as Black)
``python`` (lint)       ruff check                     No native fix-range flag; diagnostics are
                                                        per-line, so *reporting* could be filtered
                                                        post-hoc (not implemented)
``mypy``                mypy                           **N/A** — whole-program type inference; a
                                                        change on one line can surface an error on
                                                        an unrelated line
``kconfig``             west build --cmake-only        **N/A** — validates merged Kconfig state
                                                        across all ``.conf`` files together; a
                                                        warning has no single owning line
``shell``               shellcheck                     No known native flag; several checks
                                                        (unused vars, sourced-file resolution) are
                                                        whole-script by nature regardless
``rst``                 check_rst                      Yes — check_rst's own bare-mode git
                                                        integration, exploited by ``_check_rst``
                                                        when the selection is git auto-detected
======================  ===========================  ============================================

``cpp`` and ``rst`` genuinely honor a line-scoped ``--fix`` today via a
native tool mechanism (see "Optional git-scoped fix contract" above for the
exact mechanism and rationale for each); the four Prettier-backed checkers
reconstruct the same effect as a verified best-effort heuristic — the "diff
the full reformat, keep only overlapping hunks" shortcut this section used
to call categorically risky, made safe by never trusting the merge without
first confirming it canonicalizes to the expected whole-file result, and
falling back otherwise (see :func:`_best_effort_prettier_fix`).
``clang-tidy`` has the native mechanism but nothing to apply it to, since it
never writes files here.  The rest either lack a mechanism to reconstruct
from at all, or are fundamentally incompatible with the concept (mypy,
kconfig) — for those, whole-file ``--fix`` is a low-risk default because the
underlying formatters are convergent and idempotent, not because
check_formatting chose not to protect them.

Callable as a library (from another script in ``scripts/``)::

    from check_formatting import check_formatting
    ok = check_formatting(project_root)
    ok = check_formatting(project_root, verbose=True)
    ok = check_formatting(project_root, diff=True)
    ok = check_formatting(project_root, fix=True)
    ok = check_formatting(project_root, explicit_files=[pathlib.Path("src/Foo.cpp").resolve()])
    ok = check_formatting(project_root, explicit_files=None)  # unconditional full-repo scan
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import pathlib
import sys
from typing import TYPE_CHECKING

from check_formatting.cli._checkers import (
    _MYPY_CACHE_VERSION_MARKER,
    _check_clang_tidy,
    _check_cmake,
    _check_cpp,
    _check_ini,
    _check_json,
    _check_kconfig,
    _check_meson,
    _check_mypy,
    _check_python,
    _check_rst,
    _check_shell,
    _check_web,
    _check_yaml,
    _invalidate_mypy_cache_if_version_changed,
)
from check_formatting.cli._config import (
    _CONFIG_FILE,
    _CONFIG_SECTIONS,
    ProjectConfig,
    _config_error,
    _echo_project_config,
    _load_project_config,
    _optional_section,
    _require_build_combos,
    _require_str,
    _require_str_list,
    _require_table,
    _validate_check_names,
)
from check_formatting.cli._prettier import (
    _best_effort_prettier_fix,
    _best_effort_prettier_target,
    _fix_prettier_files,
    _merge_within_hunk_ranges,
    _report_prettier_files_git_scoped,
)
from check_formatting.cli._registry import _CHECKERS, Checker, _checker_kwargs, _fix_command
from check_formatting.cli._selection import (
    _bare_scoped,
    _batched_git_diff_hunk_ranges,
    _detect_changed_files,
    _file_matches_any_glob,
    _git_diff_hunk_ranges,
    _is_git_auto_detected_scope,
    _load_ignore_patterns,
    _parse_git_diff_hunks_by_relpath,
    _resolve_explicit_files,
)
from check_formatting.cli._subprocess import (
    _fmt_stdout,
    _make_log,
    _print_tool_info,
    _run,
    _run_capture_merged,
    _show_diff,
    _ThreadLocalStdout,
    _tool_version_string,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

# Every name below used to live directly in this module when it was a
# single flat cli.py file. Re-exported here — rather than left as an
# internal-only import — so the split is invisible to every existing
# monkeypatch/attribute-access site across the test suite (e.g.
# `monkeypatch.setattr(check_formatting, "_run", ...)`,
# `check_formatting._CONFIG_SECTIONS`): they all resolve through this
# package's own namespace exactly as they did before the split.
__all__ = [
    "_CHECKERS",
    "_CONFIG_FILE",
    "_CONFIG_SECTIONS",
    "_MYPY_CACHE_VERSION_MARKER",
    "Checker",
    "ProjectConfig",
    "_bare_scoped",
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
    "_config_error",
    "_detect_changed_files",
    "_echo_project_config",
    "_file_matches_any_glob",
    "_fix_command",
    "_fix_prettier_files",
    "_fmt_stdout",
    "_git_diff_hunk_ranges",
    "_invalidate_mypy_cache_if_version_changed",
    "_is_git_auto_detected_scope",
    "_load_ignore_patterns",
    "_load_project_config",
    "_make_log",
    "_merge_within_hunk_ranges",
    "_optional_section",
    "_parse_git_diff_hunks_by_relpath",
    "_print_tool_info",
    "_report_prettier_files_git_scoped",
    "_require_build_combos",
    "_require_str",
    "_require_str_list",
    "_require_table",
    "_resolve_explicit_files",
    "_run",
    "_run_capture_merged",
    "_show_diff",
    "_tool_version_string",
    "_validate_check_names",
    "check_formatting",
    "main",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_formatting(
    project_root: pathlib.Path | str,
    checks: list[str] | None = None,
    fail_fast: bool = False,
    fix: bool = False,
    diff: bool = False,
    verbose: bool = False,
    explicit_files: list[pathlib.Path] | None = None,
    quiet: bool = False,
    as_json: bool = False,
    exclude_patterns: Sequence[str] = (),
    *,
    git_auto_detected: bool = False,
) -> bool:
    """Check, verbose-check, diff, or fix source file formatting.

    Parameters
    ----------
    project_root : pathlib.Path | str
        Root of the project being checked.  The CLI passes the invoking
        process's current working directory — no parent-directory walking,
        matching check_rst's own discovery contract exactly: run the tool
        from the project root.  A library caller may pass any path instead.
    checks : list[str] | None
        Subset of checks to run.  Defaults to *project_root*'s
        ``.check_formatting.toml``'s ``checks`` list.  Any checker
        registered in :data:`_CHECKERS` but not in that list (e.g.
        ``clang-tidy``, which needs a compile database; ``cmake``/
        ``kconfig``, which only apply to CMake/Zephyr-based projects) must
        be requested explicitly via *checks* or ``--checks`` — "optional"
        is a project-relative fact, not a fixed list: a project whose
        default ``checks`` already includes ``cmake``/``kconfig`` (e.g. a
        Zephyr project) would have those run by default there instead.
    fail_fast : bool
        Stop *reporting* at the first checker that reports a problem, in
        *checks* list order — no summary table (or, under *as_json*, no
        further ``results``/``summary`` entries) beyond that point.  Every
        checker still runs to completion regardless: dispatch is
        unconditionally concurrent, threads cannot be safely killed
        mid-flight, and by the time a failure is known here the remaining
        checkers are typically already running.  This does not save
        wall-clock time — it only shortens what gets printed/returned.
    fix : bool
        Run each formatter in write/inplace mode.  Files are modified.
        Mutually exclusive with *diff* and *verbose*.
    diff : bool
        Show a unified diff of what each formatter would change; no files
        are modified.  Mutually exclusive with *fix* and *verbose*.
    verbose : bool
        Run each formatter with its maximum native diagnostic output
        (warnings, hints, source context where supported); no files are
        modified.  Mutually exclusive with *fix* and *diff*.
    explicit_files : list[pathlib.Path] | None
        Three distinct states:

        - ``None`` — full-repo scan (every file matching each enabled
          checker's configured globs/dirs). This is what release-gate library
          callers and ``--all`` request.
        - A non-empty list — each checker processes only those files that
          match its configured targets or fixed file domain; checkers with
          no matching files pass vacuously.
          Paths must be absolute.
        - An **empty** list — explicitly nothing to check.  Returns
          ``True`` immediately with a one-line "nothing to do" report (or
          the equivalent ``--json`` payload), without running any
          checker.  This is deliberately distinct from ``None``: the CLI
          produces this state when git-based auto-detection
          (:func:`_detect_changed_files`) finds no changed files, and
          collapsing it into "full repo" instead (as an earlier version
          of ``main()`` did via ``[...] or None``) would silently expand
          scope at exactly the moment nothing should run.
    quiet : bool
        Suppress this script's own chrome — section banners, the
        box-drawing summary table, the config echo, each checker's own
        "▶ command" announcement lines, and "(no files found)"-style scope
        notices.  Never suppresses genuine ERROR messages, diff content,
        the wrapped tool's own real output, or the final one-line
        machine-parseable summary.  Combinable with *fix*/*diff* (mutually
        exclusive with *verbose* only, the opposite pole of the same
        verbosity axis).  Never changes the return value or exit code —
        a display filter only, mirroring check_rst's own invariant that
        verbosity level never affects whether a run is considered a pass.
    as_json : bool
        Print one JSON object to stdout instead of the human-readable
        banners/table/summary, and nothing else — this script's own chrome
        is suppressed exactly as under *quiet* (forced on internally), and
        each checker's real output (including the wrapped tool's own
        stdout, captured for the duration of that checker's run) is
        embedded as a string field instead of being printed directly, so
        no information is lost relative to a normal run.  Payload shape:
        ``{"config_source": str, "mode": str, "checks": [str, ...],
        "results": {name: {"label": str, "ok": bool, "output": str}},
        "summary": {"total": int, "passed": int, "failed": int},
        "overall_ok": bool}``.  Never changes the return value or exit
        code.
    exclude_patterns : Sequence[str]
        Additional patterns to exclude from this run only, on top of
        ``.formatting-ignore`` (and, for the clang-tidy checker,
        ``.clang-tidy-ignore``) — same pattern syntax as
        ``.formatting-ignore`` (deliberately: one consistent syntax
        across both mechanisms, not ``check_rst --exclude``'s
        ``pathlib.PurePath.match()`` rules).  Use this for an ad hoc,
        single-invocation exclusion (e.g. a work-in-progress file you
        don't want flagged just for this run) without editing a
        committed ignore file and having to remember to revert it.
    git_auto_detected : bool, keyword-only
        True when *explicit_files* (if not ``None``) came from git
        auto-detection rather than a user-typed FILE argument — see
        :func:`_is_git_auto_detected_scope`.  The ``cpp`` checker, all four
        Prettier-backed checkers (``web``, ``json``, ``ini``, ``yaml``), and
        ``rst`` consult this to activate their respective native,
        canonically-validated best-effort, and bare-mode git-scoping behavior.
        The CLI sets this automatically; other library callers only need it
        if they pass a *file_args*-equivalent list obtained the same way.
        Keyword-only so adding it cannot shift the public API's pre-existing
        positional ``quiet``, ``as_json``, and ``exclude_patterns`` arguments.

    Every selected checker runs concurrently, regardless of *fail_fast* —
    see its own entry above for what that flag actually controls now.
    Nothing is printed incrementally while checkers are still running: all
    output (banners, each checker's own findings, the summary table or
    JSON payload) is produced together only once every checker has
    finished, in *checks* list order, never completion order.  This
    applies even to a single selected checker, deliberately: there is no
    special case for "only one checker running".

    Returns
    -------
    bool
        ``True`` if every checker passed, ``False`` otherwise.
    """
    effective_quiet = quiet or as_json
    log = _make_log(effective_quiet)
    root = pathlib.Path(project_root)
    config = _load_project_config(root)
    if checks is None:
        checks = config.checks
    else:
        _validate_check_names(checks, "checks argument")

    mode = "fix" if fix else "diff" if diff else "verbose" if verbose else "check"

    if explicit_files is not None and not explicit_files:
        if as_json:
            empty_payload: dict[str, object] = {
                "config_source": _CONFIG_FILE,
                "mode": mode,
                "checks": [],
                "results": {},
                "summary": {"total": 0, "passed": 0, "failed": 0},
                "overall_ok": True,
            }
            print(json.dumps(empty_payload))
        else:
            print("check_formatting: no changed files — nothing to do")
        return True

    if not effective_quiet:
        _echo_project_config(_CONFIG_FILE, config)
    ignore_patterns = _load_ignore_patterns(root) + list(exclude_patterns)

    results: dict[str, bool] = {}
    outputs: dict[str, str] = {}

    action = mode.capitalize()

    def run_one(name: str) -> tuple[bool, str]:
        """Run checker *name* with its own private stdout capture buffer.

        Every checker dispatches concurrently (see below), so this always
        captures rather than only under --json: 11 of 13 checkers still
        stream live via _run's per-line sys.stdout.write, which would
        interleave garbage if several ran at once against the single real
        stdout. mux (the thread-local stdout installed for the duration of
        this whole dispatch) routes this thread's writes to its own
        buffer instead.
        """
        checker = _CHECKERS[name]
        buf = mux.register()
        try:
            ok = checker.fn(
                root,
                fix,
                diff,
                verbose,
                ignore_patterns,
                explicit_files,
                quiet=True if as_json else quiet,
                **_checker_kwargs(name, config, git_auto_detected),
            )
        finally:
            mux.unregister()
        return ok, buf.getvalue()

    fail_fast_triggered = False
    real_stdout = sys.stdout
    mux = _ThreadLocalStdout(real_stdout)
    sys.stdout = mux
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(checks) or 1) as pool:
            # Submit every checker immediately — dispatch is unconditionally
            # concurrent, fail_fast or not. Consuming futures below in
            # checks' original order, only after each has actually
            # completed, is what keeps printed output deterministic
            # (checks-list order, never completion order) while still
            # gaining wall-clock parallelism — the same pattern already
            # used for the ruff/kconfig/prettier concurrency in this
            # project. Exiting the `with` block waits for every submitted
            # future regardless of whether the loop below `break`s early,
            # which is exactly what makes --fail-fast's new "every checker
            # still runs to completion" guarantee hold without any extra
            # bookkeeping.
            futures = {name: pool.submit(run_one, name) for name in checks}

            for name in checks:
                ok, output = futures[name].result()
                results[name] = ok
                outputs[name] = output

                if not as_json:
                    label = _CHECKERS[name].label
                    log()
                    log("┌──────────────────────────────────────────────────────────────┐")
                    header = f"{action}: {label}"
                    log(f"│  {header:<60}│")
                    log("└──────────────────────────────────────────────────────────────┘")
                    log()
                    print(output, end="")

                if not ok and fail_fast:
                    # "Stop reporting", not "stop running": every checker was
                    # already submitted above and keeps running to
                    # completion in the background regardless — this only
                    # truncates what gets printed/included in the payload,
                    # matching today's "no summary table" contract for a
                    # report built from already-known results instead of an
                    # early return. Threads can't be safely killed mid-flight
                    # in Python, and by the time a failure is known here,
                    # other checkers are typically already running — dispatch
                    # no longer buys fail_fast any wall-clock savings.
                    fail_fast_triggered = True
                    break
    finally:
        sys.stdout = real_stdout

    if fail_fast_triggered and not as_json:
        return False

    if as_json:
        overall_ok = all(results.values()) if results else True
        payload = {
            "config_source": _CONFIG_FILE,
            "mode": mode,
            "checks": checks,
            "results": {
                name: {"label": _CHECKERS[name][0], "ok": results[name], "output": outputs[name]}
                for name in checks
                if name in results
            },
            "summary": {
                "total": len(results),
                "passed": sum(1 for v in results.values() if v),
                "failed": sum(1 for v in results.values() if not v),
            },
            "overall_ok": overall_ok,
        }
        print(json.dumps(payload))
        return overall_ok

    # Summary table
    title = {"fix": "Fix Results", "diff": "Diff Results", "verbose": "Verbose Results", "check": "Formatting Results"}[
        mode
    ]
    title_cell = f"  {title}"
    log()
    log("╔══════════════════════════════════════════════════════════════╗")
    log(f"║{title_cell:<62}║")
    log("╠══════════════════════════════════════════════════╦═══════════╣")
    log(f"║ {'Checker':<48} ║ {'Status':<9} ║")
    log("╠══════════════════════════════════════════════════╬═══════════╣")

    overall_ok = True
    for name in checks:
        label = _CHECKERS[name][0]
        ok = results.get(name, False)
        mark = ("✓ DONE" if fix else "✓ PASS") if ok else "✗ FAIL"
        log(f"║ {label:<48} ║ {mark:<9} ║")
        if not ok:
            overall_ok = False

    log("╚══════════════════════════════════════════════════╩═══════════╝")
    log()

    passed = sum(1 for name in checks if results.get(name, False))
    failed = len(checks) - passed
    print(f"check_formatting: {len(checks)} checker(s) run, {passed} passed, {failed} failed")
    print()

    if not overall_ok:
        if fix:
            print("FORMATTING: unfixable violations remain — see output above.")
        else:
            if diff:
                print("FORMATTING: violations found — see diff above. To fix, run:")
            else:
                print("FORMATTING: violations found. To fix, run:")
            hint_git_auto_detected = _bare_scoped(explicit_files, git_auto_detected)
            failed_checks = [name for name in checks if not results.get(name, True)]
            for name in failed_checks:
                print(f"    {_fix_command(name, config, git_auto_detected=hint_git_auto_detected)}")
            auto_fixable_failures = [name for name in failed_checks if _CHECKERS[name].auto_fix]
            if auto_fixable_failures:
                print()
                if len(auto_fixable_failures) == len(failed_checks):
                    print("    (or re-run with --fix to apply all fixes at once)")
                else:
                    print(
                        "    (or re-run with --fix to apply automatic fixes where available; manual fixes will remain)"
                    )
        return False

    if fix:
        print("FORMATTING: all fixes applied successfully.")
    elif diff:
        print("FORMATTING: no formatting changes needed.")
    else:
        print("FORMATTING: all checks passed.")
    return True


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse command-line arguments and exit with the aggregate check result."""
    from check_formatting import __copyright__, __license__, __version__

    version_banner = f"%(prog)s {__version__}\n{__copyright__}\nLicense: {__license__}"

    parser = argparse.ArgumentParser(
        prog="check_formatting",
        description=(
            "Check (or fix) source file formatting against project coding standards. "
            "Exits 0 if every requested checker reports no violations, 1 otherwise — "
            "this exit-code contract is unaffected by --quiet/--verbose/--diff, which "
            "change only what is printed, never the pass/fail verdict."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""\
Examples:

  check_formatting
      Default scope: files changed since HEAD plus untracked files,
      auto-detected via git (mirrors check_rst's own default).  If
      nothing is changed, reports "nothing to do" and exits 0 without
      running any checker.

  check_formatting --all
      Force a full-repo scan instead — EVERY file matching each enabled
      checker's configured globs/dirs (.check_formatting.toml),
      regardless of git state.  Use this for a release-gate-style check,
      or any time you need the unconditional "check literally everything"
      guarantee appropriate for a release gate.

  check_formatting -- $(git diff --name-only HEAD)
      Scope the check to exactly this explicit file list instead of
      auto-detection — useful when you want a narrower or different set
      than "everything currently changed." Each checker still filters
      that list through its configured targets or fixed file domain.

  check_formatting --verbose
      Same as check, but with maximum native diagnostic output from each
      tool: source context for ruff violations, info logs from prettier.

  check_formatting --diff
      Show a unified diff of what each formatter would change, without
      modifying any file.

  check_formatting --fix
      Apply all formatters in-place (clang-format -i, meson format -i,
      prettier --write, ruff format + ruff check --fix).

  check_formatting --checks cpp meson
      Run only C++ and Meson build file formatting checks.

  check_formatting --checks cpp meson --fix
      Fix only C++ and Meson build files.

  check_formatting --fail-fast
      Shorten the report to stop at the first checker (in --checks order)
      that reports violations — no summary table beyond that point. Every
      checker still runs to completion regardless: checks always dispatch
      concurrently, so this does not save any wall-clock time, only
      output.

  check_formatting src/Foo.cpp www/index.html
      Check only those two files (each checker filters to its own type).

  check_formatting --fix src/Foo.cpp docs/conf.py
      Fix formatting in those two files only.

  check_formatting --checks cpp -- src/Foo.cpp
      Run only the C++ checker on a specific file (use -- to separate
      FILE arguments from option arguments when needed).

  check_formatting --checks clang-tidy
      Run clang-tidy static analysis (not in the default set).
      Requires compile_commands.json in the Meson build directory named
      in .check_formatting.toml's [clang_tidy].build_dir:
        meson compile -C <that build directory>

  check_formatting --exclude generated_snapshot.py
      Skip one file for this run only (repeatable), without editing
      .formatting-ignore — for a one-off exclusion you don't want to
      remember to revert.

Ignore file:

  Create .formatting-ignore at the repository root to exclude third-party
  or vendored files from all checks.  Syntax is a subset of .gitignore:

    src/base/          # exclude entire directory
    src/StaticJSON.hpp # exclude specific file
    *.pb.h             # exclude by basename pattern

{__copyright__}
License: {__license__}
""",
    )
    parser.add_argument("--version", action="version", version=version_banner)
    parser.add_argument(
        "--checks",
        nargs="+",
        metavar="CHECK",
        choices=list(_CHECKERS),
        default=None,
        help=(
            "Checks to run (default: .check_formatting.toml's `checks` list). "
            f"Valid names: {', '.join(sorted(_CHECKERS))}. A name not in the "
            "default list must be requested explicitly here — it may need extra "
            "setup (e.g. clang-tidy's compile database) or simply not apply to "
            "this project's build system (e.g. cmake/kconfig on a Meson "
            "project). 'Optional' is project-relative, not a fixed list."
        ),
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Run each tool with maximum native diagnostic output — source "
            "context, warnings, and hints.  No files are modified."
        ),
    )
    mode_group.add_argument(
        "--diff",
        action="store_true",
        help=("Show a unified diff of what each formatter would change, without modifying any file."),
    )
    mode_group.add_argument(
        "--fix",
        action="store_true",
        help=(
            "Apply formatters in-place instead of checking.  Equivalent to running each fix command shown on failure."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help=(
            "Suppress this script's own chrome (section banners, the summary table, "
            "the config echo, each checker's '▶ command' lines, and "
            "'(no files found)'-style scope notices).  Never suppresses ERROR messages, "
            "diff content, the wrapped tool's own real output, or the final one-line "
            "summary.  Combinable with --fix/--diff; mutually exclusive with --verbose "
            "only, the opposite pole of the same verbosity axis."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Print one JSON object to stdout instead of the human-readable banners/table, "
            "and nothing else — this script's own chrome is suppressed exactly as under "
            "--quiet (forced on internally), and each checker's real output (including the "
            "wrapped tool's own stdout, captured for the duration of that checker's call) "
            "is embedded as a string field instead of printed directly, so no information "
            "is lost.  Combinable with any other flag (--fix/--diff/--verbose/--quiet); "
            "never changes the exit code.  Payload: {config_source, mode, checks, "
            "results: {name: {label, ok, output}}, summary: {total, passed, failed}, "
            "overall_ok}."
        ),
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help=(
            "Stop the report at the first checker (in --checks order) that reports "
            "a problem — no summary table beyond that point.  Every checker still runs "
            "to completion regardless: checks always dispatch concurrently, so this saves "
            "no wall-clock time, only shortens what gets printed.  By default (this flag "
            "omitted) every checker's result is included and a summary table is printed."
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "Force a full-repo scan (every file matching each enabled checker's "
            "configured globs/dirs), overriding the default git-based auto-detection "
            "of changed/untracked files.  Not allowed together with FILE arguments."
        ),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Skip files matching PATTERN for this run only, on top of "
            ".formatting-ignore (and .clang-tidy-ignore for the clang-tidy checker) "
            "— same pattern syntax as .formatting-ignore, not check_rst --exclude's "
            "pathlib.PurePath.match() rules.  Repeatable.  Use this for an ad hoc, "
            "single-invocation exclusion (e.g. a work-in-progress file) without "
            "editing a committed ignore file."
        ),
    )
    parser.add_argument(
        "explicit_files",
        nargs="*",
        metavar="FILE",
        help=(
            "Optional explicit file paths to check.  Omit entirely (and omit --all) "
            "for the default scope: files changed since HEAD plus untracked files, "
            "auto-detected via git — mirrors check_rst's own default, and matches how "
            "this tool is actually used interactively (see --all for a full-repo scan "
            "instead).  Each checker processes only files matching its configured targets or fixed file domain; "
            "checkers with no matching files pass vacuously.  Use -- to separate FILE "
            "arguments from option arguments when needed."
        ),
    )
    args = parser.parse_args()
    if args.quiet and args.verbose:
        parser.error("argument --quiet: not allowed with argument --verbose")
    if args.all and args.explicit_files:
        parser.error("argument --all: not allowed with FILE arguments")

    project_root = pathlib.Path.cwd()
    explicit_files = _resolve_explicit_files(args.explicit_files, args.all, project_root)
    git_auto_detected = _is_git_auto_detected_scope(args.explicit_files, args.all)
    ok = check_formatting(
        project_root,
        checks=args.checks,
        exclude_patterns=args.exclude,
        fail_fast=args.fail_fast,
        fix=args.fix,
        diff=args.diff,
        verbose=args.verbose,
        explicit_files=explicit_files,
        git_auto_detected=git_auto_detected,
        quiet=args.quiet,
        as_json=args.json,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
