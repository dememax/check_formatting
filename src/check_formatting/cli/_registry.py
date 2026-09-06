# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
"""The checker registry: `Checker`, the `_CHECKERS` table mapping each
name to its function/kwargs/fix-command/automatic-fix capability, and the accessors
(`_checker_kwargs`/`_fix_command`) every consumer goes through instead of
maintaining their own name-keyed tables.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple

from check_formatting import cli
from check_formatting.cli._checkers import (
    _check_clang_tidy,
    _check_cmake,
    _check_cpp,
    _check_ini,
    _check_json,
    _check_kconfig,
    _check_meson,
    _check_mypy,
    _check_python,
    _check_rst,
    _check_shell,
    _check_vnu,
    _check_web,
    _check_yaml,
)

if TYPE_CHECKING:
    from check_formatting.cli._config import ProjectConfig

_CheckFn = Callable[..., bool]


class Checker(NamedTuple):
    """One checker's full registration: label, function, and the metadata
    that used to be separately-maintained, name-keyed tables alongside it.

    Before this, `_CHECKERS` (label + function), `_checker_kwargs`'s
    `by_name` dict, and `_fix_command`'s ``if name == ...`` chain each
    independently re-enumerated the same 13 checker names — adding,
    renaming, or removing a checker meant touching all three, and forgetting
    one produced a silent bug (`_checker_kwargs` fell through to ``{}`` via
    ``dict.get(name, {})``; `_fix_command` raised ``KeyError``) rather than a
    structural guarantee of completeness. A checker's registration now lives
    in exactly one place.

    A ``NamedTuple``, not a ``@dataclasses.dataclass``, so ``_CHECKERS[name]``
    keeps behaving like the legacy ``(label, fn)`` 2-tuple everywhere that
    only cares about those first two positions — including tests that
    monkeypatch ``_CHECKERS`` down to a bare
    ``{"ini": ("prettier-plugin-ini (INI)", fail_if_called)}`` stub. Both
    index access (``entry[0]``) and ``label, fn, *_ = entry``-style unpacking
    work unchanged whether *entry* is that 2-tuple stub or this full 5-field
    ``Checker``.
    """

    label: str
    fn: _CheckFn
    kwargs_fn: Callable[[ProjectConfig, bool], dict[str, object]]
    fix_command_fn: Callable[[ProjectConfig, bool], str]
    auto_fix: bool = True


def _no_extra_kwargs(config: ProjectConfig, git_auto_detected: bool) -> dict[str, object]:
    """Shared ``kwargs_fn`` for checkers needing nothing beyond the common
    prefix (``meson``, ``cmake``)."""
    return {}


def _no_auto_fix(message: str) -> Callable[[ProjectConfig, bool], str]:
    """Return a constant-*message* ``fix_command_fn`` for a checker with no
    automatic fix (``mypy``, ``clang-tidy``, ``kconfig``, ``shell``, ``vnu``)."""

    def fix_command_fn(config: ProjectConfig, git_auto_detected: bool) -> str:
        return message

    return fix_command_fn


_CHECKERS: dict[str, Checker] = {
    "cpp": Checker(
        "clang-format (C++)",
        _check_cpp,
        lambda config, git_auto_detected: {"globs": config.cpp_globs, "git_auto_detected": git_auto_detected},
        lambda config, git_auto_detected: f"clang-format -i {' '.join(config.cpp_globs)}",
    ),
    "meson": Checker(
        "meson format (build files)",
        _check_meson,
        _no_extra_kwargs,
        lambda config, git_auto_detected: "meson format -i -r -c meson.format",
    ),
    "web": Checker(
        "prettier (HTML/CSS/JS)",
        _check_web,
        lambda config, git_auto_detected: {"globs": config.web_globs, "git_auto_detected": git_auto_detected},
        lambda config, git_auto_detected: f"npx prettier --write {' '.join(f'{g!r}' for g in config.web_globs)}",
    ),
    "vnu": Checker(
        "vnu (HTML/CSS/SVG conformance)",
        _check_vnu,
        lambda config, git_auto_detected: {"globs": config.vnu_globs, "args": config.vnu_args},
        _no_auto_fix("(vnu has no automatic fix — resolve conformance findings manually)"),
        False,
    ),
    "python": Checker(
        "ruff (Python)",
        _check_python,
        lambda config, git_auto_detected: {"dirs": config.python_dirs},
        lambda config, git_auto_detected: (
            f"ruff format {' '.join(config.python_dirs)}\n    ruff check --fix {' '.join(config.python_dirs)}"
        ),
    ),
    "json": Checker(
        "prettier (JSON/JSONC)",
        _check_json,
        lambda config, git_auto_detected: {"files": config.json_files, "git_auto_detected": git_auto_detected},
        lambda config, git_auto_detected: "npx prettier --write " + " ".join(config.json_files),
    ),
    "ini": Checker(
        "prettier-plugin-ini (INI)",
        _check_ini,
        lambda config, git_auto_detected: {"globs": config.ini_globs, "git_auto_detected": git_auto_detected},
        lambda config, git_auto_detected: f"npx prettier --write {' '.join(config.ini_globs)}",
    ),
    "mypy": Checker(
        "mypy (type checking)",
        _check_mypy,
        lambda config, git_auto_detected: {"dirs": config.mypy_dirs},
        _no_auto_fix("(mypy has no automatic fix — resolve type errors manually)"),
        False,
    ),
    "rst": Checker(
        "check_rst (RST documentation)",
        _check_rst,
        lambda config, git_auto_detected: {
            "recursive_dir": config.rst_dir,
            "git_auto_detected": git_auto_detected,
        },
        lambda config, git_auto_detected: "check_rst fix --fast" if git_auto_detected else "check_rst fix",
    ),
    "clang-tidy": Checker(
        "clang-tidy (static analysis)",
        _check_clang_tidy,
        lambda config, git_auto_detected: {
            "cpp_globs": config.cpp_globs,
            "build_dir": pathlib.Path(config.clang_tidy_build_dir) if config.clang_tidy_build_dir else None,
        },
        _no_auto_fix("(clang-tidy has no automatic fix — resolve violations manually)"),
        False,
    ),
    "cmake": Checker(
        "cmake-format (CMake)",
        _check_cmake,
        _no_extra_kwargs,
        lambda config, git_auto_detected: "cmake-format --in-place $(find . -name CMakeLists.txt)",
    ),
    "kconfig": Checker(
        "west --cmake-only (Kconfig)",
        _check_kconfig,
        lambda config, git_auto_detected: {"build_combos": config.kconfig_build_combos},
        _no_auto_fix("(Kconfig has no automatic fix — correct the .conf files manually)"),
        False,
    ),
    "shell": Checker(
        "shellcheck (shell scripts)",
        _check_shell,
        lambda config, git_auto_detected: {"globs": config.shell_globs},
        _no_auto_fix("(shellcheck has no automatic fix — resolve lint findings manually)"),
        False,
    ),
    "yaml": Checker(
        "prettier (YAML)",
        _check_yaml,
        lambda config, git_auto_detected: {"globs": config.yaml_globs, "git_auto_detected": git_auto_detected},
        lambda config, git_auto_detected: f"npx prettier --write {' '.join(f'{g!r}' for g in config.yaml_globs)}",
    ),
}


def _checker_kwargs(name: str, config: ProjectConfig, git_auto_detected: bool = False) -> dict[str, object]:
    """Return the config-sourced extra keyword arguments for checker *name*.

    Delegates to :data:`_CHECKERS`'s ``kwargs_fn`` — see :class:`Checker` for
    why each checker's kwargs are declared alongside its label/function/fix
    command instead of in a separately-maintained table. *git_auto_detected*
    is a runtime fact, not a config value — see
    :func:`_is_git_auto_detected_scope`.  Consulted by every checker that
    implements the optional "git-scoped fix" contract: ``rst`` (bare vs.
    explicit-file check_rst invocation, see :func:`_check_rst`), ``cpp``
    (per-file clang-format ``-lines=`` scoping, see :func:`_check_cpp`), and
    all four Prettier-backed fixers (``web``, ``json``, ``ini``, ``yaml``),
    which share the canonically-validated best-effort merge in
    :func:`_fix_prettier_files`.  Every other checker ignores it — see
    README.md's "Scope guarantee" table for details.
    """
    return cli._CHECKERS[name].kwargs_fn(config, git_auto_detected)


def _fix_command(name: str, config: ProjectConfig, *, git_auto_detected: bool = False) -> str:
    """Return the fix command shown when checker *name* reports a violation.

    Delegates to :data:`_CHECKERS`'s ``fix_command_fn`` — derived from the
    same config-sourced values threaded into the checker itself (see
    :func:`_checker_kwargs`), so the two cannot silently drift apart the way
    a separately-maintained if-chain could.
    """
    return cli._CHECKERS[name].fix_command_fn(config, git_auto_detected)
