# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Backend CLI compatibility-policy tests — check_formatting project
"""Tests for backend version extraction, ranges, caching, and enforcement."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from check_formatting import cli as check_formatting
from check_formatting.cli import _backend_versions

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _clear_version_cache() -> None:
    _backend_versions._clear_backend_version_cache()


def test_backend_version_policies_cover_every_external_cli() -> None:
    expected = {
        "clang-format": ">=21.0.0,<24.0.0",
        "meson": ">=1.5.0,<2.0.0",
        "prettier": ">=3.0.0,<4.0.0",
        "ruff": ">=0.16.5,<0.17.0",
        "mypy": ">=1.19.0,<3.0.0",
        "check_rst": ">=0.5.0,<0.6.0",
        "clang-tidy": ">=21.0.0,<24.0.0",
        "cmake-format": ">=0.6.13,<0.7.0",
        "west": ">=1.5.0,<2.0.0",
        "shellcheck": ">=0.11.0,<0.12.0",
        "vnu": "==26.9.5",
    }

    assert {name: policy.supported for name, policy in _backend_versions._BACKEND_VERSION_POLICIES.items()} == expected


@pytest.mark.parametrize(
    ("backend", "raw_output", "expected"),
    [
        ("clang-format", "clang-format version 22.1.8\n", (22, 1, 8)),
        ("meson", "1.11.2\n", (1, 11, 2)),
        ("prettier", "3.9.6\n", (3, 9, 6)),
        ("ruff", "ruff 0.16.5\n", (0, 16, 5)),
        ("mypy", "mypy 2.2.0 (compiled: yes)\n", (2, 2, 0)),
        ("check_rst", "check_rst 0.5.0\nCopyright...\n", (0, 5, 0)),
        ("clang-tidy", "LLVM (http://llvm.org/):\n  LLVM version 22.1.8\n", (22, 1, 8)),
        ("cmake-format", "cmake-format 0.6.13\n", (0, 6, 13)),
        ("west", "West version: v1.5.0\n", (1, 5, 0)),
        ("shellcheck", "ShellCheck - shell script analysis tool\nversion: 0.11.0\n", (0, 11, 0)),
        ("vnu", "26.9.5 (a9333cb)\n", (26, 9, 5)),
    ],
)
def test_extract_backend_version(backend: str, raw_output: str, expected: tuple[int, int, int]) -> None:
    policy = _backend_versions._BACKEND_VERSION_POLICIES[backend]

    assert _backend_versions._extract_backend_version(policy, raw_output) == expected


def test_supported_backend_version_is_queried_once_and_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(_backend_versions.shutil, "which", lambda command: f"/usr/bin/{command}")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ruff 0.16.6\n", stderr="")

    monkeypatch.setattr(_backend_versions.subprocess, "run", fake_run)

    assert _backend_versions._ensure_supported_backend(["ruff", "format", "--check", "src"], tmp_path) is True
    assert _backend_versions._ensure_supported_backend(["ruff", "check", "src"], tmp_path) is True
    assert calls == [["/usr/bin/ruff", "--version"]]


def test_prettier_version_probe_uses_the_same_no_install_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(_backend_versions.shutil, "which", lambda command: f"/usr/bin/{command}")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="3.9.6\n", stderr="")

    monkeypatch.setattr(_backend_versions.subprocess, "run", fake_run)

    assert (
        _backend_versions._ensure_supported_backend(
            ["npx", "--no-install", "prettier", "--check", "index.html"], tmp_path
        )
        is True
    )
    assert calls == [["/usr/bin/npx", "--no-install", "prettier", "--version"]]


def test_prettier_verbose_version_banner_cannot_trigger_an_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "index.html"
    target.write_text("<!doctype html><title>Example</title>\n")
    calls: list[tuple[str, Path, list[str] | None]] = []

    def fake_print_tool_info(binary: str, cwd: Path, version_args: list[str] | None = None) -> None:
        calls.append((binary, cwd, version_args))

    monkeypatch.setattr(check_formatting, "_print_tool_info", fake_print_tool_info)
    monkeypatch.setattr(check_formatting, "_run", lambda command, cwd: 0)

    assert (
        check_formatting._check_web(
            tmp_path,
            verbose=True,
            explicit_files=[target],
            globs=["*.html"],
        )
        is True
    )
    assert calls == [("npx", tmp_path, ["--no-install", "prettier", "--version"])]


@pytest.mark.parametrize(
    ("backend", "raw_output"),
    [
        ("ruff", "ruff 0.16.4\n"),
        ("ruff", "ruff 0.17.0\n"),
        ("vnu", "26.9.6 (different)\n"),
    ],
)
def test_unsupported_backend_version_fails_clearly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    backend: str,
    raw_output: str,
) -> None:
    policy = _backend_versions._BACKEND_VERSION_POLICIES[backend]
    launcher = policy.command_prefix[0]
    monkeypatch.setattr(_backend_versions.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(
        _backend_versions.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout=raw_output, stderr=""),
    )

    assert (
        _backend_versions._ensure_supported_backend([launcher, *policy.command_prefix[1:], "target"], tmp_path) is False
    )
    output = capsys.readouterr().out
    assert f"unsupported {policy.display_name} version" in output
    assert policy.supported in output
    assert f"/usr/bin/{launcher}" in output


def test_unparseable_backend_version_fails_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(_backend_versions.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(
        _backend_versions.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="mystery build\n", stderr=""),
    )

    assert _backend_versions._ensure_supported_backend(["shellcheck", "script.sh"], tmp_path) is False
    output = capsys.readouterr().out
    assert "could not determine ShellCheck version" in output
    assert "mystery build" in output


def test_unknown_command_has_no_version_policy_or_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _backend_versions.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("an unrelated command must not trigger a backend version probe"),
    )

    assert _backend_versions._ensure_supported_backend(["git", "status"], tmp_path) is True


@pytest.mark.parametrize("runner", ["_run", "_fmt_stdout", "_run_capture_merged"])
def test_subprocess_helpers_refuse_an_unsupported_backend_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: str
) -> None:
    monkeypatch.setattr(check_formatting, "_ensure_supported_backend", lambda command, cwd: False)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("unsupported backend command must not execute"),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("unsupported backend command must not execute"),
    )

    result = getattr(check_formatting, runner)(["ruff", "check", "src"], tmp_path)

    if runner == "_run":
        assert result == 126
    elif runner == "_fmt_stdout":
        assert result == (126, "")
    else:
        assert isinstance(result, subprocess.CompletedProcess)
        assert result.returncode == 126
        assert "unsupported backend version" in result.stdout
