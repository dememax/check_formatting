.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Roadmap epic: onboarding guide for a new adopting project — check_formatting project

#############################################
Onboarding guide for a new adopting project
#############################################

:Status: Proposed.
:Sources: A cold-reader review of this project's own documentation
   (README.md, :doc:`../check_formatting`) from the perspective of a new
   project author adopting ``check_formatting`` for the first time, done in
   the session that produced this epic (2026-09-07) alongside the sibling
   :doc:`new-checker-architecture-guide` epic; a second review by Codex
   against this epic's first version (2026-09-07), which reproduced several
   CI/first-run edge cases directly against the installed tool and found the
   proposed CI/exclusion examples would have shipped materially incomplete
   or misleading. This revision folds those corrections in directly.
:Versions involved: ``check_formatting`` 0.3.0

*********
Summary
*********

``check_formatting``'s per-checker *reference* documentation (the Checkers
table, the per-backend paragraphs, the file-selection and git-scoped-fix
tables) is accurate and precise. But it answers "what does checker X do"
without ever answering "how do I, starting from a blank repository, reach a
good ``.check_formatting.toml``, a CI-integrated setup that actually
catches something, and a workflow my own contributors will follow." That
synthesis gap is real — but, per this revision's second review, the
concrete examples this epic proposes to fill it need real behavioral
verification before they ship, not just prose: an under-specified CI
example would teach adopters to build a CI check that silently never runs.

****************************
Evidence from this session
****************************

The :doc:`vnu-message-suppression-ergonomics` epic is itself a case study
of this gap for one single checker: a real adopter (``sagui``) had to
discover, under real usage pressure, the correct order of operations
(baseline broad, review every finding, fix genuine issues, accept one
specific finding, re-verify broad) because nothing generalized that
discipline ahead of time. That recipe is now written down — but only for
``vnu``.

This revision's own verification surfaced a second, more urgent instance of
the same shape, in the exact area this epic proposes to fix: reproduced
directly, on a clean git checkout with a syntax-broken Python file already
committed —

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Invocation
     - Result
   * - ``check_formatting --json``
     - Exit 0; ``"checks": []``, ``overall_ok: true`` — the syntax error is
       never even selected
   * - ``check_formatting --all --json``
     - Exit 1; the real syntax error reported

A bare invocation selects files changed since ``HEAD`` plus untracked
files — on a freshly cloned or freshly committed checkout, that set is
empty by definition, so the command trivially reports success. A CI
example that doesn't lead with this fact would teach adopters to wire up a
check that never actually runs on a clean build. See "No CI-integration
story" below for the full corrected requirement.

**********************
Cold-reader findings
**********************

=====================================
No starter configs by project shape
=====================================

README.md's only example config is one abstract cpp+python+mypy snippet.
Nothing shows a complete, realistic ``.check_formatting.toml`` for the
project shapes the documentation itself names as target use cases, and
nothing demonstrates that a shown config actually catches anything — a
valid config that checks zero real violations is not evidence it works.

============================================================================
No CI-integration story, and the obvious first example is wrong by default
============================================================================

No pre-commit hook example, no CI snippet, and no example consuming
``--json``'s payload, despite that flag being explicitly built for machine
consumption. Worse than merely absent: the naive version of this example
(run bare ``check_formatting --json`` in CI) is confirmed **incorrect** —
see "Evidence from this session" above. A second gap in the same area,
also verified this session: a configuration error (missing or malformed
``.check_formatting.toml``) prints plain text and exits 1 even under
``--json`` — it never enters the JSON envelope at all::

   $ check_formatting --json   # malformed .check_formatting.toml
   check_formatting: invalid .check_formatting.toml: Invalid value (at end of document)
   $ echo $?
   1

A CI script that unconditionally pipes stdout into ``json.loads()`` would
crash with a ``JSONDecodeError`` on this path rather than surfacing the
real problem. This project's own repository has no CI workflow either, so
none of this has ever been dogfooded.

========================================================================================
The mypy-cache invalidation behavior is undocumented, and more specific than described
========================================================================================

``_check_mypy`` calls ``_invalidate_mypy_cache_if_version_changed``, which
wipes ``root / ".mypy_cache"`` — the project-root cache directory this
wrapper itself manages, independent of any ``cache_dir`` a project's own
``pyproject.toml``/``mypy.ini`` configures for mypy directly — whenever the
resolved mypy's version differs from a marker recorded there, **or when no
marker is present at all** (first run, or a cache that predates this
check: "treated as a mismatch: wipe once, the safe default", per the
function's own docstring). Real, deliberate, CI-relevant, and currently
discoverable only by reading ``_checkers.py``.

==================================================
No "which checkers should I enable" decision aid
==================================================

An adopter with a mixed-language repository must reverse-map their file
types onto the Checkers table by hand. Nothing goes the other direction:
"you have ``.py`` files → consider ``python``/``mypy``; you have
``CMakeLists.txt`` → consider ``cmake``," etc.

===============================================================================================
``.formatting-ignore``'s exceptions need a selection-scope dimension, not just checker × mode
===============================================================================================

The current text ("Meson and Web ... `.formatting-ignore` applies to them
only in diff, fix, and explicit-file modes") is incomplete, not wrong, and
this revision corrects the axis rather than just the wording. Reading
``_check_web`` directly: its per-file, ignore-pattern-respecting selection
path triggers whenever ``fix or diff or explicit_files is not None`` — and
the default, git-auto-detected scope (bare ``check_formatting``, no
``--all``) *already populates* ``explicit_files`` with the changed-file
list before calling any checker. So ``.formatting-ignore`` **does** apply
in ordinary check/verbose mode too, as long as the invocation is
git-auto-detected or truly explicit (``-- FILE``); it is specifically
``--all`` (which passes ``explicit_files=None`` to force a full glob scan)
that hits the single-batched-command path where per-file exclusion is
impossible. The real table needed is **checker × mode × selection
mechanism** (auto-detected / explicit files / ``--all``), not checker ×
mode alone, with each checker's native ignore mechanism (``.prettierignore``,
``pyproject.toml``'s Ruff exclude, ``.clang-tidy-ignore``) named alongside
the wrapper's own exclusions rather than only as an aside.

======================================================================
Compatibility policy is a decision to make, not a fact to write down
======================================================================

Nothing states whether the config schema, or the ``--json`` payload shape,
is considered stable across ``check_formatting`` version bumps, what a
pre-1.0 breaking change looks like, or whether a backend-version bump
(e.g. a new ``vnu`` release) is independent of the wrapper's own
versioning. Unlike the mypy-cache finding above (a fact about existing
code, just undocumented), this is not something to merely document — it
requires Maxime to actually adopt a policy first. This host's own
``check_formatting`` 0.2.0 → 0.3.0 upgrade in this session is a concrete
instance of the open question: nothing currently promises what would or
would not have broken a pinning consumer.

================================================
No adopter-facing day-to-day workflow template
================================================

AGENTS.md prescribes an exact discipline for this project's *own*
contributors (run before every commit; ``--fix`` then verify clean; never
commit with outstanding violations) but offers nothing an adopting
project's author could copy into their own ``CONTRIBUTING.md`` — despite
that discipline being entirely generic, not specific to developing
``check_formatting`` itself.

===================================================
No generalized "verify your first setup" guidance
===================================================

The vnu epic's adoption recipe ("baseline broad, review real findings,
don't suppress anything unread") is exactly the right first-time-setup
discipline for *every* checker, not only ``vnu`` — but it was only ever
written down once, ad hoc, in that one epic. For a repository with
existing, unmaintained, or vendored/generated content, "baseline broad"
needs an explicit caveat: start from the maintained files a project's
authors actually own, establish a clean baseline there, and expand
deliberately — "broad" should not silently mean "every vendored or
generated file, indiscriminately," which the vnu recipe's own single-project
context never had to address.

================================================================================
An exhaustive backend-install matrix is more maintenance than an adopter needs
================================================================================

Each backend's install command (``apt``, ``brew``, ``pip``, ``npm``) is
correct but scattered across roughly a dozen separate paragraphs. This
revision no longer proposes a full apt×brew×pip×npm matrix for every
backend in the main guide — keeping four install variants current per
backend is a maintenance burden disproportionate to the value, and the
existing per-backend paragraphs already carry the detail. A short table
naming one supported route per backend, linking to the fuller paragraph,
is enough for a first-time entry point.

***************
Proposed work
***************

Add a "Getting started" section (README.md, expanded in
:doc:`../check_formatting`) covering:

1. Two or three complete starter configs for the project shapes the
   documentation already names as target use cases. Each must be
   demonstrated, not just valid: include the native/non-TOML prerequisites
   it actually depends on (running from the project root; Python 3.14 on
   ``PATH``; ``npm install`` for Prettier-backed checkers; a built/rendered
   output directory for a checker like ``vnu`` that validates generated
   HTML), and show it catching one deliberately introduced violation, not
   only passing cleanly. For a repository with pre-existing, unmaintained
   content, show the gradual-adoption path: scope the initial config to
   files the project's own authors maintain, establish a clean baseline,
   then broaden deliberately — not "point globs at everything, including
   vendored or generated trees, on day one."
2. A CI-integration example built around the verified findings above, not
   the naive version: use ``--all`` (or explicit files) for any CI job
   meant to gate a clean checkout — a bare invocation measures
   working-tree changes, not the commit under test, and silently passes
   with nothing selected otherwise. Show a pre-commit hook alongside it,
   with two decisions made explicitly rather than left implicit: whether
   the hook passes it the staged filenames (which changes checkers' native
   git-scoped-fix behavior — explicit files bypass the auto-detected-scope
   optimizations some checkers use) or lets ``check_formatting`` do its own
   git-aware selection, and a note that pre-commit itself temporarily
   stashes unstaged changes during a hook run (see `pre-commit's own docs
   <https://pre-commit.com/#pre-commit-during-commits>`_) — a partially
   staged file is worth testing explicitly, not assumed to behave like a
   fully staged one. Show ``--json`` consumed by a script, including
   handling the confirmed gap: a configuration error prints plain text and
   exits 1 without ever producing JSON, so a consuming script must check
   the exit status (or catch a JSON decode failure) before assuming
   parseable output, not call ``json.loads()`` unconditionally.
3. Document the mypy-cache invalidation behavior precisely next to
   ``mypy``'s existing paragraph: it wipes the project-root
   ``.mypy_cache`` this wrapper itself manages (not a project's own
   configured mypy cache directory, if that differs), on either a version
   change or no marker being present at all (including the very first run
   after adopting this checker) — relevant to any CI cache configuration
   keying on that directory.
4. A "which checkers should I enable" checklist, keyed by file type or
   build system present in the adopting repository, inverse of the
   existing Checkers table.
5. Rebuild the ``.formatting-ignore`` exceptions as one **checker × mode ×
   selection-mechanism** table (auto-detected / explicit files / ``--all``),
   correcting the current checker × mode framing, and name each checker's
   native ignore mechanism alongside the wrapper's own exclusion options
   rather than only as an aside.
6. Decide, not merely document, a compatibility policy for
   ``.check_formatting.toml`` and the ``--json`` payload shape across
   ``check_formatting`` version bumps: what a pre-1.0 breaking change looks
   like, whether/how a migration would be announced, and whether backend
   version bumps (e.g. a new pinned ``vnu`` release) are independent of the
   wrapper's own versioning. This is a decision for Maxime to make, not a
   fact this document can respond to with default a policy for, and it does
   not need to ship in the same pass as the rest of this epic.
7. A copyable day-to-day workflow template an adopting project can drop
   into its own ``CONTRIBUTING.md``, generalizing AGENTS.md's own
   before-every-commit discipline into project-agnostic language.
8. Generalize the vnu epic's "baseline broad, review, then narrow" recipe
   into first-time-setup guidance that applies when enabling *any*
   checker, including the gradual-adoption caveat for legacy repositories
   from the finding above, with the vnu recipe kept as its worked example.
9. A short backend-entry-point table — one supported install route per
   backend, linking to the existing fuller paragraph — rather than a full
   apt/brew/pip/npm matrix maintained for every backend.

Pure documentation — no production code or config-schema change for items
1-5 and 7-9, so no TDD cycle applies to those, matching item 1 of the vnu
epic. Item 6 is a policy decision, not a documentation task, and should not
be scheduled as if it were equally cheap.

************************
Recommended sequencing
************************

Codex's review of both roadmap epics together recommended prioritizing
this epic's tested onboarding baseline and CI example ahead of the sibling
:doc:`new-checker-architecture-guide` epic's corrected walkthrough, with
additional recipes and reference tables after both — adopted here. Within
this epic: item 2 (the CI/pre-commit example) is now the highest-value,
highest-risk-if-wrong piece, given this revision's own findings about what
a naive version would have shipped — do it first, and verify each claimed
behavior the way this revision did rather than trusting prose alone. Items
3 and 5 are cheap, standalone, already-verified facts, worth shipping
alongside it. Items 1 and 9 follow naturally from item 2's own worked
examples. Item 8 depends on item 1 existing. Item 6 (the compatibility
policy decision) has no dependency on the rest and no urgency forcing it
into this pass — schedule it whenever Maxime is ready to commit to an
answer, not as a checkbox alongside the documentation items.

**************
Out of scope
**************

Building a `check_formatting`-specific CI product (a GitHub Action, a
hosted dashboard, etc.) — the CI-integration item above is a documentation
example a project author copies and adapts, not a new maintained artifact.
