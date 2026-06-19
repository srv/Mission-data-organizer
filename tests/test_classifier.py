"""Tests for the source-file → destination classifier.

Tests use ``local_tz=timezone.utc`` for simplicity: with UTC as the local
TZ, no time conversion happens, so folder name assertions stay free of
TZ arithmetic. Phase B's actual TZ behaviour is exercised in
``test_timezone.py``.
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest

UTC = timezone.utc

from mission_data_organizer.classifier import (
    Assignment,
    assign_anchor,
    assign_basic_bag,
    assign_image_folder,
    assign_mission_report,
    assign_per_date,
    assign_per_mission,
    canonicalize_bag_name,
)
from mission_data_organizer.mission_catalog import Mission


@pytest.fixture
def catalog(tmp_path: Path):
    return [
        Mission(
            date=datetime(2026, 5, 4, tzinfo=UTC),
            folder_name="09_03_30",
            filename_ts=datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC),
            start=datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC),
            end=datetime(2026, 5, 4, 9, 12, 0, tzinfo=UTC),
            anchor_path=tmp_path / "sparus2_2026-05-04-09-03-30_0.bag",
        ),
        Mission(
            date=datetime(2026, 5, 4, tzinfo=UTC),
            folder_name="10_50_33",
            filename_ts=datetime(2026, 5, 4, 10, 50, 33, tzinfo=UTC),
            start=datetime(2026, 5, 4, 10, 50, 33, tzinfo=UTC),
            end=datetime(2026, 5, 4, 11, 30, 0, tzinfo=UTC),
            anchor_path=tmp_path / "sparus2_2026-05-04-10-50-33_0.bag",
        ),
    ]


def test_canonicalize_bag_name():
    assert canonicalize_bag_name("foo.bag") == ("foo.bag", False)
    assert canonicalize_bag_name("foo.bag.active") == ("foo.bag", True)


def test_per_mission_in_range(tmp_path, catalog):
    src = tmp_path / "sparus2_camera_2026-05-04-09-03-31_0.bag"
    a = assign_per_mission(
        src, datetime(2026, 5, 4, 9, 3, 31, tzinfo=UTC), catalog, tmp_path
    )
    assert a.dst == tmp_path / "2026_05_04" / "09_03_30" / src.name
    assert a.note is None


def test_per_mission_orphan_demoted(tmp_path, catalog):
    src = tmp_path / "20260504_120000_iquaview_server.log"
    a = assign_per_mission(
        src, datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC), catalog, tmp_path
    )
    assert a.dst == tmp_path / "2026_05_04" / src.name
    assert a.note is not None and "demoted" in a.note


def test_per_mission_overlap_uses_first_match(tmp_path):
    """If a timestamp is in two missions' ranges (shouldn't happen with
    sane bags, but defensive), we take the first match. This documents the
    behavior; production data should not exhibit overlap."""
    cat = [
        Mission(
            date=datetime(2026, 5, 4, tzinfo=UTC),
            folder_name="09_00_00",
            filename_ts=datetime(2026, 5, 4, 9, 0, 0, tzinfo=UTC),
            start=datetime(2026, 5, 4, 9, 0, 0, tzinfo=UTC),
            end=datetime(2026, 5, 4, 9, 30, 0, tzinfo=UTC),
            anchor_path=tmp_path / "a.bag",
        ),
        Mission(
            date=datetime(2026, 5, 4, tzinfo=UTC),
            folder_name="09_15_00",
            filename_ts=datetime(2026, 5, 4, 9, 15, 0, tzinfo=UTC),
            start=datetime(2026, 5, 4, 9, 15, 0, tzinfo=UTC),
            end=datetime(2026, 5, 4, 9, 45, 0, tzinfo=UTC),
            anchor_path=tmp_path / "b.bag",
        ),
    ]
    src = tmp_path / "sparus2_camera_2026-05-04-09-20-00_0.bag"
    a = assign_per_mission(
        src, datetime(2026, 5, 4, 9, 20, 0, tzinfo=UTC), cat, tmp_path
    )
    assert a.dst.parent.name == "09_00_00"


# --- mission_subdir (raw/ grouping for native sonar — todo #16) ---

def test_per_mission_subdir_inserted_on_match(tmp_path, catalog):
    """``mission_subdir`` is inserted between the mission folder and the
    filename when a mission matches (used to group native sonar under raw/)."""
    src = tmp_path / "2026-05-04_09-03-32_0.s7k"
    a = assign_per_mission(
        src, datetime(2026, 5, 4, 9, 3, 32, tzinfo=UTC), catalog, tmp_path,
        mission_subdir="raw",
    )
    assert a.dst == tmp_path / "2026_05_04" / "09_03_30" / "raw" / src.name
    assert a.note is None


def test_per_mission_rejects_non_component_subdir(tmp_path, catalog):
    """``mission_subdir`` is joined into the destination path; a separator,
    absolute, or empty value would relocate the file outside the mission
    folder, so it is rejected loudly (stop execution, not silent)."""
    src = tmp_path / "2026-05-04_09-03-32_0.s7k"
    ts = datetime(2026, 5, 4, 9, 3, 32, tzinfo=UTC)
    for bad in ("a/b", "/abs", "", "sub/raw"):
        with pytest.raises(ValueError):
            assign_per_mission(
                src, ts, catalog, tmp_path, mission_subdir=bad
            )


def test_per_mission_subdir_not_applied_on_demote(tmp_path, catalog):
    """A subfolder is a per-mission concept: a demoted file lands at the day
    root, never under ``<date>/raw/``."""
    src = tmp_path / "2026-05-04_14-00-00_0.s7k"
    a = assign_per_mission(
        src, datetime(2026, 5, 4, 14, 0, 0, tzinfo=UTC), catalog, tmp_path,
        mission_subdir="raw",
    )
    assert a.dst == tmp_path / "2026_05_04" / src.name
    assert a.note is not None and "demoted" in a.note


# --- mission-window boundary tolerance (todo #12) ---

def test_per_mission_window_tolerance_rescues_boundary_file(tmp_path, catalog):
    """A sensor file arriving just before a real mission's internal start (the
    gap between recording-process start and first-message arrival) is pulled
    into that mission rather than demoted. Shown together with raw/ grouping."""
    # Mission 1 starts at 09:03:30; this .s7k is 1.5 s earlier — inside the 2 s
    # tolerance, so it must land in mission 1's raw/ folder, not at day root.
    src = tmp_path / "2026-05-04_09-03-28_0.s7k"
    ts = datetime(2026, 5, 4, 9, 3, 28, 500000, tzinfo=UTC)
    a = assign_per_mission(src, ts, catalog, tmp_path, mission_subdir="raw")
    assert a.dst == tmp_path / "2026_05_04" / "09_03_30" / "raw" / src.name
    assert a.note is None


def test_per_mission_window_tolerance_is_symmetric(tmp_path, catalog):
    """The tolerance widens both ends — a file just after the internal end
    still lands in the mission."""
    # Mission 1 ends at 09:12:00; 1.5 s later is still within tolerance.
    src = tmp_path / "2026-05-04_09-12-01_0.s7k"
    ts = datetime(2026, 5, 4, 9, 12, 1, 500000, tzinfo=UTC)
    a = assign_per_mission(src, ts, catalog, tmp_path)
    assert a.dst.parent.name == "09_03_30"
    assert a.note is None


def test_per_mission_beyond_tolerance_still_demoted(tmp_path, catalog):
    """A file well outside the window (beyond the tolerance) is still demoted."""
    # 5 s before mission 1's start — outside the 2 s tolerance.
    src = tmp_path / "2026-05-04_09-03-25_0.s7k"
    ts = datetime(2026, 5, 4, 9, 3, 25, tzinfo=UTC)
    a = assign_per_mission(src, ts, catalog, tmp_path, mission_subdir="raw")
    assert a.dst == tmp_path / "2026_05_04" / src.name
    assert a.note is not None and "demoted" in a.note


def _stub_catalog(tmp_path):
    """A single stub mission: zero-width window (start == end == filename TS),
    as built by ``build_catalog`` for header-only / aborted anchors."""
    stub_ts = datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC)
    return stub_ts, [
        Mission(
            date=datetime(2026, 5, 4, tzinfo=UTC),
            folder_name="09_03_30",
            filename_ts=stub_ts,
            start=stub_ts,
            end=stub_ts,
            anchor_path=tmp_path / "sparus2_2026-05-04-09-03-30_0.bag",
        ),
    ]


def test_per_mission_stub_window_not_widened_by_tolerance(tmp_path):
    """Stub anchors keep their exact zero-width window — a file 1 s away from
    the stub TS is NOT captured, so aborted-mission behaviour is unchanged
    (latent #6)."""
    stub_ts, cat = _stub_catalog(tmp_path)
    src = tmp_path / "2026-05-04_09-03-31_0.s7k"
    ts = datetime(2026, 5, 4, 9, 3, 31, tzinfo=UTC)  # 1 s after the stub TS
    a = assign_per_mission(src, ts, cat, tmp_path, mission_subdir="raw")
    assert a.dst == tmp_path / "2026_05_04" / src.name  # demoted, no raw/
    assert a.note is not None and "demoted" in a.note


def test_per_mission_stub_window_exact_match_still_binds(tmp_path):
    """At exactly the stub's TS the file still binds to the stub mission
    (unchanged zero-width behaviour)."""
    stub_ts, cat = _stub_catalog(tmp_path)
    src = tmp_path / "2026-05-04_09-03-30_0.s7k"
    a = assign_per_mission(src, stub_ts, cat, tmp_path, mission_subdir="raw")
    assert a.dst == tmp_path / "2026_05_04" / "09_03_30" / "raw" / src.name
    assert a.note is None


def test_per_date(tmp_path):
    src = tmp_path / "bms_events_00004CFB_2026_05_04.log"
    a = assign_per_date(src, datetime(2026, 5, 4, tzinfo=UTC), tmp_path)
    assert a.dst == tmp_path / "2026_05_04" / src.name


# --- assign_per_date day_subdir (system_logs/ grouping — todo #19) ---

def test_per_date_day_subdir_inserted(tmp_path):
    """``day_subdir`` groups per-date daemon logs under <date>/<subdir>/."""
    src = tmp_path / "20260504_090330_iquaview_server.log"
    a = assign_per_date(
        src, datetime(2026, 5, 4, tzinfo=UTC), tmp_path,
        day_subdir="system_logs",
    )
    assert a.dst == tmp_path / "2026_05_04" / "system_logs" / src.name


def test_per_date_rejects_non_component_subdir(tmp_path):
    """A separator / absolute / empty ``day_subdir`` is rejected loudly."""
    src = tmp_path / "x.log"
    ts = datetime(2026, 5, 4, tzinfo=UTC)
    for bad in ("a/b", "/abs", "", "sub/logs"):
        with pytest.raises(ValueError):
            assign_per_date(src, ts, tmp_path, day_subdir=bad)


# --- assign_mission_report (content-aware window overlap — todo #8) ---

def test_mission_report_overlap_places_in_mission(tmp_path, catalog):
    """A report whose [Start, End] overlaps mission 1's bag window lands in
    mission 1's root, even though its Start precedes the bag's internal start."""
    src = tmp_path / "2026-05-04_09-03-30_mission_report.md"
    window = (
        datetime(2026, 5, 4, 9, 3, 25, tzinfo=UTC),   # before mission 1 start
        datetime(2026, 5, 4, 9, 5, 0, tzinfo=UTC),
    )
    a = assign_mission_report(src, window, catalog, tmp_path, UTC)
    assert a.dst == tmp_path / "2026_05_04" / "09_03_30" / src.name
    assert a.note is None


def test_mission_report_picks_largest_overlap(tmp_path, catalog):
    """When a report spans into two missions, the one with the most overlap
    wins (catalog mission 2 is 10:50:33–11:30:00)."""
    src = tmp_path / "r.md"
    window = (
        datetime(2026, 5, 4, 11, 0, 0, tzinfo=UTC),
        datetime(2026, 5, 4, 11, 20, 0, tzinfo=UTC),
    )
    a = assign_mission_report(src, window, catalog, tmp_path, UTC)
    assert a.dst.parent.name == "10_50_33"


def test_mission_report_no_overlap_demoted(tmp_path, catalog):
    """A report overlapping no mission window is demoted to the day root,
    keyed on its Start time converted to local TZ."""
    src = tmp_path / "r.md"
    window = (
        datetime(2026, 5, 4, 14, 0, 0, tzinfo=UTC),
        datetime(2026, 5, 4, 14, 30, 0, tzinfo=UTC),
    )
    a = assign_mission_report(src, window, catalog, tmp_path, UTC)
    assert a.dst == tmp_path / "2026_05_04" / src.name
    assert a.note is not None and "demoted" in a.note


def test_mission_report_stub_zero_width_demoted(tmp_path):
    """A zero-width stub window has no positive overlap, so the report demotes
    (it never binds to an aborted mission)."""
    stub_ts, cat = _stub_catalog(tmp_path)
    src = tmp_path / "r.md"
    window = (stub_ts, stub_ts)
    a = assign_mission_report(src, window, cat, tmp_path, UTC)
    assert a.dst == tmp_path / "2026_05_04" / src.name
    assert a.note is not None and "demoted" in a.note


def test_basic_bag_active_suffix_stripped(tmp_path):
    src = tmp_path / "sparus2_basic_2026-05-04-08-06-06_0.bag.active"
    a = assign_basic_bag(src, tmp_path, UTC)
    assert a is not None
    assert a.dst.name == "sparus2_basic_2026-05-04-08-06-06_0.bag"
    assert a.dst == tmp_path / "2026_05_04" / "sparus2_basic_2026-05-04-08-06-06_0.bag"
    assert a.note == "active_suffix_stripped"


def test_basic_bag_no_suffix(tmp_path):
    src = tmp_path / "sparus2_basic_2026-05-04-08-06-06_0.bag"
    a = assign_basic_bag(src, tmp_path, UTC)
    assert a.dst.name == src.name
    assert a.note is None


def test_basic_bag_unparseable(tmp_path):
    src = tmp_path / "sparus2_basic_no_timestamp.bag"
    a = assign_basic_bag(src, tmp_path, UTC)
    assert a is None


def test_anchor_assignment(tmp_path):
    src = tmp_path / "sparus2_2026-05-04-09-03-30_0.bag"
    a = assign_anchor(src, tmp_path, UTC)
    assert a.dst == tmp_path / "2026_05_04" / "09_03_30" / src.name


def test_anchor_active_suffix_stripped(tmp_path):
    src = tmp_path / "sparus2_2026-05-04-09-03-30_0.bag.active"
    a = assign_anchor(src, tmp_path, UTC)
    assert a.dst.name == "sparus2_2026-05-04-09-03-30_0.bag"
    assert a.note == "active_suffix_stripped"


def test_image_folder_in_range(tmp_path, catalog):
    """Default (no mission_subdir) places a camera folder at the mission root."""
    src = tmp_path / "2026-05-04-09-03-30"   # filename matches mission 1 anchor
    a = assign_image_folder(src, tmp_path, catalog, UTC)
    assert a.dst == tmp_path / "2026_05_04" / "09_03_30" / src.name


def test_image_folder_under_raw(tmp_path, catalog):
    """``mission_subdir="raw"`` routes the camera folder into the mission's
    raw/ subfolder (how blackfly_s and flir_spinnaker_* are filed — todo #18)."""
    src = tmp_path / "2026-05-04-09-03-30"
    a = assign_image_folder(src, tmp_path, catalog, UTC, mission_subdir="raw")
    assert a.dst == tmp_path / "2026_05_04" / "09_03_30" / "raw" / src.name


def test_image_folder_orphan_demoted(tmp_path, catalog):
    """A camera folder matching no mission is demoted to the day root (no
    raw/ — a subfolder is a per-mission concept)."""
    src = tmp_path / "2026-05-04-15-00-00"
    a = assign_image_folder(src, tmp_path, catalog, UTC, mission_subdir="raw")
    assert a.dst == tmp_path / "2026_05_04" / src.name
    assert a.note is not None and "demoted" in a.note
