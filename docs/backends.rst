.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Backend compatibility and installation reference — check_formatting project

##########
Backends
##########

This page is for adopters and dependency owners deciding which external tools
to install and pin.  Start with :doc:`getting_started` when the checker choice
or initial project configuration is not settled yet.

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

**********************
Backend requirements
**********************

Each row of the table above wraps exactly one independently-maintained
backend: what it is, how to install it, and any check_formatting-relevant
gotcha, one entry per backend rather than per checker — ``prettier`` backs
four checkers (``web``, ``json``, ``ini``, ``yaml``) and is described once.
None of these are ``check_formatting``'s own code or Python dependencies.
The VNU instructions below pin the exact independently installed version used
to validate this adapter. ``vnu`` is absent from the Ubuntu and Gentoo package
repositories checked for this project, so the system-wide ``~/opt`` recipe
fills that distribution gap. Upstream also publishes the official ``vnu-jar``
npm package, whose ``vnu`` executable can be pinned in a consuming project's
``package-lock.json`` and exposed through ``node_modules/.bin``. The system and
project-local routes serve different deployment models; ``check_formatting``
does not search either specially and runs whichever executable its invocation
environment resolves.

=======================
Backend compatibility
=======================

Installing a backend is not enough by itself: ``check_formatting`` is an
adapter around that backend's command-line API.  Before running a known
backend command, it therefore probes the resolved executable's version and
requires the compatibility contract below.  An installed version outside the
contract, or version output the adapter cannot recognize, fails that checker
before its real command runs and reports the resolved binary, detected version
or raw output, and supported contract.

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * - Backend
     - Used by checker(s)
     - Supported versions
   * - ``clang-format``
     - ``cpp``
     - ``>=21.0.0,<24.0.0``
   * - ``meson``
     - ``meson``
     - ``>=1.5.0,<2.0.0``
   * - ``prettier``
     - ``web``, ``json``, ``ini``, ``yaml``
     - ``>=3.0.0,<4.0.0``
   * - ``ruff``
     - ``python``
     - ``>=0.16.5,<0.17.0``
   * - ``mypy``
     - ``mypy``
     - ``>=1.19.0,<3.0.0``
   * - ``check_rst``
     - ``rst``
     - ``>=0.5.0,<0.6.0``
   * - ``clang-tidy``
     - ``clang-tidy``
     - ``>=21.0.0,<24.0.0``
   * - ``cmake-format``
     - ``cmake``
     - ``>=0.6.13,<0.7.0``
   * - ``west``
     - ``kconfig``
     - ``>=1.5.0,<2.0.0``
   * - ``shellcheck``
     - ``shell``
     - ``>=0.11.0,<0.12.0``
   * - ``vnu``
     - ``vnu``
     - ``==26.9.5``

These are adapter support boundaries, not a substitute for reproducible
dependency management.  A consuming project should still pin one exact
backend version inside the relevant interval in its package lock file, CI
image, or system manifest.  ``vnu`` is intentionally stricter: this adapter
accepts only the exact artifact documented below because its diagnostic and
suppression behavior was verified against that release.

Each resolved backend is probed only once per project root during one public
``check_formatting`` invocation.  Independent probes remain concurrent with
the checkers that need them, and a later invocation probes again so an updated
executable at the same path cannot inherit stale process-local state.  Unknown
commands used as checker plumbing are not version-gated, and a missing command
continues through the ordinary missing-backend diagnostic path.

===================================
Backend installation and behavior
===================================

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

   The adapter always passes ``-c meson.format`` (Meson's own
   ``--configuration`` flag), so a ``meson.format`` file must exist at the
   project root — even empty — before this checker will run at all;
   without one, every invocation fails immediately with ``Configuration
   file meson.format not found``, regardless of whether any
   ``meson.build``/``meson.options`` file actually needs reformatting.

``prettier`` (``web``, ``json``, ``ini``, ``yaml``)
   A Node.js tool, not a standalone system binary.  It needs Node.js
   (≥ 18 recommended) and npm installed, plus the project's own
   dependencies installed from ``package.json`` at the repository root
   (``npm install``, which populates ``node_modules/``).  The wrapper
   always invokes it as ``npx --no-install prettier`` (never bare ``npx
   prettier``), specifically so a missing dependency cannot trigger an
   on-the-fly network install.  That flag does not, however, restrict
   resolution to the current project's own ``node_modules/`` alone —
   verified directly: when the project's own ``node_modules/`` is
   present, it wins; when it is absent, ``npx --no-install`` still
   succeeds if a matching version happens to already sit in the invoking
   *user's shared* npm cache (``~/.npm``), left there by any unrelated
   ``npm install``/``npx`` run on that machine with no relationship to
   this project's own pinned version, and only fails outright if neither
   exists.  Skipping ``npm install`` for a project that enables a
   prettier-backed checker therefore does not reliably fail loudly — on a
   machine whose npm cache happens to already hold some version of
   prettier, it can silently check/format against that unrelated version
   instead of the project's own pin.  ``ini`` additionally needs
   ``prettier-plugin-ini`` (registered in ``.prettierrc``) for its
   ``iniSpaceAroundEquals`` behavior; ``json`` auto-selects the ``json``
   or ``jsonc`` parser per file via ``.prettierrc`` overrides.

``ruff`` (``python``)
   Python's formatter and linter in one binary.  Install via pip
   (``pip install ruff``).  Backs both format (``ruff format``) and lint
   (``ruff check``); both must pass.

``mypy`` (``mypy``)
   Python's static type-checker.  Resolved from ``PATH`` like every other
   backend (see :doc:`guide`'s "Installation" section).  Install via the system package
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

   Version ``26.9.5`` (upstream commit ``a9333cb``) is the only version this
   adapter accepts and is integration-tested on this host.  Its ``vnu.jar``
   SHA-256 is
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

      "${HOME}/opt/bin/vnu" --version
      sha256sum "${HOME}/opt/vnu/${vnu_version}/vnu.jar"

   The unversioned ``~/opt/vnu/vnu.jar`` symlink supports consumers that invoke
   the JAR directly; ``check_formatting`` itself deliberately resolves only
   the bare ``vnu`` command from ``PATH``.  Add ``${HOME}/opt/bin`` to the
   invoking environment's ``PATH`` (and persist it in the relevant shell or
   service configuration) before using the checker.  To upgrade, choose and
   review a new exact official package version, obtain and verify its JAR
   digest, install it into a new version-named directory, run its real
   integration tests, and only then update the launcher and compatibility
   symlink.  Keep the preceding directory until the new version has passed,
   providing an immediate rollback.
