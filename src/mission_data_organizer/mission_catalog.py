"""Build the catalog of missions from the main-bag anchors at ``<bags-root>``.

A "main bag" is any ``sparus2_*.bag`` (or ``.bag.active``) whose name
contains none of the sensor markers in :mod:`config` (``_basic_``,
``_camera_``, ``_multibeam_``, ``_sidescan_``, ``_stereo_camera_``).

Time-handling contract:
    - Bag filenames (anchor + companions) are recorded on the AUV's onboard
      computer (Orat) whose system clock is UTC by deployment policy. The
      filename timestamp is therefore parsed and attached as UTC.
    - Bag-internal timestamps are Unix-epoch seconds, UTC by definition.
      :func:`bag_inspector.inspect_bag` returns UTC-aware datetimes.
    - The mission folder name (``HH_MM_SS``) and date folder (``YYYY_MM_DD``)
      are rendered in ``local_tz`` so they match the team's manual convention
      (Madrid local time). They are precomputed here and stored on the
      :class:`Mission` so downstream code does not need to know ``local_tz``.
"""
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import List, NamedTuple, Tuple

from .bag_inspector import BagInspectionError, inspect_bag
from .config import BAG_SENSOR_MARKERS
from .timestamp_parser import (
    mission_folder_name,
    parse_bag_timestamp,
)


class Mission(NamedTuple):
    date: datetime          # midnight in local_tz; used to render YYYY_MM_DD
    folder_name: str        # HH_MM_SS rendered in local_tz
    filename_ts: datetime   # anchor filename TS, UTC-aware (Orat)
    start: datetime         # rosbag-internal start_time, UTC-aware
    end: datetime           # rosbag-internal end_time, UTC-aware
    anchor_path: Path       # the main bag file


def _is_main_bag(name: str) -> bool:
    """True iff ``name`` is a sparus2 bag with no sensor marker."""
    if not name.startswith("sparus2_"):
        return False
    if not (name.endswith(".bag") or name.endswith(".bag.active")):
        return False
    return not any(marker in name for marker in BAG_SENSOR_MARKERS)


def build_catalog(
    bags_root: Path, local_tz: tzinfo,
) -> Tuple[List[Mission], List[str]]:
    """Scan ``<bags-root>`` (top level only) for main-bag anchors.

    Returns ``(missions, warnings)``. Anchors whose internal timestamps
    cannot be read (stub bags — header-only, no messages) are retained
    in the catalog with a zero-width internal-time window
    (``start = end = filename_ts``). This keeps filename-based companion
    matching working for short / aborted missions; the internal-time
    matching path naturally cannot bind anything to a zero-width window.
    Callers must surface the warnings to the user.
    """
    if not bags_root.exists():
        return [], []

    catalog: List[Mission] = []
    warnings: List[str] = []
    for entry in sorted(bags_root.iterdir()):
        if not entry.is_file():
            continue
        if not _is_main_bag(entry.name):
            continue
        ts_naive = parse_bag_timestamp(entry.name)
        if ts_naive is None:
            continue
        ts_utc = ts_naive.replace(tzinfo=timezone.utc)
        ts_local = ts_utc.astimezone(local_tz)
        try:
            tr = inspect_bag(entry)
            start, end = tr.start, tr.end
        except BagInspectionError as e:
            warnings.append(
                f"Stub mission anchor {entry.name} "
                f"(internal timestamps unreadable: {e}); "
                f"companions will be matched by filename only"
            )
            start, end = ts_utc, ts_utc
        catalog.append(
            Mission(
                date=ts_local.replace(
                    hour=0, minute=0, second=0, microsecond=0
                ),
                folder_name=mission_folder_name(ts_local),
                filename_ts=ts_utc,
                start=start,
                end=end,
                anchor_path=entry,
            )
        )
    return catalog, warnings
