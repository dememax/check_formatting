<!--
Copyright (C) 2026 Maxime P. DEMENTYEV
SPDX-License-Identifier: GPL-3.0-only
-->

# check_formatting

A project-agnostic formatting/lint checker distributed as a Python package
under `src/check_formatting/`, plus its test suite (`tests/`). See
[README.md](README.md) for what the tool does and how a consuming project
configures it. This file covers conventions for working *on* the tool
itself. Implementing a new checker specifically? See
[docs/architecture.rst](docs/architecture.rst) for the internal package
layout, the checker function contract, and a worked example — this file's
conventions below (TDD, commits, formatting) still apply on top of it.

## File header comment

Every nontrivial file — source, test, config, and documentation alike —
starts with this block, using the comment syntax of the file's format
(`#` for Python/TOML, `<!-- -->` for Markdown, `..` comments for RST):

```
Copyright (C) 2026 Maxime P. DEMENTYEV
SPDX-License-Identifier: GPL-3.0-only
<one-line description of the file's purpose> — check_formatting project
```

Copyright first, then the SPDX identifier — `GPL-3.0-only`, matching this
project's deliberate choice of GPL version 3 only, not "or later" (do not
copy a "*-or-later" example from elsewhere without checking which this
project actually uses). Use the current year for new files. The
description line is omitted for files like this one whose purpose is
already declared by their filename/title.

For an executable Python module, the shebang line (`#!/usr/bin/env python3.14`)
appears on line 1, before the header block — the OS requires it to be the
very first line.

## Development workflow

Follow **Test-Driven Development (TDD)** — RED → GREEN → REFACTOR:

**Iron Law: no production code without a failing test first.** Wrote code
before the test? Delete it. Start over.

1. **RED** — write a failing test reproducing the bug or exercising the
   missing behavior. Run it and confirm it fails *for the right reason*
   (the feature is genuinely missing, not a typo or import error).
2. **GREEN** — write the minimum code to pass. No extra features, no
   unrelated refactoring.
3. **REFACTOR** — clean up with tests green. No behavior change.

Prefer a real, hermetic reproduction over mocks when the bug is about
actual tool behavior (git plumbing, subprocess exit codes, file
encoding) — several of this codebase's regression tests spin up a real
`tmp_path` git repository rather than mocking `git` itself. Mock the
*backend* (`_run`/`_fmt_stdout`) when the test is about check_formatting's
own dispatch logic, not about a specific backend's real output.

## Running tests

```bash
python3.14 -m pytest tests/ -v
```

No virtualenv is required — the test suite's only dependency is
`pytest` (see `tests/requirements.txt`). Individual tests that exercise a
specific backend (clang-format, prettier via `npx`, mypy, check_rst, …)
skip gracefully or are marked accordingly when that backend isn't
installed; most tests mock the backend entirely and never touch it.

## Formatting

This project dogfoods itself: `.check_formatting.toml` at the repo root
configures `check_formatting` to check its Python source, strict typing, and
RST documentation.

```bash
PYTHONPATH=src python3.14 -m check_formatting --fix
PYTHONPATH=src python3.14 -m check_formatting
```

Never commit with outstanding formatting or type-check violations.

## reStructuredText and Sphinx documentation

`check_rst` is the system-installed authority for universal RST formatting,
verified structure, and the real Sphinx build.  This repository's
`.check_rst.toml` declares `docs/` as the Sphinx source and a persistent build
directory; `.check_formatting.toml` declares the same tree as `[rst].dir`, so
the ordinary wrapper cycle includes changed RST files and `--all` includes the
complete maintained documentation baseline.

For a cold reader, the safe workflow after an RST edit is:

```bash
check_rst check --skip-fixable   # review semantic warnings and non-fixable errors
check_rst fix --fast             # mechanically fix the Git-scoped edit
check_rst check                  # authoritative rules + Sphinx validation
```

`--skip-fixable` is a display filter, not a promise of exit status 0.  Bare
selection is Git-aware; naming files or using `--recursive` expresses
whole-file intent.  In a dirty worktree with unrelated documentation edits,
use the same owned-file allowlist with `--git-scope` on all three commands.

When writing a heading, declare its intended depth with a 9-character
placeholder underline and let `fix --fast` materialize the syntax.  Reuse a
sibling's level; do not copy or hand-count title adornments.

When reading, use `check_rst outline FILE` if the structure or target is
unknown and `check_rst context ENTRY FILE` for a known entry.  Both report
complete physical ranges.  Use `refs` for reference relationships and
`compare` to explain semantic changes.  Do not rediscover document structure
with `grep`/`head`/`tail`/`sed`, and do not truncate `diff`: an incomplete
patch can look applicable.

The complete behavior belongs to `check_rst COMMAND --help`,
`~/github/check_rst/docs/guide.rst`, and
`~/github/check_rst/docs/rules.rst`.
Keep only check_formatting-specific adapter behavior in this project's own
product documentation.

## Virtualenv / tool-resolution policy

No Python virtualenv is assumed active. Every backend this tool invokes
(`ruff`, `mypy`, `npx`, `clang-format`, `clang-tidy`, `cmake-format`,
`west`, `shellcheck`, `vnu`, `check_rst`) is resolved from `PATH` — never from a
project-local `.venv/`. This is a deliberate property of the tool itself
(it has to work correctly regardless of which project it's checking, and
that project's own venv, if any, is none of this tool's business) and
extends to developing the tool itself: run `ruff`/`mypy` bare, resolved
from `PATH`.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/). Lowercase,
no period, imperative mood: `type(scope): short description`.

**Types:** `feat` · `fix` · `perf` · `refactor` · `test` · `docs` ·
`build` · `ci` · `chore`

**Granularity — split RED from GREEN.** For a TDD-driven change, commit
the failing test separately from the implementation that makes it pass:

1. `test: RED test for <behaviour>` — the new/changed test, still failing.
2. `feat: <behaviour>` or `fix: <behaviour>` — the change that turns it
   green. Fold doc updates into this second commit, not the test commit.

## Distribution model

This tool is a setuptools package using the `src/` layout. Install it with
`python3.14 -m pip install .` (or `--editable .` while developing); the
`pyproject.toml` entry point provides the `check_formatting` command. See
[README.md](README.md)'s Installation section. Keep `main` always in a state
appropriate for installation by consumers. Before issuing a version, follow
the maintainer/release-operator checklist in
[docs/architecture.rst](docs/architecture.rst)'s “Release checklist” section.

## Python version

Requires Python 3.14+. Use `python3.14` explicitly when invoking scripts
or tools directly — never bare `python3`, which may resolve to a
different major version depending on the host.
