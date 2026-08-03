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
    rst    — check_rst; three distinct scopes depending on how files were
             selected (see _check_rst's docstring and check_rst's guide,
             "History protection" for the full rationale): the default
             git-auto-detected scope runs check_rst bare (hunk-scoped —
             preserves check_rst's own "fix only what you changed"
             contract), a user-typed FILE argument runs check_rst with
             that file explicitly (whole-file scope — the user asked for
             it), and explicit_files=None (--all, or a direct library
             call) runs check_rst --recursive on [rst].dir (a genuine
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
    rst    — check_rst --verbose (adds context lines to each finding)
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
    rst    — check_rst --diff-only (native mechanical preview without validation)
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
    or the wrapper's ``--exclude`` option.  Run ``check_rst --recursive ...
    --exclude ...`` directly when an RST tree audit needs exclusions.

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

import argparse
import contextlib
import dataclasses
import difflib
import fnmatch
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Sequence

# Name of the per-project ignore file (lives at the repository root).
IGNORE_FILE = ".formatting-ignore"

# Per-checker ignore file for clang-tidy only.  Patterns in this file are
# applied in addition to IGNORE_FILE.  Use it for files that clang-tidy
# cannot parse (e.g. because they include GCC-specific headers) but that
# are still valid targets for clang-format and other checkers.
CLANG_TIDY_IGNORE_FILE = ".clang-tidy-ignore"

# Name of the per-project config file (lives at the repository root).
_CONFIG_FILE = ".check_formatting.toml"

# Known keys per config section (project-specific paths/globs/targets).
# Mypy may override the Python (Ruff) target set, with Python dirs as fallback.
_CONFIG_SECTIONS: dict[str, frozenset[str]] = {
    "cpp": frozenset({"globs"}),
    "web": frozenset({"globs"}),
    "python": frozenset({"dirs"}),
    "mypy": frozenset({"dirs"}),
    "json": frozenset({"files"}),
    "ini": frozenset({"globs"}),
    "clang_tidy": frozenset({"build_dir"}),
    "kconfig": frozenset({"build_combos"}),
    "shell": frozenset({"globs"}),
    "yaml": frozenset({"globs"}),
    "rst": frozenset({"dir"}),
}

_TOP_LEVEL_KEYS = frozenset({"checks", *_CONFIG_SECTIONS})


@dataclasses.dataclass(frozen=True)
class ProjectConfig:
    """Resolved, validated contents of `.check_formatting.toml`."""

    checks: list[str]
    cpp_globs: list[str]
    web_globs: list[str]
    python_dirs: list[str]
    mypy_dirs: list[str]
    json_files: list[str]
    ini_globs: list[str]
    clang_tidy_build_dir: str
    kconfig_build_combos: list[dict[str, object]]
    shell_globs: list[str]
    yaml_globs: list[str]
    rst_dir: str


def _config_error(message: str) -> None:
    print(f"check_formatting: {message}")
    sys.exit(1)


def _require_str_list(table: dict[str, object], key: str, where: str) -> list[str]:
    value = table.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        _config_error(f"{where}: {key!r} must be a list of strings, got {value!r}")
    return value  # type: ignore[return-value]


def _require_str(table: dict[str, object], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str):
        _config_error(f"{where}: {key!r} must be a string, got {value!r}")
    return value  # type: ignore[return-value]


def _load_project_config(root: pathlib.Path) -> ProjectConfig:
    """Load and validate `.check_formatting.toml` at *root*.

    Declaration, not auto-detection — mirrors `.check_rst.toml`'s contract:
    discovery at *root* only (no parent-directory walking), unknown keys and
    wrong-typed values are a hard error, and a missing file is a hard error
    too — the script has no meaningful default behavior without knowing what
    to check.
    """
    path = root / _CONFIG_FILE
    if not path.is_file():
        _config_error(f"{_CONFIG_FILE} not found at {root} — see .check_rst.toml for the convention this mirrors")
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        _config_error(f"invalid {_CONFIG_FILE}: {exc}")

    unknown_top = set(data) - _TOP_LEVEL_KEYS
    if unknown_top:
        _config_error(
            f"unknown key(s) in {_CONFIG_FILE}: {', '.join(sorted(unknown_top))}"
            f" — known keys: {', '.join(sorted(_TOP_LEVEL_KEYS))}"
        )

    for section, known_keys in _CONFIG_SECTIONS.items():
        if section not in data:
            continue
        table = _require_table(data, section)
        unknown = set(table) - known_keys
        if unknown:
            _config_error(
                f"unknown key(s) in [{section}]: {', '.join(sorted(unknown))}"
                f" — known keys: {', '.join(sorted(known_keys))}"
            )

    checks = _require_str_list(data, "checks", _CONFIG_FILE)
    _validate_check_names(checks, _CONFIG_FILE)
    python_dirs = _optional_section_str_list(data, "python", "dirs")
    mypy_dirs = _optional_section_str_list(data, "mypy", "dirs") if "mypy" in data else python_dirs
    return ProjectConfig(
        checks=checks,
        cpp_globs=_optional_section_str_list(data, "cpp", "globs"),
        web_globs=_optional_section_str_list(data, "web", "globs"),
        python_dirs=python_dirs,
        mypy_dirs=mypy_dirs,
        json_files=_optional_section_str_list(data, "json", "files"),
        ini_globs=_optional_section_str_list(data, "ini", "globs"),
        clang_tidy_build_dir=_optional_section_str(data, "clang_tidy", "build_dir"),
        kconfig_build_combos=_optional_section_build_combos(data, "kconfig", "build_combos"),
        shell_globs=_optional_section_str_list(data, "shell", "globs"),
        yaml_globs=_optional_section_str_list(data, "yaml", "globs"),
        rst_dir=_optional_section_str(data, "rst", "dir"),
    )


def _validate_check_names(checks: Sequence[str], where: str) -> None:
    """Reject checker names that are not registered in :data:`_CHECKERS`."""
    unknown = sorted(set(checks) - _CHECKERS.keys())
    if unknown:
        _config_error(f"{where}: unknown checker(s): {', '.join(unknown)}")


def _optional_section_str_list(data: dict[str, object], section: str, key: str) -> list[str]:
    """Return ``data[section][key]`` as a validated string list, or ``[]`` if *section* is absent.

    A project with no targets for this checker simply omits the section —
    that is not an error. If the section IS present, its keys are still fully
    validated (missing or wrong-typed values are still a hard error —
    declaring the section means declaring it correctly).
    """
    if section not in data:
        return []
    return _require_str_list(_require_table(data, section), key, f"[{section}]")


def _optional_section_str(data: dict[str, object], section: str, key: str) -> str:
    """Return ``data[section][key]`` as a validated string, or ``""`` if *section* is absent."""
    if section not in data:
        return ""
    return _require_str(_require_table(data, section), key, f"[{section}]")


def _optional_section_build_combos(data: dict[str, object], section: str, key: str) -> list[dict[str, object]]:
    """Return ``data[section][key]`` as a validated build-combo list, or ``[]`` if *section* is absent.

    Each combo is a table with ``label`` (str) and ``args`` (list of str) —
    a project-specific `west build` invocation, e.g. for the ``kconfig``
    checker. Unlike the flat string lists used elsewhere, this is a list of
    tables, so it gets its own validator.
    """
    if section not in data:
        return []
    return _require_build_combos(_require_table(data, section), key, f"[{section}]")


def _require_build_combos(table: dict[str, object], key: str, where: str) -> list[dict[str, object]]:
    value = table.get(key)
    if not isinstance(value, list):
        _config_error(f"{where}: {key!r} must be a list of tables, got {value!r}")
    combos: list[dict[str, object]] = []
    item: object
    for i, item in enumerate(value):  # type: ignore[arg-type]
        if not isinstance(item, dict):
            _config_error(f"{where}: {key!r}[{i}] must be a table, got {item!r}")
            continue
        label: object = item.get("label")
        if not isinstance(label, str):
            _config_error(f"{where}: {key!r}[{i}].label must be a string, got {label!r}")
        args: object = item.get("args")
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            _config_error(f"{where}: {key!r}[{i}].args must be a list of strings, got {args!r}")
        combos.append({"label": label, "args": args})
    return combos


def _require_table(data: dict[str, object], section: str) -> dict[str, object]:
    table = data[section]
    if not isinstance(table, dict):
        _config_error(f"[{section}] must be a table, got {table!r}")
    return table  # type: ignore[return-value]


def _echo_project_config(source: str, config: ProjectConfig) -> None:
    """Print the applied config for traceability, mirroring check_rst's echo line."""
    print(f"config: {source} — checks={config.checks}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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


def _print_tool_info(
    binary: str | pathlib.Path,
    cwd: pathlib.Path,
    version_args: list[str] | None = None,
) -> None:
    """Print the resolved binary path and version string in verbose mode."""
    binary_str = str(binary)
    resolved = binary_str if pathlib.Path(binary_str).is_absolute() else shutil.which(binary_str) or binary_str
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
        raw = (result.stdout + result.stderr).strip()
        version_line = raw.splitlines()[0] if raw else "(unknown)"
    except FileNotFoundError, OSError, subprocess.TimeoutExpired:
        version_line = "(unavailable)"
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


def _prettier_diff(files: list[pathlib.Path], root: pathlib.Path) -> bool:
    """Run prettier per-file and show a unified diff for each violation.

    Shared by the web, JSON, INI, and YAML checkers' diff mode (identical loop).
    Returns True if no file would change, False on a violation or a
    prettier invocation failure.
    """
    any_violation = False
    for f in files:
        rc, formatted = _fmt_stdout(["npx", "--no-install", "prettier", str(f)], cwd=root)
        if rc == 127:
            return False
        if rc != 0:
            print(f"ERROR: prettier exited {rc} on {f.name}")
            return False
        if _show_diff(f.read_text(encoding="utf-8"), formatted, str(f.relative_to(root))):
            any_violation = True
    return not any_violation


def _load_ignore_patterns(root: pathlib.Path, filename: str = IGNORE_FILE) -> list[str]:
    """Load ignore patterns from *filename* at the project root.

    Returns an empty list if the file does not exist.  Pass *filename* to
    load from an alternative ignore file (e.g. :data:`CLANG_TIDY_IGNORE_FILE`).

    Pattern syntax (subset of ``.gitignore``):

    - Blank lines and lines starting with ``#`` are skipped.
    - Patterns are relative to *root*, using forward slashes.
    - Trailing ``/`` → directory prefix (every file under it is excluded).
    - Trailing ``/**`` → same as trailing ``/``.
    - Patterns containing ``/`` → matched against the full relative path
      with :func:`fnmatch.fnmatch`.
    - Patterns without ``/`` → matched against the file basename only.
    """
    ignore_file = root / filename
    if not ignore_file.exists():
        return []
    patterns = []
    for line in ignore_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _is_ignored(path: pathlib.Path, root: pathlib.Path, patterns: Sequence[str]) -> bool:
    """Return True if *path* matches any pattern in *patterns*.

    See :func:`_load_ignore_patterns` for pattern syntax.
    """
    if not patterns:
        return False
    rel_posix = path.relative_to(root).as_posix()
    for pattern in patterns:
        if pattern.endswith("/"):
            # Directory prefix: "src/base/"
            if rel_posix.startswith(pattern):
                return True
        elif pattern.endswith("/**"):
            # Directory prefix: "src/base/**" → treat as "src/base/"
            prefix = pattern[:-2]  # strip "**", keep trailing "/"
            if rel_posix.startswith(prefix):
                return True
        elif "/" in pattern:
            # Path-rooted glob: match against the full relative path
            if fnmatch.fnmatch(rel_posix, pattern):
                return True
        else:
            # No slash: match against the file basename only
            if fnmatch.fnmatch(path.name, pattern):
                return True
    return False


def _detect_changed_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Return absolute paths of files changed since HEAD or untracked, at *root*.

    Mirrors check_rst's own default file-selection scope: tracked files
    modified/added since HEAD (``git diff --name-only HEAD``) plus
    untracked files (``git status --porcelain --untracked-files=all``,
    filtered to ``??`` entries so untracked directories are expanded to
    their individual files rather than reported as one directory path).

    Deleted files are excluded — a path git reports as changed but that no
    longer exists on disk has nothing to check.  May return ``[]`` when
    nothing is changed; the caller (:func:`check_formatting`) treats an
    empty list as an explicit "nothing to do" state, distinct from ``None``
    (full-repo scan).

    A ``git`` failure here (e.g. *root* is not a git repository) is a hard
    error, not a silent fallback to full-repo scanning or to "nothing
    changed" — either guess could silently hide files that should have
    been checked.
    """
    tracked = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"], cwd=root, capture_output=True, text=True, encoding="utf-8"
    )
    if tracked.returncode != 0:
        print(f"check_formatting: git diff failed: {tracked.stderr.strip()}")
        sys.exit(1)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if status.returncode != 0:
        print(f"check_formatting: git status failed: {status.stderr.strip()}")
        sys.exit(1)

    names = {line for line in tracked.stdout.splitlines() if line}
    for line in status.stdout.splitlines():
        if line.startswith("??"):
            names.add(line[3:].strip())

    return sorted((root / name).resolve() for name in names if (root / name).is_file())


# Matches a unified-diff hunk header, e.g. "@@ -3 +3 @@" or "@@ -2,0 +3,2 @@".
# Only the new-file side (after "+") is captured — see _git_diff_hunk_ranges.
_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _git_diff_hunk_ranges(root: pathlib.Path, file: pathlib.Path) -> list[tuple[int, int]] | None:
    """Return 1-indexed ``(start, end)`` line ranges changed in *file*'s current version.

    Backs the optional "git-scoped fix" contract (see :func:`_check_cpp`): a
    checker whose backend accepts a native line-range flag (clang-format's
    ``-lines=<start>:<end>``) can restrict a ``--fix`` — and, to keep
    check/fix consistent, a ``--check``/``--diff`` — to just the lines that
    actually changed, mirroring check_rst's own bare-mode hunk scoping.

    Ranges are derived from ``git diff -U0 HEAD -- <file>``'s hunk headers,
    the same mechanism check_rst itself uses.  A hunk whose new-file line
    count is zero (a pure deletion) contributes no range — nothing was
    added there for a line-range-based formatter to reformat.

    Returns ``None`` — "no hunk restriction available, use whole-file scope
    instead" — when the diff has no usable hunks: an untracked file (no
    ``HEAD`` baseline, so ``git diff HEAD`` shows nothing for it at all), a
    file whose only changes were pure deletions, or a ``git`` failure.
    Unlike :func:`_detect_changed_files`, a git failure here degrades to
    whole-file scope rather than aborting the whole run — this is an
    optional safety refinement of an already-selected file, not the
    file-selection decision itself.
    """
    result = subprocess.run(
        ["git", "diff", "-U0", "HEAD", "--", str(file)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return None
    ranges: list[tuple[int, int]] = []
    for line in result.stdout.splitlines():
        m = _HUNK_HEADER_RE.match(line)
        if not m:
            continue
        new_start = int(m.group(1))
        new_count = int(m.group(2)) if m.group(2) is not None else 1
        if new_count == 0:
            continue
        ranges.append((new_start, new_start + new_count - 1))
    return ranges or None


def _resolve_explicit_files(
    file_args: Sequence[str], all_files: bool, project_root: pathlib.Path
) -> list[pathlib.Path] | None:
    """Resolve ``main()``'s FILE positional args and ``--all`` into :func:`check_formatting`'s *explicit_files*.

    - ``all_files`` (``--all``) forces ``None`` — an explicit request for the
      full-repo scan, regardless of any FILE args (``main()`` rejects that
      combination before this is called).
    - Non-empty *file_args* scope to exactly those paths, unchanged from
      before this auto-detection feature existed.
    - No *file_args* — whether the FILE positional was omitted entirely, or
      given but expanded to nothing (e.g. ``-- $(git diff --name-only
      HEAD)`` when nothing is changed) — triggers git-based auto-detection
      via :func:`_detect_changed_files`, mirroring check_rst's own default.
      This may itself resolve to ``[]``, which is returned as-is: it is
      :func:`check_formatting`'s job to report that as "nothing to do",
      not this function's job to paper over it by falling back to ``None``
      (the bug this replaces — see the module's "no silent failures" note).
    """
    if all_files:
        return None
    if file_args:
        return [_resolve_under(p, project_root) for p in file_args]
    return _detect_changed_files(project_root)


def _is_git_auto_detected_scope(file_args: Sequence[str], all_files: bool) -> bool:
    """True when file selection came from git auto-detection — no ``--all``, no FILE args.

    Mirrors :func:`_resolve_explicit_files`'s own "no file_args" branch without
    duplicating its return-type contract (a plain ``list[Path] | None`` that
    existing callers/tests already depend on).  The rst checker needs this
    extra bit alongside the resolved file list: an auto-detected list must
    run check_rst bare to preserve its native hunk-scoped ``--fix``, while a
    list the user typed explicitly on the CLI should keep check_rst's
    whole-file scope (see :func:`_check_rst`'s docstring).
    """
    return not all_files and not file_args


def _resolve_under(path_str: str, root: pathlib.Path) -> pathlib.Path:
    """Resolve *path_str* to an absolute path, anchoring relative paths at *root*.

    ``pathlib.Path(p).resolve()`` alone anchors relative paths at the
    process's actual working directory, which only coincidentally matches
    *root* when the caller happens to run from the repository root — this
    anchors explicitly instead, since *root* (``project_root``) is this
    tool's real reference point regardless of the invoking shell's cwd.
    """
    path = pathlib.Path(path_str)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _filter_configured_targets(
    files: Sequence[pathlib.Path], root: pathlib.Path, targets: Sequence[str]
) -> list[pathlib.Path]:
    """Keep explicit *files* that equal or descend from configured *targets*.

    An empty target list preserves the legacy direct-library behavior.  Once a
    project declares targets, however, changed-file and explicit-file scopes
    may narrow that set but must never expand beyond it.
    """
    if not targets:
        return list(files)
    resolved_targets = [_resolve_under(target, root) for target in targets]
    return [
        path
        for path in files
        if any(path.resolve() == target or path.resolve().is_relative_to(target) for target in resolved_targets)
    ]


def _filter_files(
    files: list[pathlib.Path],
    root: pathlib.Path,
    ignore_patterns: Sequence[str],
) -> tuple[list[pathlib.Path], int]:
    """Remove ignored files from *files*.

    Returns
    -------
    tuple[list[pathlib.Path], int]
        Filtered file list and the number of files that were excluded.
    """
    if not ignore_patterns:
        return files, 0
    kept = [f for f in files if not _is_ignored(f, root, ignore_patterns)]
    return kept, len(files) - len(kept)


def _configured_glob_paths(root: pathlib.Path, globs: Sequence[str]) -> frozenset[pathlib.Path]:
    """Return the existing files selected by project-configured *globs*."""
    return frozenset(f.resolve() for glob in globs for f in root.glob(glob) if f.is_file())


def _select_explicit_from_globs(
    explicit_files: list[pathlib.Path],
    root: pathlib.Path,
    ignore_patterns: Sequence[str],
    globs: Sequence[str],
    *,
    fallback_extensions: frozenset[str],
) -> tuple[list[pathlib.Path], int] | None:
    """Select explicit files using configured globs, with a legacy fallback when unconfigured.

    Normal CLI dispatch always supplies the checker's configured globs.  The
    suffix fallback preserves the direct helper-call API for callers that omit
    checker configuration entirely.
    """
    if globs:
        return _select_explicit(
            explicit_files,
            root,
            ignore_patterns,
            exact_paths=_configured_glob_paths(root, globs),
        )
    return _select_explicit(
        explicit_files,
        root,
        ignore_patterns,
        extensions=fallback_extensions,
    )


def _file_count_label(total: int, excluded: int) -> str:
    """Return a human-readable label like ``(12 file(s), 3 excluded)``."""
    if excluded:
        return f"({total + excluded} file(s), {excluded} excluded)"
    return f"({total} file(s))"


def _select_explicit(
    explicit_files: list[pathlib.Path],
    root: pathlib.Path,
    ignore_patterns: Sequence[str],
    *,
    extensions: frozenset[str] | None = None,
    exact_names: frozenset[str] | None = None,
    exact_paths: frozenset[pathlib.Path] | None = None,
) -> tuple[list[pathlib.Path], int] | None:
    """Intersect *explicit_files* with this checker's file-type set.

    Returns ``None`` when the intersection is empty (caller should skip
    silently).  Returns ``(kept, excluded)`` otherwise, where *excluded*
    is the count of files removed by ignore patterns.

    Keyword matching (applied with OR logic):

    - *extensions*  — ``file.suffix`` in the set (e.g. ``{".cpp", ".hpp"}``)
    - *exact_names* — ``file.name`` in the set (e.g. ``{"meson.build"}``)
    - *exact_paths* — ``file.resolve()`` in the set (used for JSONC files)
    """
    matched = [
        f
        for f in explicit_files
        if (extensions and f.suffix in extensions)
        or (exact_names and f.name in exact_names)
        or (exact_paths and f.resolve() in exact_paths)
    ]
    if not matched:
        return None
    kept, excluded = _filter_files(sorted(matched), root, ignore_patterns)
    return kept, excluded


def _lines_flags(root: pathlib.Path, file: pathlib.Path) -> list[str]:
    """Return clang-format ``-lines=<start>:<end>`` flags for *file*'s changed hunks.

    Empty when :func:`_git_diff_hunk_ranges` finds no derivable ranges (an
    untracked file, a pure-deletion-only diff, or a git failure) — the
    caller then falls back to whole-file scope, exactly today's behavior.
    """
    ranges = _git_diff_hunk_ranges(root, file)
    if ranges is None:
        return []
    return [f"-lines={start}:{end}" for start, end in ranges]


def _merge_within_hunk_ranges(original: str, formatted: str, ranges: Sequence[tuple[int, int]]) -> str:
    """Merge *formatted* into *original*, keeping only the reformatting that overlaps *ranges*.

    Backs the Prettier checkers' "best-effort" git-scoped fix (see
    :func:`_best_effort_prettier_fix`) — prettier has no reliably-usable
    native line-range mechanism, unlike clang-format's ``-lines=`` (see
    :func:`_lines_flags`), so this reconstructs an equivalent effect by
    diffing the whole-file reformat against the original.

    *ranges* are 1-indexed inclusive line ranges in *original*'s
    coordinates (:func:`_git_diff_hunk_ranges`'s own return shape).  Using
    ``difflib.SequenceMatcher`` rather than reusing git's hunk line numbers
    directly against *formatted* is what avoids the "naive" version's
    trap: reformatting can shift line counts (splitting or collapsing
    lines), so a line number in *original* and the same line number in
    *formatted* stop corresponding once anything upstream changed shape.
    ``get_opcodes()`` instead gives each disjoint changed region in BOTH
    coordinate systems at once, so overlap is always tested against
    *original*'s own coordinates, and the corresponding *formatted* slice
    is used verbatim, never sliced further — splitting an opcode label
    would reintroduce the same "cut mid-construct" risk this exists to
    avoid.

    An opcode outside every range is reverted to *original*'s own lines —
    that formatting change is out of scope for this fix.  The result is
    NOT guaranteed to be valid or fully compliant on its own; the caller
    verifies that before trusting it (see :func:`_best_effort_prettier_fix`).
    """
    orig_lines = original.splitlines(keepends=True)
    fmt_lines = formatted.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=orig_lines, b=fmt_lines, autojunk=False)
    hunk_spans = [(start - 1, end) for start, end in ranges]  # 1-indexed inclusive -> 0-indexed half-open
    merged: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            merged.extend(orig_lines[i1:i2])
            continue
        in_scope = any(i1 < hend and i2 > hstart for hstart, hend in hunk_spans)
        merged.extend(fmt_lines[j1:j2] if in_scope else orig_lines[i1:i2])
    return "".join(merged)


def _best_effort_prettier_target(file: pathlib.Path, root: pathlib.Path) -> tuple[bool, str, str]:
    """Compute what a best-effort git-scoped prettier fix would write for *file*.

    Shared by :func:`_best_effort_prettier_fix` (which writes the result)
    and the ``web`` checker's check/verbose/diff modes (which only need to
    know the target to compare the current file against) — using ONE
    function for both is what guarantees check and fix can never disagree
    about what "fixed" means for a given file; two independently
    maintained implementations could silently drift apart.

    prettier has no reliably-usable native line-range mechanism for
    HTML/CSS (``--range-start``/``--range-end`` exist but are documented
    as unconfirmed outside JS/TS — see README.md's "Scope
    guarantee" table), so this is a heuristic "best effort" rather than a
    tool-guaranteed contract like ``cpp``'s ``-lines=`` or ``rst``'s
    check_rst bare mode:

    1. Reformat the whole file (what today's whole-file ``--write`` does).
    2. If already compliant, or the file has no derivable git hunk ranges
       (untracked, or a pure-deletion diff), stop there — nothing to merge,
       or nothing to merge against.
    3. Otherwise merge via :func:`_merge_within_hunk_ranges`, keeping only
       the reformatting that overlaps the file's changed hunks.
    4. Verify the merge before trusting it: feed the merged candidate to
       prettier through stdin with ``--stdin-filepath <real file>`` and
       require its canonical form to equal the whole-file result from step
       1.  This proves that the candidate parses and still represents the
       same canonical document while permitting deliberately retained,
       out-of-scope legacy formatting.  Using the real filepath is essential
       for parser inference and path-based config overrides.  If the candidate
       canonicalizes differently, the heuristic is unsafe and this falls back
       to the plain whole-file reformat instead, exactly today's behavior.
       This never produces a worse outcome than before, only sometimes better.

    Returns ``(ok, target, status)``.  *ok* is ``False`` only on a prettier
    invocation failure (missing tool, or a real error on the source file) —
    *target* is then meaningless.  *status* is a short human-readable
    outcome: ``"already compliant"``, ``"whole-file fix (no git hunk
    info)"``, ``"git-scoped merge"``, or ``"whole-file fallback (candidate
    canonicalized differently)"``.
    """
    original = file.read_text(encoding="utf-8")
    rc, formatted = _fmt_stdout(["npx", "--no-install", "prettier", str(file)], cwd=root)
    if rc == 127:
        return False, original, "prettier not found"
    if rc != 0:
        return False, original, f"prettier exited {rc}"
    if original == formatted:
        return True, formatted, "already compliant"

    ranges = _git_diff_hunk_ranges(root, file)
    if ranges is None:
        return True, formatted, "whole-file fix (no git hunk info)"

    merged = _merge_within_hunk_ranges(original, formatted, ranges)

    rc2, canonical_merge = _fmt_stdout(
        ["npx", "--no-install", "prettier", "--stdin-filepath", str(file)],
        cwd=root,
        input_text=merged,
    )

    if rc2 == 0 and canonical_merge == formatted:
        return True, merged, "git-scoped merge"

    return True, formatted, "whole-file fallback (candidate canonicalized differently)"


def _best_effort_prettier_fix(file: pathlib.Path, root: pathlib.Path) -> tuple[bool, str]:
    """Attempt a hunk-scoped prettier fix for *file*, writing the result in-place.

    Delegates the actual scoped-merge-vs-whole-file decision entirely to
    :func:`_best_effort_prettier_target` (see its docstring for the full
    mechanism) and writes *target* when it differs from the file's current
    content.  Returns ``(ok, status)`` — see
    :func:`_best_effort_prettier_target` for what *status* can be.
    """
    original = file.read_text(encoding="utf-8")
    ok, target, status = _best_effort_prettier_target(file, root)
    if not ok:
        return False, status
    if target != original:
        file.write_text(target, encoding="utf-8")
    return True, status


def _fix_prettier_files(
    files: Sequence[pathlib.Path],
    root: pathlib.Path,
    *,
    git_auto_detected: bool,
    label: str,
    log: Callable[..., None],
) -> bool:
    """Fix Prettier-backed *files*, optionally using best-effort Git hunk scope.

    Shared by the web, JSON/JSONC, INI, and YAML checkers.  Git-auto-detected
    scope runs :func:`_best_effort_prettier_fix` per file so each candidate
    can be merged and canonically validated independently; failures are
    accumulated without preventing later files from being attempted.  Every
    deliberate whole-file scope (``--all`` or user-typed FILE arguments)
    retains Prettier's single batched ``--write`` invocation.
    """
    if git_auto_detected:
        log(f"▶ npx prettier --write (best-effort git-scoped)  {label}")
        ok = True
        for file in files:
            file_ok, status = _best_effort_prettier_fix(file, root)
            log(f"  {file.relative_to(root)}: {status}")
            ok = file_ok and ok
        return ok

    log(f"▶ npx prettier --write  {label}")
    return _run(["npx", "--no-install", "prettier", "--write", *[str(file) for file in files]], cwd=root) == 0


def _report_prettier_files_git_scoped(
    files: Sequence[pathlib.Path],
    root: pathlib.Path,
    *,
    show_diff: bool,
    log: Callable[..., None],
) -> bool:
    """Compare each file against what :func:`_best_effort_prettier_fix` would write.

    Used by the git-auto-detected branch of check/verbose/diff modes so
    they never disagree with what a subsequent ``--fix`` would actually
    do — comparing against the unconditional whole-file reformat instead
    (as every mode did before this existed) reported a violation on any
    file whose git-scoped fix had deliberately retained out-of-scope
    legacy content, contradicting the ``--fix`` that had just succeeded.

    When *show_diff*, prints a unified diff (original vs. target) for
    each file that differs, via :func:`_show_diff`; otherwise only the
    per-file status line is logged and the boolean verdict is computed.
    """
    any_violation = False
    for file in files:
        original = file.read_text(encoding="utf-8")
        ok, target, status = _best_effort_prettier_target(file, root)
        if not ok:
            print(f"ERROR: {status} on {file.name}")
            return False
        log(f"  {file.relative_to(root)}: {status}")
        if show_diff:
            if _show_diff(original, target, str(file.relative_to(root))):
                any_violation = True
        elif original != target:
            any_violation = True
    return not any_violation


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
    if not files and not excluded:
        log("  (no C++ files found)")
        return True
    if not files:
        log(f"  (all {excluded} C++ file(s) excluded by {IGNORE_FILE})")
        return True
    label = _file_count_label(len(files), excluded)

    if fix:
        if git_auto_detected:
            log(f"▶ clang-format -i (git-scoped)  {label}")
            ok = True
            for f in files:
                cmd = ["clang-format", "-i", *_lines_flags(root, f), str(f)]
                ok = (_run(cmd, cwd=root) == 0) and ok
            return ok
        log(f"▶ clang-format -i  {label}")
        return _run(["clang-format", "-i"] + [str(f) for f in files], cwd=root) == 0
    if diff:
        log(f"▶ clang-format (diff{', git-scoped' if git_auto_detected else ''})  {label}")
        any_violation = False
        for f in files:
            lines_flags = _lines_flags(root, f) if git_auto_detected else []
            rc, formatted = _fmt_stdout(["clang-format", *lines_flags, str(f)], cwd=root)
            if rc == 127:
                return False
            if rc != 0:
                print(f"ERROR: clang-format exited {rc} on {f.name}")
                return False
            if _show_diff(f.read_text(encoding="utf-8"), formatted, str(f.relative_to(root))):
                any_violation = True
        return not any_violation
    # check and verbose: clang-format exposes no extra diagnostic flags
    if verbose:
        _print_tool_info("clang-format", cwd=root)
    if git_auto_detected:
        log(f"▶ clang-format --dry-run --Werror (git-scoped)  {label}")
        rc = 0
        for f in files:
            rc |= _run(["clang-format", *_lines_flags(root, f), "--dry-run", "--Werror", str(f)], cwd=root)
        return rc == 0
    log(f"▶ clang-format --dry-run --Werror  {label}")
    return (
        _run(
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
    if not files and not excluded:
        log("  (no CMakeLists.txt files found)")
        return True
    if not files:
        log(f"  (all {excluded} CMakeLists.txt file(s) excluded by {IGNORE_FILE})")
        return True
    label = _file_count_label(len(files), excluded)
    cmake_bin = shutil.which("cmake-format")
    if cmake_bin is None:
        print("  ERROR: cmake-format not found — install it via pip (pip install cmake-format)")
        return False
    if fix:
        log(f"▶ cmake-format --in-place  {label}")
        return _run([cmake_bin, "--in-place"] + [str(f) for f in files], cwd=root) == 0
    if diff:
        log(f"▶ cmake-format (diff)  {label}")
        any_violation = False
        for f in files:
            rc, formatted = _fmt_stdout([cmake_bin, str(f)], cwd=root)
            if rc == 127:
                return False
            if rc != 0:
                print(f"ERROR: cmake-format exited {rc} on {f.name}")
                return False
            if _show_diff(f.read_text(encoding="utf-8"), formatted, str(f.relative_to(root))):
                any_violation = True
        return not any_violation
    # check and verbose: cmake-format exposes no extra diagnostic flags
    if verbose:
        _print_tool_info(cmake_bin, cwd=root)
    log(f"▶ cmake-format --check  {label}")
    return _run([cmake_bin, "--check"] + [str(f) for f in files], cwd=root) == 0


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
        if not build_files and not excluded:
            log("  (no Meson build files found)")
            return True
        if not build_files:
            log(f"  (all Meson build files excluded by {IGNORE_FILE})")
            return True
    if fix:
        label = _file_count_label(len(build_files), excluded)
        log(f"▶ meson format -i  {label}")
        return (
            _run(
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
                rc, _ = _fmt_stdout(
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
            if _show_diff(original, formatted, str(f.relative_to(root))):
                any_violation = True
        return not any_violation
    if explicit_files is not None:
        # check/verbose with explicit files: per-file (cannot use -r)
        label = _file_count_label(len(build_files), excluded)
        if verbose:
            _print_tool_info("meson", cwd=root)
        log(f"▶ meson format --check-only -c meson.format  {label}")
        rc = 0
        for f in build_files:
            rc |= _run(
                ["meson", "format", "--check-only", "-c", "meson.format", str(f)],
                cwd=root,
            )
        return rc == 0
    # check and verbose: single batch command — .formatting-ignore not applied
    if verbose:
        _print_tool_info("meson", cwd=root)
    log("▶ meson format --check-only -r -c meson.format")
    return (
        _run(
            ["meson", "format", "--check-only", "-r", "-c", "meson.format"],
            cwd=root,
        )
        == 0
    )


# Glob patterns covering every web file passed to prettier (HTML/CSS/JS).
# Used for both file-system discovery (root.glob) and as CLI arguments.
_WEB_GLOBS: tuple[str, ...] = ()

# Pre-built quoted string for display in print statements and _FIX_COMMANDS.
_WEB_GLOBS_DISPLAY = " ".join(f'"{g}"' for g in _WEB_GLOBS)


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
        if not web_files and not excluded:
            log("  (no web files found)")
            return True
        if not web_files:
            log(f"  (all web files excluded by {IGNORE_FILE})")
            return True
    if fix:
        label = _file_count_label(len(web_files), excluded)
        return _fix_prettier_files(
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
                _print_tool_info("npx", cwd=root, version_args=["prettier", "--version"])
            log(f"▶ npx prettier --check (git-scoped)  {label}")
            return _report_prettier_files_git_scoped(web_files, root, show_diff=False, log=log)
        # check/verbose with explicit files: pass paths directly, not globs
        cmd = ["npx", "--no-install", "prettier", "--check"]
        if verbose:
            _print_tool_info("npx", cwd=root, version_args=["prettier", "--version"])
            cmd += ["--log-level", "log"]
        log(f"▶ npx prettier --check  {label}")
        return _run(cmd + [str(f) for f in web_files], cwd=root) == 0
    if verbose:
        _print_tool_info("npx", cwd=root, version_args=["prettier", "--version"])
        log(f"▶ npx prettier --check --log-level log {globs_display}")
        return _run(["npx", "--no-install", "prettier", "--check", "--log-level", "log", *globs], cwd=root) == 0
    log(f"▶ npx prettier --check {globs_display}")
    return _run(["npx", "--no-install", "prettier", "--check", *globs], cwd=root) == 0


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

    Both sub-commands must exit 0 for the check to pass.

    Note: ``.formatting-ignore`` exclusions are not applied for ruff when
    operating on directories (``scripts/`` and ``tests/``).  Use
    ``[tool.ruff.exclude]`` in ``pyproject.toml`` for per-file exclusions.
    When explicit files are provided, they are passed directly to ruff and
    ``.formatting-ignore`` patterns are applied beforehand.
    """
    log = _make_log(quiet)
    if explicit_files is not None:
        result = _select_explicit(explicit_files, root, ignore_patterns, extensions=frozenset({".py"}))
        if result is None:
            log("  (no Python files in selection)")
            return True
        py_files, excluded = result
        py_files = _filter_configured_targets(py_files, root, dirs)
        if not py_files:
            log("  (no Python files in configured targets after exclusions)")
            return True
        targets = [str(f) for f in py_files]
        targets_label = _file_count_label(len(py_files), excluded)
    else:
        targets = list(dirs)
        targets_label = f"({', '.join(targets)})"
    if fix:
        log(f"▶ ruff format  {targets_label}")
        fmt_rc = _run(["ruff", "format", *targets], cwd=root)
        log()
        log(f"▶ ruff check --fix  {targets_label}")
        lint_rc = _run(["ruff", "check", "--fix", *targets], cwd=root)
    elif diff:
        log(f"▶ ruff format --diff  {targets_label}")
        fmt_rc = _run(["ruff", "format", "--diff", *targets], cwd=root)
        log()
        log(f"▶ ruff check  {targets_label}")
        lint_rc = _run(["ruff", "check", *targets], cwd=root)
    elif verbose:
        _print_tool_info("ruff", cwd=root)
        log(f"▶ ruff format --check  {targets_label}")
        fmt_rc = _run(["ruff", "format", "--check", *targets], cwd=root)
        log()
        log(f"▶ ruff check --output-format full  {targets_label}")
        lint_rc = _run(["ruff", "check", "--output-format", "full", *targets], cwd=root)
    else:
        log(f"▶ ruff format --check  {targets_label}")
        fmt_rc = _run(["ruff", "format", "--check", *targets], cwd=root)
        log()
        log(f"▶ ruff check  {targets_label}")
        lint_rc = _run(["ruff", "check", *targets], cwd=root)
    return fmt_rc == 0 and lint_rc == 0


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
    if not matched_files and not excluded:
        log("  (no JSON files found)")
        return True
    if not matched_files:
        log(f"  (all JSON files excluded by {IGNORE_FILE})")
        return True
    label = _file_count_label(len(matched_files), excluded)
    str_files = [str(f) for f in matched_files]
    if fix:
        return _fix_prettier_files(
            matched_files,
            root,
            git_auto_detected=git_auto_detected,
            label=label,
            log=log,
        )
    if diff:
        if git_auto_detected:
            log(f"▶ npx prettier (diff, git-scoped)  {label}")
            return _report_prettier_files_git_scoped(matched_files, root, show_diff=True, log=log)
        log(f"▶ npx prettier (diff)  {label}")
        return _prettier_diff(matched_files, root)
    if git_auto_detected:
        if verbose:
            _print_tool_info("npx", cwd=root, version_args=["prettier", "--version"])
        log(f"▶ npx prettier --check (git-scoped)  {label}")
        return _report_prettier_files_git_scoped(matched_files, root, show_diff=False, log=log)
    if verbose:
        _print_tool_info("npx", cwd=root, version_args=["prettier", "--version"])
        log(f"▶ npx prettier --check --log-level log  {label}")
        return _run(["npx", "--no-install", "prettier", "--check", "--log-level", "log", *str_files], cwd=root) == 0
    log(f"▶ npx prettier --check  {label}")
    return _run(["npx", "--no-install", "prettier", "--check", *str_files], cwd=root) == 0


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
    if not files and not excluded:
        log("  (no INI files found)")
        return True
    if not files:
        log(f"  (all INI files excluded by {IGNORE_FILE})")
        return True
    label = _file_count_label(len(files), excluded)
    str_files = [str(f) for f in files]
    if fix:
        return _fix_prettier_files(
            files,
            root,
            git_auto_detected=git_auto_detected,
            label=label,
            log=log,
        )
    if diff:
        if git_auto_detected:
            log(f"▶ npx prettier (diff, git-scoped)  {label}")
            return _report_prettier_files_git_scoped(files, root, show_diff=True, log=log)
        log(f"▶ npx prettier (diff)  {label}")
        return _prettier_diff(files, root)
    if git_auto_detected:
        if verbose:
            _print_tool_info("npx", cwd=root, version_args=["prettier", "--version"])
        log(f"▶ npx prettier --check (git-scoped)  {label}")
        return _report_prettier_files_git_scoped(files, root, show_diff=False, log=log)
    if verbose:
        _print_tool_info("npx", cwd=root, version_args=["prettier", "--version"])
        log(f"▶ npx prettier --check --log-level log  {label}")
        return _run(["npx", "--no-install", "prettier", "--check", "--log-level", "log", *str_files], cwd=root) == 0
    log(f"▶ npx prettier --check  {label}")
    return _run(["npx", "--no-install", "prettier", "--check", *str_files], cwd=root) == 0


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
    if not files and not excluded:
        log("  (no YAML files found)")
        return True
    if not files:
        log(f"  (all {excluded} YAML file(s) excluded by {IGNORE_FILE})")
        return True
    label = _file_count_label(len(files), excluded)
    str_files = [str(f) for f in files]
    if fix:
        return _fix_prettier_files(
            files,
            root,
            git_auto_detected=git_auto_detected,
            label=label,
            log=log,
        )
    if diff:
        if git_auto_detected:
            log(f"▶ npx prettier (diff, git-scoped)  {label}")
            return _report_prettier_files_git_scoped(files, root, show_diff=True, log=log)
        log(f"▶ npx prettier (diff)  {label}")
        return _prettier_diff(files, root)
    if git_auto_detected:
        if verbose:
            _print_tool_info("npx", cwd=root, version_args=["prettier", "--version"])
        log(f"▶ npx prettier --check (git-scoped)  {label}")
        return _report_prettier_files_git_scoped(files, root, show_diff=False, log=log)
    if verbose:
        _print_tool_info("npx", cwd=root, version_args=["prettier", "--version"])
        log(f"▶ npx prettier --check --log-level log  {label}")
        return _run(["npx", "--no-install", "prettier", "--check", "--log-level", "log", *str_files], cwd=root) == 0
    log(f"▶ npx prettier --check  {label}")
    return _run(["npx", "--no-install", "prettier", "--check", *str_files], cwd=root) == 0


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
    if explicit_files is not None:
        result = _select_explicit(explicit_files, root, ignore_patterns, extensions=frozenset({".py"}))
        if result is None:
            log("  (no Python files in selection)")
            return True
        py_files, excluded = result
        py_files = _filter_configured_targets(py_files, root, dirs)
        if not py_files:
            log("  (no Python files in configured targets after exclusions)")
            return True
        targets = [str(f) for f in py_files]
        targets_label = _file_count_label(len(py_files), excluded)
    else:
        targets = list(dirs)
        targets_label = f"({', '.join(targets)})"
    if fix:
        log("  (mypy has no fix mode — running type-check)")
    elif diff:
        log("  (mypy has no diff mode — running type-check)")
    # Wiped unconditionally: mypy is resolved from PATH, so a machine running
    # a different mypy version than whatever last wrote this
    # cache could silently produce wrong (missing or spurious) results if the
    # (version-dependent) incremental cache format were reused across a
    # version change, instead of a clean full recheck.
    cache_dir = root / ".mypy_cache"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    found = shutil.which("mypy")
    mypy_bin = pathlib.Path(found) if found else None
    if mypy_bin is None:
        print("  ERROR: mypy not found on PATH — install it via the system package manager (e.g. apt install mypy)")
        return False
    cmd = [str(mypy_bin)]
    if verbose:
        _print_tool_info(mypy_bin, cwd=root)
        cmd += ["--show-error-context"]
    cmd += targets
    log(f"▶ mypy  {targets_label}")
    return _run(cmd, cwd=root) == 0


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

    if fix:
        log("  (clang-tidy has no fix mode — running analysis)")
    elif diff:
        log("  (clang-tidy has no diff mode — running analysis)")

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

    if not files and not excluded:
        log("  (no .cpp files found)")
        return True
    if not files:
        log(f"  (all {excluded} .cpp file(s) excluded by {IGNORE_FILE} / {CLANG_TIDY_IGNORE_FILE})")
        return True

    label = _file_count_label(len(files), excluded)
    clang_tidy_bin = shutil.which("clang-tidy")
    if clang_tidy_bin is None:
        print("  ERROR: clang-tidy not found — install LLVM:")
        print("    sudo apt install clang-tidy")
        return False

    if verbose:
        _print_tool_info("clang-tidy", cwd=root)

    log(f"▶ clang-tidy -p {build_dir}  {label}")
    return (
        _run(
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
                  toolchain-detection noise.
    Verbose mode: Streams all west/CMake/Kconfig output to the terminal
                  (warning-counting is skipped — the human reading the
                  stream sees it directly).
    Diff/fix mode: Identical to check (Kconfig has neither).

    When explicit files are given, the check runs only if at least one has
    a ``.conf`` suffix (``west`` always validates every ``.conf`` file
    together — individual file selection is not supported).

    ``west`` is resolved from PATH (bare ``shutil.which``), matching this
    project's PATH-only tool-resolution policy.
    """
    log = _make_log(quiet)
    if explicit_files is not None and not any(f.suffix == ".conf" for f in explicit_files):
        log("  (no .conf files in selection)")
        return True

    if not build_combos:
        log("  (no [kconfig].build_combos configured)")
        return True

    if fix:
        log("  (Kconfig has no fix mode — running validation)")
    elif diff:
        log("  (Kconfig has no diff mode — running validation)")

    west_bin = shutil.which("west")
    if west_bin is None:
        print("  ERROR: west not found — activate the project's Zephyr workspace first")
        return False
    if verbose:
        _print_tool_info(west_bin, cwd=root)

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

    all_ok = True
    for combo in build_combos:
        args = combo["args"]
        label = combo["label"]
        cmd = [west_bin, "build", "--cmake-only", "--pristine", *args]  # type: ignore[misc]
        log(f"▶ {' '.join(cmd)}  ({label})")
        if verbose:
            all_ok = all_ok and (_run(cmd, cwd=root) == 0)
            continue
        try:
            result = subprocess.run(
                cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8"
            )
        except FileNotFoundError:
            print(f"ERROR: could not execute {west_bin}")
            return False

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
        all_files = [f for g in globs for f in sorted(root.glob(g))]
        files, excluded = _filter_files(all_files, root, ignore_patterns)
    if not files and not excluded:
        log("  (no shell files found)")
        return True
    if not files:
        log(f"  (all {excluded} shell file(s) excluded by {IGNORE_FILE})")
        return True
    label = _file_count_label(len(files), excluded)
    if fix:
        log("  (shellcheck has no fix mode — running lint)")
    elif diff:
        log("  (shellcheck has no diff mode — running lint)")
    shellcheck_bin = shutil.which("shellcheck")
    if shellcheck_bin is None:
        print("  ERROR: shellcheck not found — install it via the system package manager (e.g. apt install shellcheck)")
        return False
    if verbose:
        _print_tool_info(shellcheck_bin, cwd=root)
    log(f"▶ shellcheck  {label}")
    return _run([shellcheck_bin] + [str(f) for f in files], cwd=root) == 0


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

    Uses the installed ``check_rst`` console entry point from PATH.
    The Sphinx facts (``--sphinx-src docs``, the incremental build cache)
    come from ``.check_rst.toml`` at the repository root — a committed,
    tool-echoed, CLI-overridable declaration — so no flags are passed
    here.

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
      own style) elsewhere in a touched file.
    - *explicit_files* is a list and *git_auto_detected* is False — the user
      (or a caller) genuinely named these files.  Pass them to check_rst
      directly: whole-file scope is the correct, explicitly-requested
      behavior here (see check_rst's guide: "Fix a specific file in full only
      when the user explicitly confirms that file should be normalized").
    - *explicit_files* is ``None`` — a real full-repo scan is wanted (``--all``
      on the CLI, or a direct release-gate library call). Bare mode does NOT
      mean this: it is git-diff-scoped by design and checks nothing on a clean
      tree — exactly the release gate's ``--all`` contract ("regardless of git
      state"). Use
      ``check_rst --recursive <recursive_dir>`` (``.check_formatting.toml``'s
      ``[rst].dir``) for a genuine unconditional scan.  A project with no
      ``[rst].dir`` fails clearly: silently falling back to bare mode would
      violate ``--all``'s scope contract.

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
        print("  ERROR: [rst].dir is required for an RST full scan (--all)")
        return False

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
    elif recursive_dir:
        label = f"(recursive: {recursive_dir})"
        base = [rst_tool, "--recursive", recursive_dir]
    else:
        label = "(git-changed RST)"
        base = [rst_tool]

    if fix:
        mode = "--fix-only" if git_auto_detected else "--fix"
        log(f"▶ check_rst {mode}  {label}")
        return _run([base[0], mode, *base[1:]], cwd=root) == 0
    if diff:
        log(f"▶ check_rst --diff-only  {label}")
        return _run([base[0], "--diff-only", *base[1:]], cwd=root) == 0
    cmd = base
    if verbose:
        log(f"  {rst_tool}")
        cmd = [base[0], "--verbose", *base[1:]]
    log(f"▶ check_rst  {label}")
    return _run(cmd, cwd=root) == 0


_CheckFn = Callable[..., bool]

_CHECKERS: dict[str, tuple[str, _CheckFn]] = {
    "cpp": ("clang-format (C++)", _check_cpp),
    "meson": ("meson format (build files)", _check_meson),
    "web": ("prettier (HTML/CSS/JS)", _check_web),
    "python": ("ruff (Python)", _check_python),
    "json": ("prettier (JSON/JSONC)", _check_json),
    "ini": ("prettier-plugin-ini (INI)", _check_ini),
    "mypy": ("mypy (type checking)", _check_mypy),
    "rst": ("check_rst (RST documentation)", _check_rst),
    "clang-tidy": ("clang-tidy (static analysis)", _check_clang_tidy),
    "cmake": ("cmake-format (CMake)", _check_cmake),
    "kconfig": ("west --cmake-only (Kconfig)", _check_kconfig),
    "shell": ("shellcheck (shell scripts)", _check_shell),
    "yaml": ("prettier (YAML)", _check_yaml),
}


def _checker_kwargs(name: str, config: ProjectConfig, git_auto_detected: bool = False) -> dict[str, object]:
    """Return the config-sourced extra keyword arguments for checker *name*.

    *git_auto_detected* is a runtime fact, not a config value — see
    :func:`_is_git_auto_detected_scope`.  Consulted by every checker that
    implements the optional "git-scoped fix" contract: ``rst`` (bare vs.
    explicit-file check_rst invocation, see :func:`_check_rst`), ``cpp``
    (per-file clang-format ``-lines=`` scoping, see :func:`_check_cpp`), and
    all four Prettier-backed fixers (``web``, ``json``, ``ini``, ``yaml``),
    which share the canonically-validated best-effort merge in
    :func:`_fix_prettier_files`.  Every other checker ignores it — see
    README.md's "Scope guarantee" table for details.
    """
    by_name: dict[str, dict[str, object]] = {
        "cpp": {"globs": config.cpp_globs, "git_auto_detected": git_auto_detected},
        "web": {"globs": config.web_globs, "git_auto_detected": git_auto_detected},
        "python": {"dirs": config.python_dirs},
        "json": {"files": config.json_files, "git_auto_detected": git_auto_detected},
        "ini": {"globs": config.ini_globs, "git_auto_detected": git_auto_detected},
        "mypy": {"dirs": config.mypy_dirs},
        "rst": {"recursive_dir": config.rst_dir, "git_auto_detected": git_auto_detected},
        "clang-tidy": {
            "cpp_globs": config.cpp_globs,
            "build_dir": pathlib.Path(config.clang_tidy_build_dir) if config.clang_tidy_build_dir else None,
        },
        "kconfig": {"build_combos": config.kconfig_build_combos},
        "shell": {"globs": config.shell_globs},
        "yaml": {"globs": config.yaml_globs, "git_auto_detected": git_auto_detected},
    }
    return by_name.get(name, {})


def _fix_command(name: str, config: ProjectConfig, *, git_auto_detected: bool = False) -> str:
    """Return the fix command shown when checker *name* reports a violation.

    Derived from the same config-sourced values threaded into the checker
    itself (see :func:`_checker_kwargs`) — previously these were separately
    hardcoded strings in a static dict, and could silently drift from the
    checker's actual glob/target values.
    """
    if name == "cpp":
        return f"clang-format -i {' '.join(config.cpp_globs)}"
    if name == "meson":
        return "meson format -i -r -c meson.format"
    if name == "web":
        return f"npx prettier --write {' '.join(f'{g!r}' for g in config.web_globs)}"
    if name == "python":
        dirs = " ".join(config.python_dirs)
        return f"ruff format {dirs}\n    ruff check --fix {dirs}"
    if name == "json":
        return "npx prettier --write " + " ".join(config.json_files)
    if name == "ini":
        return f"npx prettier --write {' '.join(config.ini_globs)}"
    if name == "mypy":
        return "(mypy has no automatic fix — resolve type errors manually)"
    if name == "rst":
        return "check_rst --fix-only" if git_auto_detected else "check_rst --fix"
    if name == "clang-tidy":
        return "(clang-tidy has no automatic fix — resolve violations manually)"
    if name == "cmake":
        return "cmake-format --in-place $(find . -name CMakeLists.txt)"
    if name == "kconfig":
        return "(Kconfig has no automatic fix — correct the .conf files manually)"
    if name == "shell":
        return "(shellcheck has no automatic fix — resolve lint findings manually)"
    if name == "yaml":
        return f"npx prettier --write {' '.join(f'{g!r}' for g in config.yaml_globs)}"
    raise KeyError(name)


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
        Stop at the first checker that reports a problem without running
        the remaining ones.  No summary table is printed.
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
        stdout, captured via redirecting stdout for the duration of that
        checker's call) is embedded as a string field instead of being
        printed directly, so no information is lost relative to a normal
        run.  Payload shape: ``{"config_source": str, "mode": str,
        "checks": [str, ...], "results": {name: {"label": str, "ok": bool,
        "output": str}}, "summary": {"total": int, "passed": int, "failed":
        int}, "overall_ok": bool}``.  Never changes the return value or
        exit code.
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

    if explicit_files is not None and not explicit_files:
        if as_json:
            empty_payload: dict[str, object] = {
                "config_source": _CONFIG_FILE,
                "mode": "fix" if fix else "diff" if diff else "verbose" if verbose else "check",
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

    for name in checks:
        label, fn = _CHECKERS[name]
        if fix:
            action = "Fix"
        elif diff:
            action = "Diff"
        elif verbose:
            action = "Verbose"
        else:
            action = "Check"

        log()
        log("┌──────────────────────────────────────────────────────────────┐")
        header = f"{action}: {label}"
        log(f"│  {header:<60}│")
        log("└──────────────────────────────────────────────────────────────┘")
        log()

        if as_json:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ok = fn(
                    root,
                    fix,
                    diff,
                    verbose,
                    ignore_patterns,
                    explicit_files,
                    quiet=True,
                    **_checker_kwargs(name, config, git_auto_detected),
                )
            outputs[name] = buf.getvalue()
        else:
            ok = fn(
                root,
                fix,
                diff,
                verbose,
                ignore_patterns,
                explicit_files,
                quiet=quiet,
                **_checker_kwargs(name, config, git_auto_detected),
            )
        results[name] = ok

        if not ok and fail_fast:
            if as_json:
                break
            return False

    if as_json:
        mode = "fix" if fix else "diff" if diff else "verbose" if verbose else "check"
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
    if fix:
        title = "Fix Results"
    elif diff:
        title = "Diff Results"
    elif verbose:
        title = "Verbose Results"
    else:
        title = "Formatting Results"
    title_cell = f"  {title}"
    log()
    log("╔══════════════════════════════════════════════════════════════╗")
    log(f"║{title_cell:<62}║")
    log("╠══════════════════════════════════════════════════╦═══════════╣")
    log(f"║ {'Checker':<48} ║ {'Status':<9} ║")
    log("╠══════════════════════════════════════════════════╬═══════════╣")

    overall_ok = True
    for name in checks:
        label, _ = _CHECKERS[name]
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
            for name in checks:
                if not results.get(name, True):
                    print(f"    {_fix_command(name, config, git_auto_detected=git_auto_detected)}")
            print()
            print("    (or re-run with --fix to apply all fixes at once)")
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
    from check_formatting import __version__

    parser = argparse.ArgumentParser(
        prog="check_formatting",
        description=(
            "Check (or fix) source file formatting against project coding standards. "
            "Exits 0 if every requested checker reports no violations, 1 otherwise — "
            "this exit-code contract is unaffected by --quiet/--verbose/--diff, which "
            "change only what is printed, never the pass/fail verdict."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
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
      Stop at the first formatting check that reports violations.

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
""",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
            "Stop after the first checker that reports a problem.  "
            "By default all checks are attempted and a summary table is printed."
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
