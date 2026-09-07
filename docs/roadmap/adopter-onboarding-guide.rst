.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Roadmap epic: onboarding guide for a new adopting project — check_formatting project

#############################################
Onboarding guide for a new adopting project
#############################################

:Status: Items 1-5 and 7-9 shipped (2026-09-07). Item 6 is a policy
   decision with no urgency, per its own section below — the only item
   remaining.
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

1. Shipped, in :doc:`../check_formatting`'s new "Getting started" section:
   two complete starter configs, both actually run end to end while
   writing the docs (not just written to look plausible) — a pure Python
   package, and a Meson C++/web/Python project — each demonstrated
   catching a deliberately introduced violation and recovering via
   ``--fix``, plus a third, explicitly illustrative-only CMake/Zephyr
   config shape. Running the Meson example live surfaced a genuine,
   previously undocumented prerequisite: the adapter always passes ``-c
   meson.format``, so a ``meson.format`` file must exist at the project
   root — even empty — or the checker fails immediately with
   ``Configuration file meson.format not found``, regardless of whether
   anything actually needs reformatting; now documented next to
   ``meson format``'s own paragraph. Also includes the gradual-adoption
   guidance for a pre-existing, unmaintained repository: scope the initial
   config to files the project's own authors maintain, establish a clean
   baseline, then broaden deliberately.
2. Shipped, as a new "Continuous integration" section
   (:doc:`../check_formatting`, summarized in README.md): a generic CI job
   example built around the verified findings above, using ``--all``
   (never a bare invocation) to gate a clean checkout; a verified
   Python JSON-consumption script that catches the config-error-bypasses-JSON
   gap rather than calling ``json.loads()`` unconditionally (run against
   three real scenarios — malformed config, a real committed failure, a
   clean repo — not just written to look plausible); and a pre-commit hook
   recommending bare invocation (``pass_filenames: false``,
   ``always_run: true``) over passing matched filenames, with the
   git-scoped-fix trade-off and pre-commit's own stash-during-commit
   behavior (confirmed against `pre-commit's own docs
   <https://pre-commit.com/#pre-commit-during-commits>`_) both explained
   as the reasoning, not just asserted.
3. Shipped, next to ``mypy``'s existing paragraph in
   :doc:`../check_formatting`: it wipes the project-root ``.mypy_cache``
   this wrapper itself manages (not a project's own configured mypy cache
   directory, if that differs), on either a version change or no marker
   being present at all (including the very first run after adopting this
   checker).
4. Shipped, alongside item 1: a "which checkers should I enable" checklist,
   keyed by file type or build system present in the adopting repository,
   inverse of the existing Checkers table.
5. Shipped, in :doc:`../check_formatting`'s "Excluding files" section,
   as a table grouped by verified behavior rather than a uniform checker ×
   mode × selection-mechanism grid — the actual code splits into distinct
   families, not one shared pattern: most checkers (``cpp``, ``cmake``,
   ``json``, ``ini``, ``yaml``, ``shell``, ``vnu``) apply
   ``.formatting-ignore`` in every mode and every selection, including
   ``--all``; ``meson``/``web`` skip it only in check/verbose mode under
   ``--all`` specifically (their single-batched-command path); ``python``/
   ``mypy`` apply it whenever a concrete selection exists but never under
   ``--all`` in any mode; ``rst`` never uses it at all. Each row also names
   the checker's own native alternative alongside the wrapper's exclusion.
6. Decide, not merely document, a compatibility policy for
   ``.check_formatting.toml`` and the ``--json`` payload shape across
   ``check_formatting`` version bumps: what a pre-1.0 breaking change looks
   like, whether/how a migration would be announced, and whether backend
   version bumps (e.g. a new pinned ``vnu`` release) are independent of the
   wrapper's own versioning. This is a decision for Maxime to make, not a
   fact this document can respond to with default a policy for, and it does
   not need to ship in the same pass as the rest of this epic.
7. Shipped: a copyable day-to-day workflow template an adopting project
   can drop into its own ``CONTRIBUTING.md``, including the Ruff
   format/lint interaction found while verifying item 1 (a single
   ``--fix`` pass doesn't always converge — a lint fix can reintroduce a
   formatting issue only a second ``ruff format`` pass corrects) as the
   concrete reason the template says "verify clean, re-run ``--fix`` if
   not" rather than assuming one pass is always enough.
8. Shipped, as the "First-time setup: baseline broad, then narrow" section:
   the vnu epic's own recipe generalized to any checker, with the
   gradual-adoption caveat from item 1's finding folded in, and the vnu
   recipe kept as its cited worked example.
9. Shipped: a short backend-entry-point table — one supported install
   route per backend, pointing back at the existing fuller paragraph —
   rather than a full apt/brew/pip/npm matrix maintained for every
   backend.

Pure documentation — no production code or config-schema change for items
1-5 and 7-9, so no TDD cycle applied to those, matching item 1 of the vnu
epic. Item 6 is a policy decision, not a documentation task, and remains
the one open item — it should not be scheduled as if it were equally
cheap, and has no urgency forcing it into any particular pass.

************************
Recommended sequencing
************************

Codex's review of both roadmap epics together recommended prioritizing
this epic's tested onboarding baseline and CI example ahead of the sibling
:doc:`new-checker-architecture-guide` epic's corrected walkthrough, with
additional recipes and reference tables after both — adopted: items 2, 3,
and 5 shipped first, the architecture guide shipped as
:doc:`../architecture` next, and items 1, 4, 7, 8, and 9 shipped together
in this final pass, in that order (1 and 9 as the worked examples the rest
build on, 4/7/8 following naturally once those examples existed). Item 6
(the compatibility policy decision) remains open, with no dependency on
anything shipped and no urgency forcing it into this or any pass —
schedule it whenever Maxime is ready to commit to an answer.

**************
Out of scope
**************

Building a `check_formatting`-specific CI product (a GitHub Action, a
hosted dashboard, etc.) — the CI-integration item above is a documentation
example a project author copies and adapts, not a new maintained artifact.
