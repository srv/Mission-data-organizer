"""Assemble the full move plan and validate it before any move is applied.

Validation rules:
- No two sources may map to the same destination (collision detection).
- No destination may already exist on disk.
- Files already inside an already-organized ``YYYY_MM_DD/HH_MM_SS/`` subtree
  are skipped silently (idempotent re-runs).

Time-handling contract (see ``mission_catalog`` and ``classifier`` for the
deeper rationale):
    - Bag filenames (Orat-recorded) are attached as UTC.
    - Non-bag sensor filenames are also attached as UTC. The drivers for
      every non-bag source (Norbit multibeam → ``.s7k``, mk_ii sidescan →
      ``.xtf``, iquaview server → ``mission_report.md`` /
      ``iquaview_server.log``) run on Orat itself, so the filename TS
      string is whatever Orat's clock said at write time — and Orat is
      UTC. The UTC-aware datetime is then converted to ``local_tz`` (the
      team's local time, default Europe/Madrid) so the demote-path date
      folder renders in local time, matching the team's convention.
    - Bag-internal timestamps are UTC-aware out of ``bag_inspector``.
    - All comparisons happen between TZ-aware datetimes; Python normalizes
      to UTC internally so the script's behavior is host-TZ-independent.
"""
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import List, NamedTuple

from .bag_inspector import BagInspectionError, inspect_bag
from .classifier import (
    DEMOTED_OUTSIDE_MISSION,
    Assignment,
    assign_anchor,
    assign_basic_bag,
    assign_companion_bag,
    assign_image_folder,
    assign_mission_report,
    assign_per_date,
    assign_per_mission,
    canonicalize_bag_name,
)
from .config import RAW_NATIVE_SOURCES, SYSTEM_LOG_SUBDIR
from .mission_catalog import build_catalog
from .report_inspector import parse_report_window
from .source_walker import walk_bags_root, walk_logs_root
from .timestamp_parser import parse_any, parse_bag_timestamp


class MovePlan(NamedTuple):
    moves: List[Assignment]
    warnings: List[str]
    errors: List[str]


def build_plan(
    bags_root: Path, logs_root: Path, local_tz: tzinfo,
) -> MovePlan:
    """Walk both roots, classify each item, validate, and return the plan.

    Does not perform any move; safe to invoke for a dry-run print.
    """
    moves: List[Assignment] = []
    warnings: List[str] = []
    errors: List[str] = []

    catalog, catalog_warnings = build_catalog(bags_root, local_tz)
    warnings.extend(catalog_warnings)

    # ---- bags ----
    for sf in walk_bags_root(bags_root):
        if sf.granularity == "anchor":
            a = assign_anchor(sf.path, bags_root, local_tz)
            if a is None:
                warnings.append(
                    f"Cannot parse timestamp from {sf.path.name}, skipping"
                )
                continue
            moves.append(a)

        elif sf.granularity == "per_mission":
            canon_name, stripped = canonicalize_bag_name(sf.path.name)
            extra = "active_suffix_stripped" if stripped else None
            fname_ts_naive = parse_bag_timestamp(sf.path.name)
            if fname_ts_naive is None:
                # source_walker only tags a bag as per_mission when its
                # name matches the sensor-marker pattern, which already
                # contains a parseable timestamp. Hitting this branch
                # means an upstream invariant has broken; surface it
                # rather than silently routing the bag through the
                # internal-time fallback.
                warnings.append(
                    f"Cannot parse timestamp from {sf.path.name}, skipping"
                )
                continue
            fname_ts_utc = fname_ts_naive.replace(tzinfo=timezone.utc)

            # Filename-first: sensor companions share their anchor's
            # filename TS by construction (same launcher invocation).
            a = assign_companion_bag(
                sf.path, fname_ts_utc, catalog, bags_root,
                dst_name=canon_name, extra_note=extra,
            )
            if a is not None:
                moves.append(a)
                continue

            # Fallback: split continuations (``_1``, ``_2``) carry a new
            # filename TS at the split instant, so they only match by
            # internal-time containment against the anchor's window.
            try:
                tr = inspect_bag(sf.path)
            except BagInspectionError as e:
                warnings.append(f"Skipping {sf.path.name}: {e}")
                continue
            tr_start_local = tr.start.astimezone(local_tz)
            a = assign_per_mission(
                sf.path, tr_start_local, catalog, bags_root,
                dst_name=canon_name, extra_note=extra,
            )
            if a.note and DEMOTED_OUTSIDE_MISSION in a.note:
                warnings.append(
                    f"Skipping {sf.path.name}: no anchor matches by filename "
                    f"and internal start {tr.start.isoformat()} falls outside "
                    f"every mission"
                )
                continue
            moves.append(a)

        elif sf.granularity == "per_date":
            a = assign_basic_bag(sf.path, bags_root, local_tz)
            if a is None:
                warnings.append(
                    f"Cannot parse timestamp from {sf.path.name}, skipping"
                )
                continue
            moves.append(a)

        elif sf.granularity == "day_text":
            # Operator .txt note → day folder, keyed by file mtime (the
            # filename date is irregular or absent). mtime is a POSIX epoch
            # (UTC); convert to local_tz so the date folder matches convention.
            mtime = datetime.fromtimestamp(
                sf.path.stat().st_mtime, tz=timezone.utc
            ).astimezone(local_tz)
            moves.append(assign_per_date(sf.path, mtime, bags_root))

    # ---- logs ----
    for sf in walk_logs_root(logs_root):
        if sf.granularity == "image_folder":
            # Camera image folders are raw sensor data → mission's raw/
            # subfolder. Source-driver keyed (parent dir name) so the routing
            # rule lives in one place; a folder matching no mission is demoted.
            mission_subdir = (
                "raw" if sf.path.parent.name in RAW_NATIVE_SOURCES else None
            )
            a = assign_image_folder(
                sf.path, bags_root, catalog, local_tz,
                mission_subdir=mission_subdir,
            )
            if a is None:
                warnings.append(
                    f"Cannot parse timestamp from {sf.path.name}, skipping"
                )
                continue
            moves.append(a)

        elif sf.granularity == "mission_report":
            # Content-aware pairing (#8): read the report's Start/End header and
            # place it in the mission whose bag window overlaps that span. If
            # the header is unreadable, fall back to filename-TS matching at the
            # mission root so the file is never lost.
            window = parse_report_window(sf.path)
            if window is not None:
                moves.append(
                    assign_mission_report(
                        sf.path, window, catalog, bags_root, local_tz
                    )
                )
                continue
            ts_naive = parse_any(sf.path.name)
            if ts_naive is None:
                warnings.append(
                    f"Cannot parse timestamp from {sf.path.name}, skipping"
                )
                continue
            warnings.append(
                f"{sf.path.name}: report header unreadable, "
                f"fell back to filename-TS matching"
            )
            ts_local = ts_naive.replace(tzinfo=timezone.utc).astimezone(local_tz)
            moves.append(
                assign_per_mission(sf.path, ts_local, catalog, bags_root)
            )

        elif sf.granularity == "per_mission":
            ts_naive = parse_any(sf.path.name)
            if ts_naive is None:
                warnings.append(
                    f"Cannot parse timestamp from {sf.path.name}, skipping"
                )
                continue
            ts_local = ts_naive.replace(tzinfo=timezone.utc).astimezone(local_tz)
            # Native sonar recordings (Norbit multibeam, mk_ii sidescan) are
            # grouped under a raw/ subfolder inside the mission folder; every
            # other per-mission source stays at the mission root.
            mission_subdir = (
                "raw" if sf.path.parent.name in RAW_NATIVE_SOURCES else None
            )
            moves.append(
                assign_per_mission(
                    sf.path, ts_local, catalog, bags_root,
                    mission_subdir=mission_subdir,
                )
            )

        elif sf.granularity == "per_date":
            ts_naive = parse_any(sf.path.name)
            if ts_naive is None:
                warnings.append(
                    f"Cannot parse timestamp from {sf.path.name}, skipping"
                )
                continue
            ts_local = ts_naive.replace(tzinfo=timezone.utc).astimezone(local_tz)
            # Per-date daemon logs (emus_bms, iquaview_server) are grouped under
            # <date>/system_logs/. Basic bags and operator .txt notes also use
            # assign_per_date but WITHOUT day_subdir, so they stay at the day root.
            moves.append(
                assign_per_date(
                    sf.path, ts_local, bags_root, day_subdir=SYSTEM_LOG_SUBDIR
                )
            )

    # ---- validation ----
    seen = {}
    for m in moves:
        if m.dst in seen:
            errors.append(
                f"Collision: both {seen[m.dst]} and {m.src} would land at {m.dst}"
            )
        else:
            seen[m.dst] = m.src
        if m.dst.exists():
            errors.append(f"Destination already exists, refusing: {m.dst}")

    return MovePlan(moves=moves, warnings=warnings, errors=errors)
