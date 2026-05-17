"""Pytest configuration: make the package importable when running tests
directly from the package directory (without sourcing the catkin workspace).
"""
import os
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
_SRC = os.path.realpath(os.path.join(_HERE, "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
