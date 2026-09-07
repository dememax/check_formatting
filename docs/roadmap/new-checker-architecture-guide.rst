.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Roadmap epic: architecture guide for implementing a new checker — check_formatting project

###################################################
Architecture guide for implementing a new checker
###################################################

:Status: Proposed.
:Source: A cold-reader review of this project's own documentation
   (README.md, :doc:`../check_formatting`, AGENTS.md) from the perspective
   of a contributor about to implement a fifteenth checker, done in this
   session (2026-09-07) while extending the ``vnu`` adapter for the
   :doc:`vnu-message-suppression-ergonomics` epic.
:Versions involved: ``check_formatting`` 0.3.0

*********
Summary
*********

``check_formatting``'s per-checker *reference* documentation (the Checkers
table, the per-backend paragraphs, the git-scoped-fix tiers) is thorough and,
as this session's own work repeatedly confirmed, accurate. But nothing
documents the *internal contract* a new checker must satisfy: no
``CONTRIBUTING.md``, no architecture document, not even a "read this file as
a worked example" pointer. A search for "architecture", "new checker",
"adding a checker", "extend", or "contribut" across README.md, AGENTS.md,
CLAUDE.md, and both ``docs/*.rst`` returns zero hits. The only path
available to an implementor today is: find the most structurally similar
existing ``_check_X`` function, read it, and copy its shape — exactly what
whoever added ``vnu`` must have done, and exactly the exercise that, one
level down, surfaced Findings 1-3 of the vnu epic (undocumented,
silently-failing contracts in a *backend's* CLI). This epic is that same
observation applied to ``check_formatting``'s own internals: undocumented,
easy-to-get-wrong contracts, just one layer further in.

****************************
Evidence from this session
****************************

While implementing item 2 of :doc:`vnu-message-suppression-ergonomics`
(promoted from a stretch idea to shipped code), an early draft of that
epic asserted that appending a diagnostic to ``_check_vnu`` would require
switching away from live-streamed subprocess output, trading away
real-time terminal feedback. That claim was wrong, and only caught by
reading ``cli.__init__``'s ``run_one``/``_ThreadLocalStdout`` directly:
every checker's output is already fully buffered per-thread and printed
only once that checker's subprocess has finished, for every mode, even a
single-checker run. Nothing states this anywhere outside that one
docstring. A full source read, in the same session that had just spent
several passes forensically verifying a *different* tool's CLI, still
produced a wrong first guess about this project's own internals — good
evidence that a contributor without that context would fare no better,
and probably worse.

**********************
Cold-reader findings
**********************

Reading ``_registry.py``, ``_config.py``, ``_checkers.py``,
``_selection.py``, and ``_subprocess.py`` end to end surfaces a consistent,
well-applied, but entirely undocumented contract:

=====================================
The three-file registration surface
=====================================

Adding a checker touches three files, each a different kind of edit:
``_config.py`` (a ``(section, key)`` tuple added to ``_CONFIG_FIELDS``, a
``ProjectConfig`` field, and the actual TOML-parsing logic),
``_registry.py`` (a ``Checker(label, fn, kwargs_fn, fix_command_fn,
auto_fix)`` entry plus an import), and ``_checkers.py`` (the ``_check_X``
function itself). The ``Checker`` ``NamedTuple``'s own docstring narrates
*why* this used to be three separately hand-synced tables that silently
drifted — a real lesson from this project's own history, invisible until a
contributor happens to read that one class's docstring. ``_CONFIG_FIELDS``/
``_CONFIG_SECTIONS`` in ``_config.py`` is a second, separate instance of the
exact same "one shared table, not several hand-synced ones" pattern,
undocumented as such — nothing points out that this table exists for the
same reason and must be extended the same way.

=====================================
The checker function's own contract
=====================================

Every ``_check_X`` shares a positional signature (``root, fix, diff,
verbose, ignore_patterns, explicit_files, quiet, **kwargs`` returning
``bool``), resolves its backend via bare ``shutil.which`` and prints a
specific ``"  ERROR: <tool> not found — ..."`` shape when absent, and must
dispatch subprocesses only through ``cli._run``/``cli._run_capture_merged``
— never raw ``subprocess`` — to stay compatible with concurrent dispatch.
None of this is written down outside the existing checkers themselves.

==============================
The output/concurrency model
==============================

``_ThreadLocalStdout`` buffers every checker's ``print()``/``log()`` output
per-thread during concurrent dispatch and releases it only once that
checker's subprocess has finished — true for every mode, even a
single-checker run. ``cli._run`` (one subprocess, "streamed" in the sense
of writing line-by-line, though never actually reaching the real terminal
before the checker finishes) and ``cli._run_capture_merged`` (for a checker
that itself runs multiple subprocesses concurrently, avoiding interleaved
output) are two different tools for two different situations, and nothing
states when to reach for which. Separately, ``print()`` (survives
``--quiet``, reaches ``--json``'s captured output) versus ``_make_log(quiet)``
(gated chrome) is a real, load-bearing convention, discoverable only by
noticing that the pre-existing missing-backend ``ERROR:`` line already uses
plain ``print()``.

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

==============================
The two-tier test convention
==============================

Every checker in ``tests/`` gets a mocked-backend file (dispatch-logic
tests) and, when a real backend is installed, an ``_integration.py`` file
(real-backend tests, ``pytest.mark.skipif`` when absent) — a real,
consistent pattern, stated only as a general principle in AGENTS.md's TDD
section ("mock the backend... prefer a real, hermetic reproduction..."),
never as "every checker gets exactly these two files."

===================
No worked example
===================

Nothing points a new contributor at ``vnu`` — the simplest checker in the
registry (analysis-only, no fix mode, two config keys) — as the reference
implementation to read end-to-end, even though it would shortcut most of
the above for free.

***************
Proposed work
***************

Write a single architecture/contributor document (``CONTRIBUTING.md`` or
``docs/architecture.rst``, linked from both README.md and AGENTS.md) with:

1. A concepts section naming the five internal modules
   (``_config``/``_registry``/``_checkers``/``_selection``/``_subprocess``)
   and each one's single responsibility, mirroring their own module
   docstrings but tying them together as one picture instead of five
   separate ones a reader must assemble themselves.
2. The checker function contract, spelled out explicitly: shared
   signature, ``shutil.which`` + the standard missing-backend error shape,
   ``print()`` vs. ``log()`` and why, always dispatching through
   ``cli._run``/``cli._run_capture_merged``.
3. The output/concurrency model, stated as fact rather than left to be
   rediscovered: every checker's output is fully buffered before printing,
   for every mode, including a single-checker run; when to reach for
   ``_run`` versus ``_run_capture_merged``.
4. A "adding a checker, step by step" walkthrough using ``vnu`` as the
   running worked example: the exact edits to ``_config.py``,
   ``_registry.py``, and ``_checkers.py``, in order, cross-referencing each
   real edit vnu's own addition made.
5. The two-tier testing pattern, named explicitly as a requirement:
   one mocked-dispatch test file, one real-backend
   ``test_check_formatting_<name>_integration.py`` file skipped when the
   backend is absent.
6. A pointer to the selection-helper library in ``_selection.py`` with
   one sentence per helper on when it's the right choice.

Pure documentation — no production code or config-schema change, so no TDD
cycle applies, matching item 1 of the vnu epic. Verification is a
dry-run: a future contributor (or a fresh agent session) implementing a
trivial synthetic checker using only this new document plus the existing
per-checker examples, needing no other undocumented lookup, is the
acceptance bar.

************************
Recommended sequencing
************************

No dependency on the vnu epic's own remaining items (native-argument
policy, ``ignore_messages``) — this can proceed independently, at any
time. Worth doing before the next new checker is actually added, since
that is exactly the moment this gap turns into either a slow,
copy-and-hope implementation or a set of new, undocumented conventions
invented ad hoc rather than reusing the ones already established.

**************
Out of scope
**************

Rewriting or restructuring the five internal modules themselves — this
epic documents the architecture as it stands, which this session found to
be sound and consistently applied; the gap is purely that it is
undocumented, not that it is wrong.
