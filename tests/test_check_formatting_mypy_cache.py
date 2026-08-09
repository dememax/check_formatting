# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED tests for version-gated mypy cache invalidation — check_formatting project
"""Tests for _invalidate_mypy_cache_if_version_changed.

Before this fix, `_check_mypy` unconditionally `shutil.rmtree`d
`.mypy_cache/` before every invocation. The code's own comment said this
exists only to guard against a *version-mismatched* incremental cache
silently producing wrong results — not to disable incremental analysis on
every run regardless of version. These tests pin the corrected behavior: the
cache is wiped only when a version marker recorded inside `.mypy_cache/`
itself disagrees with the currently-resolved mypy's version (or is absent
entirely — first run, or a pre-existing cache from before this marker
existed), and left alone otherwise.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from check_formatting import cli as check_formatting

if TYPE_CHECKING:
    import pathlib
    from pathlib import Path

_MARKER = check_formatting._MYPY_CACHE_VERSION_MARKER


def _mock_version(monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    monkeypatch.setattr(check_formatting, "_tool_version_string", lambda binary, cwd, version_args=None: version)


def test_mypy_cache_wiped_when_no_marker_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_version(monkeypatch, "mypy 1.2.3")
    cache_dir = tmp_path / ".mypy_cache"
    cache_dir.mkdir()
    (cache_dir / "some_file.json").write_text("{}")

    check_formatting._invalidate_mypy_cache_if_version_changed(tmp_path, tmp_path / "mypy")

    assert not (cache_dir / "some_file.json").exists()
    assert (cache_dir / _MARKER).read_text(encoding="utf-8") == "mypy 1.2.3"


def test_mypy_cache_not_wiped_when_marker_matches_current_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_version(monkeypatch, "mypy 1.2.3")
    cache_dir = tmp_path / ".mypy_cache"
    cache_dir.mkdir()
    (cache_dir / _MARKER).write_text("mypy 1.2.3", encoding="utf-8")
    (cache_dir / "CACHEDATA").write_text("{}")

    check_formatting._invalidate_mypy_cache_if_version_changed(tmp_path, tmp_path / "mypy")

    assert (cache_dir / "CACHEDATA").exists()


def test_mypy_cache_wiped_when_marker_version_mismatches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_version(monkeypatch, "mypy 1.2.3")
    cache_dir = tmp_path / ".mypy_cache"
    cache_dir.mkdir()
    (cache_dir / _MARKER).write_text("mypy 1.0.0", encoding="utf-8")
    (cache_dir / "CACHEDATA").write_text("{}")

    check_formatting._invalidate_mypy_cache_if_version_changed(tmp_path, tmp_path / "mypy")

    assert not (cache_dir / "CACHEDATA").exists()
    assert (cache_dir / _MARKER).read_text(encoding="utf-8") == "mypy 1.2.3"


def test_mypy_cache_marker_write_failure_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read-only root (or any mkdir/write failure) must not crash the check —
    it just forfeits the cache-marker optimization for the next invocation."""
    _mock_version(monkeypatch, "mypy 1.2.3")

    def raising_mkdir(self: pathlib.Path, *args: object, **kwargs: object) -> None:
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(check_formatting.pathlib.Path, "mkdir", raising_mkdir)

    check_formatting._invalidate_mypy_cache_if_version_changed(tmp_path, tmp_path / "mypy")


def test_check_mypy_writes_marker_before_running_mypy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The marker must reflect the version about to run BEFORE mypy actually
    runs, so a crash mid-run can't leave a stale marker claiming a clean,
    matching cache for a run that never finished."""
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/mypy")
    monkeypatch.setattr(
        check_formatting, "_tool_version_string", lambda binary, cwd, version_args=None: "mypy 1.2.3"
    )

    seen_marker_content: list[str] = []

    def fake_run(cmd: list[str], cwd: Path) -> int:
        marker = tmp_path / ".mypy_cache" / _MARKER
        seen_marker_content.append(marker.read_text(encoding="utf-8") if marker.exists() else "")
        return 0

    monkeypatch.setattr(check_formatting, "_run", fake_run)

    ok = check_formatting._check_mypy(tmp_path, dirs=["src"])

    assert ok is True
    assert seen_marker_content == ["mypy 1.2.3"]
