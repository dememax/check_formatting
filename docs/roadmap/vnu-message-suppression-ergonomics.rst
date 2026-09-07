.. Copyright (C) 2026 Maxime P. DEMENTYEV
.. SPDX-License-Identifier: GPL-3.0-only
.. Roadmap epic: vnu message-suppression ergonomics — check_formatting project

####################################
vnu message-suppression ergonomics
####################################

:Status: Proposed. Items 1-3 are ready to implement; item 4 is deferred
   until its own behavioral contract is settled (see below).
:Sources: ``~/check_formatting-vnu-cli-feedback.md`` (Claude Code, Sonnet 5,
   written while adopting ``vnu`` in the ``sagui`` project, 2026-09-07);
   a second review by Codex against the installed ``vnu`` backend and this
   epic's first version (2026-09-07). Both files live outside any git
   repository and are not themselves versioned. This page is their durable
   record inside ``check_formatting`` and supersedes both: every technical
   claim below was independently reproduced against the installed backend
   during this revision (fixtures and exact commands are inline, not
   "see the feedback file"), and known inaccuracies in the first-round
   feedback are called out explicitly rather than carried forward silently.
:Versions involved: ``check_formatting`` 0.3.0, ``vnu`` 26.9.5 (``a9333cb``)

*********
Summary
*********

``sagui``'s first adoption of the ``vnu`` checker alongside its existing
Prettier-formatted ``www/index.html`` hit one recurring finding: Prettier's
HTML printer unconditionally self-closes void elements (``<meta ... />``),
and ``vnu`` reports that as an info-level "Trailing slash on void elements
has no effect ..." finding. For markup where every attribute value is
quoted, accepting that finding is reasonable — but working out *which*
native ``vnu`` option actually suppresses it safely surfaced two confirmed,
silently-failing ``vnu`` footguns (Findings 1-2 below), and asking that
question also surfaced a third, more serious one that neither round of
feedback originally looked for: native options that quietly weaken the
adapter's own "always strict" ``--Werror`` guarantee (Finding 3). All three
are worth mitigating at the ``check_formatting`` layer; this page also
records where the first-round feedback's own explanations didn't hold up
under direct reproduction, so a future reader isn't reintroduced to those
errors by trusting an earlier version of this document.

*******************
Verified findings
*******************

Every claim in this section was reproduced directly against the installed
``vnu`` 26.9.5 in this session, using the minimal fixture below — no
``sagui`` checkout required:

.. code-block:: bash

   cat > clean.html <<'EOF'
   <!DOCTYPE html>
   <html lang="en">
   <head>
   <meta charset="UTF-8" />
   <title>Test</title>
   </head>
   <body>
   <p>Hello</p>
   </body>
   </html>
   EOF
   vnu --Werror --also-check-css --also-check-svg clean.html

which prints exactly one finding and exits 1::

   info: Trailing slash on void elements has no effect and interacts badly
   with unquoted attribute values.

===============================================================================
Finding 1 — ``--skip-info-messages`` does not affect ``--Werror``'s exit code
===============================================================================

Confirmed. ``--skip-info-messages`` changes only what ``vnu`` prints; the
adapter's mandatory ``--Werror`` still exits non-zero for a filtered-out
info message::

   $ vnu --Werror --also-check-css --also-check-svg --skip-info-messages clean.html
   $ echo $?
   1

Nothing is printed, yet the check still fails. ``--skip-info-messages``'s
own ``--help`` text ("only error-level ... and warnings are reported — but
not info messages") describes printing, not the exit-code decision, but a
first-time reader reasonably expects an option literally named for
suppressing a message to suppress it. In direct tension with this project's
existing no-silent-failure standard (a missing ``vnu`` binary already
prints an explicit ``ERROR:`` line rather than failing quietly — see
``_check_vnu``), this is currently the one path through the adapter that
*does* produce an unexplained FAIL.

===============================================================================
Finding 2 — filters require the finding's ENTIRE message text, not a fragment
===============================================================================

Confirmed, but the first-round feedback's explanation of *why* was wrong,
and is corrected here rather than carried forward. ``--filterpattern`` and
each line of ``--filterfile`` use Java ``Matcher.matches()`` semantics: the
pattern must match the **entire** message, not find a match somewhere
inside it (``find()`` — the substring semantics grep/ESLint/ripgrep use).
The first-round feedback described this as an "anchoring" requirement
(wrap the pattern in ``.*...*.``\ ); reproduction shows that framing is
wrong — anchors don't fix a fragment, and a complete message needs no
anchors at all:

.. list-table::
   :header-rows: 1
   :widths: 55 45

   * - ``--filterpattern`` value
     - Suppresses the finding?
   * - ``Trailing slash on void elements has no effect``
     - No — a fragment, unanchored
   * - ``^Trailing slash on void elements has no effect$``
     - No — still only a fragment; anchors don't turn part of the message
       into the whole message
   * - ``.*Trailing slash on void elements has no effect.*``
     - Yes — wildcards bridge a fragment to a whole-string match
   * - ``Trailing slash on void elements has no effect and interacts badly with unquoted attribute values.``
     - Yes — the complete message, verbatim, needs no wildcards or anchors
       at all

Two further points confirmed directly, neither mentioned in the first-round
feedback:

* The pattern matches the message text **without** its printed severity
  prefix. ``info: Trailing slash on void elements ...`` (copied verbatim
  from the terminal, prefix included) does **not** match; dropping the
  ``info: `` prefix does. Copying a line straight from ``vnu``'s own output
  into a filter is a natural but incorrect instinct.
* ``--skip-info-messages`` combined with ``--format json`` does **not**
  produce empty output — it produces a well-formed, non-empty envelope with
  no messages in it, while still exiting 1::

   $ vnu --Werror --also-check-css --also-check-svg --skip-info-messages --format json clean.html
   {"version":"26.9.5 (a9333cb)","messages":[]}
   $ echo $?
   1

  A detector for Finding 1 (see item 2 below) therefore cannot key on
  "output was empty" — it must key on "the flag is configured and the
  check failed," independent of what the subprocess printed.

=============================================================================
Finding 3 — some native options quietly weaken ``--Werror``'s own guarantee
=============================================================================

New in this revision; not identified by the first-round feedback and not
one of its two original findings. The adapter's docstring and README both
promise that ``vnu`` checking is always strict (``--Werror`` is always
supplied). Two native options undermine that promise while remaining
perfectly legal entries in ``[vnu].args``:

* ``--errors-only`` — upstream: "only error-level messages ... are
  reported (so that warnings and info messages are not reported)."
  Reproduced: on a document whose only finding is the info-level
  trailing-slash message, adding ``--errors-only`` makes the check **pass**
  under ``--Werror``::

     $ vnu --Werror --also-check-css --also-check-svg --errors-only clean.html
     $ echo $?
     0

  Unlike ``--skip-info-messages`` (Finding 1), this option changes what
  counts toward the exit-code decision, not just what's printed — a
  materially different mechanism worth distinguishing precisely in any
  future documentation or diagnostic.

* ``--exit-zero-always`` — upstream, explicitly: "Makes vnu exit zero even
  if errors are reported for any documents." Reproduced on a document with
  a genuine error (a duplicate ``id``)::

     $ vnu --Werror --also-check-css --also-check-svg --exit-zero-always bad.html
     "bad.html":8.1-8.10: error: Duplicate ID "x".
     "bad.html":7.1-7.10: info warning: The first occurrence of ID "x" was here.
     $ echo $?
     0

  The error text is printed — visible only to a reader who scrolls the raw
  output — while ``check_formatting`` would report a plain ``✓ PASS``, since
  ``_check_vnu`` decides pass/fail purely from the subprocess exit code.
  This is the most dangerous of the three findings: it turns a real,
  already-detected conformance error into a silent pass rather than a
  silent fail.

==========================================================
``check_formatting``'s own arg-passing is not implicated
==========================================================

The first-round feedback left open whether the whole-string-match
requirement (Finding 2) was ``vnu``'s own design or an artifact of how the
adapter invokes it. Resolved by reading the adapter directly: ``_check_vnu``
builds ``[vnu_bin, *mandatory_args, *args, *files]`` and passes it straight
to ``cli._run``, which calls ``subprocess.Popen(cmd, ...)`` with no
``shell=True`` and no re-quoting or re-escaping of any element — confirmed
in ``src/check_formatting/cli/_checkers.py`` and
``src/check_formatting/cli/_subprocess.py``. ``[vnu].args`` entries reach
the ``vnu`` process exactly as configured. Findings 1-3 are entirely
upstream (validator.nu) behavior; the mitigation belongs in
``check_formatting``'s own docs/config/adapter layer, which is the only
layer that can soften an upstream footgun for adopters. This does not rule
out *also* asking upstream to document the ``--Werror``/
``--skip-info-messages`` interaction and the whole-message-match
requirement more explicitly — see "Out of scope" below.

====================================================================
This project's own dispatch already buffers every checker's output
====================================================================

Correcting a claim in this epic's first version, not the feedback file: any
future adapter change that captures ``vnu``'s own output internally (Finding
1's diagnostic, item 2 below) does **not** trade away "live" terminal
streaming. ``check_formatting``'s concurrent dispatch (``cli.__init__``'s
``run_one``/``_ThreadLocalStdout``) already redirects every checker's
per-line writes into a private buffer and prints them only after that
checker's subprocess has finished — true for every mode and even a
single-checker run (``--checks vnu``), matching the README's own "nothing
prints incrementally" contract. Capturing ``vnu``'s text a second time
inside ``_check_vnu`` itself, to decide whether to append a hint, is a real
and separately testable code change, but it changes nothing about what the
user already sees.

*******************************************
Corrections to the original feedback file
*******************************************

The first-round feedback (``~/check_formatting-vnu-cli-feedback.md``)
correctly identified real footguns and its recommended recipe and
maintenance advice are preserved below, but four of its explanations do not
hold up under direct reproduction and should not be trusted from that file
going forward — this page is the corrected version:

* Anchoring, not whole-message matching — already corrected in Finding 2
  above; the feedback's own examples still contain a literal typo,
  ``.*...*.``, where a working pattern is ``.*...*``.
* "Zero semantic effect either way" — the feedback describes the
  Prettier/vnu void-element disagreement as having no semantic effect
  either way. That is too broad: per the WHATWG parsing algorithm and
  `Nu's own void-element guidance
  <https://github.com/validator/validator/wiki/Markup-%C2%BB-Void-elements>`_,
  a trailing slash immediately after an unquoted attribute value
  becomes part of that value (``src=logo.svg/`` parses as the literal value
  ``logo.svg/``). Accepting the finding is reasonable for markup where
  every attribute value is quoted (true of Prettier's own output, and of
  ``sagui``'s reviewed files) — but the safety is conditional on that fact,
  not a property of the trailing slash itself.
* "The tools agree on everything else" — unsupported by the evidence
  actually gathered. The defensible statement is narrower: this was the
  only conflict observed in ``sagui``'s tested files and the tool versions
  involved.
* "Oscillation between the two tools" — ``vnu`` never rewrites a file
  (it is analysis-only); nothing in the adapter or upstream tool makes it
  do so. What actually happens is a human running ``--fix`` (which
  reintroduces Prettier's slash) and then ``check`` (which flags it) in
  separate, manual invocations — worth stating plainly rather than
  describing it as two tools alternately modifying the file.
* Recipe scope drifts mid-walkthrough — the feedback's own step-by-step
  starts with ``--all`` and later verifies with a bare/git-scoped
  invocation, which can miss files that didn't change under ordinary Git
  selection. The recipe below keeps ``--all`` throughout baseline
  acceptance and any filter change.

*****************
Adoption recipe
*****************

A project adopting ``vnu`` alongside an existing Prettier-formatted ``web``
scope for the first time:

.. code-block:: toml

   [vnu]
   globs = ["public/**/*.html", "public/**/*.css", "public/**/*.svg"]
   # Accept Prettier's trailing slash on void elements: harmless here
   # because every attribute value in this project's markup is quoted.
   # See docs/roadmap/vnu-message-suppression-ergonomics.rst, Finding 3's
   # sibling note, for why that qualifier matters.
   args = [
     "--filterpattern",
     ".*Trailing slash on void elements has no effect and interacts badly with unquoted attribute values.*",
   ]

Add ``vnu`` to the project's ``checks`` list; an existing project that
already declares ``[vnu].args`` for another reason merges these entries
into its own list rather than replacing it.

1. Run ``check_formatting --all --checks vnu`` with **no** ``[vnu].args``
   yet, on a project already through ``check_formatting --fix`` for
   Prettier. Read every real finding; a first adoption on an existing
   codebase typically surfaces genuine issues too (missing ``lang``,
   heading-level skips), not only the void-element disagreement.
2. Fix every genuine finding by hand — ``vnu`` is analysis-only and has no
   fix mode. Confirm the check is down to *only* known-benign,
   deliberately-accepted messages before touching ``[vnu].args`` at all.
3. Add exactly one ``--filterpattern`` (or one ``--filterfile`` line) per
   accepted message, matching its **complete** text (Finding 2), and
   comment *why* it's accepted next to it in ``.check_formatting.toml``
   — not just what it suppresses.
4. Re-run ``check_formatting --all --checks vnu``: confirm it now passes.
   Keep using ``--all`` here, not a git-scoped/default invocation — a
   filter-only change touches no tracked source file, so ordinary
   changed-file selection will not revalidate files that were already
   passing before the filter existed, and a stale-but-still-matching
   filter can silently stop mattering without anyone noticing.
5. Confirm the fixed point is stable: ``check_formatting --fix``
   (Prettier reintroduces the accepted pattern) immediately followed by
   ``check_formatting`` (now filtered) should both be clean, repeatably.
   (``sagui`` reported exactly this: ``check_formatting --all`` → 9/9
   checkers passing, repeatable across multiple consecutive runs — cited
   here as reported evidence from that session, not independently
   re-run against ``sagui`` while writing this page.)
6. Treat any filter as provisional: periodically — especially when
   upgrading either Prettier or ``vnu`` — remove it and re-run ``--all``
   to confirm the message still occurs and still means what it meant when
   accepted, since either tool's wording or behavior can drift across
   versions.

For a generated/static site, build the site first and point ``[vnu].globs``
at the rendered output directory, not the source templates; account for Git
selection and any build-output exclusions already in ``.formatting-ignore``.

==================================================
Installation: tested version vs. an enforced one
==================================================

``check_formatting`` currently resolves whatever ``vnu`` is first on
``PATH`` and does not itself verify its version. 26.9.5 (``a9333cb``) is the
version this project has installed and integration-tested against — a
statement about what's verified, not a runtime-enforced minimum. Installing
it requires ``~/opt/bin`` (or wherever the launcher lands) to actually be on
``PATH``; this is assumed rather than stated in the existing installation
walkthrough and should be called out explicitly there.

=================
Troubleshooting
=================

* A malformed ``--filterpattern``/``--filterfile`` regex currently crashes
  with a raw, uncaught Java stack trace rather than a clean error::

     $ vnu --Werror --also-check-css --also-check-svg --filterpattern '.*(unclosed' clean.html
     Exception in thread "main" java.util.regex.PatternSyntaxException: Unclosed group near index 11
     ...

  worth documenting so an adopter recognizes it rather than assuming
  ``check_formatting`` itself crashed.
* A missing ``--filterfile`` path, by contrast, already produces a clean,
  legible error (``error: File not found: <path>``) and needs no additional
  documentation.

***************
Proposed work
***************

===================================================
1. README/guide documentation fix — ready to ship
===================================================

Replace the current single sentence (present near-verbatim in both
``README.md``'s ``vnu`` row/paragraph and :doc:`../check_formatting`'s
``vnu`` backend entry — both need the same edit, they currently duplicate
each other) with the corrected recipe and gotchas above: the worked
void-element example with its quoted-attributes qualifier, the
``--skip-info-messages`` warning (Finding 1), the whole-message-match
requirement stated correctly (Finding 2), and a pointer to this page for the
full recipe and troubleshooting detail. Pure documentation — no production
code or config-schema change, so no TDD cycle applies — but both copies
need editing consistently, plus a ``check_formatting``/``check_rst`` pass
before commit, per this project's own dogfooding rule.

===================================================================
2. Actionable diagnostic for a hidden vnu failure — ready to ship
===================================================================

Promoted from a stretch idea to initial delivery: the failure mode is
already reproduced (this page's fixture), so no further adopting project's
evidence is needed to justify it. Trigger condition, corrected from this
epic's first draft: ``--skip-info-messages`` present in ``[vnu].args`` *and*
the check failed — not "output was empty" (Finding 2 above shows
``--format json`` failures are non-empty). On that condition, append:

   ``vnu`` exited with status 1. ``--skip-info-messages`` can hide findings
   that still cause failure under ``--Werror``. Remove it to inspect the
   findings; use a targeted message filter for accepted exceptions.

Implementation needs ``_check_vnu`` to capture its own subprocess output
(e.g. via ``cli._run_capture_merged``, already used by the ``kconfig``
checker) instead of relying only on the outer dispatch's buffering, so it
can inspect the exit code and append the hint. As established above, this
does not change what the user sees in terms of live vs. batched output —
everything is already batched — so the remaining work is a normal,
testable adapter change: preserve the real failure status, show the hint
under ``--quiet`` too, and include it in the ``--json`` result payload.

==================================================================
3. Native-argument policy: reject validation-weakening overrides
==================================================================

New in this revision. ``[vnu].args`` currently accepts any native option
unfiltered, but Finding 3 shows ``--errors-only`` and ``--exit-zero-always``
directly undermine the adapter's own "always strict" promise — the second
can make a document with a real, printed error report as ``✓ PASS``.
Recommendation: reject both at config-load time (a hard error, the same
tier as this project's existing ``.check_formatting.toml`` schema
validation) rather than let them through as ordinary native options,
given "strict validation" is the contract this checker advertises. A
project that wants to accept a specific finding still has the fully
supported path: a targeted ``--filterpattern``/``--filterfile`` entry
(items 1-2 above), which narrows exactly one message rather than an entire
severity class. Also worth a follow-up audit, not yet performed: whether
any other native ``vnu`` option silently narrows the advertised HTML/CSS/SVG
scope (e.g. skips a file type ``--also-check-css``/``--also-check-svg``
already turned on) the same way these two narrow the exit-code guarantee.

============================================================
4. ``[vnu].ignore_messages`` convenience option — deferred
============================================================

Still a plausible convenience (a config key taking literal message
text/fragments, with the adapter building the filter internally), but not
ready for a RED test: its behavioral contract needs settling first, not
just another adopting project's demand. Specifically:

* Literal, case-sensitive matching — user-supplied text is free-form
  message content, not a regex the user is expected to write, so any
  regex metacharacters in it must be escaped before being handed to
  ``vnu``, not passed through raw.
* Reject empty or whitespace-only entries at config-load time.
* Define how this composes with an already-present
  ``--filterpattern``/``--filterfile`` in the same ``[vnu].args`` —
  reproduction during this revision shows repeated ``--filterpattern``
  flags currently work in practice on 26.9.5, but upstream only documents
  one supported multi-pattern mechanism (``|`` inside a single pattern, or
  one pattern per ``--filterfile`` line); building on the undocumented
  repeated-flag behavior is a version-fragility risk this feature should
  avoid, so it should generate a ``--filterfile``-style newline-joined
  file (or a single ``|``-joined pattern) rather than repeat the flag.
* Define whether a matching **error**-level message is suppressed too, or
  only warning/info-level ones — silently suppressing a real error by
  message text is a materially different, riskier feature than suppressing
  a known-benign info message.
* State plainly that suppression applies across every file the checker
  selects, not per-file.
* Document that ``vnu``'s own message wording can change across upstream
  versions, silently turning a literal match into a no-op after an
  upgrade — the same drift risk item 6 of the adoption recipe already
  asks projects to watch for manually.

Until these are answered, native ``--filterpattern``/``--filterfile``
(items 1-2) remain the supported, documented path.

*********************
Acceptance criteria
*********************

Whichever of items 1-3 ship, extend the real-backend integration suite
(alongside the existing ``tests/test_check_formatting_vnu_integration.py``)
to cover, at minimum:

* The documented single-message suppression passes, and stays stable
  across a repeated ``--fix`` then ``check_formatting`` cycle.
* A fixture containing **both** the accepted message and an unrelated real
  error (e.g. a duplicate ``id``) still fails — reproduced manually during
  this revision (the narrow filter suppressed only the accepted message;
  the duplicate-``id`` error still exited 1), now needs a permanent
  regression test rather than a one-off manual check.
* The item-2 diagnostic appears in normal, ``--quiet``, and ``--json``
  modes, and never changes the underlying pass/fail result.
* A missing ``--filterfile`` path and a malformed ``--filterpattern``
  regex are both covered — the former already produces a clean vnu-native
  error, the latter currently a raw Java stack trace; decide whether
  ``check_formatting`` should catch and reword the latter, and document
  whichever choice is made either way.
* Once item 3 ships: ``--errors-only``/``--exit-zero-always`` in
  ``[vnu].args`` are rejected at config-load time, with a clear error
  naming the option and why.

************************
Recommended sequencing
************************

Correct this plan and its adoption recipe (this revision) → regression
tests and the item-2 diagnostic → item 3's native-argument policy → only
then reconsider item 4. This ordering is this epic's own judgment call, not
something either round of feedback specified outright: the item-2
diagnostic no longer waits on a second adopting project, since its failure
mode is now reproduced independently of ``sagui`` (this page's own
fixture); a second project's experience (or ``sagui`` needing a second
suppressed message) remains useful, non-blocking evidence for whether item
4 is ever worth building, not a precondition for items 1-3.

**************
Out of scope
**************

Arbitrating whether Prettier's self-closing void elements or ``vnu``'s
info-level opinion against them is "more correct": both are internally
consistent, independently maintained house styles, and this project's job
is interop between them, not a ruling on either. Separately: this epic
does not itself change ``vnu``'s own upstream behavior (not this project's
code to change) — but that is not the same as ruling out an upstream
documentation request. Filing an issue asking validator.nu to document (a)
that ``--Werror``'s exit-code decision is made before
``--skip-info-messages`` filters the display stream, and (b)
``--filterpattern``/``--filterfile``'s whole-message-match semantics, would
be a reasonable, low-cost, non-blocking action alongside this epic's own
local mitigations — it is simply not required for, or blocking, anything
in items 1-4.
