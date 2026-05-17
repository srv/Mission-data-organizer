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
    assign_blackfly_folder,
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


def test_per_date(tmp_path):
    src = tmp_path / "bms_events_00004CFB_2026_05_04.log"
    a = assign_per_date(src, datetime(2026, 5, 4, tzinfo=UTC), tmp_path)
    assert a.dst == tmp_path / "2026_05_04" / src.name


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


def test_blackfly_folder_in_range(tmp_path, catalog):
    src = tmp_path / "2026-05-04-09-03-30"   # filename matches mission 1 anchor
    a = assign_blackfly_folder(src, tmp_path, catalog, UTC)
    assert a.dst == tmp_path / "2026_05_04" / "09_03_30" / src.name


def test_blackfly_folder_orphan_demoted(tmp_path, catalog):
    src = tmp_path / "2026-05-04-15-00-00"
    a = assign_blackfly_folder(src, tmp_path, catalog, UTC)
    assert a.dst == tmp_path / "2026_05_04" / src.name
    assert a.note is not None and "demoted" in a.note
