.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Roadmap epic: backend installation policy, system vs. project-specific, per distro — check_formatting project

######################################################################
Backend installation policy: system vs. project-specific, per distro
######################################################################

:Status: Proposed.
:Sources: A live conversation auditing installed-vs-latest backend
   versions across two real hosts — an Ubuntu 26.04 ("resolute") host
   and a Gentoo host ("gl63", reached via SSH at the user's direction) —
   which surfaced two real documentation gaps in the process: an
   unexplained asymmetry in how ``vnu`` versus every other backend is
   documented, and a materially wrong description of ``prettier``'s
   version-resolution fallback. Both were corrected already (see
   :doc:`../check_formatting`'s "Backends" section, commit ``2ceeee5``);
   this epic generalizes the underlying policy those two fixes only
   applied locally.
:Versions involved: ``check_formatting`` 0.3.0

*********
Summary
*********

``check_formatting`` has exactly one backend-resolution mechanism,
uniformly, for all fourteen checkers: a bare ``PATH`` lookup
(``shutil.which``), never a project-local ``.venv/`` search of its own —
see :doc:`../architecture`'s checker-contract section and AGENTS.md's
existing "Virtualenv / tool-resolution policy". "System install" versus
"project-specific pin" was never a switch this tool offers; it is entirely
a property of what happens to be on ``PATH`` at invocation time. Do
nothing, and you get whatever is installed system-wide. Want a
project-specific version instead? Install it somewhere project-scoped and
make sure that location is earlier on ``PATH`` when ``check_formatting``
runs (activate a venv, etc.) — the tool never discovers or prefers either
on its own initiative.

That single mechanism turns out to cover every backend already — this
session's own research (below) found a legitimate, ecosystem-native,
per-project pinning route for all but one of them. What's missing is not
a *feature*; it's that this project's own docs never state the mechanism
once, generally, and then apply it consistently per backend. Instead,
today's docs read as if ``vnu`` alone got special, careful treatment
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
  Gentoo's main tree either. Every *other* backend already has an
  ecosystem-standard way to pin an exact version if wanted. Nothing in
  the shipped docs said this was *why* ``vnu`` alone gets a from-scratch
  install recipe — a reader had to ask to find out.
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
     - Not actually available — see below
     - The one real exception; see "vnu has no project-specific route"
       below.

==========================================================================================
``vnu`` has no project-specific route, and that's architectural, not a documentation gap
==========================================================================================

Unlike every other backend above, ``check_formatting`` resolves ``vnu``
via a bare ``shutil.which("vnu")`` call — never through a resolver like
``npx`` that would naturally prefer a project-local install if one
existed. Even though ``vnu-jar`` exists on npm, a project installing it
locally (``npm install vnu-jar`` in its own ``package.json``) would never
be picked up by this adapter, because the adapter never looks in
``node_modules/`` at all for it. The *closest* equivalent — a
project-scoped install directory added to ``PATH`` ahead of the system
one, using this project's own pinned-install-and-verify recipe pointed at
a project-local directory instead of ``~/opt`` — is possible in principle
(the same PATH-ordering mechanism as everything else), but there is no
packaged ecosystem making it convenient the way ``pip``/``npm`` do for
every other backend in this table. Worth stating plainly rather than
leaving a reader to discover it by testing, the way this session had to
discover prettier's fallback behavior.

***************
Proposed work
***************

Restate the general mechanism once, prominently, in the Backends section's
existing intro paragraph (which already gained the ``vnu``-rationale
sentence in commit ``2ceeee5``): "system default" is simply whatever
resolves first on ``PATH``; a project gets a project-specific version by
installing it somewhere of its own choosing and ensuring that location is
first on ``PATH`` when ``check_formatting`` runs — not a feature this tool
implements, a consequence of how ``PATH`` lookup already works.

Then, for each backend paragraph, add a consistent structure that today's
paragraphs only partially have:

1. Ubuntu install command, with a version-currency note when the
   packaged version meaningfully lags upstream (already true for
   ``clang-format``/``clang-tidy``, ``meson``, and especially ``mypy`` — a
   full major version behind is worth a reader's attention, not silently
   left to be discovered by a version mismatch later).
2. Gentoo install command (``emerge <atom>``), alongside the existing
   Ubuntu one — currently entirely absent from every backend paragraph.
   Note explicitly where a package doesn't exist in the main tree at all
   (``cmake-format``, ``west``), so a Gentoo-using reader isn't left
   assuming an omission is an oversight.
3. Project-specific pin, named explicitly with the concrete package
   and version-pin syntax (``pip install clang-format==23.1.0`` in a
   project's own venv, etc.) for every backend that has one, plus the one
   sentence of "how to make it take priority" (activate the venv before
   invoking ``check_formatting``) rather than leaving that connection
   implicit.
4. Where no project-specific route exists at all (``vnu``, and
   ``check_rst`` for a different reason), say so explicitly rather than
   silently omitting the row — a missing entry currently reads as an
   oversight rather than a fact.

Add a compact summary table (the shape of this epic's own evidence table
above, without the "Notes" column) near the top of the Backends section
for scannability — the existing per-backend prose stays authoritative for
the caveats a table would flatten away (prettier's silent-cache-fallback
risk, vnu's architectural exception), exactly the lesson already learned
from the ``.formatting-ignore`` table earlier in this project's own
roadmap (see :doc:`adopter-onboarding-guide`, item 5): a table communicates
structure, prose carries the nuance a table would wrongly imply is
uniform.

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
  project-specific pinning route.
* Every backend paragraph that has a real Gentoo package gets an
  ``emerge`` line; every one that doesn't says so explicitly.
* The ``vnu`` and ``prettier`` paragraphs' existing fixes (commit
  ``2ceeee5``) are not duplicated or contradicted by the new general
  structure — this epic's work should read as one coherent policy applied
  everywhere, not two one-off fixes plus nine differently-shaped
  paragraphs.
* A reader asking "does backend X have a distro package, and can I pin a
  project-specific version instead" should find the answer in that
  backend's own paragraph without needing to ask, the way this session's
  own conversation partner had to.

************************
Recommended sequencing
************************

No dependency on any other epic's remaining items. The highest-value
single fix, if done alone before the rest: ``mypy``'s paragraph, given the
full major-version gap found this session and that project's own
``strict = true`` mypy configuration in ``pyproject.toml`` makes a version
bump behavior-relevant, not just a version-number curiosity. The rest can
follow in any order — each backend's paragraph is independent of the
others.

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
