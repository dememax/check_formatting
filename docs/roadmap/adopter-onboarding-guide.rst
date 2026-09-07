.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Roadmap epic: onboarding guide for a new adopting project — check_formatting project

#############################################
Onboarding guide for a new adopting project
#############################################

:Status: Proposed.
:Source: A cold-reader review of this project's own documentation
   (README.md, :doc:`../check_formatting`) from the perspective of a new
   project author adopting ``check_formatting`` for the first time, done in
   this session (2026-09-07) alongside the sibling
   :doc:`new-checker-architecture-guide` epic.
:Versions involved: ``check_formatting`` 0.3.0

*********
Summary
*********

``check_formatting``'s per-checker *reference* documentation (the Checkers
table, the per-backend paragraphs, the file-selection and git-scoped-fix
tables) is accurate and precise — nothing found while reading it as a cold
adopter turned out to be wrong. But it answers "what does checker X do"
without ever answering "how do I, starting from a blank repository, reach a
good `.check_formatting.toml`, a CI-integrated setup, and a workflow my own
contributors will actually follow." That is a synthesis gap sitting one
level above the reference, the same shape as the sibling
:doc:`new-checker-architecture-guide` epic's finding for implementors, just
at the adopter's altitude instead.

****************************
Evidence from this session
****************************

The :doc:`vnu-message-suppression-ergonomics` epic is itself a case study of
this exact gap for one single checker: a real adopter (``sagui``) had to
discover, under real usage pressure, the correct order of operations
(baseline with ``--all`` and no filters, review every finding, fix genuine
issues, accept one specific finding by its complete message text, then
re-verify ``--all``) because nothing generalized that discipline ahead of
time. That recipe is now written down — but only for ``vnu``. Nothing tells
a first-time adopter to apply the same discipline to *any* checker before
narrowing its scope or accepting a finding.

Reading ``_checkers.py`` directly (the same pass that produced the sibling
epic) surfaced a second, previously undiscussed instance of the same
pattern: ``_check_mypy`` calls
``_invalidate_mypy_cache_if_version_changed``, which silently wipes a
project's ``.mypy_cache/`` whenever the *resolved mypy's own version*
changes — a real, deliberate safety behavior with zero mention in
README.md or :doc:`../check_formatting`. A project caching ``.mypy_cache/``
in CI (an entirely standard speedup) would see occasional, unexplained
full-cache rebuilds with no documented reason — the identical shape as
Finding 1 of the vnu epic (a real, intentional behavior with no surfaced
explanation), just for a different backend.

**********************
Cold-reader findings
**********************

=====================================
No starter configs by project shape
=====================================

README.md's only example config is one abstract cpp+python+mypy snippet.
Nothing shows a complete, realistic ``.check_formatting.toml`` for the
project shapes the documentation itself names as the tool's actual use
cases — "a pure Python package," "a Meson/prettier/ruff project," "a
CMake/Zephyr project." An adopter must assemble one by hand from the
Checkers table, one row at a time, with no worked example to check against.

=========================
No CI-integration story
=========================

No pre-commit hook example, no CI snippet, and no example consuming
``--json``'s payload (``summary.failed``, per-checker ``results``) despite
that flag being explicitly built for machine consumption. This project's
own repository has no CI workflow either, so the gap has never been
dogfooded even once.

==============================================================
The mypy-cache version-invalidation behavior is undocumented
==============================================================

See "Evidence from this session" above. Real, deliberate, CI-relevant, and
currently discoverable only by reading ``_checkers.py``.

==================================================
No "which checkers should I enable" decision aid
==================================================

An adopter with a mixed-language repository must reverse-map their file
types onto the Checkers table by hand. Nothing goes the other direction:
"you have ``.py`` files → consider ``python``/``mypy``; you have
``CMakeLists.txt`` → consider ``cmake``," etc.

==================================================================
``.formatting-ignore``'s exceptions are scattered, not tabulated
==================================================================

Individually correct, collectively hard to use: RST ignores it entirely;
Meson and Web only honor it outside check/verbose mode; Python never
honors it without explicit files (use ``pyproject.toml``'s own Ruff
exclude instead). Each fact lives in its own sentence, in prose, with no
single "does `.formatting-ignore` apply to checker X in mode Y" table to
check against.

===============================================================
No stated compatibility policy for ``.check_formatting.toml``
===============================================================

Nothing states whether the config schema is considered stable across
``check_formatting`` version bumps, or what happens to a project's config
if a key is ever renamed or removed. This matters concretely: this very
host just carried a project through a ``0.2.0`` → ``0.3.0`` upgrade in this
session, and any consuming project pinning a ``check_formatting`` version
has the same open question with no documented answer.

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

The vnu epic's adoption recipe ("baseline broad with ``--all`` before any
filter, review real findings, don't suppress anything unread") is exactly
the right first-time-setup discipline for *every* checker, not only
``vnu`` — but it was only ever written down once, ad hoc, in that one
epic, rather than as general first-time-setup guidance a new adopter
would find before configuring their first checker.

========================================
No consolidated backend-install matrix
========================================

Each backend's install command (``apt``, ``brew``, ``pip``, ``npm``) is
correct but scattered across roughly a dozen separate paragraphs in the
"Backends" section. Provisioning a fresh dev container or CI image means
reading all of them individually rather than scanning one table.

***************
Proposed work
***************

Add a "Getting started" section (README.md, expanded in
:doc:`../check_formatting`) covering:

1. Two or three complete starter configs for the project shapes the
   documentation already names as target use cases, each a full, valid
   ``.check_formatting.toml`` ready to adapt rather than assemble from
   scratch.
2. A CI-integration example: a pre-commit hook snippet and a CI job
   snippet, including one showing ``--json`` consumed by a script (parsing
   ``summary.failed``/``overall_ok``) rather than only piping human output.
3. Document the mypy-cache version-invalidation behavior next to
   ``mypy``'s existing paragraph, with a one-line note for CI cache
   configurations.
4. A "which checkers should I enable" checklist, keyed by file type or
   build system present in the adopting repository, inverse of the
   existing Checkers table.
5. Consolidate ``.formatting-ignore``'s per-checker, per-mode exceptions
   into one table (checker × mode → does ``.formatting-ignore`` apply, and
   if not, what to use instead), replacing the current scattered prose
   without removing the detail.
6. State a compatibility policy for ``.check_formatting.toml`` across
   ``check_formatting`` version bumps — at minimum, whether a key rename or
   removal would be a breaking change requiring a version bump of its own,
   and where such a change would be announced.
7. A copyable day-to-day workflow template an adopting project can drop
   into its own ``CONTRIBUTING.md``, generalizing AGENTS.md's own
   before-every-commit discipline into project-agnostic language.
8. Generalize the vnu epic's "baseline broad, review, then narrow"
   recipe into first-time-setup guidance that applies when enabling *any*
   checker, with the vnu recipe kept as its worked example rather than an
   isolated special case.
9. A consolidated backend-install matrix: one table, tool → apt package
   → brew package → pip package → npm dependency, for every backend, in one
   scannable place instead of a dozen paragraphs.

Pure documentation — no production code or config-schema change, so no TDD
cycle applies, matching item 1 of the vnu epic.

************************
Recommended sequencing
************************

Independent of both the vnu epic's remaining items and the sibling
:doc:`new-checker-architecture-guide` epic — different audience, no shared
prerequisite. Items 3 and 6 are cheap, standalone facts worth shipping
first; items 1, 2, 5, and 9 are the bulk of the "Getting started" section
and are more naturally written together; item 8 depends on item 1 existing
(the generalized recipe needs a real starter config to attach to as an
example).

**************
Out of scope
**************

Building a `check_formatting`-specific CI product (a GitHub Action, a
hosted dashboard, etc.) — the CI-integration item above is a documentation
example a project author copies and adapts, not a new maintained artifact.
