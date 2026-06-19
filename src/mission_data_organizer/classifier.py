"""Decide where each source file should land, given the mission catalog.

The classifier never moves anything — it only computes destinations.

Time-handling contract:
    - Helpers that parse a filename themselves (``assign_anchor``,
      ``assign_basic_bag``, ``assign_blackfly_folder``) take a ``local_tz``
      argument: they attach UTC to the parsed naive datetime (these
      filenames are all Orat-recorded, hence UTC) and then convert to
      ``local_tz`` for folder rendering.
    - Helpers that receive a pre-parsed timestamp (``assign_per_mission``,
      ``assign_per_date``, ``assign_companion_bag``) expect it to be
      TZ-aware; the caller is responsible for having attached the correct
      TZ at the source. Date-folder rendering uses ``strftime`` on the
      datetime as given — callers wanting a local-TZ date folder must pass
      a local-TZ-aware datetime.
"""
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

from .mission_catalog import Mission
from .timestamp_parser import (
    date_folder_name,
    mission_folder_name,
    parse_bag_timestamp,
)


class Assignment(NamedTuple):
    src: Path
    dst: Path
    note: Optional[str] = None


# Note string written into an :class:`Assignment` when a per-mission
# source could not be placed in any mission's window. Imported by the
# planner so the demote-vs-skip branch is decided on a shared symbol
# rather than a brittle substring match.
DEMOTED_OUTSIDE_MISSION = "demoted: timestamp outside any mission"


# Tolerance for companion-bag filename-TS matching. Parallel
# ``rosbag record`` processes share a launcher invocation but their
# individual process-start instants can straddle a one-second boundary,
# producing companion filenames whose TS is ±1 s from the anchor's.
# Real missions are minutes apart, so this tolerance cannot accidentally
# bind a companion to a neighbouring mission.
COMPANION_FILENAME_TS_TOLERANCE_S = 1.0


# Symmetric tolerance applied to the bag-internal mission window when placing
# non-bag sensor files. A sensor recording can begin up to ~1 s before the
# bag's first message: the bag's filename TS marks when ``rosbag record``
# *started*, while the window's ``start`` is when the first message *arrived*.
# Files in that gap would otherwise be demoted to the day root. Real missions
# are minutes apart, so this tolerance cannot bind a file to a neighbour. Only
# applied to real (non-stub) windows — see :func:`assign_per_mission`.
MISSION_WINDOW_TOLERANCE_S = 2.0


def canonicalize_bag_name(name: str) -> Tuple[str, bool]:
    """Strip the ``.active`` suffix from a ``.bag.active`` file.

    Returns ``(final_name, was_stripped)``.
    """
    if name.endswith(".bag.active"):
        return name[: -len(".active")], True
    return name, False


def _join_notes(*notes: Optional[str]) -> Optional[str]:
    parts = [n for n in notes if n]
    return "; ".join(parts) if parts else None


def assign_per_mission(
    src: Path,
    src_timestamp: datetime,
    catalog: List[Mission],
    bags_root: Path,
    dst_name: Optional[str] = None,
    extra_note: Optional[str] = None,
    mission_subdir: Optional[str] = None,
) -> Assignment:
    """Find the mission whose window contains ``src_timestamp`` and return the
    corresponding :class:`Assignment` to
    ``<bags-root>/YYYY_MM_DD/HH_MM_SS/[<mission_subdir>/]<dst_name or src.name>``.

    ``src_timestamp`` and the catalog's mission windows must agree on
    TZ-awareness so Python's comparison is unambiguous. The recommended
    convention is: catalog UTC-aware (from bag internals); ``src_timestamp``
    TZ-aware in whatever zone is natural at the call site — comparison
    across zones is fine because Python normalizes aware datetimes to UTC.

    The window is widened by :data:`MISSION_WINDOW_TOLERANCE_S` on both ends,
    but only for missions with a real (non-zero-width) internal window. Stub
    anchors (``start == end``, header-only/aborted bags) keep their exact
    zero-width window, so the tolerance never inflates them.

    ``mission_subdir``, when given, is inserted between the mission folder and
    the filename **only on a match** (e.g. ``"raw"`` for native sonar files).
    It is never applied to the demote path — a subfolder is a per-mission
    concept.

    If no mission matches, the file is **demoted** to per-date treatment:
    target becomes ``<bags-root>/YYYY_MM_DD/<dst_name or src.name>`` (the
    date folder is rendered from ``src_timestamp.strftime``, so callers who
    want a local-TZ date should pass a local-TZ-aware datetime).
    """
    if mission_subdir is not None and (
        mission_subdir != Path(mission_subdir).name or not mission_subdir
    ):
        # mission_subdir is joined into the destination path; a separator or an
        # absolute/empty value would silently relocate the file outside the
        # mission folder. Callers pass a hardcoded single component ("raw"); a
        # bad value is a programming error and must stop, not pass silently.
        raise ValueError(
            f"mission_subdir must be a single path component, got {mission_subdir!r}"
        )
    name = dst_name or src.name
    tol = timedelta(seconds=MISSION_WINDOW_TOLERANCE_S)
    for mission in catalog:
        lo, hi = mission.start, mission.end
        # A real (non-stub) window has end > start; widen it by the boundary
        # tolerance. Stub anchors carry a zero-width window (start == end ==
        # filename_ts; mission_catalog.build_catalog) and are matched exactly.
        # A genuine single-message mission also has start == end and is thus
        # deliberately treated as a stub here — such a recording is effectively
        # aborted, so demoting a boundary file near it (rather than widening) is
        # the safe behaviour.
        if hi > lo:
            lo, hi = lo - tol, hi + tol
        if lo <= src_timestamp <= hi:
            dst = bags_root / date_folder_name(mission.date) / mission.folder_name
            if mission_subdir:
                dst = dst / mission_subdir
            dst = dst / name
            return Assignment(src=src, dst=dst, note=extra_note)
    # No match — demote to date level
    dst = bags_root / date_folder_name(src_timestamp) / name
    return Assignment(
        src=src,
        dst=dst,
        note=_join_notes(extra_note, DEMOTED_OUTSIDE_MISSION),
    )


def assign_companion_bag(
    src: Path,
    companion_filename_ts: datetime,
    catalog: List[Mission],
    bags_root: Path,
    dst_name: Optional[str] = None,
    extra_note: Optional[str] = None,
) -> Optional[Assignment]:
    """Place a sensor companion bag (camera/multibeam/sidescan/stereo_camera)
    into the mission folder whose anchor has the closest filename timestamp,
    within :data:`COMPANION_FILENAME_TS_TOLERANCE_S`.

    Companion bags are siblings of the anchor by construction: the mission
    launcher starts all parallel ``rosbag record`` processes together, so
    each companion's filename TS is at most one second off from the
    anchor's (the jitter when parallel process-start instants straddle a
    second boundary). Filename matching is therefore the right key —
    internal-time containment fails on short / aborted missions because
    the parallel processes' first messages skew by tens of milliseconds
    relative to the anchor's window.

    Both ``companion_filename_ts`` and ``mission.filename_ts`` are
    UTC-aware (Orat hardcode). When two missions both fall within the
    tolerance window (a degenerate case — real missions are minutes
    apart), the one with the smaller absolute time delta wins, so an
    exact match always beats a tolerance-only match.

    Returns ``None`` if no anchor lies within the tolerance window
    (caller should fall through to internal-time matching, which is
    correct for split continuations whose filename TS differs from
    every anchor's by more than the tolerance).
    """
    best_mission: Optional[Mission] = None
    best_delta: Optional[float] = None
    for mission in catalog:
        delta = abs(
            (mission.filename_ts - companion_filename_ts).total_seconds()
        )
        if delta > COMPANION_FILENAME_TS_TOLERANCE_S:
            continue
        if best_delta is None or delta < best_delta:
            best_mission = mission
            best_delta = delta
    if best_mission is None:
        return None
    name = dst_name or src.name
    dst = (
        bags_root
        / date_folder_name(best_mission.date)
        / best_mission.folder_name
        / name
    )
    return Assignment(src=src, dst=dst, note=extra_note)


def assign_per_date(
    src: Path,
    src_timestamp: datetime,
    bags_root: Path,
    dst_name: Optional[str] = None,
    extra_note: Optional[str] = None,
) -> Assignment:
    """Return :class:`Assignment` to ``<bags-root>/YYYY_MM_DD/<dst_name or src.name>``.

    The date folder is rendered from ``src_timestamp.strftime`` — callers
    wanting a local-TZ date folder must pass a local-TZ-aware datetime.
    """
    name = dst_name or src.name
    return Assignment(
        src=src,
        dst=bags_root / date_folder_name(src_timestamp) / name,
        note=extra_note,
    )


def assign_basic_bag(
    src: Path, bags_root: Path, local_tz: tzinfo,
) -> Optional[Assignment]:
    """``sparus2_basic_*.bag`` (and ``.bag.active``) land at the date level.

    The filename TS is attached as UTC (Orat) then converted to ``local_tz``
    so the date folder matches the team's local-time convention.
    """
    ts_naive = parse_bag_timestamp(src.name)
    if ts_naive is None:
        return None
    ts_local = ts_naive.replace(tzinfo=timezone.utc).astimezone(local_tz)
    name, stripped = canonicalize_bag_name(src.name)
    note = "active_suffix_stripped" if stripped else None
    return assign_per_date(src, ts_local, bags_root, dst_name=name, extra_note=note)


def assign_anchor(
    src: Path, bags_root: Path, local_tz: tzinfo,
) -> Optional[Assignment]:
    """Main mission bag → ``<bags-root>/YYYY_MM_DD/HH_MM_SS/<name>``.

    Folder names are rendered from the anchor's filename TS (UTC, Orat)
    converted to ``local_tz``.
    """
    ts_naive = parse_bag_timestamp(src.name)
    if ts_naive is None:
        return None
    ts_local = ts_naive.replace(tzinfo=timezone.utc).astimezone(local_tz)
    name, stripped = canonicalize_bag_name(src.name)
    note = "active_suffix_stripped" if stripped else None
    dst = (
        bags_root
        / date_folder_name(ts_local)
        / mission_folder_name(ts_local)
        / name
    )
    return Assignment(src=src, dst=dst, note=note)


def assign_blackfly_folder(
    src: Path,
    bags_root: Path,
    catalog: List[Mission],
    local_tz: tzinfo,
) -> Optional[Assignment]:
    """``blackfly_s/YYYY-MM-DD-HH-MM-SS/`` is moved as a whole folder into
    the matching mission directory.

    The folder name is recorded by the camera daemon on Orat (UTC), so the
    parsed naive timestamp is attached as UTC and then converted to
    ``local_tz`` before being handed to :func:`assign_per_mission`. The
    mission-window comparison is TZ-aware (host-TZ-independent); the
    conversion is what makes the demote-path date folder render in local
    time, consistent with every other source.
    """
    ts_naive = parse_bag_timestamp(src.name)
    if ts_naive is None:
        return None
    ts_local = ts_naive.replace(tzinfo=timezone.utc).astimezone(local_tz)
    return assign_per_mission(src, ts_local, catalog, bags_root)
