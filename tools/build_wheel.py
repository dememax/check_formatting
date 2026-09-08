#!/usr/bin/env python3.14
# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Reproducible checksummed wheel builder — check_formatting project
"""Build the local release wheel twice, verify it, and emit its SHA-256."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL_REQUIREMENTS = PROJECT_ROOT / "tools" / "release-requirements.txt"
INSTALLER = PROJECT_ROOT / "tools" / "install_standalone.py"


class ReleaseError(RuntimeError):
    """A cleanly reportable wheel-build or verification failure."""


def _run(
    command: list[str],
    *,
    cwd: pathlib.Path = PROJECT_ROOT,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        details = "\n".join(part.rstrip() for part in (result.stdout, result.stderr) if part.strip())
        suffix = f"\n{details}" if details else ""
        raise ReleaseError(f"command failed with status {result.returncode}: {shlex.join(command)}{suffix}")
    return result


def _locked_tools() -> dict[str, str]:
    requirements: dict[str, str] = {}
    for raw_line in TOOL_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, version = line.partition("==")
        if not separator or not name or not version:
            raise ReleaseError(f"release tool must use an exact == pin: {raw_line!r}")
        requirements[name] = version
    if not requirements:
        raise ReleaseError(f"release tool lock is empty: {TOOL_REQUIREMENTS}")
    return requirements


def _check_tool_versions() -> None:
    mismatches: list[str] = []
    for name, expected in _locked_tools().items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = "not installed"
        if actual != expected:
            mismatches.append(f"{name}: expected {expected}, found {actual}")
    if mismatches:
        joined = "; ".join(mismatches)
        raise ReleaseError(
            f"release toolchain does not match {TOOL_REQUIREMENTS}: {joined}; "
            f"install it with {sys.executable} -m pip install -r {TOOL_REQUIREMENTS}"
        )


def _git_output(*arguments: str) -> str:
    return _run(["git", *arguments]).stdout.strip()


def _release_source() -> tuple[str, str]:
    status = _git_output("status", "--porcelain", "--untracked-files=all")
    if status:
        raise ReleaseError(f"worktree is not clean:\n{status}")
    commit = _git_output("rev-parse", "HEAD")
    epoch = _git_output("show", "-s", "--format=%ct", "HEAD")
    if not epoch.isdecimal():
        raise ReleaseError(f"Git returned an invalid commit timestamp: {epoch!r}")
    return commit, epoch


def _build_once(destination: pathlib.Path, epoch: str) -> pathlib.Path:
    destination.mkdir(parents=True)
    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = epoch
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-build-isolation",
            "--no-deps",
            "--wheel-dir",
            str(destination),
            str(PROJECT_ROOT),
        ],
        environment=environment,
    )
    wheels = list(destination.glob("check_formatting-*.whl"))
    if len(wheels) != 1:
        raise ReleaseError(f"expected exactly one check_formatting wheel, found {len(wheels)} in {destination}")
    return wheels[0]


def _digest(path: pathlib.Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def _write_checksum(wheel: pathlib.Path, digest: str) -> pathlib.Path:
    checksum = wheel.with_suffix(f"{wheel.suffix}.sha256")
    checksum.write_text(f"{digest}  {wheel.name}\n", encoding="utf-8")
    return checksum


def _validate_wheel(wheel: pathlib.Path) -> None:
    try:
        with zipfile.ZipFile(wheel) as archive:
            corrupt_member = archive.testzip()
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReleaseError(f"invalid wheel archive {wheel}: {exc}") from exc
    if corrupt_member is not None:
        raise ReleaseError(f"wheel contains corrupt member: {corrupt_member}")


def _smoke_install(wheel: pathlib.Path, temporary_root: pathlib.Path) -> None:
    prefix = temporary_root / "standalone"
    installed = _run([sys.executable, str(INSTALLER), "install", str(wheel), "--prefix", str(prefix)])
    if "verified SHA-256" not in installed.stdout:
        raise ReleaseError("standalone installer did not report checksum verification")
    launcher = prefix / "bin" / "check_formatting"
    _run([str(launcher), "--help"])
    _run([str(launcher), "--version"])
    _run([sys.executable, str(INSTALLER), "uninstall", "--prefix", str(prefix)])


def _publish(
    wheel: pathlib.Path, checksum: pathlib.Path, output_dir: pathlib.Path
) -> tuple[pathlib.Path, pathlib.Path]:
    output_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    published_wheel = output_dir / wheel.name
    published_checksum = output_dir / checksum.name
    for source, destination in ((wheel, published_wheel), (checksum, published_checksum)):
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=output_dir)
        os.close(descriptor)
        temporary = pathlib.Path(temporary_name)
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    return published_wheel, published_checksum


def _build_release(output_dir: pathlib.Path) -> None:
    _check_tool_versions()
    commit, epoch = _release_source()
    with tempfile.TemporaryDirectory(prefix="check-formatting-release-") as temporary_name:
        temporary_root = pathlib.Path(temporary_name)
        first = _build_once(temporary_root / "first", epoch)
        second = _build_once(temporary_root / "second", epoch)
        first_digest = _digest(first)
        second_digest = _digest(second)
        if first.name != second.name or first_digest != second_digest:
            raise ReleaseError(
                "two builds from the same commit were not byte-for-byte reproducible: "
                f"{first.name} {first_digest}; {second.name} {second_digest}"
            )

        _validate_wheel(first)
        checksum = _write_checksum(first, first_digest)
        _smoke_install(first, temporary_root)
        published_wheel, published_checksum = _publish(first, checksum, output_dir.expanduser().resolve())

    print(f"source commit: {commit}")
    print(f"SOURCE_DATE_EPOCH: {epoch}")
    print(f"wheel: {published_wheel}")
    print(f"checksum: {published_checksum}")
    print(f"SHA-256: {first_digest}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a reproducible check-formatting wheel and verify it in a fresh standalone environment."
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=PROJECT_ROOT / "dist",
        help="artifact directory; default PROJECT_ROOT/dist",
    )
    return parser


def main() -> int:
    arguments = _build_parser().parse_args()
    try:
        _build_release(arguments.output_dir)
    except (ReleaseError, OSError) as exc:
        print(f"build_wheel: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
