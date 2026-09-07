.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Adopter onboarding and daily workflow — check_formatting project

#################
Getting started
#################

**********************
Backend entry points
**********************

One supported install route per backend — see :doc:`backends` for alternatives
and gotchas.  The commands here identify the package; for a reproducible
project or CI image, select and lock one exact version inside that page's
compatibility table rather than tracking an unbounded latest release:

.. list-table::
   :header-rows: 1
   :widths: 16 24 60

   * - Checker(s)
     - Backend
     - Install
   * - ``cpp``, ``clang-tidy``
     - clang-format / clang-tidy
     - ``sudo apt install clang-format clang-tidy`` (part of LLVM)
   * - ``meson``
     - meson format
     - ``pip install meson`` — also needs a ``meson.format`` file at the
       project root, even empty (see :doc:`backends`)
   * - ``web``, ``json``, ``ini``, ``yaml``
     - prettier
     - ``npm install`` (the project's own ``package.json``); ``ini`` also
       needs ``prettier-plugin-ini``
   * - ``python``
     - ruff
     - ``pip install ruff``
   * - ``mypy``
     - mypy
     - ``pip install mypy``
   * - ``rst``
     - check_rst
     - Installed and versioned separately from ``check_formatting`` — see
       check_rst's own installation instructions
   * - ``cmake``
     - cmake-format
     - ``pip install cmake-format``
   * - ``kconfig``
     - west
     - Part of a Zephyr-style West workspace — see Zephyr's own
       installation instructions
   * - ``shell``
     - shellcheck
     - ``sudo apt install shellcheck``
   * - ``vnu``
     - Nu Html Checker
     - No package-manager one-liner — see :doc:`backends` for the
       pinned-version ``~/opt`` install procedure

*********************************
Which checkers should I enable?
*********************************

Inverse of :doc:`backends`' "Registered checkers" table — keyed by what's
already in the repository, not by checker name:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - The repository has...
     - Consider enabling
   * - ``.cpp``/``.hpp`` files
     - ``cpp``; ``clang-tidy`` too if a build directory produces
       ``compile_commands.json``
   * - ``.html``/``.css``/``.js`` files
     - ``web``; ``vnu`` as well for HTML/CSS/SVG conformance analysis on
       top of Prettier's formatting
   * - ``.py`` files
     - ``python``; ``mypy`` as well for type-checking
   * - ``meson.build``/``meson.options``
     - ``meson`` (discovered recursively, no globs to configure)
   * - ``CMakeLists.txt``
     - ``cmake`` (discovered recursively, no globs to configure)
   * - A Zephyr/West workspace
     - ``kconfig``
   * - ``.sh`` scripts (or extensionless scripts with a shell shebang)
     - ``shell``
   * - ``.rst`` documentation built with Sphinx
     - ``rst``
   * - ``.json``/``.ini``/``.yaml`` files you want Prettier-formatted
     - ``json``/``ini``/``yaml`` respectively

*****************
Starter configs
*****************

Both examples below were run end to end while writing this section:
a clean baseline passes, a deliberately introduced violation in each
checker is caught, and ``--fix`` returns the project to a clean state.

=======================
A pure Python package
=======================

.. code-block:: toml

   checks = ["python", "mypy"]

   [python]
   dirs = ["src", "tests"]

Prerequisites: run from the project root; Python 3.14 on ``PATH``;
``pip install ruff mypy``. Introducing an unused import and bad spacing in
``src/mypkg/core.py`` and running ``check_formatting --all`` reports both a
``ruff format`` and a ``ruff check`` violation; ``check_formatting --fix
--all`` resolves them. Ruff's own format and lint fixes can interact —
a lint fix (e.g. removing an unused import) can leave a line-spacing issue
that only a second ``ruff format`` pass corrects — so after ``--fix``,
always re-run plain ``check_formatting`` to confirm clean, and run
``--fix`` a second time if it isn't; this project's own AGENTS.md-style
discipline (see "Day-to-day workflow" below) already asks for this
verification step, not a single blind ``--fix``.

================================
A Meson C++/web/Python project
================================

.. code-block:: toml

   checks = ["cpp", "meson", "web", "python", "mypy"]

   [cpp]
   globs = ["src/**/*.cpp", "src/**/*.hpp"]

   [web]
   globs = ["www/**/*.html"]

   [python]
   dirs = ["scripts"]

Prerequisites: an empty ``meson.format`` file at the project root (see
:doc:`backends`); ``clang-format``, ``meson``, ``ruff``, and ``mypy`` on ``PATH``;
``npm install`` with ``prettier`` as a dependency. Introducing bad spacing
in both ``src/main.cpp`` and ``meson.build`` and running
``check_formatting --all`` reports both violations distinctly (clang-format
and meson format run and fail independently); ``check_formatting --fix
--all`` resolves both in one pass here — unlike the Ruff format/lint
interaction above, clang-format and meson format each converge in a single
run since they don't have a second, independent fixer stepping on the
first one's output.

=======================================
A CMake/Zephyr project (illustrative)
=======================================

.. code-block:: toml

   checks = ["cmake", "kconfig"]

   [kconfig]
   build_combos = [
     { label = "native_posix", args = ["-b", "native_posix"] },
   ]

Unlike the two examples above, this one is illustrative rather than
demonstrated end to end here — ``kconfig`` needs a real Zephyr/West
workspace and target board to build against, which this documentation does
not maintain a live copy of.

==============================================
Adopting into an existing, legacy repository
==============================================

Point globs at everything, including vendored or generated trees, on day
one is the wrong default for a repository with pre-existing, unmaintained
content. Instead: scope the initial config to the files a project's own
authors actively maintain (e.g. ``[python].dirs = ["src"]``, not the whole
repository root), run ``check_formatting --all``, fix what it reports until
clean, commit that as the baseline, and broaden the config deliberately
from there — one directory or glob at a time, each broadening its own
reviewed commit — rather than accepting whatever a maximally broad config
reports on day one, most of which would be pre-existing content nobody
asked to have reformatted in one pass.

***********************************************
First-time setup: baseline broad, then narrow
***********************************************

Once a checker is enabled at all, the same discipline that adopting
``vnu`` first established (see
:doc:`roadmap/vnu-message-suppression-ergonomics`'s adoption recipe)
applies to *every* checker, not only ``vnu``:

#. Run ``check_formatting --all`` with no suppressions/exclusions/filters
   configured yet.
#. Review every real finding — a first adoption on an existing codebase
   typically surfaces genuine issues, not only stylistic noise.
#. Fix genuine findings by hand where the checker has no ``--fix`` mode
   (analysis-only checkers like ``vnu``/``clang-tidy``), or via
   ``check_formatting --fix`` where it does.
#. Only once genuinely clean, add a narrowly scoped, documented suppression
   (a ``.formatting-ignore`` entry, a native filter such as ``vnu``'s
   ``--filterpattern``) for anything deliberately accepted — with a comment
   explaining *why*, not just *what*.
#. Re-run ``check_formatting --all`` to confirm the suppression achieved
   exactly what was intended and nothing broader.
#. Revisit any suppression periodically — especially across a backend
   version bump — since a message's wording or a tool's behavior can drift.

*********************
Day-to-day workflow
*********************

A template an adopting project can drop into its own ``CONTRIBUTING.md``,
generalizing this project's own AGENTS.md discipline:

.. code-block:: markdown

   ## Formatting

   Before committing, run:

   ```bash
   check_formatting --fix
   check_formatting
   ```

   The second command must report all checks passed. If it doesn't,
   `--fix` may need a second pass — some backends' own format and lint
   fixers can interact (a lint fix can reintroduce a formatting issue a
   second format pass would catch) — so re-run `--fix` and check again
   rather than assuming one pass is always enough. Never commit with
   outstanding violations. See [docs/integration.rst's "Continuous
   integration" section](docs/integration.rst#continuous-integration)
   for a pre-commit hook that automates this.
