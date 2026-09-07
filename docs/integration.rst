.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. CI, pre-commit, exit-status, and library integration guide — check_formatting project

############################
Integration and automation
############################

This page is for CI owners and library integrators.  See :doc:`guide` for
installation and :doc:`reference` for interactive command behavior.

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
your own ``checks`` list actually needs, pinning one exact version inside
each documented support interval in a lock file, image, or package manifest):

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
         - uses: actions/checkout@v4
           with:
             repository: dememax/check_formatting
             ref: <pinned-commit-or-release-tag>
             path: .tools/check_formatting
         - run: python3.14 -m pip install .tools/check_formatting
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
Calls must not overlap in multiple threads in one Python process: dispatch
temporarily installs a process-global ``sys.stdout`` multiplexer while the
selected checkers run.  Separate processes are the supported concurrency
boundary for library integrators.
