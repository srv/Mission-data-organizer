#!/usr/bin/env python3
"""Entry point for the mission_data_organizer CLI.

Designed to be invoked from anywhere on the vehicle. Resolves its own
location (following any symlink) and ensures the directory it actually
lives in is on sys.path, so the sibling `mission_data_organizer` package
can be imported.

See ../README.md for the source-to-destination contract and full usage.
"""
import os
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from mission_data_organizer.runner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
