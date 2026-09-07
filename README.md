<!--
Copyright (C) 2026 Maxime P. DEMENTYEV
SPDX-License-Identifier: GPL-3.0-only
-->

# check_formatting

A project-agnostic formatting/lint checker: a thin, pluggable wrapper over
independently-maintained backends (clang-format, meson format, prettier,
ruff, mypy, check_rst, clang-tidy, cmake-format,
west, shellcheck, vnu). Each backend is registered as a *checker* the tool can
run in check, verbose, diff, or fix mode — uniformly, across languages and
file types, from one CLI.

No per-repo fact is hardcoded in the tool itself: every checker's active
status, file globs/directories/paths, and any tool-specific settings are
declared once, per project, in a committed `.check_formatting.toml`.

The detailed reference is in [docs/check_formatting.rst](docs/check_formatting.rst).
Implementing a new checker? See
[docs/architecture.rst](docs/architecture.rst) for the internal
contract every existing checker already follows.

## Installation

Requires Python 3.14 or newer. The shortest path from a clone to a working
command is:

```bash
python3.14 -m pip install /path/to/check_formatting
check_formatting --help
check_formatting --version
```

`pip install` builds a wheel internally and installs both the Python package
and its console entry point. To build the wheel explicitly instead:

```bash
cd /path/to/check_formatting
python3.14 -m pip wheel --wheel-dir dist .
python3.14 -m pip install dist/check_formatting-0.3.0-py3-none-any.whl
```

The generated wheel is a pure-Python, platform-independent package. Its exact
filename includes the package version from `check_formatting.__version__`.
The setuptools build hook repopulates the staged `check_formatting` package
from source on every build, preventing deleted modules from leaking out of a
reused `build/` directory into a later wheel.

For development, install the checkout in editable mode:

```bash
cd /path/to/check_formatting
python3.14 -m pip install --editable .
```

Ordinary Python source edits then take effect without reinstalling. Reinstall
after changing packaging metadata or console entry points in `pyproject.toml`.

The `pyproject.toml` console entry point installs `check_formatting` in the
selected Python environment's scripts directory, which must be on `PATH`.
The equivalent module invocation is:

```bash
python3.14 -m check_formatting
```

Run either form from the root of a consuming project containing its committed
`.check_formatting.toml`:

```bash
check_formatting          # changed and untracked files
check_formatting --all    # complete configured project scope
check_formatting --fix    # fix the default scope in place
```

Individual checkers additionally require their own
backend on `PATH` (clang-format, `npx`+prettier, ruff, mypy, etc.) — only
for the checkers a given project actually enables. These backends are not
Python package dependencies and are therefore not installed by pip.

To update a normal installation after updating the checkout:

```bash
cd /path/to/check_formatting
python3.14 -m pip install --upgrade .
```

To remove the package and its console entry point:

```bash
python3.14 -m pip uninstall check-formatting
```

The distribution name is `check-formatting`; the Python import package and
shell command both use the underscore form, `check_formatting`.

## Per-repo configuration

A project declares its own facts in `.check_formatting.toml` at its
repository root — a committed, explicit declaration, never auto-detected.
A missing file is a hard error: the tool has no meaningful default
behavior without knowing what to check.

```toml
checks = ["cpp", "python", "mypy"]

[cpp]
globs = ["src/**/*.cpp", "src/**/*.hpp"]

[python]
dirs = ["scripts", "tests"]

# Optional: omit this table to type-check the same targets as Ruff.
[mypy]
dirs = ["src", "tests"]
```

Unknown or duplicate checker names, unknown top-level keys, unknown keys
within a section, malformed TOML, and wrong-typed values are all hard errors.
A section for a checker not in `checks` is simply unused, not an error —
declare only what you need.

New to the tool? See
[docs/check_formatting.rst's "Getting started" section](docs/check_formatting.rst#getting-started)
for a backend-install-at-a-glance table, a "which checkers should I
enable" checklist keyed by what's already in your repository, two
complete starter configs (a pure Python package; a Meson C++/web/Python
project) verified end to end including catching a deliberate violation,
gradual-adoption guidance for an existing repository, and a copyable
day-to-day workflow template for your own `CONTRIBUTING.md`.

Discovery is **CWD-only**: run the tool from the project root (or pass a
different `project_root` when calling it as a library). There is no
parent-directory walking, matching
check_rst's own discovery contract exactly.

### Ignoring files

`.formatting-ignore` at the project root excludes files/directories from
wrapper-selected checkers, in a `.gitignore`-like syntax (blank lines and `#`
comments skipped; a trailing `/` or `/**` excludes a whole directory; a
pattern containing `/` matches the full relative path; a bare pattern
matches only the file's basename). `--exclude PATTERN` (repeatable) adds
an ad hoc, single-invocation exclusion without editing the committed file.
RST is the exception: `check_rst` owns its native selection, so invoke
`check_rst check --recursive ... --exclude ...` directly for an excluded RST audit.
Most checkers apply this in every mode, including ordinary check mode with
the default auto-detected scope, not only under `--fix`/`--diff` or explicit
files — `meson`/`web` and `python`/`mypy` are exceptions with their own
narrower rules. See
[docs/check_formatting.rst's "Excluding files" table](docs/check_formatting.rst#excluding-files)
for the exact rule per checker.

## Checkers

| Checker | Tool | Config key |
|---|---|---|
| `cpp` | clang-format | `[cpp].globs` |
| `meson` | meson format | (discovers `meson.build`/`meson.options` recursively) |
| `web` | prettier | `[web].globs` |
| `vnu` | Nu Html Checker | `[vnu].globs`, optional `[vnu].args` |
| `python` | ruff (format + lint) | `[python].dirs` |
| `json` | prettier | `[json].files` |
| `ini` | prettier (prettier-plugin-ini) | `[ini].globs` |
| `mypy` | mypy | `[mypy].dirs`, falling back to `[python].dirs` |
| `rst` | check_rst | `[rst].dir` (required for a full-repo `--recursive` scan) |
| `clang-tidy` | clang-tidy | `[clang_tidy].build_dir` |
| `cmake` | cmake-format | (discovers `CMakeLists.txt` recursively) |
| `kconfig` | `west build --cmake-only` | `[kconfig].build_combos` |
| `shell` | shellcheck | `[shell].globs` |
| `yaml` | prettier | `[yaml].globs` |

The `shell` adapter runs bare `shellcheck` from the project root, preserving
ShellCheck's native `.shellcheckrc` policy. Use that file for settings such as
`shell=bash`, `external-sources=true`, `source-path=SCRIPTDIR`,
`check-sourced=true`, and the deliberately stricter `enable=all`; keep
project-specific dialect and suppression choices out of the global wrapper.

The `vnu` adapter performs strict HTML, XHTML, standalone CSS, and standalone
SVG conformance analysis. It always supplies `--Werror`, `--also-check-css`,
and `--also-check-svg`; `[vnu].args` may add native options such as
`--filterfile`/`--filterpattern` to accept one specific, reviewed finding —
for example, Prettier's HTML printer always self-closes void elements
(`<meta ... />`), which `vnu` reports as an info-level "Trailing slash on
void elements" finding, safe to accept where every attribute value in the
markup is quoted. Two gotchas before reaching for either flag:
**`--skip-info-messages` does not work for this** — it only changes what
`vnu` prints, not whether `--Werror` still exits non-zero, so a
filtered-out message still fails the check with no visible reason; and
**a filter must match a finding's entire message text**, not a fragment
(Java `Matcher.matches()` semantics — `--help` describes it as a "regular
expression," but neither `--filterpattern` nor `--filterfile` documents
that it requires a whole-string match). See
[the vnu message-suppression-ergonomics roadmap epic](docs/roadmap/vnu-message-suppression-ergonomics.rst)
for the full adoption recipe, reproduction commands, and troubleshooting.
`--errors-only`, `--exit-zero-always`, `--css`, and `--svg` are rejected as
`[vnu].args` entries — a hard config error at load time — because each
silently weakens the adapter's own always-strict, always-HTML/CSS/SVG
contract rather than narrowing one specific finding; use
`--filterpattern`/`--filterfile` to accept a specific finding instead.
Its scope is deliberately independent of `[web].globs`:
`web` identifies files formatted by Prettier, while `vnu` identifies files
validated by Nu. Overlap is expected and useful, JavaScript belongs only to
`web`, and SVG may belong only to `vnu`.

```toml
[vnu]
globs = ["public/**/*.html", "public/**/*.css", "public/**/*.svg"]
# Accept Prettier's trailing slash on void elements: harmless here because
# every attribute value in this project's markup is quoted (see the vnu
# roadmap epic linked above for why that qualifier matters).
args = [
  "--filterpattern",
  ".*Trailing slash on void elements has no effect and interacts badly with unquoted attribute values.*",
]
```

This host uses the exact upstream Nu release `26.9.5` (`a9333cb`), installed
as `~/opt/vnu/26.9.5/vnu.jar`. The artifact SHA-256 is
`b37a0a67cde28d6a3b361f4c774cbd80fe3e1fde38824304e295c8d764296756`.
The complete reproducible installation and upgrade procedure is in
[the backend guide](docs/check_formatting.rst#backends); it never resolves a
mutable `latest` release.

`kconfig`'s configured `build_combos` build concurrently (non-verbose mode)
— give each combo its own `-d`/`--build-dir` in `args` if it needs isolated
build state; `west build` already supports this directly, no
`check_formatting`-specific configuration exists or is needed for it.
Combos sharing a build directory will race. `--verbose` stays sequential,
one combo at a time, so its live-streamed output is never interleaved.

A category name names the **file domain** it covers (`cpp`, `web`,
`python`, ...) — except where a domain already has a primary
formatter/linter and a second, deeper-analysis tool exists for the *same*
files: `mypy` layers Python type-checking on top of `python` (ruff format
+ lint), `clang-tidy` layers C++ static analysis on top of `cpp`
(clang-format), and `vnu` layers HTML/CSS/SVG conformance analysis on top of
the overlapping `web` formatting domain. These are named after the tool
itself to disambiguate from the domain category they extend.

Whether a checker is in a project's default `checks` list is entirely
project-relative: a Meson/prettier/ruff project might default to
`cpp`/`meson`/`web`/`python`/`mypy`; a CMake/Zephyr project would default
to `cmake`/`kconfig` instead. Any registered checker not in a project's
`checks` list is still reachable via `--checks <name>`.

The tool exits 0 if every check passes, 1 if any check reports
violations. When violations are found, the exact fix command(s) for the
failed checker(s) are printed.

## Modes

Mutually exclusive; check mode is the default when none is given.

| Flag | Effect |
|---|---|
| *(none)* | Check mode: pass/fail per checker plus a summary table. No files modified. |
| `--verbose` | Same checks, but each tool's maximum native diagnostic output. No files modified. |
| `--diff` | Unified diff of what each formatter would change. No files modified. |
| `--fix` | Apply every formatter in-place. Files are modified. |

Output verbosity is a separate, combinable axis:

| Flag | Effect |
|---|---|
| `--quiet` | Suppresses the tool's own chrome (banners, summary table, config echo, per-checker command lines). Never suppresses ERROR messages, diff content, or a wrapped tool's own output. |
| `--json` | Prints one JSON object instead of the banners/table: `{config_source, mode, checks, results: {name: {label, ok, output}}, summary: {total, passed, failed}, overall_ok}`. |

Neither `--quiet` nor `--json` changes the pass/fail return value or exit code.

Every selected checker runs concurrently, so nothing prints incrementally —
all output appears together, in `--checks` order, once every checker has
finished. `--fail-fast` shortens the *report* to stop at the first checker
(list order) that reports a problem; every checker still runs to completion
regardless, so it saves no wall-clock time, only output. See
[docs/check_formatting.rst](docs/check_formatting.rst)'s "Concurrent checker
dispatch" section for the full rationale.

## File-selection scope

| Invocation | Scope |
|---|---|
| *(none)* | Auto-detected: files changed since HEAD plus untracked files, via git (mirrors check_rst's own default). Nothing changed → reports "nothing to do" and exits 0. |
| `--all` | Full-repo scan: every file matching each enabled checker's configured globs/dirs, regardless of git state. |
| `-- FILE ...` | Scope to exactly those files. Each checker filters them through its configured globs/files or fixed file domain. |

## Optional "git-scoped fix" contract

Some checkers' backends support restricting a `--fix` to just the lines a
file actually changed, instead of the whole file — protecting
pre-existing content elsewhere in a touched file from being silently
renormalized when the file selection is git-auto-detected. This is an
explicit, **optional** per-checker contract, gated on the backend
actually exposing (or the tool reconstructing) a working line/hunk-range
mechanism. It comes in two tiers:

**Native tier** — tool-guaranteed, applies to check/verbose/diff/fix alike:

| Checker | Mechanism |
|---|---|
| `rst` | check_rst's own bare-mode git integration — native, first-party. |
| `cpp` | clang-format's native `-lines=<start>:<end>`, computed per file from `git diff -U0 HEAD`. |

**Best-effort tier** — heuristic:

| Checker | Mechanism |
|---|---|
| `web`, `json`, `ini`, `yaml` | prettier has no reliably-usable native line-range mechanism (`--range-start`/`--range-end` exist but are documented mainly for JS/TS), so the tool reconstructs the effect: diff the whole-file reformat against the original, keep only the reformatting overlapping the file's changed hunks, then verify formatting the merge produces the same canonical whole-file result as formatting the original. If the candidate doesn't parse or canonicalizes differently, this falls back to the plain whole-file reformat — never a worse outcome than not having the contract at all, only sometimes a better one. Check/verbose/diff compare against this same target, so a file already at its git-scoped-fixed state passes even though it still differs from a full reformat. |

Every other checker's backend has no equivalent mechanism at all — native
or reconstructable — so `--fix` is necessarily whole-file for them. This
is a materially lower risk for them than for `rst`: clang-format,
prettier, and `ruff format` are convergent, idempotent formatters —
re-running one over already-compliant, untouched lines is a no-op —
whereas check_rst's adornment-hierarchy remap can rewrite content that is
valid but intentionally non-standard, which is exactly what makes
whole-file scope risky there.

### Scope guarantee: file-level, not line-level

| Checker | Tool | Line-range restriction available? |
|---|---|---|
| `cpp` | clang-format | Yes — native `-lines=<start>:<end>`, exploited when auto-detected |
| `clang-tidy` | clang-tidy | Yes — native `-line-filter=<json>` — unexploited: this checker never writes files (report-only) |
| `web` | prettier | No reliable native mechanism, but reconstructed on a best-effort basis for `--fix` (see above) |
| `json` / `ini` / `yaml` | prettier | Same reconstructed mechanism as `web` |
| `meson` / `cmake` | meson format / cmake-format | No — whole-file only |
| `python` (format) | ruff format | No — whole-file only (same gap as Black) |
| `python` (lint) | ruff check | No native fix-range flag |
| `mypy` | mypy | N/A — whole-program type inference |
| `kconfig` | west build --cmake-only | N/A — validates merged Kconfig state across all `.conf` files together |
| `shell` | shellcheck | No known native flag |
| `vnu` | Nu Html Checker | N/A — report-only conformance analysis |
| `rst` | check_rst | Yes — check_rst's own git integration |

For RST, default Git-scoped fixing uses `check_rst fix --fast` and diff
mode uses `check_rst diff --fast`. Explicit files and configured recursive
scans retain ordinary `check_rst fix` because those scopes deliberately request
whole-file validation. An RST `--all` run without `[rst].dir` is an error;
the tool never silently substitutes a changed-file scan for a requested full
scan.

## Continuous integration

**Use `--all` (or explicit files), not a bare invocation, for any CI job
gating a clean checkout.** A bare invocation only selects files changed
since `HEAD` plus untracked files — on a freshly cloned or freshly
committed checkout that set is empty by definition, so it trivially
reports success regardless of what the checkout actually contains
(verified: a syntax-broken, already-committed Python file goes completely
undetected by `check_formatting --json`, and is caught only by
`check_formatting --all --json`). `--json` also does not wrap every
failure in JSON — a missing or malformed `.check_formatting.toml` prints
plain text and exits 1 without ever producing JSON, so a consuming script
must check the exit status (or catch a JSON decode failure), not call
`json.loads()` on stdout unconditionally.

See
[docs/check_formatting.rst's "Continuous integration" section](docs/check_formatting.rst#continuous-integration)
for a complete CI job example, a verified JSON-consumption script, and a
pre-commit hook example — including why letting `check_formatting` do its
own git-based file selection (rather than passing it pre-commit's matched
filenames) preserves the native/best-effort git-scoped-fix optimizations
above.

## License

Copyright (C) 2026 Maxime P. DEMENTYEV.

Licensed under the GNU General Public License version 3 only
(SPDX-License-Identifier: `GPL-3.0-only`). See [LICENSE](LICENSE) for the
complete, unmodified license text.
