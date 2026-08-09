# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
"""Best-effort Prettier tier: web/JSON/INI/YAML have no reliable native
line-range mechanism, so this reconstructs the effect of a Git-scoped
fix/diff by formatting the whole file, keeping only the hunks that
overlap changed lines, and verifying the merge canonicalizes identically
to a full reformat before trusting it. Falls back to whole-file
formatting when that verification fails.
"""

from __future__ import annotations

import concurrent.futures
import difflib
from typing import TYPE_CHECKING

from check_formatting import cli

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Sequence


def _lines_flags(ranges: list[tuple[int, int]] | None) -> list[str]:
    """Return clang-format ``-lines=<start>:<end>`` flags for precomputed *ranges*.

    Empty when *ranges* is ``None`` — no derivable hunks (an untracked
    file, a pure-deletion-only diff, or a git failure) — the caller then
    falls back to whole-file scope, exactly today's behavior. *ranges*
    comes from :func:`_batched_git_diff_hunk_ranges`, computed once per
    selected file set rather than looked up here per file.
    """
    if ranges is None:
        return []
    return [f"-lines={start}:{end}" for start, end in ranges]


def _merge_within_hunk_ranges(original: str, formatted: str, ranges: Sequence[tuple[int, int]]) -> str:
    """Merge *formatted* into *original*, keeping only the reformatting that overlaps *ranges*.

    Backs the Prettier checkers' "best-effort" git-scoped fix (see
    :func:`_best_effort_prettier_fix`) — prettier has no reliably-usable
    native line-range mechanism, unlike clang-format's ``-lines=`` (see
    :func:`_lines_flags`), so this reconstructs an equivalent effect by
    diffing the whole-file reformat against the original.

    *ranges* are 1-indexed inclusive line ranges in *original*'s
    coordinates (:func:`_git_diff_hunk_ranges`'s own return shape).  Using
    ``difflib.SequenceMatcher`` rather than reusing git's hunk line numbers
    directly against *formatted* is what avoids the "naive" version's
    trap: reformatting can shift line counts (splitting or collapsing
    lines), so a line number in *original* and the same line number in
    *formatted* stop corresponding once anything upstream changed shape.
    ``get_opcodes()`` instead gives each disjoint changed region in BOTH
    coordinate systems at once, so overlap is always tested against
    *original*'s own coordinates, and the corresponding *formatted* slice
    is used verbatim, never sliced further — splitting an opcode label
    would reintroduce the same "cut mid-construct" risk this exists to
    avoid.

    An opcode outside every range is reverted to *original*'s own lines —
    that formatting change is out of scope for this fix.  The result is
    NOT guaranteed to be valid or fully compliant on its own; the caller
    verifies that before trusting it (see :func:`_best_effort_prettier_fix`).
    """
    orig_lines = original.splitlines(keepends=True)
    fmt_lines = formatted.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=orig_lines, b=fmt_lines, autojunk=False)
    hunk_spans = [(start - 1, end) for start, end in ranges]  # 1-indexed inclusive -> 0-indexed half-open
    merged: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            merged.extend(orig_lines[i1:i2])
            continue
        in_scope = any(i1 < hend and i2 > hstart for hstart, hend in hunk_spans)
        merged.extend(fmt_lines[j1:j2] if in_scope else orig_lines[i1:i2])
    return "".join(merged)


def _best_effort_prettier_target(
    file: pathlib.Path, root: pathlib.Path, ranges: list[tuple[int, int]] | None
) -> tuple[bool, str, str]:
    """Compute what a best-effort git-scoped prettier fix would write for *file*.

    *ranges* is *file*'s precomputed hunk ranges from
    :func:`_batched_git_diff_hunk_ranges` — computed once per selected file
    set by the caller, not looked up here per file.

    Shared by :func:`_best_effort_prettier_fix` (which writes the result)
    and the ``web`` checker's check/verbose/diff modes (which only need to
    know the target to compare the current file against) — using ONE
    function for both is what guarantees check and fix can never disagree
    about what "fixed" means for a given file; two independently
    maintained implementations could silently drift apart.

    prettier has no reliably-usable native line-range mechanism for
    HTML/CSS (``--range-start``/``--range-end`` exist but are documented
    as unconfirmed outside JS/TS — see README.md's "Scope
    guarantee" table), so this is a heuristic "best effort" rather than a
    tool-guaranteed contract like ``cpp``'s ``-lines=`` or ``rst``'s
    check_rst bare mode:

    1. Reformat the whole file (what today's whole-file ``--write`` does).
    2. If already compliant, or the file has no derivable git hunk ranges
       (untracked, or a pure-deletion diff), stop there — nothing to merge,
       or nothing to merge against.
    3. Otherwise merge via :func:`_merge_within_hunk_ranges`, keeping only
       the reformatting that overlaps the file's changed hunks.
    4. Verify the merge before trusting it: feed the merged candidate to
       prettier through stdin with ``--stdin-filepath <real file>`` and
       require its canonical form to equal the whole-file result from step
       1.  This proves that the candidate parses and still represents the
       same canonical document while permitting deliberately retained,
       out-of-scope legacy formatting.  Using the real filepath is essential
       for parser inference and path-based config overrides.  If the candidate
       canonicalizes differently, the heuristic is unsafe and this falls back
       to the plain whole-file reformat instead, exactly today's behavior.
       This never produces a worse outcome than before, only sometimes better.

    Returns ``(ok, target, status)``.  *ok* is ``False`` only on a prettier
    invocation failure (missing tool, or a real error on the source file) —
    *target* is then meaningless.  *status* is a short human-readable
    outcome: ``"already compliant"``, ``"whole-file fix (no git hunk
    info)"``, ``"git-scoped merge"``, or ``"whole-file fallback (candidate
    canonicalized differently)"``.
    """
    original = file.read_text(encoding="utf-8")
    rc, formatted = cli._fmt_stdout(["npx", "--no-install", "prettier", str(file)], cwd=root)
    if rc == 127:
        return False, original, "prettier not found"
    if rc != 0:
        return False, original, f"prettier exited {rc}"
    if original == formatted:
        return True, formatted, "already compliant"

    if ranges is None:
        return True, formatted, "whole-file fix (no git hunk info)"

    merged = _merge_within_hunk_ranges(original, formatted, ranges)

    rc2, canonical_merge = cli._fmt_stdout(
        ["npx", "--no-install", "prettier", "--stdin-filepath", str(file)],
        cwd=root,
        input_text=merged,
    )

    if rc2 == 0 and canonical_merge == formatted:
        return True, merged, "git-scoped merge"

    return True, formatted, "whole-file fallback (candidate canonicalized differently)"


def _best_effort_prettier_fix(
    file: pathlib.Path, root: pathlib.Path, ranges: list[tuple[int, int]] | None
) -> tuple[bool, str]:
    """Attempt a hunk-scoped prettier fix for *file*, writing the result in-place.

    Delegates the actual scoped-merge-vs-whole-file decision entirely to
    :func:`_best_effort_prettier_target` (see its docstring for the full
    mechanism, including *ranges*) and writes *target* when it differs from
    the file's current content.  Returns ``(ok, status)`` — see
    :func:`_best_effort_prettier_target` for what *status* can be.
    """
    original = file.read_text(encoding="utf-8")
    ok, target, status = cli._best_effort_prettier_target(file, root, ranges)
    if not ok:
        return False, status
    if target != original:
        file.write_text(target, encoding="utf-8")
    return True, status


def _fix_prettier_files(
    files: Sequence[pathlib.Path],
    root: pathlib.Path,
    *,
    git_auto_detected: bool,
    label: str,
    log: Callable[..., None],
) -> bool:
    """Fix Prettier-backed *files*, optionally using best-effort Git hunk scope.

    Shared by the web, JSON/JSONC, INI, and YAML checkers.  Git-auto-detected
    scope runs :func:`_best_effort_prettier_fix` per file concurrently — each
    candidate is independent (its own file, its own merge/validation) and
    this pipeline already captures rather than streams its subprocess
    output, so there is no interleaving risk in running them at once.
    Results are still consumed/printed in *files*' original order once each
    resolves; failures are accumulated without preventing other files from
    being attempted.  Every deliberate whole-file scope (``--all`` or
    user-typed FILE arguments) retains Prettier's single batched ``--write``
    invocation.
    """
    if git_auto_detected:
        log(f"▶ npx prettier --write (best-effort git-scoped)  {label}")
        hunk_ranges = cli._batched_git_diff_hunk_ranges(root, files)
        with concurrent.futures.ThreadPoolExecutor() as pool:
            futures = [pool.submit(cli._best_effort_prettier_fix, file, root, hunk_ranges[file]) for file in files]
            ok = True
            for file, future in zip(files, futures, strict=True):
                file_ok, status = future.result()
                log(f"  {file.relative_to(root)}: {status}")
                ok = file_ok and ok
        return ok

    log(f"▶ npx prettier --write  {label}")
    return cli._run(["npx", "--no-install", "prettier", "--write", *[str(file) for file in files]], cwd=root) == 0


def _report_prettier_files_git_scoped(
    files: Sequence[pathlib.Path],
    root: pathlib.Path,
    *,
    show_diff: bool,
    log: Callable[..., None],
) -> bool:
    """Compare each file against what :func:`_best_effort_prettier_fix` would write.

    Used by the git-auto-detected branch of check/verbose/diff modes so
    they never disagree with what a subsequent ``--fix`` would actually
    do — comparing against the unconditional whole-file reformat instead
    (as every mode did before this existed) reported a violation on any
    file whose git-scoped fix had deliberately retained out-of-scope
    legacy content, contradicting the ``--fix`` that had just succeeded.

    When *show_diff*, prints a unified diff (original vs. target) for
    each file that differs, via :func:`_show_diff`; otherwise only the
    per-file status line is logged and the boolean verdict is computed.

    Each file's target is computed concurrently (independent, capture-based
    work — see :func:`_fix_prettier_files`'s docstring for why that's safe
    here), consumed/printed in *files*' original order once each resolves.
    """
    hunk_ranges = cli._batched_git_diff_hunk_ranges(root, files)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        futures = [pool.submit(cli._best_effort_prettier_target, file, root, hunk_ranges[file]) for file in files]
        any_violation = False
        for file, future in zip(files, futures, strict=True):
            original = file.read_text(encoding="utf-8")
            ok, target, status = future.result()
            if not ok:
                print(f"ERROR: {status} on {file.name}")
                return False
            log(f"  {file.relative_to(root)}: {status}")
            if show_diff:
                if cli._show_diff(original, target, str(file.relative_to(root))):
                    any_violation = True
            elif original != target:
                any_violation = True
    return not any_violation
