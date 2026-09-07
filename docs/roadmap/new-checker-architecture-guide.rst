.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Roadmap epic: architecture guide for implementing a new checker — check_formatting project

###################################################
Architecture guide for implementing a new checker
###################################################

:Status: Proposed.
:Sources: A cold-reader review of this project's own documentation
   (README.md, :doc:`../check_formatting`, AGENTS.md) from the perspective
   of a contributor about to implement a fifteenth checker, done in the
   session that produced this epic (2026-09-07) while extending the ``vnu``
   adapter for the :doc:`vnu-message-suppression-ergonomics` epic; a second
   review by Codex against this epic's first version (2026-09-07), which
   corrected several of its own claims about the codebase after running 41
   focused tests and reading the actual dispatcher, package, and test-suite
   structure. This revision folds in Codex's corrections directly rather
   than listing them as a separate errata section — the previous version's
   inaccuracies are simply gone.
:Versions involved: ``check_formatting`` 0.3.0

*********
Summary
*********

``check_formatting``'s per-checker *reference* documentation (the Checkers
table, the per-backend paragraphs, the git-scoped-fix tiers) is thorough and
accurate. But nothing documents the *internal contract* a new checker must
satisfy: no ``CONTRIBUTING.md``, no architecture document, not even a "read
this file as a worked example" pointer. A search for "architecture", "new
checker", "adding a checker", "extend", or "contribut" across README.md,
AGENTS.md, CLAUDE.md, and both ``docs/*.rst`` returns zero hits. The only
path available to an implementor today is: find the most structurally
similar existing ``_check_X`` function, read it, and copy its shape — the
findings below are what that reading actually reveals, corrected once
against a second, independent read rather than shipped as first-draft
guesses.

****************************
Evidence from this session
****************************

While implementing item 2 of :doc:`vnu-message-suppression-ergonomics`,
this epic's first draft asserted that appending a diagnostic to
``_check_vnu`` would require switching away from live-streamed subprocess
output. That claim was wrong on its own terms (corrected in that epic
already), but it is also the wrong frame for this one: the *user-facing*
behavior — checkers run concurrently, nothing is printed interleaved,
README.md and :doc:`../check_formatting` both describe this in a dedicated
section — is already documented, accurately. What is missing is not "is
concurrency documented" but "is the *contributor-facing implementation
mechanism* documented": the thread-local output buffer, when a checker must
capture its own subprocess output instead of writing to ``sys.stdout``
directly, and the precise ordering guarantee (see below). Getting the
framing itself wrong on a first pass, while already deep in this exact
codebase, is the best evidence this epic has that a contributor without
that context needs it written down.

**********************
Cold-reader findings
**********************

Reading ``cli/__init__.py``, ``_registry.py``, ``_config.py``,
``_checkers.py``, ``_selection.py``, ``_subprocess.py``, and ``_prettier.py``
end to end, together with ``tests/test_check_formatting_cli_package_imports.py``
(which documents a real convention no other file states), surfaces a
consistent, well-applied, but under-documented contract:

==================================================
The package entry point and re-export convention
==================================================

``check_formatting.cli`` is a *package*, not a flat module:
``__init__.py`` (the dispatch loop, CLI entry point, and re-exports) plus
``_config``, ``_selection``, ``_subprocess``, ``_prettier``, ``_checkers``,
and ``_registry``. Cross-submodule calls to any name a test might
monkeypatch on the package (``_run``, ``_print_tool_info``, ...) go through
``from check_formatting import cli`` followed by a deferred
``cli.<name>(...)`` attribute lookup, never a plain
``from ._subprocess import _run`` — the latter binds at import time and
would silently stop observing a patch applied to the package later.
``tests/test_check_formatting_cli_package_imports.py`` states this
precisely and pins it down with cold-interpreter import tests; nothing
outside that one test file explains it, and a new checker written with a
direct submodule import would work today and only fail once a test tried
to monkeypatch it.

Adding a checker still edits exactly three files — corrected back from
this epic's own second revision, which briefly claimed a fourth:
``_config.py`` (a ``(section, key)`` tuple added to ``_CONFIG_FIELDS``, a
``ProjectConfig`` field, the TOML-parsing logic), ``_registry.py`` (a
``Checker(label, fn, kwargs_fn, fix_command_fn, auto_fix)`` entry plus an
import), and ``_checkers.py`` (the ``_check_X`` function itself).
``cli/__init__.py`` needs no edit at all: it imports ``_CHECKERS`` once
from ``_registry.py`` and re-exports it in ``__all__``, both already done
and shared by reference, so a new dict entry in ``_registry.py`` is visible
to ``run_one``'s dispatch immediately. What a contributor *does* need to
understand about ``cli/__init__.py``, without editing it, is the re-export
convention above — the ``Checker`` ``NamedTuple``'s own docstring narrates
*why* ``_registry.py`` used to be three separately hand-synced tables that
silently drifted, a real lesson from this project's own history, invisible
until a contributor happens to read that one class's docstring.
``_CONFIG_FIELDS``/``_CONFIG_SECTIONS`` in ``_config.py`` is a second,
separate instance of the exact same "one shared table, not several
hand-synced ones" pattern, undocumented as such.

=====================================
The checker function's own contract
=====================================

Corrected from this epic's first draft: the dispatcher (``run_one`` in
``cli/__init__.py``) calls every checker with exactly six shared
*positional* arguments (``root, fix, diff, verbose, ignore_patterns,
explicit_files``), then ``quiet`` and every checker-specific option **by
keyword** (``quiet=..., **_checker_kwargs(name, config, ...)``). ``quiet``
is not part of a shared positional prefix — each ``_check_X`` places it
wherever suits that function's own signature (sometimes right after
``explicit_files``, sometimes after its checker-specific parameters,
sometimes past a ``*,`` keyword-only marker alongside ``git_auto_detected``)
and it works only because the call site always passes it by name.

Backend resolution and subprocess dispatch are two separate, *required
outcomes*, each with more than one legitimate implementation already in
use — document the outcome, then show the patterns as examples, not as the
one true mechanism:

* Outcome: a missing backend fails cleanly, not with a traceback. Ten
  of the fourteen checkers pre-check with a bare ``shutil.which`` call and
  print a specific ``"  ERROR: <tool> not found — ..."`` line; the rest
  (``cpp``, ``web``, ``meson``) rely on ``_run``/``_fmt_stdout``'s own
  ``FileNotFoundError`` handling (both already catch it and print
  ``"ERROR: command not found: ..."``), letting the subprocess call itself
  fail cleanly instead of pre-checking. Both are legitimate; a new checker
  can use whichever fits its own control flow.
* Outcome: subprocess dispatch stays compatible with concurrent
  dispatch. There are *three* legitimate helpers, not two: ``cli._run``
  (streams a single subprocess's output line-by-line — see the
  output/concurrency model below for what "streams" actually means during
  concurrent dispatch), ``cli._run_capture_merged`` (one subprocess,
  stdout+stderr merged, captured rather than written — used when a checker
  itself runs several subprocesses concurrently, or needs to inspect output
  before deciding what to print), and ``cli._fmt_stdout`` (captures only
  stdout, optionally feeding stdin — used for diff-mode previews and
  Prettier's canonical-equivalence check in ``_prettier.py``). Never call
  raw ``subprocess`` directly from a checker.

Separately, ``print()`` (survives ``--quiet``, reaches ``--json``'s
captured output) versus ``_make_log(quiet)`` (gated chrome) is a real,
load-bearing convention, discoverable only by noticing that the
pre-existing missing-backend ``ERROR:`` line already uses plain ``print()``.

==============================
The output/concurrency model
==============================

README.md and :doc:`../check_formatting` already document the user-facing
behavior — every checker runs concurrently, output prints in ``--checks``
order rather than completion order, ``--fail-fast`` shortens the report but
not the work. What neither states, because neither is written for a
contributor, is the mechanism and its consequences for a checker
implementation:

* ``_ThreadLocalStdout`` gives each dispatched checker's *own* worker
  thread a private ``io.StringIO`` buffer for the duration of concurrent
  dispatch; a thread that never registers (the main thread) falls straight
  through to the real ``sys.stdout``.
* The main thread's own dispatch loop iterates ``checks`` **in configured
  order**, blocking on ``futures[name].result()`` for each name in turn and
  printing that checker's banner plus its buffered output immediately once
  that future resolves — it does **not** wait for every checker to finish
  before printing anything. A checker earlier in ``--checks`` order that
  finishes slowly still gates when a faster, already-finished checker
  later in the list gets printed, since the loop only reaches it after
  the earlier one's turn — this is why checker order in the list is worth
  choosing deliberately, and why **checker order is not dependency order**:
  nothing in the dispatcher expresses or enforces one checker's targets
  depending on another's having already run.
* A checker that itself spawns internal worker threads (``kconfig``'s
  per-combo builds, the Prettier best-effort fixer's per-file concurrency)
  cannot rely on those inner threads inheriting the outer thread's
  registered buffer — ``_ThreadLocalStdout`` is genuinely per-OS-thread.
  The existing pattern avoids the problem entirely rather than solving it:
  inner threads never call ``print()``/``sys.stdout.write`` at all: they
  run ``cli._run_capture_merged`` (which captures via
  ``subprocess.run(..., stdout=PIPE)``, independent of ``sys.stdout``), and
  only the *outer*, already-registered checker thread writes the captured
  text out, once each inner future resolves. A new checker adding its own
  internal concurrency should copy this pattern, not attempt to register
  the inner threads with the outer mux directly.
* ``--fail-fast`` does not cancel other checkers — every checker was
  already submitted before the loop starts consuming results, and Python
  cannot safely kill a thread mid-flight, so every checker keeps running to
  completion regardless; ``--fail-fast`` only shortens what gets printed
  and included in the payload.
* A checker with its own internal concurrency needs to account for
  overlapping reads/writes and shared state the same way ``kconfig`` already
  documents for itself: combos sharing a build directory race, so each
  needs its own isolated build state if run concurrently.

==============================
The selection-helper library
==============================

``_selection.py`` exposes ``_select_explicit_from_globs``, ``_filter_files``,
``_filter_configured_targets``, ``_report_empty_selection``, and
Git-hunk-range helpers. Composing the right one for a new checker's
selection semantics (glob-matched, fixed file domain, or whole-project) has
no guidance beyond "find a checker that looks similar and copy it."

===================================================
The git-scoped-fix contract's implementation side
===================================================

README/docs document the *outcome* of the native/best-effort/none tiers
precisely (the tables both files share). Nothing documents how to
*implement* the best-effort tier — the reformat/diff/merge/re-verify
algorithm lives in ``_prettier.py`` — or when a new checker's backend
characteristics make it worth attempting versus settling for whole-file.

================================================================
The testing pattern is real but not yet a strict two-file rule
================================================================

Corrected from this epic's first draft, which overstated this as an
established convention: only ``shell`` and ``vnu`` currently have a
dedicated ``test_check_formatting_<name>_integration.py`` file
(``pytest.mark.skipif`` when the real backend is absent). Every other
checker's real-backend coverage, where it exists, is mixed directly into
its main test file alongside mocked-dispatch tests — ``web``'s and
``yaml``'s test files, for example, both call real ``npx prettier`` next to
tests that monkeypatch ``_run``. The underlying principle **is** real and
worth stating (AGENTS.md's TDD section already names it in general terms:
mock the backend for dispatch-logic tests, use a real, hermetic
reproduction for backend-behavior tests) — but "every checker gets exactly
two files, one named ``_integration.py``" would be a **new** contributor
policy this guide proposes, not a description of current practice, and
should be labeled as such rather than presented as already-established.

===================
No worked example
===================

Nothing points a new contributor at ``vnu`` — the simplest checker in the
registry (analysis-only, no fix mode, two config keys) — as a first
reference implementation, even though it would shortcut most of the above
for free. ``vnu``'s contract is also simpler than most: a new contributor
generalizing from it alone would miss everything about ``--fix``/``--diff``
mode handling and native git-scoping. The guide should pair it with one
formatter/fixer example (e.g. ``cpp`` for a checker with native git-scoped
fix, or ``python`` for one with concurrent format+lint dispatch) so a
reader sees both a report-only and a mutating checker before generalizing.

***************
Proposed work
***************

Write a single architecture/contributor document (``CONTRIBUTING.md`` or
``docs/architecture.rst``, linked from both README.md and AGENTS.md) with:

1. A concepts section naming the package's modules
   (``__init__``/``_config``/``_registry``/``_checkers``/``_selection``/
   ``_subprocess``/``_prettier``) and each one's single responsibility,
   mirroring their own module docstrings but tying them together as one
   picture instead of seven separate ones a reader must assemble
   themselves — including the package-level re-export convention
   (``from check_formatting import cli`` + deferred ``cli.<name>(...)``
   attribute access) and why it exists.
2. The checker function contract, spelled out explicitly: the six shared
   positional arguments plus ``quiet``/checker-specific options by keyword;
   the *outcomes* required of backend resolution and subprocess dispatch,
   each with its legitimate implementation options (``shutil.which``
   pre-check vs. relying on ``_run``/``_fmt_stdout``'s own
   ``FileNotFoundError`` handling; ``_run`` vs. ``_run_capture_merged`` vs.
   ``_fmt_stdout``); ``print()`` vs. ``log()`` and why.
3. The output/concurrency model, stated precisely: checker order is
   configured-list order, not completion order and not dependency order;
   a checker's output prints once its own future resolves, gated by
   whichever earlier-listed checker is still running; nested internal
   concurrency must avoid writing to ``sys.stdout`` from inner threads,
   using the capture-then-write-from-the-outer-thread pattern
   ``kconfig``/``_prettier.py`` already establish; ``--fail-fast`` never
   cancels other checkers.
4. A "adding a checker, step by step" walkthrough using ``vnu`` as the
   primary worked example (paired with one mutating/git-scoped example,
   per the finding above) — the exact edits to ``_config.py``,
   ``_registry.py``, and ``_checkers.py``, in order, cross-referencing each
   real edit ``vnu``'s own addition made, noting that ``cli/__init__.py``
   needs no edit at all, ending with the RED tests written before the
   implementation that makes them pass.
5. The two kinds of test evidence this project's TDD policy already asks
   for — mocked dispatch-logic tests and real-backend behavior tests —
   named explicitly, with the ``shell``/``vnu`` ``_integration.py`` split
   shown as one way to organize them and the web/yaml mixed-file approach
   shown as the other; if this guide chooses to require one dedicated
   ``_integration.py`` file per checker going forward, label that
   explicitly as a new policy this document introduces, not an existing
   rule it's merely writing down.
6. A pointer to the selection-helper library in ``_selection.py`` with
   one sentence per helper on when it's the right choice.

Pure documentation — no production code or config-schema change, so no TDD
cycle applies, matching item 1 of the vnu epic. Acceptance criteria for the
eventual document, verified by a dry run — a future contributor (or a
fresh agent session) implementing a trivial synthetic checker using only
this document plus the existing per-checker examples, needing no other
undocumented lookup — should include demonstrating:

* ``explicit_files=None``, ``explicit_files=[]``, and a non-empty
  ``explicit_files`` list each produce distinct, correct selection
  behavior (full-repo/glob scan, "nothing to do", and exactly the named
  files respectively).
* Check, fix, and diff modes agree on the same selection and formatting
  target for a given scope — none silently diverges from what the others
  would report or apply.
* An empty selection and a missing backend both return cleanly (``True``
  for empty scope, a clear ``False`` plus an ``ERROR:`` line for a missing
  backend), never a traceback.
* Any diagnostic a checker prints for a failure survives ``--quiet`` and is
  present inside the ``--json`` payload's per-checker ``output``.
* An analysis-only checker (no fix mode) registers ``auto_fix=False`` in
  its ``Checker`` entry.
* The implementation itself was written RED (a failing test) before GREEN
  (the checker code), per this project's own TDD policy — the walkthrough
  should show this order, not present finished code first.

************************
Recommended sequencing
************************

No dependency on the vnu epic's own remaining items — this can proceed
independently, at any time. Codex's review of both roadmap epics together
suggested treating the sibling :doc:`adopter-onboarding-guide` epic's
tested CI/baseline example as the higher-priority piece of the two, with
this architecture guide corrected and following it; that ordering is
adopted here rather than contested; see that epic's own sequencing section.
Worth doing before the next new checker is actually added, since that is
exactly the moment this gap turns into either a slow, copy-and-hope
implementation or a set of new, undocumented conventions invented ad hoc
rather than reusing the ones already established.

**************
Out of scope
**************

Rewriting or restructuring the package's internal modules themselves —
this epic documents the architecture as it stands, which this session
(across two independent reviews) found to be sound and consistently
applied; the gap is purely that it is undocumented, not that it is wrong.
