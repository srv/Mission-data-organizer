"""Tests for filename-first companion-bag matching.

Sensor companions (``_camera_``, ``_multibeam_``, ``_sidescan_``,
``_stereo_camera_``) are siblings of their anchor by construction — they
share the anchor's filename TS exactly because the mission launcher starts
all parallel ``rosbag record`` processes together. The matching key is
the filename TS; internal-time containment alone would be fragile on
short missions where the parallel processes' first messages skew by tens
of milliseconds.

Split continuations (``_1``, ``_2``) are the one case where filename TS
diverges from any anchor's. They are matched by internal-time containment.
"""
from datetime import datetime, timezone

import pytest

from mission_data_organizer.classifier import (
    assign_companion_bag,
    assign_per_mission,
)
from mission_data_organizer.mission_catalog import Mission, build_catalog

UTC = timezone.utc


def test_companion_with_ms_skew_matches_by_filename(tmp_path):
    """All four sensor companions land in the mission folder even though
    each one's internal start is 50 ms BEFORE the anchor's internal window.
    Filename-first matching makes this case robust against the millisecond
    skew between parallel ``rosbag record`` processes on short missions.
    """
    anchor_ts = datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC)
    catalog = [
        Mission(
            date=datetime(2026, 5, 4, tzinfo=UTC),
            folder_name="09_03_30",
            filename_ts=anchor_ts,
            start=datetime(2026, 5, 4, 9, 3, 30, 739543, tzinfo=UTC),
            end=datetime(2026, 5, 4, 9, 3, 34, 414826, tzinfo=UTC),
            anchor_path=tmp_path / "sparus2_2026-05-04-09-03-30_0.bag",
        )
    ]
    for marker in ("camera", "multibeam", "sidescan", "stereo_camera"):
        companion = tmp_path / f"sparus2_{marker}_2026-05-04-09-03-30_0.bag"
        a = assign_companion_bag(companion, anchor_ts, catalog, tmp_path)
        assert a is not None, f"{marker} should match by filename"
        assert a.dst == (
            tmp_path / "2026_05_04" / "09_03_30" / companion.name
        )
        assert a.note is None


def test_companion_no_anchor_with_same_filename_ts_returns_none(tmp_path):
    """If no anchor in the catalog shares the companion's filename TS,
    assign_companion_bag returns None so the planner can fall through to
    internal-time containment (the split-continuation path)."""
    catalog = [
        Mission(
            date=datetime(2026, 5, 4, tzinfo=UTC),
            folder_name="10_50_33",
            filename_ts=datetime(2026, 5, 4, 10, 50, 33, tzinfo=UTC),
            start=datetime(2026, 5, 4, 10, 50, 33, tzinfo=UTC),
            end=datetime(2026, 5, 4, 11, 30, 0, tzinfo=UTC),
            anchor_path=tmp_path / "sparus2_2026-05-04-10-50-33_0.bag",
        )
    ]
    split_ts = datetime(2026, 5, 4, 10, 52, 0, tzinfo=UTC)
    split = tmp_path / "sparus2_stereo_camera_2026-05-04-10-52-00_1.bag"
    assert assign_companion_bag(split, split_ts, catalog, tmp_path) is None


def test_split_continuation_uses_internal_time(tmp_path):
    """A split's filename TS doesn't match any anchor, so the fallback
    (internal-time containment via assign_per_mission) correctly places it
    in the mission whose [start, end] contains its internal start."""
    catalog = [
        Mission(
            date=datetime(2026, 5, 4, tzinfo=UTC),
            folder_name="10_50_33",
            filename_ts=datetime(2026, 5, 4, 10, 50, 33, tzinfo=UTC),
            start=datetime(2026, 5, 4, 10, 50, 33, tzinfo=UTC),
            end=datetime(2026, 5, 4, 11, 30, 0, tzinfo=UTC),
            anchor_path=tmp_path / "sparus2_2026-05-04-10-50-33_0.bag",
        )
    ]
    split = tmp_path / "sparus2_stereo_camera_2026-05-04-10-52-00_1.bag"
    internal_start = datetime(2026, 5, 4, 11, 0, 0, tzinfo=UTC)
    a = assign_per_mission(split, internal_start, catalog, tmp_path)
    assert a.dst == tmp_path / "2026_05_04" / "10_50_33" / split.name
    assert a.note is None or "demoted" not in a.note


def test_stub_anchor_kept_in_catalog_with_zero_width_window(
    tmp_path, monkeypatch
):
    """An anchor whose internal timestamps are unreadable (4-KB header-only
    stub from an aborted recording) must still appear in the catalog so
    its companions can be matched by filename. The internal window is
    zero-width (start == end == filename_ts), which means the fallback
    internal-time path naturally cannot bind anything spurious to it.
    """
    from mission_data_organizer import mission_catalog as mc

    anchor = tmp_path / "sparus2_2026-05-04-09-03-30_0.bag"
    anchor.write_bytes(b"#ROSBAG V2.0\n")
    companion = tmp_path / "sparus2_camera_2026-05-04-09-03-30_0.bag"
    companion.write_bytes(b"#ROSBAG V2.0\n")

    def fake_inspect(_path):
        raise mc.BagInspectionError("header-only stub")
    monkeypatch.setattr(mc, "inspect_bag", fake_inspect)

    catalog, warnings = build_catalog(tmp_path, UTC)

    assert len(catalog) == 1
    m = catalog[0]
    assert m.filename_ts == datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC)
    assert m.start == m.end == m.filename_ts
    assert any("Stub mission anchor" in w for w in warnings)

    a = assign_companion_bag(companion, m.filename_ts, catalog, tmp_path)
    assert a is not None
    assert a.dst == tmp_path / "2026_05_04" / "09_03_30" / companion.name


def test_companion_one_second_filename_drift_matches(tmp_path):
    """When parallel ``rosbag record`` processes' start instants straddle
    a one-second boundary, the companion's filename TS lands one second
    after the anchor's. The match must still bind them to the same
    mission. (Real-world example: 2026-05-06 Porto Pi anchor at 10:05:30
    paired with sidescan at 10:05:31.)
    """
    catalog = [
        Mission(
            date=datetime(2026, 5, 6, tzinfo=UTC),
            folder_name="12_05_30",
            filename_ts=datetime(2026, 5, 6, 10, 5, 30, tzinfo=UTC),
            start=datetime(2026, 5, 6, 10, 5, 31, 288133, tzinfo=UTC),
            end=datetime(2026, 5, 6, 10, 10, 14, 702580, tzinfo=UTC),
            anchor_path=tmp_path / "sparus2_2026-05-06-10-05-30_0.bag",
        )
    ]
    companion_ts = datetime(2026, 5, 6, 10, 5, 31, tzinfo=UTC)
    companion = tmp_path / "sparus2_sidescan_2026-05-06-10-05-31_0.bag"
    a = assign_companion_bag(companion, companion_ts, catalog, tmp_path)
    assert a is not None
    assert a.dst == tmp_path / "2026_05_06" / "12_05_30" / companion.name


def test_companion_two_second_filename_drift_does_not_match(tmp_path):
    """A two-second drift is beyond plausible parallel-process jitter and
    must fall through to internal-time matching instead of being absorbed
    by the tolerance window."""
    catalog = [
        Mission(
            date=datetime(2026, 5, 6, tzinfo=UTC),
            folder_name="12_05_30",
            filename_ts=datetime(2026, 5, 6, 10, 5, 30, tzinfo=UTC),
            start=datetime(2026, 5, 6, 10, 5, 31, tzinfo=UTC),
            end=datetime(2026, 5, 6, 10, 10, 14, tzinfo=UTC),
            anchor_path=tmp_path / "sparus2_2026-05-06-10-05-30_0.bag",
        )
    ]
    companion_ts = datetime(2026, 5, 6, 10, 5, 32, tzinfo=UTC)
    companion = tmp_path / "sparus2_sidescan_2026-05-06-10-05-32_0.bag"
    assert assign_companion_bag(
        companion, companion_ts, catalog, tmp_path
    ) is None


def test_companion_picks_closest_mission_within_tolerance(tmp_path):
    """When two missions both lie within the tolerance window (a
    degenerate case — real missions are minutes apart), the closer one
    wins. Guards against a tolerance-only false match when an exact
    match exists in the catalog."""
    catalog = [
        Mission(
            date=datetime(2026, 5, 6, tzinfo=UTC),
            folder_name="10_05_30",
            filename_ts=datetime(2026, 5, 6, 10, 5, 30, tzinfo=UTC),
            start=datetime(2026, 5, 6, 10, 5, 30, tzinfo=UTC),
            end=datetime(2026, 5, 6, 10, 6, 0, tzinfo=UTC),
            anchor_path=tmp_path / "a.bag",
        ),
        Mission(
            date=datetime(2026, 5, 6, tzinfo=UTC),
            folder_name="10_05_31",
            filename_ts=datetime(2026, 5, 6, 10, 5, 31, tzinfo=UTC),
            start=datetime(2026, 5, 6, 10, 5, 31, tzinfo=UTC),
            end=datetime(2026, 5, 6, 10, 6, 1, tzinfo=UTC),
            anchor_path=tmp_path / "b.bag",
        ),
    ]
    companion_ts = datetime(2026, 5, 6, 10, 5, 31, tzinfo=UTC)
    companion = tmp_path / "sparus2_camera_2026-05-06-10-05-31_0.bag"
    a = assign_companion_bag(companion, companion_ts, catalog, tmp_path)
    assert a is not None
    assert a.dst.parent.name == "10_05_31"


def test_companion_dual_miss_warns_and_skips(tmp_path, monkeypatch):
    """A companion bag with no filename match against any anchor AND an
    internal start outside every mission window is left in place (not
    demoted). The planner emits a WARNING and the companion is absent
    from the move plan.
    """
    from mission_data_organizer import planner as pl
    from mission_data_organizer.bag_inspector import BagTimeRange

    bags_root = tmp_path / "bags"
    logs_root = tmp_path / "logs"
    bags_root.mkdir()
    logs_root.mkdir()

    anchor = bags_root / "sparus2_2026-05-04-09-03-30_0.bag"
    anchor.write_bytes(b"#ROSBAG V2.0\n")
    orphan_companion = bags_root / "sparus2_camera_2026-05-04-15-00-00_0.bag"
    orphan_companion.write_bytes(b"#ROSBAG V2.0\n")

    anchor_window = BagTimeRange(
        start=datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC),
        end=datetime(2026, 5, 4, 9, 3, 34, tzinfo=UTC),
    )
    orphan_window = BagTimeRange(
        start=datetime(2026, 5, 4, 15, 0, 0, tzinfo=UTC),
        end=datetime(2026, 5, 4, 15, 0, 30, tzinfo=UTC),
    )

    def fake_inspect(path):
        if path.name == anchor.name:
            return anchor_window
        if path.name == orphan_companion.name:
            return orphan_window
        raise AssertionError(f"unexpected inspect_bag call for {path}")

    monkeypatch.setattr(pl, "inspect_bag", fake_inspect)
    monkeypatch.setattr(
        "mission_data_organizer.mission_catalog.inspect_bag", fake_inspect
    )

    plan = pl.build_plan(bags_root, logs_root, UTC)
    move_names = {m.src.name for m in plan.moves}
    assert orphan_companion.name not in move_names, (
        f"orphan companion should not be in the plan: {plan.moves}"
    )
    assert any(
        orphan_companion.name in w and "no anchor matches by filename" in w
        for w in plan.warnings
    ), f"expected warn+skip warning, got: {plan.warnings}"
