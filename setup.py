# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
# Setuptools build hook for reproducible wheel contents — check_formatting project
"""Prevent deleted package modules from surviving in reused build trees."""

from __future__ import annotations

import pathlib
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py


class _CleanPackageBuild(build_py):
    """Repopulate this distribution's staged package from source each build."""

    def run(self) -> None:
        staged_package = pathlib.Path(self.build_lib) / "check_formatting"
        if staged_package.exists():
            shutil.rmtree(staged_package)
        super().run()


setup(cmdclass={"build_py": _CleanPackageBuild})
