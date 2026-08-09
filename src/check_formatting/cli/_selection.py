# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
"""File-selection and exclusion: detecting the Git-changed/untracked scope,
`.formatting-ignore`/`--exclude` filtering, matching files against
configured globs, and batched Git-hunk-range lookups for the checkers
that restrict a fix/diff to changed lines.
"""

from __future__ import annotations

import fnmatch
import pathlib
import re
import subprocess
import sys
from typing import TYPE_CHECKING

from check_formatting import cli

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

IGNORE_FILE = ".formatting-ignore"

# Per-checker ignore file for clang-tidy only.  Patterns in this file are
# applied in addition to IGNORE_FILE.  Use it for files that clang-tidy
# cannot parse (e.g. because they include GCC-specific headers) but that
# are still valid targets for clang-format and other checkers.
CLANG_TIDY_IGNORE_FILE = ".clang-tidy-ignore"

# Name of the per-project config file (lives at the repository root).


def _load_ignore_patterns(root: pathlib.Path, filename: str = IGNORE_FILE) -> list[str]:
    """Load ignore patterns from *filename* at the project root.

    Returns an empty list if the file does not exist.  Pass *filename* to
    load from an alternative ignore file (e.g. :data:`CLANG_TIDY_IGNORE_FILE`).

    Pattern syntax (subset of ``.gitignore``):

    - Blank lines and lines starting with ``#`` are skipped.
    - Patterns are relative to *root*, using forward slashes.
    - Trailing ``/`` → directory prefix (every file under it is excluded).
    - Trailing ``/**`` → same as trailing ``/``.
    - Patterns containing ``/`` → matched against the full relative path
      with :func:`fnmatch.fnmatch`.
    - Patterns without ``/`` → matched against the file basename only.
    """
    ignore_file = root / filename
    if not ignore_file.exists():
        return []
    patterns = []
    for line in ignore_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _is_ignored(path: pathlib.Path, root: pathlib.Path, patterns: Sequence[str]) -> bool:
    """Return True if *path* matches any pattern in *patterns*.

    See :func:`_load_ignore_patterns` for pattern syntax.
    """
    if not patterns:
        return False
    rel_posix = path.relative_to(root).as_posix()
    for pattern in patterns:
        if pattern.endswith("/"):
            # Directory prefix: "src/base/"
            if rel_posix.startswith(pattern):
                return True
        elif pattern.endswith("/**"):
            # Directory prefix: "src/base/**" → treat as "src/base/"
            prefix = pattern[:-2]  # strip "**", keep trailing "/"
            if rel_posix.startswith(prefix):
                return True
        elif "/" in pattern:
            # Path-rooted glob: match against the full relative path
            if fnmatch.fnmatch(rel_posix, pattern):
                return True
        else:
            # No slash: match against the file basename only
            if fnmatch.fnmatch(path.name, pattern):
                return True
    return False


def _detect_changed_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Return absolute paths of files changed since HEAD or untracked, at *root*.

    Mirrors check_rst's own default file-selection scope: tracked files
    modified/added since HEAD (``git diff --name-only HEAD``) plus
    untracked files (``git status --porcelain --untracked-files=all``,
    filtered to ``??`` entries so untracked directories are expanded to
    their individual files rather than reported as one directory path).

    Deleted files are excluded — a path git reports as changed but that no
    longer exists on disk has nothing to check.  May return ``[]`` when
    nothing is changed; the caller (:func:`check_formatting`) treats an
    empty list as an explicit "nothing to do" state, distinct from ``None``
    (full-repo scan).

    A ``git`` failure here (e.g. *root* is not a git repository) is a hard
    error, not a silent fallback to full-repo scanning or to "nothing
    changed" — either guess could silently hide files that should have
    been checked.
    """
    tracked = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"], cwd=root, capture_output=True, text=True, encoding="utf-8"
    )
    if tracked.returncode != 0:
        print(f"check_formatting: git diff failed: {tracked.stderr.strip()}")
        sys.exit(1)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if status.returncode != 0:
        print(f"check_formatting: git status failed: {status.stderr.strip()}")
        sys.exit(1)

    names = {line for line in tracked.stdout.splitlines() if line}
    for line in status.stdout.splitlines():
        if line.startswith("??"):
            names.add(line[3:].strip())

    return sorted((root / name).resolve() for name in names if (root / name).is_file())


# Matches a unified-diff hunk header, e.g. "@@ -3 +3 @@" or "@@ -2,0 +3,2 @@".
# Only the new-file side (after "+") is captured — see _batched_git_diff_hunk_ranges.
_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

# Matches a unified-diff "new file" header, e.g. "+++ b/src/foo.py" or, for a
# file deleted entirely, "+++ /dev/null" — see _parse_git_diff_hunks_by_relpath.
_DIFF_NEW_FILE_HEADER_RE = re.compile(r"^\+\+\+ (?:b/(?P<path>.+)|/dev/null)$")


def _parse_git_diff_hunks_by_relpath(diff_output: str) -> dict[str, list[tuple[int, int]]]:
    """Parse a (possibly multi-file) ``git diff -U0``'s stdout into 1-indexed
    ``(start, end)`` new-file line ranges, keyed by each file's path exactly
    as printed after ``+++ b/``.

    A hunk whose new-file line count is zero (a pure deletion) contributes no
    range, and a file deleted entirely (``+++ /dev/null``) contributes no
    entry at all — nothing was added there for a line-range-based formatter
    to reformat, the same rule the single-file lookup already applied.
    """
    ranges_by_path: dict[str, list[tuple[int, int]]] = {}
    current: list[tuple[int, int]] | None = None
    for line in diff_output.splitlines():
        header = _DIFF_NEW_FILE_HEADER_RE.match(line)
        if header is not None:
            path = header.group("path")
            current = ranges_by_path.setdefault(path, []) if path is not None else None
            continue
        if current is None:
            continue
        hunk = _HUNK_HEADER_RE.match(line)
        if not hunk:
            continue
        new_start = int(hunk.group(1))
        new_count = int(hunk.group(2)) if hunk.group(2) is not None else 1
        if new_count == 0:
            continue
        current.append((new_start, new_start + new_count - 1))
    return {path: ranges for path, ranges in ranges_by_path.items() if ranges}


def _batched_git_diff_hunk_ranges(
    root: pathlib.Path, files: Sequence[pathlib.Path]
) -> dict[pathlib.Path, list[tuple[int, int]] | None]:
    """Return each of *files*'s 1-indexed ``(start, end)`` changed-line ranges,
    from a single ``git diff -U0 HEAD`` covering all of them at once.

    Backs the optional "git-scoped fix" contract (see :func:`_check_cpp`): a
    checker whose backend accepts a native line-range flag (clang-format's
    ``-lines=<start>:<end>``) can restrict a ``--fix`` — and, to keep
    check/fix consistent, a ``--check``/``--diff`` — to just the lines that
    actually changed, mirroring check_rst's own bare-mode hunk scoping.
    Batching one subprocess call across every selected file (instead of one
    per file, as an earlier version of this function did) matters once a
    git-scoped run spans many changed files across several checkers.

    ``--`` scopes the diff to exactly *files* — an unfiltered ``git diff -U0
    HEAD`` would return hunks for every changed file in the whole
    repository, not just the ones the caller selected.  An empty *files*
    means the opposite to git (no ``--`` restriction at all, not "nothing"),
    so it is handled explicitly before any subprocess is spawned.
    ``--relative`` makes git report paths relative to *root* (this call's
    cwd) rather than the repository's top-level directory, so parsed paths
    line up with *files* even when *root* is a subdirectory of a larger
    worktree.

    A file with no usable hunks maps to ``None`` — "no hunk restriction
    available, use whole-file scope instead": an untracked file (no
    ``HEAD`` baseline, so ``git diff HEAD`` shows nothing for it at all), a
    file whose only changes were pure deletions, or a ``git`` failure (which
    maps every file to ``None``).  Unlike :func:`_detect_changed_files`, a
    git failure here degrades to whole-file scope rather than aborting the
    whole run — this is an optional safety refinement of an already-selected
    file set, not the file-selection decision itself.
    """
    ranges: dict[pathlib.Path, list[tuple[int, int]] | None] = dict.fromkeys(files)
    if not files:
        return ranges
    result = subprocess.run(
        ["git", "diff", "-U0", "--relative", "HEAD", "--", *(str(f) for f in files)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return ranges
    by_relpath = _parse_git_diff_hunks_by_relpath(result.stdout)
    by_resolved = {(root / relpath).resolve(): file_ranges for relpath, file_ranges in by_relpath.items()}
    for f in files:
        ranges[f] = by_resolved.get(f.resolve())
    return ranges


def _git_diff_hunk_ranges(root: pathlib.Path, file: pathlib.Path) -> list[tuple[int, int]] | None:
    """Return 1-indexed ``(start, end)`` line ranges changed in *file*'s current version.

    A thin, single-file convenience wrapper over
    :func:`_batched_git_diff_hunk_ranges` — see its docstring for the full
    contract. Kept for callers that only ever need one file's ranges.
    """
    return cli._batched_git_diff_hunk_ranges(root, [file])[file]


def _resolve_explicit_files(
    file_args: Sequence[str], all_files: bool, project_root: pathlib.Path
) -> list[pathlib.Path] | None:
    """Resolve ``main()``'s FILE positional args and ``--all`` into :func:`check_formatting`'s *explicit_files*.

    - ``all_files`` (``--all``) forces ``None`` — an explicit request for the
      full-repo scan, regardless of any FILE args (``main()`` rejects that
      combination before this is called).
    - Non-empty *file_args* scope to exactly those paths, unchanged from
      before this auto-detection feature existed.
    - No *file_args* — whether the FILE positional was omitted entirely, or
      given but expanded to nothing (e.g. ``-- $(git diff --name-only
      HEAD)`` when nothing is changed) — triggers git-based auto-detection
      via :func:`_detect_changed_files`, mirroring check_rst's own default.
      This may itself resolve to ``[]``, which is returned as-is: it is
      :func:`check_formatting`'s job to report that as "nothing to do",
      not this function's job to paper over it by falling back to ``None``
      (the bug this replaces — see the module's "no silent failures" note).
    """
    if all_files:
        return None
    if file_args:
        return [_resolve_under(p, project_root) for p in file_args]
    return cli._detect_changed_files(project_root)


def _is_git_auto_detected_scope(file_args: Sequence[str], all_files: bool) -> bool:
    """True when file selection came from git auto-detection — no ``--all``, no FILE args.

    Mirrors :func:`_resolve_explicit_files`'s own "no file_args" branch without
    duplicating its return-type contract (a plain ``list[Path] | None`` that
    existing callers/tests already depend on).  The rst checker needs this
    extra bit alongside the resolved file list: an auto-detected list must
    run check_rst bare to preserve its native hunk-scoped ``--fix``, while a
    list the user typed explicitly on the CLI should keep check_rst's
    whole-file scope (see :func:`_check_rst`'s docstring).
    """
    return not all_files and not file_args


def _bare_scoped(explicit_files: list[pathlib.Path] | None, git_auto_detected: bool) -> bool:
    """True only for the actual bare/hunk-scoped rst case: an auto-detected file
    list, not just *git_auto_detected* on its own.

    *git_auto_detected* is meaningful only when *explicit_files* is an actual
    file list — the CLI never produces ``explicit_files=None`` (a full/
    recursive scan) together with ``git_auto_detected=True``
    (:func:`_is_git_auto_detected_scope` ties the two together), but the
    public :func:`check_formatting` API doesn't enforce that pairing for a
    direct library caller. Used by both :func:`_check_rst` (to choose
    ``fix --fast`` vs. ordinary ``fix``) and :func:`check_formatting`'s own
    remediation-hint call site, so the guard is defined once instead of
    independently re-derived in two places.
    """
    return explicit_files is not None and git_auto_detected


def _resolve_under(path_str: str, root: pathlib.Path) -> pathlib.Path:
    """Resolve *path_str* to an absolute path, anchoring relative paths at *root*.

    ``pathlib.Path(p).resolve()`` alone anchors relative paths at the
    process's actual working directory, which only coincidentally matches
    *root* when the caller happens to run from the repository root — this
    anchors explicitly instead, since *root* (``project_root``) is this
    tool's real reference point regardless of the invoking shell's cwd.
    """
    path = pathlib.Path(path_str)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _filter_configured_targets(
    files: Sequence[pathlib.Path], root: pathlib.Path, targets: Sequence[str]
) -> list[pathlib.Path]:
    """Keep explicit *files* that equal or descend from configured *targets*.

    An empty target list preserves the legacy direct-library behavior.  Once a
    project declares targets, however, changed-file and explicit-file scopes
    may narrow that set but must never expand beyond it.
    """
    if not targets:
        return list(files)
    resolved_targets = [_resolve_under(target, root) for target in targets]
    return [
        path
        for path in files
        if any(path.resolve() == target or path.resolve().is_relative_to(target) for target in resolved_targets)
    ]


def _filter_files(
    files: list[pathlib.Path],
    root: pathlib.Path,
    ignore_patterns: Sequence[str],
) -> tuple[list[pathlib.Path], int]:
    """Remove ignored files from *files*.

    Returns
    -------
    tuple[list[pathlib.Path], int]
        Filtered file list and the number of files that were excluded.
    """
    if not ignore_patterns:
        return files, 0
    kept = [f for f in files if not _is_ignored(f, root, ignore_patterns)]
    return kept, len(files) - len(kept)


def _file_matches_any_glob(file: pathlib.Path, root: pathlib.Path, globs: Sequence[str]) -> bool:
    """True if *file* would be selected by any of *globs* under *root*.

    Tests *file* directly against each pattern via ``PurePath.full_match``
    (Python 3.13+) instead of globbing the entire configured target tree
    from disk just to check membership of a handful of explicit/git-changed
    files — ``full_match`` is designed as ``glob()``'s own membership test
    and was verified empirically to produce identical accept/reject
    decisions, including for ``**`` (both a nested match and a file sitting
    directly at *root*, since ``**`` matches zero-or-more directories).
    """
    try:
        relative = file.resolve().relative_to(root.resolve())
    except ValueError:
        return False  # file is outside root entirely — no configured glob could match it
    return any(relative.full_match(pattern) for pattern in globs)


def _select_explicit_from_globs(
    explicit_files: list[pathlib.Path],
    root: pathlib.Path,
    ignore_patterns: Sequence[str],
    globs: Sequence[str],
    *,
    fallback_extensions: frozenset[str],
) -> tuple[list[pathlib.Path], int] | None:
    """Select explicit files using configured globs, with a legacy fallback when unconfigured.

    Normal CLI dispatch always supplies the checker's configured globs.  The
    suffix fallback preserves the direct helper-call API for callers that omit
    checker configuration entirely.
    """
    if globs:
        return _select_explicit(
            explicit_files,
            root,
            ignore_patterns,
            configured_globs=globs,
        )
    return _select_explicit(
        explicit_files,
        root,
        ignore_patterns,
        extensions=fallback_extensions,
    )


def _file_count_label(total: int, excluded: int) -> str:
    """Return a human-readable label like ``(12 file(s), 3 excluded)``."""
    if excluded:
        return f"({total + excluded} file(s), {excluded} excluded)"
    return f"({total} file(s))"


def _report_empty_selection(
    files: Sequence[pathlib.Path],
    excluded: int,
    log: Callable[..., None],
    noun: str,
    *,
    ignore_file: str = IGNORE_FILE,
) -> bool:
    """Log and return True ("nothing to do") when *files* is empty; False to continue.

    Every ``_check_*`` backend selects its files, then faces the same two empty
    outcomes: nothing of this *noun* exists at all, or everything that does was
    excluded by *ignore_file*. Centralizing the pair also fixes a copy-paste
    drift a few call sites had: some previously dropped *excluded* from the
    "all ... excluded" message.
    """
    if not files and not excluded:
        log(f"  (no {noun} files found)")
        return True
    if not files:
        log(f"  (all {excluded} {noun} file(s) excluded by {ignore_file})")
        return True
    return False


def _select_explicit(
    explicit_files: list[pathlib.Path],
    root: pathlib.Path,
    ignore_patterns: Sequence[str],
    *,
    extensions: frozenset[str] | None = None,
    exact_names: frozenset[str] | None = None,
    exact_paths: frozenset[pathlib.Path] | None = None,
    configured_globs: Sequence[str] | None = None,
) -> tuple[list[pathlib.Path], int] | None:
    """Intersect *explicit_files* with this checker's file-type set.

    Returns ``None`` when the intersection is empty (caller should skip
    silently).  Returns ``(kept, excluded)`` otherwise, where *excluded*
    is the count of files removed by ignore patterns.

    Keyword matching (applied with OR logic):

    - *extensions*  — ``file.suffix`` in the set (e.g. ``{".cpp", ".hpp"}``)
    - *exact_names* — ``file.name`` in the set (e.g. ``{"meson.build"}``)
    - *exact_paths* — ``file.resolve()`` in the set (used for JSONC files)
    - *configured_globs* — matches any pattern directly (see
      :func:`_file_matches_any_glob`), without globbing the whole
      configured target tree first
    """
    matched = [
        f
        for f in explicit_files
        if (extensions and f.suffix in extensions)
        or (exact_names and f.name in exact_names)
        or (exact_paths and f.resolve() in exact_paths)
        or (configured_globs and _file_matches_any_glob(f, root, configured_globs))
    ]
    if not matched:
        return None
    kept, excluded = _filter_files(sorted(matched), root, ignore_patterns)
    return kept, excluded
