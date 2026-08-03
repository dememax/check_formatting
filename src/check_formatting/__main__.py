# Copyright (C) 2026 Maxime P. DEMENTYEV
# SPDX-License-Identifier: GPL-3.0-only
"""Support ``python -m check_formatting``."""


def _run() -> None:
    """Import the CLI lazily so module execution follows the console entry point."""
    from check_formatting.cli import main

    main()


if __name__ == "__main__":
    _run()
