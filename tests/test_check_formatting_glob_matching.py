# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for _file_matches_any_glob — check_formatting project
"""Tests for _file_matches_any_glob, which replaces _configured_glob_paths.

_configured_glob_paths(root, globs) used to glob the *entire* configured
target tree from disk (`root.glob(glob)` for every pattern) just to test
whether a handful of explicit/git-changed files were inside it. Python
3.13+'s `PurePath.full_match()` tests a path directly against a glob
pattern (including `**`) without touching the filesystem, and was verified
empirically to produce identical accept/reject decisions to `Path.glob()`
for both nested and zero-directory `**` patterns. These tests pin
_file_matches_any_glob's contract directly, ahead of wiring it into
_select_explicit in place of the old frozenset-membership approach.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from check_formatting import cli as check_formatting

if TYPE_CHECKING:
    from pathlib import Path


def test_file_matches_any_glob_nested_nonrecursive_pattern(tmp_path: Path) -> None:
    nested = tmp_path / "src" / "a.cpp"
    nested.parent.mkdir()
    nested.write_text("")

    assert check_formatting._file_matches_any_glob(nested, tmp_path, ["src/*.cpp"]) is True


def test_file_matches_any_glob_recursive_star_star_pattern(tmp_path: Path) -> None:
    nested = tmp_path / "src" / "deep" / "nested" / "b.cpp"
    nested.parent.mkdir(parents=True)
    nested.write_text("")

    assert check_formatting._file_matches_any_glob(nested, tmp_path, ["src/**/*.cpp"]) is True


def test_file_matches_any_glob_star_star_matches_file_at_tree_root(tmp_path: Path) -> None:
    """`**` matches zero-or-more directories, including none — a file
    directly at *root* (not nested at all) must still match `**/*.h`,
    mirroring what test_check_cpp_auto_detected_scope_uses_configured_globs
    already relies on end-to-end."""
    header = tmp_path / "api.h"
    header.write_text("")

    assert check_formatting._file_matches_any_glob(header, tmp_path, ["**/*.h"]) is True


def test_file_matches_any_glob_no_match(tmp_path: Path) -> None:
    other = tmp_path / "src" / "a.txt"
    other.parent.mkdir()
    other.write_text("")

    assert check_formatting._file_matches_any_glob(other, tmp_path, ["src/*.cpp"]) is False


def test_file_matches_any_glob_file_outside_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.cpp"

    assert check_formatting._file_matches_any_glob(outside, tmp_path / "project", ["*.cpp"]) is False


def test_file_matches_any_glob_checks_every_pattern(tmp_path: Path) -> None:
    header = tmp_path / "src" / "a.hpp"
    header.parent.mkdir()
    header.write_text("")

    assert check_formatting._file_matches_any_glob(header, tmp_path, ["src/*.cpp", "src/*.hpp"]) is True
