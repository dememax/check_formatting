.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Roadmap epic: backend installation policy, system vs. project-specific, per distro — check_formatting project

######################################################################
Backend installation policy: system vs. project-specific, per distro
######################################################################

:Status: Shipped (2026-09-08) in :doc:`../backends`'s "Installation
   routes" table and per-backend paragraphs.
:Sources: A live conversation auditing installed-vs-latest backend
   versions across two real hosts — an Ubuntu 26.04 ("resolute") host
   and a Gentoo host ("gl63", reached via SSH at the user's direction) —
   which surfaced two real documentation gaps in the process: an
   unexplained asymmetry in how ``vnu`` versus every other backend is
   documented, and a materially wrong description of ``prettier``'s
   version-resolution fallback. Both were corrected already (see
   :doc:`../backends`, commit ``2ceeee5``);
   this epic generalizes the underlying policy those two fixes only
   applied locally.
:Versions involved: ``check_formatting`` 0.3.0

*********
Summary
*********

``check_formatting`` delegates executable resolution to its invocation
environment. Most backends are bare commands resolved from ``PATH`` (some
checkers preflight that lookup with ``shutil.which`` and some let the shared
subprocess helpers report a missing command); Prettier is the deliberate
exception, invoked through ``npx --no-install prettier`` so a consuming
project's installation can win. ``check_formatting`` never searches a
project-local ``.venv`` itself. A caller that intentionally wants a
project-scoped tool must expose it through ``PATH`` before invoking the
utility.

Runtime compatibility is a separate, shipped layer on top of this
installation policy: every backend has a version probe and explicit supported
CLI interval in :doc:`../backends`' "Backend compatibility" section.
The interval tells the adapter which CLI versions it understands; it does not
choose, install, or pin a backend for a consuming project. This epic's own
installation and pinning guidance is the "Installation routes" table and the
per-backend paragraphs immediately below it in that same page — a related but
distinct concern from the compatibility interval, now also shipped.

That single mechanism turns out to cover every third-party backend already —
this session's own research (below) found a legitimate, ecosystem-native,
per-project pinning route for all of them; the first-party ``check_rst`` is
the documented exception.  At the time this epic was written, what was
missing was not a *feature* but a general explanation applied consistently
per backend.  The normative guide now states the general runtime compatibility
rule, while this epic's proposed per-backend installation matrix remains
unfinished.  The then-current docs read as if ``vnu`` alone got special,
careful treatment
(a full pinned install-and-verify recipe) while everything else is a bare
"install via the system package manager" — an asymmetry a careful reader
(as this session's own conversation partner was) reasonably reads as an
unexplained inconsistency, because until this session investigated it, it
was one: the reason for the difference existed in the code and in
upstream packaging reality, but nowhere in this project's own written
record.

****************************
Evidence from this session
****************************

Two concrete, previously-shipped documentation defects, already fixed
locally as part of this same investigation (commit ``2ceeee5``), are the
seed of this epic rather than something newly found for it:

* ``vnu`` has no system package on either host checked — confirmed
  directly, not assumed: no ``apt`` candidate on Ubuntu, nothing in
  Gentoo's main tree either. It does have an official project-specific
  route: ``vnu-jar`` exposes a ``vnu`` executable from a pinned npm
  dependency. The system-wide recipe remains useful because it supplies
  the missing distro installation, not because no ecosystem package exists.
* The shipped ``prettier`` paragraph described a wrong fallback
  mechanism ("bare ``npx prettier``... one-off network download") when
  the actual invocation (every call site, grepped directly) always
  carries ``--no-install``. Reproduced directly: with the project's own
  ``node_modules/`` present, that wins; absent, ``npx --no-install``
  does **not** fail — it silently resolves whatever happens to already
  sit in the invoking *user's shared* npm cache, from unrelated prior
  activity on that machine, with no relationship to the project's own
  pin, and only fails outright if neither exists. This is a real
  reproducibility gap in the tool's own documented behavior, not overhead
  a reader is expected to intuit.

Researching the general policy this epic proposes surfaced that most
other backends **already** have an ecosystem-native, per-project pinning
route, previously undocumented as such:

.. list-table::
   :header-rows: 1
   :widths: 14 20 24 24 18

   * - Backend
     - Ubuntu 26.04 (``apt``)
     - Gentoo (Portage)
     - Project-specific pin
     - Notes
   * - ``clang-format``
     - ``clang-format`` 21.1.8 (matches candidate)
     - ``llvm-core/clang`` 22.1.8 active (23.1.0/24.0.0 unemerged in tree)
     - PyPI ``clang-format`` — pinned at 23.1.0
     - Upstream (LLVM) latest: 23.1.0. Ubuntu is 2 majors behind; Gentoo's
       *installed* version is 1 behind what its own tree already offers.
   * - ``clang-tidy``
     - ``clang-tidy`` 21.1.8 (same LLVM package family)
     - same ``llvm-core/clang`` package (owns both binaries — confirmed
       via ``equery belongs``)
     - PyPI ``clang-tidy`` — pinned at 22.1.8
     - The two PyPI wrapper packages are maintained independently and
       currently sit at *different* versions from each other.
   * - ``meson``
     - ``meson`` 1.10.1 (matches candidate)
     - ``dev-build/meson`` 1.11.2 active (1.12.0 unemerged)
     - PyPI ``meson`` — pinned at 1.12.0
     - Upstream latest: 1.12.0.
   * - ``cmake-format``
     - not installed; candidate 0.6.13 (= upstream)
     - not in the main tree at all
     - PyPI ``cmake-format`` — pinned at 0.6.13
     - The PyPI route is Gentoo's only practical path for this one.
   * - ``prettier``
     - n/a — Node ecosystem, not distro-packaged
     - n/a
     - npm ``package.json``/``package-lock.json`` — but only reproducible
       if ``npm install`` was actually run (see above)
     - The one backend invoked through a resolver (``npx``) that
       *prefers* the project-local install automatically when present.
   * - ``ruff``
     - not packaged in ``apt`` at all
     - ``dev-util/ruff`` 0.16.5 (upstream 0.16.6 — 1 patch behind; the
       only case in this table where Gentoo lags a distro that *does*
       package the tool)
     - PyPI ``ruff`` — pinned at 0.16.6
     - Distinct from Astral's own standalone installer, which is
       system-wide only, not project-scoped.
   * - ``mypy``
     - ``mypy``/``python3-mypy`` 1.19.1 (matches candidate)
     - ``dev-python/mypy`` 2.2.0 active (2.3.1 unemerged)
     - PyPI ``mypy`` — pinned at 2.3.1
     - Upstream latest: 2.3.1 — a full **major** version ahead of
       Ubuntu's packaged version, the largest gap in this table.
   * - ``shellcheck``
     - ``shellcheck`` 0.11.0 (matches candidate and upstream exactly)
     - ``dev-util/shellcheck-bin`` 0.11.0 (matches)
     - PyPI ``shellcheck-py`` — pinned at 0.11.0.1, bundles the official
       prebuilt binary
     - Both distros already track upstream exactly; the PyPI route is a
       genuine alternative even so, not a fallback for a gap.
   * - ``west``
     - not installed; candidate 1.5.0 (= upstream)
     - not in the main tree at all
     - PyPI ``west`` — pinned at 1.5.0
     - The PyPI/venv route is actually Zephyr's own *recommended*
       default, not merely a fallback.
   * - ``check_rst``
     - n/a — first-party project, no distro or PyPI package
     - n/a
     - n/a — see check_rst's own installation guide
     - Correctly not duplicated here already; the existing paragraph's
       treatment is the template the others should match in spirit
       (point at the authoritative source, don't re-document it).
   * - ``vnu``
     - not packaged at all
     - not packaged at all
     - npm ``vnu-jar`` — pin in ``package.json``/``package-lock.json`` and
       expose ``node_modules/.bin`` through the invocation environment
     - The ``~/opt`` recipe provides a system-wide alternative where distro
       packages are absent.

===========================================================
``vnu`` has both project-local and system-wide pin routes
===========================================================

``check_formatting`` resolves ``vnu`` with ``shutil.which("vnu")``. A local
``npm install --save-dev vnu-jar@<version>`` creates
``node_modules/.bin/vnu``; an npm script adds that directory to ``PATH``
automatically, and another launcher may add it explicitly. The adapter then
finds that pinned executable without needing backend-specific discovery.
The documented ``~/opt`` installation instead supplies a centrally managed
executable for projects that intentionally share one tested backend version.

***************
Proposed work
***************

Shipped. The general mechanism is restated once, prominently, at the top of
:doc:`../backends`'s new "Installation routes" section: "system default" is
simply whatever resolves first on ``PATH``; a project gets a
project-specific version by installing it somewhere of its own choosing and
ensuring that location is first on ``PATH`` when ``check_formatting`` runs —
not a feature this tool implements, a consequence of how ``PATH`` lookup
already works.

Each backend paragraph now carries a consistent structure:

1. Ubuntu install command, with a version-currency note when the
   packaged version meaningfully lags upstream (true for
   ``clang-format``/``clang-tidy``, ``meson``, and especially ``mypy`` — a
   full major version behind, called out prominently rather than left to be
   discovered by a version mismatch later).
2. Gentoo install command (``emerge <atom>``), alongside the Ubuntu one.
   Explicitly noted where a package doesn't exist in the main tree at all
   (``cmake-format``, ``west``), so a Gentoo-using reader isn't left
   assuming an omission is an oversight.
3. Project-specific pin, named explicitly with the concrete package
   (``pip install clang-format`` in a project's own venv, etc.) for every
   backend that has one — which turned out to be every backend, including
   ``vnu`` (see the correction below) — plus the one sentence of "how to
   make it take priority" (activate the venv, or invoke through an npm
   script for ``prettier``/``vnu``, before running ``check_formatting``)
   rather than leaving that connection implicit.
4. Where no packaged project-specific route exists (only ``check_rst``),
   said so explicitly rather than silently omitting the row.

A compact summary table (the shape of this epic's own evidence table
above, without the "Notes" column) sits at the top of that section for
scannability — the per-backend prose stays authoritative for the caveats a
table would flatten away (prettier's silent-cache-fallback risk, the exact
npm-script mechanism that makes vnu's pin work), exactly the lesson already
learned from the ``.formatting-ignore`` table earlier in this project's own
roadmap (see :doc:`adopter-onboarding-guide`, item 5): a table communicates
structure, prose carries the nuance a table would wrongly imply is
uniform.

One correction made while shipping this, independent of commit ``7403560``'s
earlier one: this epic's own "vnu has no project-specific route" claim
(the version this epic shipped with before Codex corrected it) was tested
directly rather than taken on faith — ``npm run`` genuinely does prepend
``node_modules/.bin`` to the child process's ``PATH``, confirmed with a
throwaway script, so a project-local ``vnu-jar`` install reached through an
npm script *is* picked up by ``check_formatting``'s bare ``PATH`` lookup,
the same as every other backend. The corrected claim, not the original one,
is what shipped.

This directly extends, rather than contradicts, the already-shipped
:doc:`adopter-onboarding-guide` item 9 ("one supported install route per
backend... rather than a full apt/brew/pip/npm matrix — maintenance
burden"). That scoping decision was about avoiding an *exhaustive,
unstructured* matrix; this epic proposes a *structured* one — system
default vs. project-specific, with the "why" narrative attached — which is
a different, smaller, and more maintainable thing than what item 9
correctly declined. The two-distro scope (Ubuntu + Gentoo, plus whatever
macOS/``brew`` mentions already exist) is a deliberate limit, not an
oversight — see "Out of scope" below.

Pure documentation — no production code or config-schema change, so no
TDD cycle applies, matching item 1 of the vnu epic's own precedent.

*********************
Acceptance criteria
*********************

* Every backend paragraph states, or explicitly disclaims, a
  project-specific pinning route — verified: all eleven do (ten name a
  concrete package; ``check_rst`` explicitly disclaims one).
* Every backend paragraph that has a real Gentoo package gets an
  ``emerge`` line; every one that doesn't says so explicitly — verified
  against this epic's own evidence table.
* The ``vnu`` and ``prettier`` paragraphs' existing fixes (commits
  ``2ceeee5`` and ``7403560``) are not duplicated or contradicted by the
  new general structure — ``vnu``'s paragraph now states its Ubuntu/Gentoo
  absence and its ``vnu-jar`` project-specific route inline, alongside
  (not instead of) the existing gotchas and the system-wide ``~/opt``
  recipe.
* A reader asking "does backend X have a distro package, and can I pin a
  project-specific version instead" now finds the answer in that
  backend's own paragraph without needing to ask, the way this session's
  own conversation partner had to.

Validated: ``check_rst`` (0 errors, 0 warnings, clean Sphinx build) and the
full test suite (293 passed, 2 skipped) after this revision.

************************
Recommended sequencing
************************

Shipped in the order this section originally recommended: ``mypy``'s
paragraph (the full major-version gap, behavior-relevant given this
project's own ``strict = true`` configuration) got the same explicit
treatment as every other backend, alongside the rest rather than as an
isolated fix — the whole set shipped together in one pass once the
underlying research (and Codex's two corrections to it) was settled.

**************
Out of scope
**************

Auto-detecting or switching between system and project-specific
resolution at runtime — that would be a real code change to a
deliberately simple, uniform mechanism this session found to be sound,
not merely undocumented; see :doc:`../architecture`'s own "out of scope"
reasoning for the sibling epic that reached the same conclusion about the
dispatch internals. Also out of scope: covering distros beyond Ubuntu and
Gentoo (the two hosts actually available to verify against this session)
or removing already-correct existing macOS/``brew`` mentions — extending
to a third distro without a real host to verify against would reintroduce
exactly the unverified-claim problem this whole session has been
correcting.
