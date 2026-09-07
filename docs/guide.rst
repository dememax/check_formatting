.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Overview, installation, and documentation navigation — check_formatting project

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
newer.  For a standalone installation under ``~/opt``, isolate its own Python
package without requiring callers to activate that environment::

   python3.14 -m venv "${HOME}/opt/check_formatting"
   "${HOME}/opt/check_formatting/bin/python" -m pip install /path/to/check_formatting
   export PATH="${HOME}/opt/check_formatting/bin:${PATH}"
   check_formatting --help
   check_formatting --version

Persist that ``PATH`` entry in the shell's startup configuration.  This
environment isolates the utility's Python package only; backend executables
still resolve from the invoking process's ``PATH``.  Installing into another
already-selected Python environment is also supported::

   python3.14 -m pip install /path/to/check_formatting

``--version`` prints the release version followed by the copyright and
license lines; the same two lines are appended to ``--help``'s epilog,
mirroring check_rst's own ``--version``/``--help`` convention.

For development, use an editable installation from the repository root::

   python3.14 -m pip install --editable .

The console entry point and the selected environment's module invocation are
equivalent.  For the standalone installation above, the latter is::

   "${HOME}/opt/check_formatting/bin/python" -m check_formatting

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

*************
Where next?
*************

Choose the page matching the job at hand:

``Getting started``
   :doc:`getting_started` is the adopter path: select checkers, start from a
   known project shape, establish a baseline, and define the daily pre-commit
   loop.
``Backends``
   :doc:`backends` is for dependency owners: CLI compatibility contracts,
   installation routes, and backend-specific behavior.
``Command reference``
   :doc:`reference` covers modes, selection, exclusions, command examples,
   and exact Git-scoped behavior for daily users and committers.
``Integration and automation``
   :doc:`integration` covers CI, pre-commit, JSON consumption, exit status,
   and library embedding.
``Architecture guide``
   :doc:`architecture` is for contributors, backend maintainers, and release
   operators, including the new-checker contract and release checklist.
