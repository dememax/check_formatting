# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# RED test for check_formatting's locale-independent UTF-8 decoding — check_formatting project
"""Regression test for check_formatting's file/subprocess-output decoding.

Every ``subprocess.run``/``Popen`` call made with ``text=True`` and every
``pathlib.Path.read_text()`` call in ``check_formatting`` must
decode as UTF-8 explicitly, never via the ambient locale's preferred
encoding.  This project's files (and check_formatting's own prose) use
non-ASCII characters routinely — most commonly the em-dash.  Both
development hosts happen to run under a UTF-8 locale (``C.utf8``), so an
implicit, locale-dependent decode has silently worked so far.  Under a
plain ``C``/``POSIX`` locale with UTF-8 auto-coercion disabled — the
default in some minimal CI containers, and something reproducibility-
focused pipelines set deliberately via ``LC_ALL=C`` — the same code
raises an uncaught ``UnicodeDecodeError`` instead of failing gracefully.

This is reproduced via a real subprocess (rather than monkeypatching
``locale``) because Python 3.10+ resolves the default text encoding
through ``io.text_encoding()`` at a level module-level monkeypatching of
``locale.getpreferredencoding`` does not intercept — only an actual
hostile locale in the interpreter's environment reproduces the bug.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).parent.parent / "src"


def test_load_ignore_patterns_survives_non_utf8_locale(tmp_path: Path) -> None:
    """`_load_ignore_patterns` must decode `.formatting-ignore` as UTF-8 even when the
    process locale is plain C/POSIX (ASCII), not crash with UnicodeDecodeError."""
    ignore_file = tmp_path / ".formatting-ignore"
    ignore_file.write_bytes("# vendored code — do not reformat\nsrc/base/\n".encode())

    driver = tmp_path / "_drive_load_ignore_patterns.py"
    driver.write_text(
        "import sys, pathlib\n"
        f"sys.path.insert(0, {str(_SRC_DIR)!r})\n"
        "from check_formatting import cli\n"
        f"patterns = cli._load_ignore_patterns(pathlib.Path({str(tmp_path)!r}))\n"
        "print(patterns)\n"
    )

    env = dict(os.environ, LC_ALL="C", LANG="C", PYTHONCOERCECLOCALE="0", PYTHONUTF8="0")
    result = subprocess.run(
        [sys.executable, str(driver)],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "src/base/" in result.stdout
