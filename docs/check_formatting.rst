.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Detailed user guide for the formatting checker — check_formatting project

##################
check_formatting
##################

.. contents:: Contents
   :depth: 3
   :local:

**********
Overview
**********

``check_formatting`` is a project-agnostic front end for independently
maintained formatters, linters, and static-analysis tools.  It gives those
backends one command-line interface, one file-selection model, and one summary
without embedding project-specific paths or build choices in the utility.

Each consuming repository declares its enabled checkers and their targets in a
committed ``.check_formatting.toml`` at the repository root.  Configuration is
discovered from the current working directory only; the command does not walk
parent directories.

**************
Installation
**************

The utility is distributed as a Python package and requires Python 3.14 or
newer.  Install it from a clone with pip::

   python3.14 -m pip install /path/to/check_formatting
   check_formatting --help
   check_formatting --version

``--version`` prints the release version followed by the copyright and
license lines; the same two lines are appended to ``--help``'s epilog,
mirroring check_rst's own ``--version``/``--help`` convention.

For development, use an editable installation from the repository root::

   python3.14 -m pip install --editable .

The console entry point and ``python3.14 -m check_formatting`` are equivalent.

Only backends enabled by the consuming project need to be installed.  Backend
executables are always resolved from ``PATH``; a project-local virtual
environment is not consulted implicitly.

***********************
Project configuration
***********************

A minimal configuration is::

   checks = ["cpp", "python", "mypy"]

   [cpp]
   globs = ["src/**/*.cpp", "src/**/*.hpp"]

   [python]
   dirs = ["scripts", "tests"]

   # Optional: omit this table to type-check the same targets as Ruff.
   [mypy]
   dirs = ["src", "tests"]

The configuration is a declaration, not auto-detection.  A missing file,
malformed TOML, an unknown checker or key, a section of the wrong type, or a
wrongly typed value is a hard error.  A valid section for a checker not listed
in ``checks`` is permitted and remains available through ``--checks``.

*********************
Registered checkers
*********************

.. list-table::
   :header-rows: 1
   :widths: 18 32 50

   * - Checker
     - Backend
     - Project configuration or discovery
   * - ``cpp``
     - ``clang-format``
     - ``[cpp].globs``
   * - ``meson``
     - ``meson format``
     - Discovers ``meson.build`` and ``meson.options`` recursively
   * - ``web``
     - ``prettier``
     - ``[web].globs``
   * - ``python``
     - ``ruff format`` and ``ruff check``
     - ``[python].dirs``
   * - ``json``
     - ``prettier``
     - ``[json].files``
   * - ``ini``
     - ``prettier`` with ``prettier-plugin-ini``
     - ``[ini].globs``
   * - ``mypy``
     - ``mypy``
     - ``[mypy].dirs``, falling back to ``[python].dirs``
   * - ``rst``
     - ``check_rst``
     - ``[rst].dir``, required for a recursive full scan
   * - ``clang-tidy``
     - ``clang-tidy``
     - ``[cpp].globs`` and ``[clang_tidy].build_dir``
   * - ``cmake``
     - ``cmake-format``
     - Discovers ``CMakeLists.txt`` recursively
   * - ``kconfig``
     - ``west build --cmake-only``
     - ``[kconfig].build_combos``
   * - ``shell``
     - ``shellcheck``
     - ``[shell].globs``
   * - ``yaml``
     - ``prettier``
     - ``[yaml].globs``

Every ``kconfig`` combo always runs ``west build --cmake-only --pristine``,
forcing a fresh Kconfig evaluation — and therefore a real rebuild — on every
invocation rather than reusing cached ``.config`` state.

``kconfig``'s configured ``build_combos`` build concurrently in non-verbose
mode.  Give each combo its own ``-d``/``--build-dir`` in ``args`` if it needs
isolated build state — ``west build`` already supports this directly through
``args``; no ``check_formatting``-specific configuration exists or is needed
for it.  Combos sharing a build directory will race.  ``--verbose`` stays
sequential, one combo at a time, so its live-streamed output is never
interleaved.

Checker names normally describe a file domain.  ``mypy`` and ``clang-tidy``
are named for their backends because they add deeper analysis to domains that
already have primary ``python`` and ``cpp`` format/lint checkers.

Whether a checker is enabled by default is a fact about the consuming
repository.  A Meson project may enable ``cpp`` and ``meson`` while a
CMake-based embedded project enables ``cmake`` and ``kconfig``.  Any registered
checker may be selected explicitly with ``--checks`` when its required
configuration is present.

*****************
Operating modes
*****************

The four operating modes are mutually exclusive.  Check mode is used when no
mode flag is supplied.

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Flag
     - Effect
   * - *(none)*
     - Run enabled backends in check mode and print pass/fail results.  Source
       files are not rewritten.
   * - ``--verbose``
     - Perform the same checks with the maximum native diagnostics available
       from each backend.  Source files are not rewritten.
   * - ``--diff``
     - Print a unified diff of formatter changes without applying them.
   * - ``--fix``
     - Apply supported formatter and linter fixes in place.  Report-only
       checkers still validate but do not modify files.

=============================
Concurrent checker dispatch
=============================

Every selected checker runs concurrently, regardless of ``--fail-fast``.
Nothing is printed incrementally while checkers are still running — all
output (banners, each checker's own findings, the summary table or
``--json`` payload) is produced together only once every checker has
finished, in ``--checks`` order, never completion order.  This applies
even when only one checker is selected: there is no special case for it.

``--fail-fast``
   Stops the *report* at the first checker (in ``--checks`` order) that
   reports a problem — no summary table (or, under ``--json``, no further
   ``results``/``summary`` entries) beyond that point.  Every checker
   still runs to completion regardless: dispatch is unconditionally
   concurrent, threads cannot be safely killed mid-flight, and by the
   time a failure is known here the remaining checkers are typically
   already running.  This does not save wall-clock time — it only
   shortens what gets printed or returned.

=================
Output controls
=================

Output verbosity is independent from the operating mode.

``--quiet``
   Suppresses banners, the summary table, the configuration echo, command
   announcements, and routine scope notices.  Errors, backend output, diff
   content, and the final machine-parseable summary line remain visible.
   ``--quiet`` is incompatible with ``--verbose`` but may be combined with
   ``--fix`` or ``--diff``.

``--json``
   Replaces human-oriented output with one JSON object.  Each checker's output
   is captured in its result entry.  The payload contains ``config_source``,
   ``mode``, ``checks``, ``results``, ``summary``, and ``overall_ok``.

Neither option changes the return value or process exit status.

****************
File selection
****************

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Invocation
     - Scope
   * - No FILE arguments
     - Files changed since ``HEAD`` plus untracked files, detected with Git.
       Deleted files are omitted.  If the resulting set is empty, the command
       reports that there is nothing to do and exits successfully after
       validating the project configuration.
   * - ``--all``
     - Every configured target in the repository, regardless of Git state.
       ``rst`` uses ``check_rst check --recursive`` with ``[rst].dir``.  This option
       cannot be combined with FILE arguments; selecting ``rst`` without a
       configured directory is an error, never a changed-file fallback.
   * - ``-- FILE ...``
     - Exactly the named files, filtered through each checker's configured
       targets or fixed file domain.

Configured globs remain authoritative in changed-file and explicit-file
scopes.  A configured C++ header, TypeScript file, or extensionless shell
script is therefore not discarded by an unrelated built-in suffix list.

***********************
Git-scoped formatting
***********************

Ordinary file selection is file-level: once selected, most backends process a
whole file.  Some formatters can protect unrelated legacy content elsewhere in
a changed file by restricting their effective changes to Git hunks.  This
behavior is enabled only for the default Git-auto-detected scope.

=============
Native tier
=============

``cpp``
   ``clang-format`` receives one ``-lines=<start>:<end>`` option per range from
   ``git diff -U0 HEAD``.  Check, verbose, diff, and fix modes use the same
   ranges so that check and fix cannot disagree about scope.

``rst``
   ``check_rst`` is invoked without explicit filenames for the auto-detected
   scope, preserving its native Git-hunk behavior.  Fix mode selects
   ``fix --fast`` and diff mode selects ``diff --fast`` so the wrapper's
   mutation-only and preview-only contracts do not trigger duplicate Sphinx
   validation.  A user-provided RST file is intentionally passed explicitly
   and therefore checked or fixed as a whole file; its fix mode retains
   ordinary ``fix`` (full validation, not ``--fast``).  ``--all`` is a
   recursive whole-tree scan (``check_rst check --recursive``) and requires
   ``[rst].dir``.

If no usable hunk range exists, such as for an untracked file or a pure
deletion, ``cpp`` falls back to whole-file processing for that file.

===========================
Best-effort Prettier tier
===========================

Prettier does not provide one reliable line-range mechanism across the web,
JSON, INI, and YAML parsers.  For these checkers, ``check_formatting``:

#. formats the complete original file in memory;
#. computes the formatter's changes;
#. retains only changes overlapping the file's Git hunks;
#. formats the merged candidate again using the real pathname for parser,
   plugin, and configuration discovery; and
#. accepts the merge only if it canonicalizes to the same result as the
   complete original formatting pass.

If parsing fails or canonical results differ, the checker falls back to the
ordinary whole-file formatter result.  Check, verbose, diff, and fix modes all
compare against or apply the same chosen target.

======================
Backend scope matrix
======================

.. list-table::
   :header-rows: 1
   :widths: 24 28 48

   * - Checker
     - Backend
     - Line-range behavior
   * - ``cpp``
     - ``clang-format``
     - Native Git-hunk ranges in the auto-detected scope
   * - ``rst``
     - ``check_rst``
     - Native Git integration in the default scope
   * - ``web``, ``json``, ``ini``, ``yaml``
     - ``prettier``
     - Canonically verified best-effort reconstruction with whole-file fallback
   * - ``clang-tidy``
     - ``clang-tidy``
     - Report-only; no source mutation to restrict
   * - ``meson``, ``cmake``
     - Meson / ``cmake-format``
     - Whole-file only
   * - ``python``
     - Ruff
     - Whole-file formatting; no native fix-range flag
   * - ``mypy``
     - ``mypy``
     - Whole-program inference; line restriction is not applicable
   * - ``kconfig``
     - West / Kconfig
     - Validates merged configuration; line restriction is not applicable
   * - ``shell``
     - ``shellcheck``
     - Whole-script analysis

*****************
Excluding files
*****************

``.formatting-ignore``
   A committed, standing exclusion list at the project root.  Blank lines and
   comments are ignored.  A trailing ``/`` or ``/**`` excludes a directory;
   patterns containing ``/`` match repository-relative paths; bare patterns
   match basenames.

``--exclude PATTERN``
   A repeatable, invocation-local exclusion using the same pattern language.

``.clang-tidy-ignore``
   Additional exclusions for the ``clang-tidy`` checker, useful for translation
   units that cannot be analyzed but remain valid ``clang-format`` targets.

Backend limitations affect full-scan exclusions.  RST uses ``check_rst``'s own
selection and does not receive either wrapper exclusion mechanism; invoke
``check_rst check --recursive ... --exclude ...`` directly for an excluded RST tree
audit.  Meson and Web delegate their non-explicit-file check and verbose modes
to a single batched backend command that cannot filter individual files;
``.formatting-ignore`` applies to them only in diff, fix, and explicit-file
modes, so use ``.prettierignore`` for finer-grained web exclusions there.
Python is scoped to ``[python].dirs`` directly, in every mode, whenever no
explicit files are given, so ``.formatting-ignore`` never applies to it
without explicit files; use ``[tool.ruff.exclude]`` in ``pyproject.toml``
instead.  Explicit-file, diff, and fix paths can apply the wrapper's per-file
filtering directly for other checkers.

*******
Usage
*******

.. code-block:: bash

   # Check files changed since HEAD plus untracked files
   check_formatting

   # Check every configured target
   check_formatting --all

   # Select checkers explicitly
   check_formatting --checks cpp meson

   # Shorten the report at the first failed checker (every checker still runs)
   check_formatting --fail-fast

   # Show maximum backend diagnostics
   check_formatting --verbose

   # Preview formatter changes
   check_formatting --diff

   # Apply supported fixes to the default Git-selected files
   check_formatting --fix

   # Apply fixes to explicitly named files
   check_formatting --fix src/example.cpp scripts/example.py

   # Add a temporary exclusion
   check_formatting --exclude generated_snapshot.py

   # Produce a machine-readable report
   check_formatting --json

*************
Exit status
*************

The process exits with status 0 when every executed checker passes and status 1
when any checker reports a violation or required configuration/backend is
unavailable.  Display options never change that result.

*************
Library use
*************

The script may also be imported directly::

   from pathlib import Path

   from check_formatting import check_formatting

   project_root = Path("/path/to/project")
   ok = check_formatting(project_root, explicit_files=None)

For library calls, ``explicit_files=None`` means a full-repository scan.  A
non-empty list selects those absolute paths, while an empty list means that
there is nothing to check.  Configuration is validated in all three cases.
