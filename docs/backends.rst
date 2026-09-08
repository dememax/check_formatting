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

=====================
Installation routes
=====================

Two independent questions, for every backend: does a distro package it at a
usable version (Ubuntu, Gentoo — the two hosts this project has verified
against; see :doc:`roadmap/backend-install-policy` for the underlying
research), and can a project pin its own version instead of the system one.
"System default" is simply whatever ``check_formatting`` resolves first on
``PATH`` — installing a distro package is enough for that. A project-specific
pin instead means installing the backend somewhere project-scoped (a
project's own virtual environment, ``node_modules/``, etc.) and making sure
that location is earlier on ``PATH`` when ``check_formatting`` runs — the
adapter never discovers or prefers either on its own initiative; this is a
property of the invocation environment, not a feature this tool implements.
The paragraphs below carry the caveats a table alone would flatten away (a
missing distro package, a version gap worth knowing about, a fallback that
doesn't fail loudly); this table is only for a fast lookup.

.. list-table::
   :header-rows: 1
   :widths: 16 26 26 32

   * - Backend
     - Ubuntu 26.04 (``apt``)
     - Gentoo (Portage)
     - Project-specific pin
   * - ``clang-format``
     - ``clang-format`` — 2 majors behind upstream
     - ``llvm-core/clang`` — 1 behind its own tree
     - PyPI ``clang-format``
   * - ``clang-tidy``
     - ``clang-tidy`` (same LLVM package family)
     - ``llvm-core/clang`` (same package)
     - PyPI ``clang-tidy`` (maintained separately from the ``clang-format``
       package above; can lag it)
   * - ``meson``
     - ``meson`` — 2 minors behind upstream
     - ``dev-build/meson`` — 1 behind its own tree
     - PyPI ``meson``
   * - ``prettier``
     - not distro-packaged (Node ecosystem)
     - not distro-packaged
     - npm ``package.json``/``package-lock.json`` — see the gotcha above
   * - ``ruff``
     - not packaged at all
     - ``dev-util/ruff`` — 1 patch behind upstream
     - PyPI ``ruff`` (distinct from Astral's own system-wide standalone
       installer)
   * - ``mypy``
     - ``mypy``/``python3-mypy`` — a full **major** version behind upstream
     - ``dev-python/mypy`` — 1 behind its own tree
     - PyPI ``mypy``
   * - ``check_rst``
     - n/a — first-party, no distro or PyPI package
     - n/a
     - n/a — see check_rst's own installation guide
   * - ``cmake-format``
     - ``cmake-format`` (matches upstream)
     - not in the main tree at all
     - PyPI ``cmake-format`` — the only practical Gentoo route
   * - ``west``
     - ``west`` (matches upstream)
     - not in the main tree at all
     - PyPI ``west`` — Zephyr's own recommended default, not merely a
       fallback
   * - ``shellcheck``
     - ``shellcheck`` (matches upstream)
     - ``dev-util/shellcheck-bin`` (matches upstream)
     - PyPI ``shellcheck-py``, bundling the official prebuilt binary
   * - ``vnu``
     - not packaged at all
     - not packaged at all
     - npm ``vnu-jar``, exposed via ``node_modules/.bin`` — see below

===================================
Backend installation and behavior
===================================

``clang-format`` (``cpp``)
   Part of the LLVM toolchain.  Install via the system package manager
   (``sudo apt install clang-format`` on Debian/Ubuntu — currently 2 major
   LLVM releases behind upstream there; ``emerge llvm-core/clang`` on
   Gentoo; ``brew install llvm`` on macOS).  For a project-specific pin
   instead, ``pip install clang-format`` in the project's own virtual
   environment and activate it before invoking ``check_formatting`` — the
   adapter resolves whichever ``clang-format`` is first on ``PATH``, with
   no preference of its own.  It cannot report *which* rule a file violates
   or *why* — the only diagnostic it emits is the generic
   ``[-Wclang-format-violations]`` warning, meaning "this file would look
   different after formatting".  Run ``--diff`` to see the actual changes
   it would make; ``--verbose`` produces identical output to plain check
   mode because clang-format exposes no extra diagnostic flags.

``meson format`` (``meson``)
   Provided by Meson itself; ``--check-only`` requires Meson ≥ 1.5.0.
   Install via the system package manager (``sudo apt install meson`` on
   Debian/Ubuntu — currently 2 minor releases behind upstream there;
   ``emerge dev-build/meson`` on Gentoo) or ``pip install meson`` in a
   project's own virtual environment for a project-specific pin, activated
   before invoking ``check_formatting``.  Like clang-format, it exposes no
   rule-level diagnostics beyond pass/fail.

   The adapter always passes ``-c meson.format`` (Meson's own
   ``--configuration`` flag), so a ``meson.format`` file must exist at the
   project root — even empty — before this checker will run at all;
   without one, every invocation fails immediately with ``Configuration
   file meson.format not found``, regardless of whether any
   ``meson.build``/``meson.options`` file actually needs reformatting.

``prettier`` (``web``, ``json``, ``ini``, ``yaml``)
   A Node.js tool, not a standalone system binary, and never itself
   distro-packaged — only Node.js/npm are (``sudo apt install nodejs npm``
   on Debian/Ubuntu, ``emerge net-libs/nodejs`` on Gentoo). It needs Node.js
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
   Python's formatter and linter in one binary. Not packaged in Ubuntu's
   ``apt`` repositories at all; Gentoo packages ``dev-util/ruff``, currently
   1 patch release behind upstream. Install via ``pip install ruff`` for a
   project-specific pin in the project's own virtual environment (activated
   before invoking ``check_formatting``) — distinct from Astral's own
   standalone installer script, which installs system-wide only, not
   project-scoped. Backs both format (``ruff format``) and lint
   (``ruff check``); both must pass.

``mypy`` (``mypy``)
   Python's static type-checker.  Resolved from ``PATH`` like every other
   backend (see :doc:`guide`'s "Installation" section).  Install via the
   system package manager (``sudo apt install mypy`` on Debian/Ubuntu —
   currently a full **major** version behind upstream there, the largest
   gap of any backend this project has checked; ``emerge dev-python/mypy``
   on Gentoo) or ``pip install mypy`` in a project's own virtual
   environment for a project-specific pin, activated before invoking
   ``check_formatting`` — the most common way projects already pin mypy.
   Reads its own configuration from ``[tool.mypy]`` in
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
   Part of the LLVM toolchain, installed the same way as clang-format
   (``sudo apt install clang-tidy`` on Debian/Ubuntu; ``emerge
   llvm-core/clang`` on Gentoo — the same package provides both binaries).
   For a project-specific pin, ``pip install clang-tidy`` — maintained as a
   separate PyPI package from ``clang-format``'s own, and can sit at a
   different version from it.  Additionally requires an up-to-date
   ``compile_commands.json`` in the
   build directory named by ``.check_formatting.toml``'s
   ``[clang_tidy].build_dir`` (generated automatically by Meson on
   ``meson compile``).  A project with no ``[clang_tidy]`` section skips
   this checker cleanly, without requiring ``clang-tidy`` on ``PATH`` at
   all.

``cmake-format`` (``cmake`` — optional, CMake-based projects only)
   Install via the system package manager (``sudo apt install
   cmake-format`` on Debian/Ubuntu, matching upstream) or ``pip install
   cmake-format`` in a project's own virtual environment for a
   project-specific pin.  Not in Gentoo's main Portage tree at all — the
   ``pip`` route is the only practical option there.  Not relevant to
   Meson-based projects.

``west`` (``kconfig`` — optional, Zephyr/west projects only)
   Part of a Zephyr-style West workspace.  Install via the system package
   manager (``sudo apt install west`` on Debian/Ubuntu, matching upstream;
   not in Gentoo's main tree) or ``pip install west`` in a project's own
   virtual environment — actually Zephyr's own recommended default, not
   merely a fallback for Gentoo's missing package.  Requires at least one
   entry in ``.check_formatting.toml``'s ``[kconfig].build_combos``; a
   project with none skips this checker cleanly, without requiring
   ``west`` on ``PATH``.

``shellcheck`` (``shell`` — optional)
   Install via the system package manager (``sudo apt install
   shellcheck`` on Debian/Ubuntu, ``emerge dev-util/shellcheck-bin`` on
   Gentoo, ``brew install shellcheck`` on macOS — all three currently match
   upstream exactly). For a project-specific pin instead, ``pip install
   shellcheck-py`` bundles the official prebuilt binary in a project's own
   virtual environment; a genuine alternative even though the distro
   packages above are already current, not only a fallback for a gap.
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
   adapter accepts and is integration-tested on this host. Not packaged by
   Ubuntu's or Gentoo's package repositories at all — the two routes below
   are the only ones available, and ``check_formatting`` does not prefer
   either: it runs whichever ``vnu`` its invocation environment resolves
   first on ``PATH``. For a project-specific pin, ``npm install --save-dev
   vnu-jar@26.9.5`` creates ``node_modules/.bin/vnu``; invoking
   ``check_formatting`` through an npm script (or any launcher that exposes
   ``node_modules/.bin`` on ``PATH``) resolves that pinned executable ahead
   of any system-wide one. The system-wide route below instead installs one
   centrally managed, integrity-verified executable for projects that
   intentionally share a single tested backend version. Its ``vnu.jar``
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
