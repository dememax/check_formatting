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
newer.  Its supported standalone layout uses an ordinary isolated environment
at ``~/opt/check_formatting`` and a project-managed stable launcher in
``~/opt/bin``. Build and install it from a clean, committed checkout without
activating that environment::

   cd /path/to/check_formatting
   python3.14 tools/build_wheel.py
   python3.14 tools/install_standalone.py install
   export PATH="${HOME}/opt/bin:${PATH}"
   check_formatting --help
   check_formatting --version

Persist that ``PATH`` entry in the shell's startup configuration. Backend
executables still resolve from the invoking process's ``PATH``. The builder
requires the exact tools in ``tools/release-requirements.txt``, derives the
archive timestamp from the source commit, proves two builds byte-identical,
emits an adjacent ``.whl.sha256`` file, and smoke-tests a fresh standalone
installation before placing either local artifact under ``dist/``. The
repository, rather than the wheel, remains the source of the RST documentation.

An existing system-site environment or unmanaged launcher is never replaced
implicitly; migrate it once with::

   python3.14 tools/install_standalone.py install --recreate

Installing into another already-selected Python environment is also supported
after checking the wheel against its generated sidecar::

   sha256sum -c dist/check_formatting-VERSION-py3-none-any.whl.sha256
   python3.14 -m pip install dist/check_formatting-VERSION-py3-none-any.whl

Replace ``VERSION`` with the version printed by the builder. The standalone
installer derives the exact filename from the checkout automatically.

``--version`` prints the release version followed by the copyright and
license lines; the same two lines are appended to ``--help``'s epilog,
mirroring check_rst's own ``--version``/``--help`` convention.

For development, use an editable installation from the repository root::

   python3.14 -m pip install --editable .

The console entry point and the selected environment's module invocation are
equivalent.  For the standalone installation above, the latter is::

   "${HOME}/opt/check_formatting/bin/python" -m check_formatting

Update by rebuilding from the new clean commit and running the same installer.
Remove both the dedicated environment and its owned launcher with::

   python3.14 tools/install_standalone.py uninstall

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
