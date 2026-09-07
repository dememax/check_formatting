# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# External backend CLI compatibility enforcement — check_formatting project
"""Resolve and validate versions for every external backend CLI."""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import threading
from concurrent.futures import Future
from typing import Final, NamedTuple

type BackendVersion = tuple[int, int, int]


class BackendVersionPolicy(NamedTuple):
    """One backend command's version probe and supported interval."""

    display_name: str
    command_prefix: tuple[str, ...]
    version_args: tuple[str, ...]
    version_pattern: re.Pattern[str]
    supported: str
    minimum: BackendVersion | None = None
    maximum_exclusive: BackendVersion | None = None
    exact: BackendVersion | None = None


class _BackendVersionObservation(NamedTuple):
    resolved_launcher: str
    returncode: int
    output: str
    version: BackendVersion | None


def _pattern(prefix: str = "") -> re.Pattern[str]:
    return re.compile(rf"{prefix}(?P<version>\d+\.\d+\.\d+)", re.MULTILINE)


_BACKEND_VERSION_POLICIES: Final[dict[str, BackendVersionPolicy]] = {
    "clang-format": BackendVersionPolicy(
        "clang-format",
        ("clang-format",),
        ("--version",),
        _pattern(r"clang-format version\s+"),
        ">=21.0.0,<24.0.0",
        (21, 0, 0),
        (24, 0, 0),
    ),
    "meson": BackendVersionPolicy(
        "Meson",
        ("meson",),
        ("--version",),
        _pattern(r"^"),
        ">=1.5.0,<2.0.0",
        (1, 5, 0),
        (2, 0, 0),
    ),
    "prettier": BackendVersionPolicy(
        "Prettier",
        ("npx", "--no-install", "prettier"),
        ("--no-install", "prettier", "--version"),
        _pattern(r"^"),
        ">=3.0.0,<4.0.0",
        (3, 0, 0),
        (4, 0, 0),
    ),
    "ruff": BackendVersionPolicy(
        "Ruff",
        ("ruff",),
        ("--version",),
        _pattern(r"ruff\s+"),
        ">=0.16.5,<0.17.0",
        (0, 16, 5),
        (0, 17, 0),
    ),
    "mypy": BackendVersionPolicy(
        "mypy",
        ("mypy",),
        ("--version",),
        _pattern(r"mypy\s+"),
        ">=1.19.0,<3.0.0",
        (1, 19, 0),
        (3, 0, 0),
    ),
    "check_rst": BackendVersionPolicy(
        "check_rst",
        ("check_rst",),
        ("--version",),
        _pattern(r"check_rst\s+"),
        ">=0.5.0,<0.6.0",
        (0, 5, 0),
        (0, 6, 0),
    ),
    "clang-tidy": BackendVersionPolicy(
        "clang-tidy",
        ("clang-tidy",),
        ("--version",),
        _pattern(r"LLVM version\s+"),
        ">=21.0.0,<24.0.0",
        (21, 0, 0),
        (24, 0, 0),
    ),
    "cmake-format": BackendVersionPolicy(
        "cmake-format",
        ("cmake-format",),
        ("--version",),
        _pattern(r"cmake-format\s+"),
        ">=0.6.13,<0.7.0",
        (0, 6, 13),
        (0, 7, 0),
    ),
    "west": BackendVersionPolicy(
        "West",
        ("west",),
        ("--version",),
        _pattern(r"West version:\s+v?"),
        ">=1.5.0,<2.0.0",
        (1, 5, 0),
        (2, 0, 0),
    ),
    "shellcheck": BackendVersionPolicy(
        "ShellCheck",
        ("shellcheck",),
        ("--version",),
        _pattern(r"^version:\s+"),
        ">=0.11.0,<0.12.0",
        (0, 11, 0),
        (0, 12, 0),
    ),
    "vnu": BackendVersionPolicy(
        "VNU",
        ("vnu",),
        ("--version",),
        _pattern(r"^"),
        "==26.9.5",
        exact=(26, 9, 5),
    ),
}

_POLICIES_BY_LAUNCHER: Final = {
    policy.command_prefix[0]: policy
    for policy in _BACKEND_VERSION_POLICIES.values()
    if policy.command_prefix[0] != "npx"
}
type _VersionCacheKey = tuple[str, str, pathlib.Path]

_VERSION_CACHE: dict[_VersionCacheKey, Future[_BackendVersionObservation]] = {}
_VERSION_CACHE_LOCK = threading.Lock()


def _policy_for_command(command: list[str]) -> BackendVersionPolicy | None:
    if not command:
        return None
    launcher = pathlib.Path(command[0]).name
    if launcher == "npx" and command[1:3] == ["--no-install", "prettier"]:
        return _BACKEND_VERSION_POLICIES["prettier"]
    return _POLICIES_BY_LAUNCHER.get(launcher)


def _extract_backend_version(policy: BackendVersionPolicy, output: str) -> BackendVersion | None:
    """Extract a normalized three-component version from backend output."""
    match = policy.version_pattern.search(output)
    if match is None:
        return None
    major, minor, patch = (int(component) for component in match.group("version").split("."))
    return major, minor, patch


def _version_is_supported(policy: BackendVersionPolicy, version: BackendVersion) -> bool:
    if policy.exact is not None:
        return version == policy.exact
    if policy.minimum is not None and version < policy.minimum:
        return False
    return policy.maximum_exclusive is None or version < policy.maximum_exclusive


def _observe_backend_version(
    policy: BackendVersionPolicy, resolved_launcher: str, cwd: pathlib.Path
) -> _BackendVersionObservation:
    command = [resolved_launcher, *policy.version_args]
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return _BackendVersionObservation(resolved_launcher, 126, str(error), None)
    output = (result.stdout + result.stderr).strip()
    return _BackendVersionObservation(
        resolved_launcher,
        result.returncode,
        output,
        _extract_backend_version(policy, output),
    )


def _clear_backend_version_cache() -> None:
    """Clear process-local observations; exposed for hermetic tests."""
    with _VERSION_CACHE_LOCK:
        _VERSION_CACHE.clear()


def _cached_backend_observation(
    policy: BackendVersionPolicy,
    resolved_launcher: str,
    cwd: pathlib.Path,
) -> _BackendVersionObservation:
    cache_key: _VersionCacheKey = (policy.display_name, resolved_launcher, cwd.resolve())
    with _VERSION_CACHE_LOCK:
        future = _VERSION_CACHE.get(cache_key)
        if future is None:
            future = Future()
            _VERSION_CACHE[cache_key] = future
            owns_probe = True
        else:
            owns_probe = False

    if owns_probe:
        try:
            future.set_result(_observe_backend_version(policy, resolved_launcher, cwd))
        except BaseException as error:
            future.set_exception(error)
            with _VERSION_CACHE_LOCK:
                if _VERSION_CACHE.get(cache_key) is future:
                    del _VERSION_CACHE[cache_key]
            raise
    return future.result()


def _backend_version_error(command: list[str], cwd: pathlib.Path) -> str | None:
    """Return a compatibility diagnostic, or ``None`` when execution may proceed.

    Unknown commands pass through untouched. A missing launcher also passes
    through so the existing subprocess/missing-backend path retains its more
    specific error. Installed but unparseable or unsupported backends fail
    before the requested formatting or analysis command can execute.
    """
    policy = _policy_for_command(command)
    if policy is None:
        return None

    resolved_launcher = shutil.which(command[0])
    if resolved_launcher is None:
        return None
    observation = _cached_backend_observation(policy, resolved_launcher, cwd)

    if observation.returncode != 0 or observation.version is None:
        detail = observation.output or f"version command exited {observation.returncode} without output"
        return (
            f"ERROR: could not determine {policy.display_name} version; "
            f"check_formatting supports {policy.supported}\n"
            f"  Binary: {observation.resolved_launcher}\n"
            f"  Output: {detail}"
        )
    if not _version_is_supported(policy, observation.version):
        version = ".".join(str(component) for component in observation.version)
        return (
            f"ERROR: unsupported {policy.display_name} version {version}; "
            f"check_formatting supports {policy.supported}\n"
            f"  Binary: {observation.resolved_launcher}"
        )
    return None


def _ensure_supported_backend(command: list[str], cwd: pathlib.Path) -> bool:
    """Print any backend compatibility diagnostic and return whether execution may proceed."""
    error = _backend_version_error(command, cwd)
    if error is not None:
        print(error)
        return False
    return True
