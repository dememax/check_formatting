# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
"""`.check_formatting.toml` schema and loader: `ProjectConfig`, the known
section/key table, and the validating TOML reader. No checker logic lives
here — only the declarative project-facts contract every checker reads
from.
"""

from __future__ import annotations

import collections
import dataclasses
import sys
import tomllib
from typing import TYPE_CHECKING, Final, NoReturn

from check_formatting import cli

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Sequence

_CONFIG_FILE = ".check_formatting.toml"

# Each checker's (section, key) pair, the single source of truth for both
# _CONFIG_SECTIONS' unknown-key validation and _load_project_config's
# per-field lookups below — one place to update, not two kept in sync by
# hand. Every section has exactly one key today.
_CPP: Final = ("cpp", "globs")
_WEB: Final = ("web", "globs")
_PYTHON: Final = ("python", "dirs")
_MYPY: Final = ("mypy", "dirs")
_JSON: Final = ("json", "files")
_INI: Final = ("ini", "globs")
_CLANG_TIDY: Final = ("clang_tidy", "build_dir")
_KCONFIG: Final = ("kconfig", "build_combos")
_SHELL: Final = ("shell", "globs")
_YAML: Final = ("yaml", "globs")
_RST: Final = ("rst", "dir")

# Known keys per config section (project-specific paths/globs/targets).
# Mypy may override the Python (Ruff) target set, with Python dirs as fallback.
_CONFIG_SECTIONS: dict[str, frozenset[str]] = {
    section: frozenset({key})
    for section, key in (_CPP, _WEB, _PYTHON, _MYPY, _JSON, _INI, _CLANG_TIDY, _KCONFIG, _SHELL, _YAML, _RST)
}

_TOP_LEVEL_KEYS = frozenset({"checks", *_CONFIG_SECTIONS})


@dataclasses.dataclass(frozen=True)
class ProjectConfig:
    """Resolved, validated contents of `.check_formatting.toml`."""

    checks: list[str]
    cpp_globs: list[str]
    web_globs: list[str]
    python_dirs: list[str]
    mypy_dirs: list[str]
    json_files: list[str]
    ini_globs: list[str]
    clang_tidy_build_dir: str
    kconfig_build_combos: list[dict[str, object]]
    shell_globs: list[str]
    yaml_globs: list[str]
    rst_dir: str


def _config_error(message: str) -> NoReturn:
    print(f"check_formatting: {message}")
    sys.exit(1)


def _require_str_list(table: dict[str, object], key: str, where: str) -> list[str]:
    value = table.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        _config_error(f"{where}: {key!r} must be a list of strings, got {value!r}")
    return value


def _require_str(table: dict[str, object], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str):
        _config_error(f"{where}: {key!r} must be a string, got {value!r}")
    return value


def _load_project_config(root: pathlib.Path) -> ProjectConfig:
    """Load and validate `.check_formatting.toml` at *root*.

    Declaration, not auto-detection — mirrors `.check_rst.toml`'s contract:
    discovery at *root* only (no parent-directory walking), unknown keys and
    wrong-typed values are a hard error, and a missing file is a hard error
    too — the script has no meaningful default behavior without knowing what
    to check.
    """
    path = root / _CONFIG_FILE
    if not path.is_file():
        _config_error(f"{_CONFIG_FILE} not found at {root} — see .check_rst.toml for the convention this mirrors")
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        _config_error(f"invalid {_CONFIG_FILE}: {exc}")

    unknown_top = set(data) - _TOP_LEVEL_KEYS
    if unknown_top:
        _config_error(
            f"unknown key(s) in {_CONFIG_FILE}: {', '.join(sorted(unknown_top))}"
            f" — known keys: {', '.join(sorted(_TOP_LEVEL_KEYS))}"
        )

    for section, known_keys in _CONFIG_SECTIONS.items():
        if section not in data:
            continue
        table = _require_table(data, section)
        unknown = set(table) - known_keys
        if unknown:
            _config_error(
                f"unknown key(s) in [{section}]: {', '.join(sorted(unknown))}"
                f" — known keys: {', '.join(sorted(known_keys))}"
            )

    checks = _require_str_list(data, "checks", _CONFIG_FILE)
    _validate_check_names(checks, _CONFIG_FILE)
    python_dirs: list[str] = _optional_section(data, *_PYTHON, _require_str_list, [])
    mypy_dirs: list[str] = _optional_section(data, *_MYPY, _require_str_list, []) if "mypy" in data else python_dirs
    return ProjectConfig(
        checks=checks,
        cpp_globs=_optional_section(data, *_CPP, _require_str_list, []),
        web_globs=_optional_section(data, *_WEB, _require_str_list, []),
        python_dirs=python_dirs,
        mypy_dirs=mypy_dirs,
        json_files=_optional_section(data, *_JSON, _require_str_list, []),
        ini_globs=_optional_section(data, *_INI, _require_str_list, []),
        clang_tidy_build_dir=_optional_section(data, *_CLANG_TIDY, _require_str, ""),
        kconfig_build_combos=_optional_section(data, *_KCONFIG, _require_build_combos, []),
        shell_globs=_optional_section(data, *_SHELL, _require_str_list, []),
        yaml_globs=_optional_section(data, *_YAML, _require_str_list, []),
        rst_dir=_optional_section(data, *_RST, _require_str, ""),
    )


def _validate_check_names(checks: Sequence[str], where: str) -> None:
    """Reject unknown or duplicate checker names before concurrent dispatch."""
    unknown = sorted(set(checks) - cli._CHECKERS.keys())
    if unknown:
        _config_error(f"{where}: unknown checker(s): {', '.join(unknown)}")
    duplicates = sorted(name for name, count in collections.Counter(checks).items() if count > 1)
    if duplicates:
        _config_error(f"{where}: duplicate checker(s): {', '.join(duplicates)}")


def _optional_section[T](
    data: dict[str, object],
    section: str,
    key: str,
    validator: Callable[[dict[str, object], str, str], T],
    default: T,
) -> T:
    """Return ``validator(data[section], key, ...)``, or *default* if *section* is absent.

    A project with no targets for this checker simply omits the section —
    that is not an error. If the section IS present, its keys are still fully
    validated by *validator* (missing or wrong-typed values are still a hard
    error — declaring the section means declaring it correctly). Shared by
    every optional per-checker config field: plain string lists and single
    strings (:func:`_require_str_list`/:func:`_require_str`) alike with
    kconfig's build-combo tables (:func:`_require_build_combos`), which
    otherwise needed their own copy of this same "absent section" check.
    """
    if section not in data:
        return default
    return validator(_require_table(data, section), key, f"[{section}]")


def _require_build_combos(table: dict[str, object], key: str, where: str) -> list[dict[str, object]]:
    value = table.get(key)
    if not isinstance(value, list):
        _config_error(f"{where}: {key!r} must be a list of tables, got {value!r}")
    combos: list[dict[str, object]] = []
    item: object
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            _config_error(f"{where}: {key!r}[{i}] must be a table, got {item!r}")
        label: object = item.get("label")
        if not isinstance(label, str):
            _config_error(f"{where}: {key!r}[{i}].label must be a string, got {label!r}")
        args: object = item.get("args")
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            _config_error(f"{where}: {key!r}[{i}].args must be a list of strings, got {args!r}")
        combos.append({"label": label, "args": args})
    return combos


def _require_table(data: dict[str, object], section: str) -> dict[str, object]:
    table = data[section]
    if not isinstance(table, dict):
        _config_error(f"[{section}] must be a table, got {table!r}")
    return table


def _echo_project_config(source: str, config: ProjectConfig) -> None:
    """Print the applied config for traceability, mirroring check_rst's echo line."""
    print(f"config: {source} — checks={config.checks}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
