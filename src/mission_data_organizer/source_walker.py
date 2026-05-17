"""Iterate over the in-scope sources defined in :mod:`config`.

The walker locates each source item on disk and tags its granularity.
Classification (which mission/date a file belongs to) is a separate concern
handled by :mod:`classifier`.
"""
from pathlib import Path
from typing import Iterator, NamedTuple

from .config import (
    BAG_SENSOR_MARKER_PER_DATE,
    BAG_SENSOR_MARKERS_PER_MISSION,
    LOG_SOURCES_PER_DATE,
    LOG_SOURCES_PER_MISSION,
)


class SourceFile(NamedTuple):
    path: Path

    # One of:
    #   "anchor"            — main mission bag (defines a mission)
    #   "per_mission"       — sensor bag, mission report, mk_ii, multibeam, etc.
    #   "per_date"          — basic bag, emus_bms log
    #   "blackfly_folder"   — whole folder under blackfly_s/
    granularity: str


def _classify_bag(name: str) -> str:
    """Return the granularity tag for a bag filename."""
    if BAG_SENSOR_MARKER_PER_DATE in name:
        return "per_date"
    if any(marker in name for marker in BAG_SENSOR_MARKERS_PER_MISSION):
        return "per_mission"
    return "anchor"


def walk_bags_root(bags_root: Path) -> Iterator[SourceFile]:
    """Yield every bag file at ``<bags-root>`` (top level only — does not
    descend into already-organized ``YYYY_MM_DD/`` subtrees), tagged by family.
    """
    if not bags_root.exists():
        return
    for entry in sorted(bags_root.iterdir()):
        if not entry.is_file():
            continue
        name = entry.name
        if not name.startswith("sparus2_"):
            continue
        if not (name.endswith(".bag") or name.endswith(".bag.active")):
            continue
        yield SourceFile(path=entry, granularity=_classify_bag(name))


def walk_logs_root(logs_root: Path) -> Iterator[SourceFile]:
    """Yield candidate items from each in-scope subdirectory of
    ``<logs-root>``. Out-of-scope subdirectories are silently skipped.

    Special cases:
        - ``blackfly_s/`` yields its first-level *subfolders* (each is a
          mission's worth of paired stereo images).
        - All other in-scope sub-dirs yield *files* (any file regardless
          of extension — includes the extensionless ``_bathy_data_raw``
          siblings under ``norbit_wbms_multibeam/``).
    """
    if not logs_root.exists():
        return

    # blackfly_s — yield subfolders (each one is a mission)
    bf = logs_root / "blackfly_s"
    if bf.is_dir():
        for sub in sorted(bf.iterdir()):
            if sub.is_dir():
                yield SourceFile(path=sub, granularity="blackfly_folder")

    # Per-mission file sources.
    for sub_name in LOG_SOURCES_PER_MISSION:
        if sub_name == "blackfly_s":
            continue  # handled above as folders
        sub = logs_root / sub_name
        if sub.is_dir():
            for f in sorted(sub.iterdir()):
                if f.is_file():
                    yield SourceFile(path=f, granularity="per_mission")

    # Per-date file sources.
    for sub_name in LOG_SOURCES_PER_DATE:
        sub = logs_root / sub_name
        if sub.is_dir():
            for f in sorted(sub.iterdir()):
                if f.is_file():
                    yield SourceFile(path=f, granularity="per_date")
