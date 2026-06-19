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
    DAY_TEXT_MARKERS,
    LOG_SOURCES_FOLDER_PER_MISSION,
    LOG_SOURCES_PER_DATE,
    LOG_SOURCES_PER_MISSION,
)


class SourceFile(NamedTuple):
    path: Path

    # One of:
    #   "anchor"          — main mission bag (defines a mission)
    #   "per_mission"     — sensor bag, mk_ii, multibeam file
    #   "per_date"        — basic bag, emus_bms / iquaview_server log
    #   "image_folder"    — whole camera-image folder (blackfly_s, flir_*)
    #   "mission_report"  — mission_reports/*.md (content-aware window pairing)
    #   "day_text"        — root-level operator .txt note, filed by mtime
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

    Also yields root-level operator ``.txt`` notes whose lowercased name
    contains a :data:`~.config.DAY_TEXT_MARKERS` substring, tagged
    ``"day_text"`` — these are filed into the day folder by file mtime.
    """
    if not bags_root.exists():
        return
    for entry in sorted(bags_root.iterdir()):
        if not entry.is_file():
            continue
        name = entry.name
        lname = name.lower()
        if name.startswith("sparus2_") and (
            name.endswith(".bag") or name.endswith(".bag.active")
        ):
            yield SourceFile(path=entry, granularity=_classify_bag(name))
        elif lname.endswith(".txt") and any(
            marker in lname for marker in DAY_TEXT_MARKERS
        ):
            yield SourceFile(path=entry, granularity="day_text")


def walk_logs_root(logs_root: Path) -> Iterator[SourceFile]:
    """Yield candidate items from each in-scope subdirectory of
    ``<logs-root>``. Out-of-scope subdirectories are silently skipped.

    Special cases:
        - Camera image folders (``blackfly_s/``, ``flir_spinnaker_*/``) yield
          their first-level *subfolders* (each is a mission's worth of paired
          stereo images), tagged ``"image_folder"``.
        - ``mission_reports/`` files are tagged ``"mission_report"`` (placed by
          content-aware window overlap, not filename TS).
        - All other in-scope sub-dirs yield *files* (any file regardless
          of extension — includes the extensionless ``_bathy_data_raw``
          siblings under ``norbit_wbms_multibeam/``).
    """
    if not logs_root.exists():
        return

    # Camera image folders — yield each first-level subfolder (one per mission).
    for sub_name in LOG_SOURCES_FOLDER_PER_MISSION:
        sub = logs_root / sub_name
        if sub.is_dir():
            for folder in sorted(sub.iterdir()):
                if folder.is_dir():
                    yield SourceFile(path=folder, granularity="image_folder")

    # Per-mission file sources. mission_reports get their own granularity so the
    # planner pairs them by report-window overlap rather than filename TS.
    for sub_name in LOG_SOURCES_PER_MISSION:
        sub = logs_root / sub_name
        if sub.is_dir():
            tag = "mission_report" if sub_name == "mission_reports" else "per_mission"
            for f in sorted(sub.iterdir()):
                if f.is_file():
                    yield SourceFile(path=f, granularity=tag)

    # Per-date file sources.
    for sub_name in LOG_SOURCES_PER_DATE:
        sub = logs_root / sub_name
        if sub.is_dir():
            for f in sorted(sub.iterdir()):
                if f.is_file():
                    yield SourceFile(path=f, granularity="per_date")
