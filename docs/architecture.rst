.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Contributor architecture guide for implementing a new checker — check_formatting project

####################
Architecture guide
####################

This page is for a contributor about to implement a new checker, or
otherwise change how ``check_formatting`` dispatches, selects files for, or
captures output from a backend. It documents the internal contract every
existing checker already follows — verified against the actual source and
test suite, not inferred — so a fifteenth checker can reuse established
conventions instead of rediscovering or accidentally reinventing them.
Everything here describes the architecture as it stands; where this guide
introduces a new policy rather than describing an existing one, it says so
explicitly. See :doc:`guide` for the *user-facing* documentation entry point
(what each checker does, how a project configures it) and
:doc:`roadmap/new-checker-architecture-guide` for the roadmap epic this
page fulfills, including the evidence behind each claim below.

****************
Package layout
****************

``check_formatting.cli`` is a *package*, not a flat module:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Module
     - Responsibility
   * - ``__init__.py``
     - The dispatch loop (concurrent checker execution, output ordering,
       the summary table/``--json`` payload), the ``main()`` CLI entry
       point, and the package's re-export surface.
   * - ``_config.py``
     - ``.check_formatting.toml``'s schema and validating loader:
       ``ProjectConfig``, the known section/key table, and per-checker
       config validation such as :data:`_VNU_FORBIDDEN_ARGS`.
   * - ``_registry.py``
     - The ``Checker`` registration type and the ``_CHECKERS`` table
       mapping each checker name to its function, kwargs/fix-command
       derivation, and ``auto_fix`` capability.
   * - ``_checkers.py``
     - The ``_check_*`` functions themselves — one per backend.
   * - ``_selection.py``
     - File-selection and exclusion: Git auto-detection,
       ``.formatting-ignore``/``--exclude`` filtering, glob matching, and
       Git-hunk-range lookups for the checkers with a native git-scoped
       fix.
   * - ``_subprocess.py``
     - Subprocess dispatch (``_run``, ``_run_capture_merged``,
       ``_fmt_stdout``) and the thread-local output buffer
       (``_ThreadLocalStdout``) concurrent dispatch installs.
   * - ``_backend_versions.py``
     - External CLI version parsing, compatibility policies, and the
       invocation-local, concurrency-safe probe cache used by every shared
       subprocess helper.
   * - ``_prettier.py``
     - Shared Prettier plumbing: the best-effort git-scoped fix
       reconstruction algorithm, used by ``web``/``json``/``ini``/``yaml``.

==========================
The re-export convention
==========================

Cross-submodule calls to any name a test might monkeypatch on the package
(``_run``, ``_print_tool_info``, ``_fmt_stdout``, ...) go through
``from check_formatting import cli`` followed by a deferred
``cli.<name>(...)`` attribute lookup — **never** a plain
``from ._subprocess import _run``. The latter binds the name at import
time; a test's ``monkeypatch.setattr(check_formatting, "_run", ...)``
patches the *package* attribute, which a direct submodule import would
never observe. Every existing checker follows this already (see
``_checkers.py``'s own ``cli._run(...)``, ``cli._print_tool_info(...)``
calls); ``tests/test_check_formatting_cli_package_imports.py`` pins the
convention down directly with cold-interpreter import tests, and is the
only other place that states it. A new checker calling a shared helper via
a direct submodule import will work today and only fail once a test tries
to monkeypatch it.

===========================
Registering a new checker
===========================

Three production files always make up the registration surface, each a
different kind of change.  A fourth is required when the checker introduces
a new external CLI (tests and user/contributor documentation are additional
required work):

#. ``_config.py`` — add the section/key ``Final`` tuple(s) to
   ``_CONFIG_FIELDS`` (this alone gives the new section's unknown-key and
   type validation for free), a field on ``ProjectConfig``, and the actual
   TOML-parsing line(s) in ``_load_project_config``.
#. ``_registry.py`` — import the new ``_check_X`` function and add a
   ``Checker(label, fn, kwargs_fn, fix_command_fn, auto_fix)`` entry to
   ``_CHECKERS``.
#. ``_checkers.py`` — the ``_check_X`` function itself.
#. ``_backend_versions.py`` — for a new external CLI, add its version probe,
   parser, and deliberately reviewed supported interval.  Reusing an existing
   backend needs no new policy entry.

``cli/__init__.py`` needs **no edit**: it imports ``_CHECKERS`` once from
``_registry.py`` and re-exports it via ``__all__``; both are already done,
and a new dict entry in ``_registry.py`` is visible to ``run_one``'s
dispatch immediately, by reference. The ``Checker`` ``NamedTuple``'s own
docstring is worth reading once: ``_registry.py`` used to be three
separately hand-synced tables (label+function, kwargs-by-name, fix-command
logic) that could silently drift out of sync — a real lesson from this
project's own history. ``_CONFIG_FIELDS``/``_CONFIG_SECTIONS`` in
``_config.py`` is a second, independent instance of the same "one shared
table, not several hand-synced ones" pattern; extend it the same way.

*******************************
The checker function contract
*******************************

Every registered checker is called from ``run_one`` (in ``cli/__init__.py``)
with exactly six shared **positional** arguments —

.. code-block:: python

   checker.fn(
       root,               # pathlib.Path — the project root
       fix,                # bool
       diff,                # bool
       verbose,             # bool
       ignore_patterns,     # Sequence[str] — .formatting-ignore/--exclude patterns
       explicit_files,      # list[pathlib.Path] | None
       quiet=...,           # keyword
       **_checker_kwargs(name, config, git_auto_detected),  # keyword
   )

— then ``quiet`` and every checker-specific option **by keyword**. A
checker's own signature may place ``quiet`` wherever suits it (some put it
right after ``explicit_files``, others after their own checker-specific
parameters, others past a ``*,`` keyword-only marker alongside
``git_auto_detected``) — it is never part of a shared positional prefix,
and this works only because the call site always names it.

``explicit_files`` has three states, and a checker must handle all three
distinctly:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - ``explicit_files``
     - Meaning
   * - ``None``
     - Full-repo scan: glob/discover by the checker's own configured
       globs/dirs, regardless of Git state (``--all``, or a direct library
       call with no explicit files).
   * - ``[]`` (empty list)
     - Nothing to check — return ``True`` without invoking the backend at
       all.
   * - non-empty list
     - Exactly those paths — either Git auto-detected (default scope) or a
       user-typed ``-- FILE`` argument. Filter through the checker's own
       configured globs/files/fixed domain, and apply ``ignore_patterns``.

Backend resolution and subprocess dispatch are two separate *required
outcomes*; each has more than one legitimate implementation already in use
in this codebase — pick whichever fits the new checker's own control flow,
don't treat either example below as the one mandatory mechanism:

=======================================================
Missing backend fails cleanly, never with a traceback
=======================================================

Seven of the fourteen checkers pre-check with a bare ``shutil.which`` call
and print a specific ``"  ERROR: <tool> not found — ..."`` line before
dispatch. The other seven (``cpp``, ``meson``, ``python``, and the four
Prettier-backed ``web``/``json``/``ini``/``yaml`` checkers) rely on
``_run``/``_fmt_stdout``'s own ``FileNotFoundError`` handling instead —
both already catch it and print ``"ERROR: command not found: ..."`` —
letting the subprocess call itself fail cleanly rather than pre-checking.
Either is acceptable.

===============================================================
Subprocess dispatch stays compatible with concurrent dispatch
===============================================================

Never call raw ``subprocess`` from a checker. Three helpers exist, for
three different situations:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Helper
     - When to use it
   * - ``cli._run``
     - One subprocess whose output should reach the terminal as the
       checker's own findings — see "Output and concurrency" below for
       what "reach the terminal" actually means during concurrent
       dispatch.
   * - ``cli._run_capture_merged``
     - One subprocess, stdout+stderr merged, captured (not printed)
       rather than written — used when a checker itself runs several
       subprocesses concurrently (``kconfig``'s per-combo builds), or
       needs to inspect the output before deciding what, if anything, to
       print (the item-2 vnu diagnostic in
       :doc:`roadmap/vnu-message-suppression-ergonomics` decides *whether*
       to print an extra hint from the exit code alone, not from output
       content, so it still uses plain ``cli._run``).
   * - ``cli._fmt_stdout``
     - Captures only stdout, optionally feeding stdin — used for
       diff-mode previews and Prettier's canonical-equivalence check in
       ``_prettier.py``.

All three helpers first consult ``_backend_versions.py`` when the command is
a registered external backend.  Keep that gate in the shared helper instead
of duplicating it in checker functions: one public invocation probes each
resolved backend/root once, simultaneous requests for that same probe share
one result, and unrelated backend probes can proceed concurrently.

The output contract still differs by helper.  ``_run`` and ``_fmt_stdout``
print a compatibility diagnostic into the checker's normal captured stream;
``_run_capture_merged`` returns that diagnostic in its
``CompletedProcess.stdout`` without printing it.  The latter distinction is
required for a checker's own worker threads, which are not registered with
the outer thread-local stdout capture and would otherwise leak or interleave
output.

==============================
``print()`` versus ``log()``
==============================

``_make_log(quiet)`` returns a ``log()`` function gated on ``--quiet`` —
use it for chrome: banners, command announcements, routine scope notices.
Use plain ``print()`` for anything that must survive ``--quiet`` and reach
``--json``'s per-checker ``output`` field: error messages, findings,
diagnostics. The existing missing-backend ``"  ERROR: ... not found"``
line already does this; so does the vnu adapter's
``--skip-info-messages``-masked-failure hint. Getting this backward — using
``log()`` for something that should survive ``--quiet`` — is a real, easy
mistake with no test that catches it generically; a new checker's own
tests should assert quiet/json behavior explicitly (see "Acceptance
criteria" below).

************************
Output and concurrency
************************

Every selected checker runs concurrently regardless of ``--fail-fast``, and
the *user-facing* behavior is already documented precisely in
:doc:`reference`'s "Concurrent checker dispatch" section: output
prints in ``--checks`` order, never completion order, and nothing prints
interleaved. What that section doesn't cover, because it isn't written for
a contributor, is the mechanism and what it implies for a checker
implementation:

* ``_ThreadLocalStdout`` (``cli/__init__.py``) gives each dispatched
  checker's own worker thread a private ``io.StringIO`` buffer for the
  duration of concurrent dispatch. A thread that never registers (the main
  thread) falls straight through to the real ``sys.stdout``.
* The main thread's own loop iterates ``checks`` **in configured order**,
  blocking on ``futures[name].result()`` for each name in turn and printing
  that checker's banner plus its buffered output immediately once that
  future resolves — it does **not** wait for every checker to finish
  first. A checker earlier in ``--checks`` order that runs slowly still
  gates when a faster, already-finished checker later in the list actually
  gets printed. **Checker order is not dependency order**: nothing in the
  dispatcher expresses or enforces one checker's targets depending on
  another's having already run.
* A checker that spawns its *own* internal worker threads (``kconfig``'s
  per-combo builds, the Prettier best-effort fixer's per-file concurrency)
  cannot rely on those inner threads inheriting the outer thread's
  registered buffer — ``_ThreadLocalStdout`` is genuinely per-OS-thread.
  The existing pattern avoids the problem rather than solving it: inner
  threads never call ``print()``/``sys.stdout.write`` at all. They run
  ``cli._run_capture_merged`` (which captures via
  ``subprocess.run(..., stdout=PIPE)``, independent of ``sys.stdout``), and
  only the *outer*, already-registered checker thread writes the captured
  text out once each inner future resolves. Copy this pattern for any new
  checker adding its own internal concurrency; do not attempt to register
  inner threads with the outer buffer directly.
* ``--fail-fast`` never cancels other checkers — every checker is already
  submitted before the loop starts consuming results, and Python cannot
  safely kill a thread mid-flight, so every checker keeps running to
  completion regardless. ``--fail-fast`` only shortens what gets printed
  and included in the payload.
* A checker with its own internal concurrency needs to account for
  overlapping reads/writes and shared state the same way ``kconfig``
  already documents for itself: combos sharing a build directory race, so
  each needs its own isolated build state if run concurrently.

********************************
Worked example: adding ``vnu``
********************************

``vnu`` is the simplest checker in the registry — analysis-only (no fix
mode), two config keys, no native git-scoped fix — and its real addition
is reproduced exactly below. Pair it with a checker that *does* mutate
files and has a native git-scoped fix, such as ``cpp``, before generalizing
from ``vnu`` alone: a report-only checker's contract is a strict subset of
a mutating one's.

#. RED: write the failing tests first — see
   ``tests/test_check_formatting_vnu.py`` and
   ``tests/test_check_formatting_vnu_integration.py`` for what shipped.
   ``git log`` for this project's own history (``c7dd417``,
   ``feat(vnu): add web conformance checker``) shows the real commit
   sequence: a RED test commit before the implementation commit, per this
   project's own TDD/commit-granularity policy in ``AGENTS.md``.

#. ``_config.py``:

   .. code-block:: python

      _VNU_GLOBS: Final = ("vnu", "globs")
      _VNU_ARGS: Final = ("vnu", "args")
      # ... added to _CONFIG_FIELDS ...

      # ProjectConfig gains:
      vnu_globs: list[str]
      vnu_args: list[str]

      # _load_project_config gains:
      vnu_table = _require_table(data, "vnu") if "vnu" in data else None
      vnu_args = (
          _require_str_list(vnu_table, "args", "[vnu]")
          if vnu_table is not None and "args" in vnu_table
          else []
      )
      # ... and, in the returned ProjectConfig:
      vnu_globs=_optional_section(data, *_VNU_GLOBS, _require_str_list, []),
      vnu_args=vnu_args,

#. ``_registry.py``:

   .. code-block:: python

      "vnu": Checker(
          "vnu (HTML/CSS/SVG conformance)",
          _check_vnu,
          lambda config, git_auto_detected: {"globs": config.vnu_globs, "args": config.vnu_args},
          _no_auto_fix("(vnu has no automatic fix — resolve conformance findings manually)"),
          False,  # auto_fix
      ),

   ``auto_fix=False`` is what makes this an *analysis-only* checker: fix
   mode still runs the same validation (see ``_log_analysis_only`` in
   ``_checkers.py``) but never claims to have applied a fix, and the
   summary table's "apply all fixes" framing excludes it. A checker that
   *does* rewrite files in fix mode omits this argument (``auto_fix``
   defaults to ``True``) and gives ``fix_command_fn`` a real command
   string instead of ``_no_auto_fix``'s constant message — see ``cpp``'s
   own entry, ``lambda config, git_auto_detected: f"clang-format -i
   {' '.join(config.cpp_globs)}"``.

#. ``_checkers.py`` — ``_check_vnu`` itself: resolve the glob/explicit-file
   selection (reusing ``_select_explicit_from_globs``/``_filter_files``
   from ``_selection.py``, per the pointer below), resolve the backend via
   ``shutil.which`` with the standard missing-backend error, then dispatch
   via ``cli._run`` with the mandatory ``--Werror --also-check-css
   --also-check-svg`` flags plus the project's own ``args``.

#. ``_backend_versions.py`` — register the external ``vnu`` command's exact
   ``26.9.5`` contract and the parser for its real ``vnu --version`` output.
   The exact pin is deliberate here because the adapter's diagnostic and
   filtering behavior was integration-tested against that artifact.  For a
   ranged policy, make the lower bound the oldest CLI behavior actually
   covered and the upper bound the first incompatible or unverified release;
   do not advertise a broad interval merely because its versions parse.

******************************
The selection-helper library
******************************

``_selection.py`` exposes the following; pick whichever matches the new
checker's own selection semantics rather than reimplementing file
filtering from scratch:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Helper
     - When it's the right choice
   * - ``_select_explicit_from_globs``
     - Explicit files, filtered through configured globs plus a fallback
       extension set — the usual choice for a glob-configured checker
       (``vnu``, ``cpp``, ``web``, ...).
   * - ``_select_explicit``
     - Explicit files, filtered by exact filename(s)/extension(s) rather
       than globs — used where the checker discovers by a fixed name
       (``meson.build``) or extension set, not a project-declared glob.
   * - ``_filter_files``
     - Applies ``ignore_patterns`` to an already-discovered file list —
       the ``--all``/no-explicit-files counterpart to the two helpers
       above.
   * - ``_filter_configured_targets``
     - Further restricts a file list to configured directories
       (``[python].dirs``) — used where a checker's config is
       directory-scoped rather than glob-scoped.
   * - ``_report_empty_selection``
     - Prints the standard "nothing selected" message and returns whether
       the caller should bail out early — call this once selection is
       resolved, before touching the backend.
   * - Git-hunk-range helpers (``_git_diff_hunk_ranges`` and friends)
     - Only needed for a checker implementing the *native* tier of the
       git-scoped-fix contract (see :doc:`reference`'s
       "Git-scoped formatting" section for the user-facing contract this
       supports) — most new checkers won't need these directly.

*********
Testing
*********

This project's TDD policy (``AGENTS.md``) already asks for two *kinds* of
evidence: mocked dispatch-logic tests (mock ``_run``/``_fmt_stdout``, test
``check_formatting``'s own selection/dispatch logic) and real-backend
behavior tests (a hermetic reproduction against the actual installed
tool). How that's organized into files is *not* yet a strict, established
rule: only ``shell`` and ``vnu`` currently split real-backend coverage into
a dedicated ``test_check_formatting_<name>_integration.py`` file
(``pytest.mark.skipif`` when the real backend is absent); every other
checker's real-backend coverage, where it exists, is mixed directly into
its main test file (``web``'s and ``yaml``'s test files both call real
``npx prettier`` next to tests that monkeypatch ``_run``).

New policy this guide introduces: a new checker should follow the
``shell``/``vnu`` split — one mocked-dispatch test file, one dedicated
``_integration.py`` file — rather than the older mixed-file style, since
the dedicated file makes it trivial to skip real-backend tests in an
environment without that backend installed without hand-picking test IDs.

*******************
Release checklist
*******************

This is the maintainer/release-operator path; it is separate from an
adopter's installation and a contributor's ordinary pre-commit loop.

#. Start from a clean worktree whose feature and documentation commits have
   already passed ``python3.14 -m pytest tests/ -v`` and
   ``PYTHONPATH=src python3.14 -m check_formatting --all``.
#. Add a RED packaging test for the intended release in
   ``tests/test_check_formatting_packaging.py`` and commit it separately.
#. Change the single public version in ``src/check_formatting/__init__.py``.
   Sphinx imports that value directly; the installation examples contain no
   second release literal. Roadmap ``Versions involved`` fields are historical
   evidence and are not blanket-rewritten.
#. Commit the release bump after its source-tree tests pass. The reproducible
   builder requires a clean commit and uses that commit's timestamp as
   ``SOURCE_DATE_EPOCH``; building from an uncommitted release change would
   leave the artifact without an exact source identity.
#. Use a Python environment containing exactly the versions pinned in
   ``tools/release-requirements.txt`` and run ``python3.14
   tools/build_wheel.py``. The builder produces only the pure-Python wheel and
   adjacent ``.whl.sha256`` file: this project deliberately distributes no
   sdist and keeps its RST documentation in the repository, not the wheel.
#. The builder must complete both identical builds, ZIP validation, checksum
   generation, and its clean standalone install/``pip check``/help/version/
   uninstall smoke test before copying either local artifact to ``dist/``.
#. Install that exact wheel into the real standalone target with
   ``python3.14 tools/install_standalone.py install``. Use ``--recreate`` only
   for an explicit migration from a system-site environment or unmanaged
   launcher. Verify ``check_formatting --version`` and at least one complete
   consuming-project ``check_formatting --all`` run. A source-tree dogfood run
   alone does not prove the installed copy was updated.
#. A version, its ignored local wheel, and checksum are a local release. A Git
   tag or a downloadable wheel/checksum attached to a hosting-service release
   is a separate publication channel and is created only when explicitly in
   scope. A "release asset" means such an attached downloadable file; it is
   not required for this repository-local installation model.

*********************
Acceptance criteria
*********************

Before considering a new checker done, demonstrate each of the following
— ideally as tests, not just manual verification:

* ``explicit_files=None``, ``explicit_files=[]``, and a non-empty
  ``explicit_files`` list each produce distinct, correct behavior (full
  scan, "nothing to do", exactly the named files).
* Check, fix, and diff modes agree on the same selection and formatting
  target for a given scope.
* An empty selection returns ``True`` without invoking the backend; a
  missing backend returns ``False`` with a clear ``ERROR:`` line — neither
  ever raises.
* Any diagnostic the checker prints for a failure survives ``--quiet`` and
  is present inside the ``--json`` payload's per-checker ``output``.
* An analysis-only checker (no fix mode) registers ``auto_fix=False``.
* Every new external CLI has a tested version parser and explicit support
  contract in ``_backend_versions.py``; installed-but-unsupported versions
  fail before the backend's real command executes.
* The implementation was written RED (a failing test) before GREEN (the
  checker code) — commit them separately, per ``AGENTS.md``'s own
  granularity convention.

The real dry-run test of this document: a contributor (or a fresh agent
session) implementing a trivial synthetic checker using only this page
plus the existing per-checker source as examples, needing no other
undocumented lookup.
