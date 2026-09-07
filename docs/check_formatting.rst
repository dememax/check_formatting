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

The setuptools build hook repopulates the staged ``check_formatting`` package
from source on every build.  Reusing a checkout's ``build/`` directory
therefore cannot leak a deleted module into a later wheel.

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
malformed TOML, an unknown or duplicate checker name, an unknown key, a
section of the wrong type, or a wrongly typed value is a hard error.  A valid
section for a checker not listed in ``checks`` is permitted and remains
available through ``--checks``.

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
   * - ``vnu``
     - Nu Html Checker
     - ``[vnu].globs`` and optional ``[vnu].args``
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

Checker names normally describe a file domain.  ``mypy``, ``clang-tidy``, and
``vnu`` are named for their backends because they add deeper analysis to
domains that already have primary ``python``, ``cpp``, and ``web``
format/lint checkers.  ``vnu`` is preferable to ``html`` because Nu also
checks standalone CSS and SVG.

Whether a checker is enabled by default is a fact about the consuming
repository.  A Meson project may enable ``cpp`` and ``meson`` while a
CMake-based embedded project enables ``cmake`` and ``kconfig``.  Any registered
checker may be selected explicitly with ``--checks`` when its required
configuration is present.

**********
Backends
**********

Each row of the table above wraps exactly one independently-maintained
backend: what it is, how to install it, and any check_formatting-relevant
gotcha, one entry per backend rather than per checker — ``prettier`` backs
four checkers (``web``, ``json``, ``ini``, ``yaml``) and is described once.
None of these are ``check_formatting``'s own code or Python dependencies.
The VNU instructions below pin the exact independently installed version used
to validate this adapter.

``clang-format`` (``cpp``)
   Part of the LLVM toolchain.  Install via the system package manager
   (``sudo apt install clang-format`` on Debian/Ubuntu, ``brew install
   llvm`` on macOS).  It cannot report *which* rule a file violates or
   *why* — the only diagnostic it emits is the generic
   ``[-Wclang-format-violations]`` warning, meaning "this file would look
   different after formatting".  Run ``--diff`` to see the actual changes
   it would make; ``--verbose`` produces identical output to plain check
   mode because clang-format exposes no extra diagnostic flags.

``meson format`` (``meson``)
   Provided by Meson itself; ``--check-only`` requires Meson ≥ 1.5.0.
   Install via pip or the system package manager (``pip install meson``).
   Like clang-format, it exposes no rule-level diagnostics beyond
   pass/fail.

``prettier`` (``web``, ``json``, ``ini``, ``yaml``)
   A Node.js tool, not a standalone system binary.  It needs Node.js
   (≥ 18 recommended) and npm installed, plus the project's own
   dependencies installed from ``package.json`` at the repository root
   (``npm install``, which populates ``node_modules/``).  The wrapper
   invokes it as ``npx prettier``, which resolves the locally installed
   version from ``node_modules/.bin/prettier``; running it without
   ``node_modules/`` present makes ``npx`` attempt a one-off network
   download, which can fail offline or silently pick a different version
   than the project pins.  ``ini`` additionally needs
   ``prettier-plugin-ini`` (registered in ``.prettierrc``) for its
   ``iniSpaceAroundEquals`` behavior; ``json`` auto-selects the ``json``
   or ``jsonc`` parser per file via ``.prettierrc`` overrides.

``ruff`` (``python``)
   Python's formatter and linter in one binary.  Install via pip
   (``pip install ruff``).  Backs both format (``ruff format``) and lint
   (``ruff check``); both must pass.

``mypy`` (``mypy``)
   Python's static type-checker.  Resolved from ``PATH`` like every other
   backend (see "Installation" above).  Install via the system package
   manager or pip.  Reads its own configuration from ``[tool.mypy]`` in
   the consuming project's ``pyproject.toml`` — entirely independent of
   ``.check_formatting.toml``.

   Before running, the adapter wipes the project-root ``.mypy_cache``
   directory it manages — not any different cache directory a project's own
   ``[tool.mypy]``/``mypy.ini`` might configure — whenever the resolved
   ``mypy``'s version differs from a marker recorded inside that cache, or
   when no marker is present at all (including the first run after adopting
   this checker, or a pre-existing cache from before this behavior
   existed).  mypy's incremental cache format is version-dependent; reusing
   one written by a different version can silently produce wrong results,
   so a wipe is the safe default rather than every-run overhead.  A CI job
   that caches ``.mypy_cache`` across runs to speed up ``mypy`` should
   expect this cache to be invalidated wholesale on any ``mypy`` version
   bump, and on the very first cached run.

``check_rst`` (``rst``)
   A standalone RST/Sphinx linter and fixer, installed and versioned
   separately from ``check_formatting`` and resolved from ``PATH``.  A
   full-repo scan (``--all``, or a direct library call with no
   ``explicit_files``) additionally needs ``.check_formatting.toml``'s
   ``[rst].dir`` set to the project's RST root, matching
   ``.check_rst.toml``'s own ``sphinx-src``.  See check_rst's own guide
   for its full contract.

``clang-tidy`` (``clang-tidy`` — optional)
   Part of the LLVM toolchain, installed the same way as clang-format.
   Additionally requires an up-to-date ``compile_commands.json`` in the
   build directory named by ``.check_formatting.toml``'s
   ``[clang_tidy].build_dir`` (generated automatically by Meson on
   ``meson compile``).  A project with no ``[clang_tidy]`` section skips
   this checker cleanly, without requiring ``clang-tidy`` on ``PATH`` at
   all.

``cmake-format`` (``cmake`` — optional, CMake-based projects only)
   Install via pip (``pip install cmake-format``).  Not relevant to
   Meson-based projects.

``west`` (``kconfig`` — optional, Zephyr/west projects only)
   Part of a Zephyr-style West workspace.  Requires at least one entry in
   ``.check_formatting.toml``'s ``[kconfig].build_combos``; a project
   with none skips this checker cleanly, without requiring ``west`` on
   ``PATH``.

``shellcheck`` (``shell`` — optional)
   Install via the system package manager (``sudo apt install
   shellcheck`` on Debian/Ubuntu, ``brew install shellcheck`` on macOS).
   The adapter invokes ``shellcheck`` from the project root without replacing
   its native policy, so a committed ``.shellcheckrc`` is the right place for
   dialect, sourced-file, severity, and optional-check settings.  A Bash
   project that wants complete analysis of sourced libraries can start with:

   .. code-block:: ini

      shell=bash
      external-sources=true
      source-path=SCRIPTDIR
      check-sourced=true
      enable=all

   ``enable=all`` deliberately opts into advisory style checks as well as
   correctness checks; omit it when the project wants ShellCheck's default
   policy.  Prefer a narrow, documented file-level ``# shellcheck disable=...``
   directive when a sourced configuration library intentionally looks unused
   in isolation instead of disabling that diagnostic for the whole project.

``vnu`` (``vnu`` — optional)
   The Nu Html Checker performs standards-conformance analysis for HTML,
   XHTML, CSS, and SVG.  The adapter always enables standalone CSS and SVG
   checking and treats warnings as failures.  Additional native options, such
   as ``--filterfile``/``--filterpattern``, may be supplied through
   ``[vnu].args`` to accept one specific, reviewed finding — for example,
   Prettier's HTML printer always self-closes void elements
   (``<meta ... />``), which ``vnu`` reports as an info-level "Trailing
   slash on void elements" finding, safe to accept where every attribute
   value in the markup is quoted (a trailing slash immediately after an
   *unquoted* attribute value becomes part of that value, per the WHATWG
   parsing algorithm — the qualifier matters).

   Two gotchas, both reproduced against the pinned ``vnu`` release below,
   before reaching for either suppression flag:

   * ``--skip-info-messages`` does **not** suppress a finding for the
     purpose of ``--Werror``.  It only changes what ``vnu`` prints; the
     exit-code decision is made independently, so a filtered-out message
     still fails the check with no visible reason at all.
   * ``--filterpattern`` (and each line of ``--filterfile``) must match a
     finding's **entire** message text, not a fragment — Java
     ``Matcher.matches()`` semantics, not the substring ``find()``
     semantics most "regex filter" tools use.  Neither option's own
     ``--help`` text documents this.  Wrapping a fragment in ``^``/``$``
     does not fix it either — only wildcarding the fragment (``.*...*``)
     or supplying the complete message verbatim does.

   :doc:`roadmap/vnu-message-suppression-ergonomics` has the full adoption
   recipe (with a standalone reproduction fixture), the reasoning above in
   more depth, and current troubleshooting notes (a malformed
   ``--filterpattern`` regex currently surfaces as a raw Java stack trace).

   ``--errors-only``, ``--exit-zero-always``, ``--css``, and ``--svg`` are
   rejected as ``[vnu].args`` entries — a hard configuration error at load
   time, the same tier as this project's other schema validation — because
   each silently weakens the adapter's advertised always-strict,
   always-HTML/CSS/SVG contract rather than narrowing one specific finding:
   the first two bypass ``--Werror``'s exit-code guarantee outright, and the
   latter two force every selected file to be parsed as the wrong type,
   confirmed against the installed backend even for individually named
   files.  A project that wants to accept a specific, reviewed finding uses
   ``--filterpattern``/``--filterfile`` instead.

   ``[vnu].globs`` and ``[web].globs`` are independent declarations with
   intentionally overlapping scope.  ``web`` says which HTML/CSS/JavaScript
   files Prettier owns; ``vnu`` says which HTML/XHTML/CSS/SVG files Nu
   validates.  Start broad, review every finding, and add exclusions or a
   narrowly documented Nu filter only after judging actual project output.
   Duplicate parsing and corroborating diagnostics are expected.

   .. code-block:: toml

      [vnu]
      globs = ["public/**/*.html", "public/**/*.css", "public/**/*.svg"]
      # Accept Prettier's trailing slash on void elements: harmless here
      # because every attribute value in this project's markup is quoted.
      args = [
        "--filterpattern",
        ".*Trailing slash on void elements has no effect and interacts badly with unquoted attribute values.*",
      ]

   Version ``26.9.5`` (upstream commit ``a9333cb``) is the version installed
   and integration-tested on this host.  Its ``vnu.jar`` SHA-256 is
   ``b37a0a67cde28d6a3b361f4c774cbd80fe3e1fde38824304e295c8d764296756``.
   Install that exact official ``vnu-jar`` package into ``~/opt``; npm is used
   only to acquire and integrity-check the versioned package, while the
   resulting launcher needs only Java 17 or newer at run time:

   .. code-block:: bash

      set -euo pipefail
      vnu_version=26.9.5
      vnu_sha256=b37a0a67cde28d6a3b361f4c774cbd80fe3e1fde38824304e295c8d764296756
      vnu_stage=$(mktemp -d)
      trap 'rm -rf -- "${vnu_stage}"' EXIT

      java -version
      npm --version
      npm pack "vnu-jar@${vnu_version}" --pack-destination "${vnu_stage}"
      tar -xf "${vnu_stage}/vnu-jar-${vnu_version}.tgz" -C "${vnu_stage}"
      printf '%s  %s\n' "${vnu_sha256}" \
         "${vnu_stage}/package/build/dist/vnu.jar" | sha256sum -c -

      install -d "${HOME}/opt/vnu/${vnu_version}" "${HOME}/opt/bin"
      install -m 0644 "${vnu_stage}/package/build/dist/vnu.jar" \
         "${HOME}/opt/vnu/${vnu_version}/vnu.jar"
      ln -sfn "${vnu_version}/vnu.jar" "${HOME}/opt/vnu/vnu.jar"
      printf '#!/bin/sh\nexec java -jar "%s/opt/vnu/%s/vnu.jar" "$@"\n' \
         "${HOME}" "${vnu_version}" >"${HOME}/opt/bin/vnu"
      chmod 0755 "${HOME}/opt/bin/vnu"

      vnu --version
      sha256sum "${HOME}/opt/vnu/${vnu_version}/vnu.jar"

   The unversioned ``~/opt/vnu/vnu.jar`` symlink supports consumers that invoke
   the JAR directly; ``check_formatting`` itself deliberately resolves only
   the bare ``vnu`` command from ``PATH``.  To upgrade, choose and review a new
   exact official package version, obtain and verify its JAR digest, install it
   into a new version-named directory, run its real integration tests, and only
   then update the launcher and compatibility symlink.  Keep the preceding
   directory until the new version has passed, providing an immediate rollback.

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

************************
Continuous integration
************************

A CI job gating a clean checkout must use ``--all`` (or explicit files) —
this is not optional.  The default, git-auto-detected scope only selects
files changed since ``HEAD`` plus untracked files; on a freshly cloned or
freshly committed checkout that set is empty by definition, so a bare
invocation trivially reports success regardless of what the checkout
actually contains.  Reproduced directly, on a checkout with a real,
already-committed syntax error::

   $ check_formatting --json
   {"config_source": ".check_formatting.toml", "mode": "check", "checks": [],
    "results": {}, "summary": {"total": 0, "passed": 0, "failed": 0}, "overall_ok": true}
   $ echo $?
   0

   $ check_formatting --all --json
   {"config_source": ".check_formatting.toml", "mode": "check", "checks": ["python"],
    "results": {"python": {"label": "ruff (Python)", "ok": false, "output": "..."}},
    "summary": {"total": 1, "passed": 0, "failed": 1}, "overall_ok": false}
   $ echo $?
   1

Because ``--all`` scans by configured globs/dirs rather than Git state, a
shallow, single-commit checkout is sufficient in CI — no
``fetch-depth: 0`` or equivalent is needed the way it would be for a
diff-based check.

``--json`` does not wrap every failure mode in JSON.  A configuration
error (a missing or malformed ``.check_formatting.toml``) prints plain
text and exits 1 without ever entering the JSON envelope::

   $ check_formatting --json   # malformed .check_formatting.toml
   check_formatting: invalid .check_formatting.toml: Invalid value (at end of document)
   $ echo $?
   1

A script consuming ``--json`` output must account for this — check the
exit status, or catch a JSON decode failure — rather than calling
``json.loads()`` on stdout unconditionally:

.. code-block:: python

   import json
   import subprocess
   import sys

   result = subprocess.run(
       ["check_formatting", "--all", "--json"],
       capture_output=True,
       text=True,
   )
   try:
       payload = json.loads(result.stdout)
   except json.JSONDecodeError:
       # A config-load error prints plain text and exits 1 without ever
       # producing JSON.
       sys.stderr.write(result.stdout)
       sys.exit(result.returncode or 1)

   if not payload["overall_ok"]:
       for name, entry in payload["results"].items():
           if not entry["ok"]:
               print(f"FAILED: {entry['label']}")
       sys.exit(1)

A generic CI job (illustrative — adapt the install step to the backends
your own ``checks`` list actually needs):

.. code-block:: yaml

   # .github/workflows/check_formatting.yml
   jobs:
     check_formatting:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: "3.14"
         - run: python3.14 -m pip install check-formatting
         # npm install, apt-get install <backend>, etc. — only for the
         # backends this project's own checks list enables
         - run: python3.14 ci_check.py  # the script above; it invokes check_formatting --all --json itself

For a pre-commit hook, two decisions are worth making explicitly rather
than leaving them implicit:

.. code-block:: yaml

   # .pre-commit-config.yaml — recommended: let check_formatting select its own scope
   - repo: local
     hooks:
       - id: check_formatting
         name: check_formatting
         entry: check_formatting
         language: system
         pass_filenames: false
         always_run: true

``pass_filenames: false`` plus ``always_run: true`` invokes
``check_formatting`` bare, letting it perform its own git-based
auto-detection rather than receiving pre-commit's matched filenames as
explicit arguments.  This matters because passing filenames explicitly
sets ``explicit_files`` to a concrete list the tool did not derive from
Git itself — which disables the native/best-effort git-scoped-fix
optimizations some checkers use (``cpp``'s native ``-lines=``,
``rst``'s ``fix --fast``, the Prettier-backed checkers' best-effort hunk
reconstruction), falling back to whole-file processing for those checkers
instead.  Bare invocation avoids that cost entirely, and composes cleanly
with pre-commit's own behavior: pre-commit "only runs on the staged
contents of files by temporarily stashing the unstaged changes while
running hooks" (`pre-commit's own documentation
<https://pre-commit.com/#pre-commit-during-commits>`_), so the working
tree at hook-run time already matches the would-be commit — including a
partially staged file, where only its staged hunks are present — and
``check_formatting``'s own "changed since ``HEAD``" detection naturally
captures exactly that.  Passing filenames explicitly
(``pass_filenames: true``, pre-commit's own default) remains a reasonable
choice for a team that specifically wants pre-commit's own ``files``/``types``
matching instead of relying on ``.check_formatting.toml``'s configured
globs, at the cost above.

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
