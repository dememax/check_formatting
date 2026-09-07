.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Command modes, selection, and exclusion reference — check_formatting project

###################
Command reference
###################

This page is for daily users and committers who already have a configured
project.  See :doc:`getting_started` for adoption and :doc:`backends` for
external tool installation and version contracts.

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
Each checker writes to its own buffer.  The main thread consumes those buffers
in ``--checks`` order: a later fast checker waits behind an earlier slow one,
while an earlier completed checker's banner and findings may be printed even
if later checkers are still running.  The summary table or single ``--json``
payload is produced only after the thread pool finishes.  A single selected
checker follows the same path; there is no special case for it.

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
     - ``meson format`` / ``cmake-format``
     - Whole-file only
   * - ``python`` (format)
     - ``ruff format``
     - Whole-file only (same gap as Black)
   * - ``python`` (lint)
     - ``ruff check``
     - No native fix-range flag; diagnostics are per-line, so reporting
       could be filtered post-hoc (not implemented)
   * - ``mypy``
     - ``mypy``
     - Whole-program inference; line restriction is not applicable
   * - ``kconfig``
     - ``west build --cmake-only``
     - Validates merged configuration; line restriction is not applicable
   * - ``shell``
     - ``shellcheck``
     - Whole-script analysis
   * - ``vnu``
     - Nu Html Checker
     - Report-only conformance analysis; no source mutation to restrict

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

Whether ``.formatting-ignore``/``--exclude`` actually take effect depends on
*both* the checker and the selection mechanism (auto-detected default scope,
explicit ``-- FILE`` arguments, or ``--all``) — not on the operating mode
alone.  The default, git-auto-detected scope already resolves to a concrete
file list before any checker runs, so most checkers apply wrapper exclusions
there too, in ordinary check mode, not only under ``--fix``/``--diff`` or
explicit files:

.. list-table::
   :header-rows: 1
   :widths: 16 46 38

   * - Checker(s)
     - When ``.formatting-ignore``/``--exclude`` apply
     - Native alternative
   * - ``cpp``, ``cmake``, ``json``, ``ini``, ``yaml``, ``shell``, ``vnu``
     - Always — every mode, every selection mechanism including ``--all``.
       Each always resolves a concrete per-file list before invoking its
       backend.
     - —
   * - ``meson``, ``web``
     - Fix, diff, and explicit-file modes always; check/verbose mode only
       when a concrete selection already exists (auto-detected default
       scope or explicit files).  ``--all``'s check/verbose mode hands
       globs/recursive discovery directly to the backend as one batched
       command, with no per-file list to filter.
     - ``.prettierignore`` (web)
   * - ``python``, ``mypy``
     - Every mode, whenever a concrete selection exists (auto-detected
       default scope or explicit files).  Never under ``--all``, in any
       mode — ``[python].dirs``/``[mypy].dirs`` are handed to the backend
       directly.
     - ``[tool.ruff.exclude]`` in ``pyproject.toml``
   * - ``rst``
     - Never — check_rst owns its own native selection entirely.
     - ``check_rst check --recursive ... --exclude ...`` directly
   * - ``clang-tidy``
     - Same as ``cpp`` (shares ``[cpp].globs``), plus its own separate file
       below.
     - ``.clang-tidy-ignore``
   * - ``kconfig``
     - N/A — validates merged Kconfig state across every ``.conf`` file
       together, not a per-file selection.
     - —

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
