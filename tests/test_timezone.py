"""Tests for timezone-explicit comparisons.

The script's deployment target is Orat (UTC system clock). Every
non-bag source's driver (Norbit multibeam, mk_ii sidescan, iquaview
server) runs on Orat itself, so non-bag filenames are also UTC strings.
All comparisons between filename-derived and bag-internal timestamps
happen between TZ-aware datetimes, so the script's behaviour is
independent of the host TZ.

These tests pin the invariants:
    1. ``--local-tz=Europe/Madrid`` renders mission folders in CEST.
    2. A non-bag sensor filename (written in UTC by an Orat-resident
       driver) correctly matches a UTC bag window.
    3. Classifier helpers accept any TZ-aware input and normalise.
    4. Classifier results are identical regardless of host TZ.
"""
import os
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dateutil import tz as _tz

from mission_data_organizer.bag_inspector import _parse_time
from mission_data_organizer.classifier import (
    assign_anchor,
    assign_basic_bag,
    assign_per_mission,
)
from mission_data_organizer.mission_catalog import Mission


MADRID = _tz.gettz("Europe/Madrid")
UTC = timezone.utc


def test_local_tz_madrid_renders_folder_in_local(tmp_path):
    """A bag filename 09-03-30 (Orat UTC) → mission folder 11_03_30 in CEST
    (May → DST → UTC+2). Folder names follow the team's local-time
    convention.
    """
    src = tmp_path / "sparus2_2026-05-04-09-03-30_0.bag"
    a = assign_anchor(src, tmp_path, MADRID)
    assert a is not None
    assert a.dst == tmp_path / "2026_05_04" / "11_03_30" / src.name


def test_local_tz_madrid_basic_bag_late_night_date_rolls_over(tmp_path):
    """A basic bag at 23:30 UTC = 01:30 CEST the next day must land under
    the local-CEST date folder."""
    src = tmp_path / "sparus2_basic_2026-05-04-23-30-00_0.bag"
    a = assign_basic_bag(src, tmp_path, MADRID)
    assert a is not None
    # 23:30 UTC + 2h = 01:30 CEST on 2026-05-05.
    assert a.dst == tmp_path / "2026_05_05" / src.name


def test_assign_per_mission_normalises_across_tzs(tmp_path):
    """``assign_per_mission`` accepts any TZ-aware ``src_timestamp`` and
    compares correctly against UTC bag windows. Python normalises both
    sides to UTC internally; we exercise that with a hypothetical
    Madrid-aware input to prove the comparison itself is TZ-agnostic.
    The planner does not actually produce Madrid-aware inputs anymore
    (see ``test_planner_attaches_utc_to_non_bag_filenames``) but the
    invariant is still worth pinning, since any future source that
    happens to be Madrid-clocked would Just Work.
    """
    catalog = [
        Mission(
            date=datetime(2026, 5, 4, tzinfo=MADRID),
            folder_name="11_03_30",
            filename_ts=datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC),
            # Bag internal window in UTC.
            start=datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC),
            end=datetime(2026, 5, 4, 9, 3, 34, tzinfo=UTC),
            anchor_path=tmp_path / "sparus2_2026-05-04-09-03-30_0.bag",
        ),
    ]
    s7k = tmp_path / "2026-05-04_11-03-32_0.s7k"
    # Hypothetical CEST-aware: 11:03:32 CEST = 09:03:32 UTC, inside window.
    ts_madrid = datetime(2026, 5, 4, 11, 3, 32, tzinfo=MADRID)
    a = assign_per_mission(s7k, ts_madrid, catalog, tmp_path)
    assert a.dst == tmp_path / "2026_05_04" / "11_03_30" / s7k.name
    assert a.note is None


def test_planner_attaches_utc_to_non_bag_filenames(tmp_path, monkeypatch):
    """``build_plan`` must attach UTC to non-bag sensor filenames so that
    a ``.s7k`` whose filename TS is UTC (the real on-Orat convention)
    matches the bag's UTC internal window.

    Regression guard for the residual leg of Bug 2 (issue #9): an earlier
    revision attached ``local_tz`` here, which silently shifted every
    sensor file ±2 h on a CEST configuration and demoted them all on the
    real Orat layout.
    """
    from mission_data_organizer import planner as pl
    from mission_data_organizer.bag_inspector import BagTimeRange

    bags_root = tmp_path / "bags"
    logs_root = tmp_path / "logs"
    bags_root.mkdir()
    (logs_root / "norbit_wbms_multibeam").mkdir(parents=True)

    # Anchor bag with UTC-named filename, internal window also UTC.
    anchor = bags_root / "sparus2_2026-05-04-09-03-30_0.bag"
    anchor.write_bytes(b"#ROSBAG V2.0\n")
    # Sensor filename written in UTC by the on-Orat driver; falls inside
    # the bag's UTC window [09:03:30, 09:03:34].
    s7k = logs_root / "norbit_wbms_multibeam" / "2026-05-04_09-03-32_0.s7k"
    s7k.touch()
    # And another sensor file that would only land in the mission folder
    # if the filename is read as UTC (under the Bug 2 residual it would
    # be read as Madrid → 07:03:33 UTC, demoted to day-root).
    s7k2 = logs_root / "norbit_wbms_multibeam" / "2026-05-04_09-03-33_0.s7k"
    s7k2.touch()

    fake_window = BagTimeRange(
        start=datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC),
        end=datetime(2026, 5, 4, 9, 3, 34, tzinfo=UTC),
    )

    def fake_inspect(_path):
        return fake_window

    monkeypatch.setattr(pl, "inspect_bag", fake_inspect)
    monkeypatch.setattr(
        "mission_data_organizer.mission_catalog.inspect_bag", fake_inspect
    )

    plan = pl.build_plan(bags_root, logs_root, MADRID)
    by_src = {m.src.name: m.dst for m in plan.moves}

    mission_dir = bags_root / "2026_05_04" / "11_03_30"
    assert by_src[s7k.name] == mission_dir / s7k.name, (
        f"sensor file with UTC filename {s7k.name} should land in the "
        f"mission folder; got {by_src[s7k.name]}"
    )
    assert by_src[s7k2.name] == mission_dir / s7k2.name


def test_results_identical_on_utc_host_simulating_orat(tmp_path):
    """Every classifier helper produces identical results regardless of
    the host's TZ. The script never reads ``os.environ['TZ']``; flipping
    ``TZ`` and calling ``time.tzset()`` is a no-op for the placement.
    """
    src_anchor = tmp_path / "sparus2_2026-05-04-09-03-30_0.bag"
    src_basic = tmp_path / "sparus2_basic_2026-05-04-23-30-00_0.bag"

    def run():
        return (
            assign_anchor(src_anchor, tmp_path, MADRID).dst,
            assign_basic_bag(src_basic, tmp_path, MADRID).dst,
        )

    saved_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "UTC"
        time.tzset()
        utc_results = run()

        os.environ["TZ"] = "Europe/Madrid"
        time.tzset()
        cest_results = run()
    finally:
        if saved_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved_tz
        time.tzset()

    assert utc_results == cest_results


def test_build_plan_identical_on_utc_and_cest_hosts(tmp_path, monkeypatch):
    """``build_plan`` (the end-to-end planner driver) produces an identical
    move set under host ``TZ=UTC`` and ``TZ=Europe/Madrid``. Pins the
    invariant that the full pipeline — catalog build, bag inspection,
    classifier helpers, demotion paths — has no implicit host-TZ
    dependency.
    """
    from mission_data_organizer import planner as pl
    from mission_data_organizer.bag_inspector import BagTimeRange

    bags_root = tmp_path / "bags"
    logs_root = tmp_path / "logs"
    bags_root.mkdir()
    (logs_root / "norbit_wbms_multibeam").mkdir(parents=True)

    anchor = bags_root / "sparus2_2026-05-04-09-03-30_0.bag"
    anchor.write_bytes(b"#ROSBAG V2.0\n")
    s7k = logs_root / "norbit_wbms_multibeam" / "2026-05-04_11-03-32_0.s7k"
    s7k.touch()

    fake_window = BagTimeRange(
        start=datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC),
        end=datetime(2026, 5, 4, 9, 3, 34, tzinfo=UTC),
    )

    def fake_inspect(_path):
        return fake_window

    monkeypatch.setattr(pl, "inspect_bag", fake_inspect)
    monkeypatch.setattr(
        "mission_data_organizer.mission_catalog.inspect_bag", fake_inspect
    )

    def run():
        plan = pl.build_plan(bags_root, logs_root, MADRID)
        return sorted((m.src.name, m.dst.as_posix()) for m in plan.moves)

    saved_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "UTC"
        time.tzset()
        utc_plan = run()

        os.environ["TZ"] = "Europe/Madrid"
        time.tzset()
        cest_plan = run()
    finally:
        if saved_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved_tz
        time.tzset()

    assert utc_plan == cest_plan
    assert any("11_03_30" in dst for _, dst in utc_plan)


def test_parse_time_is_host_tz_independent():
    """``_parse_time`` returns the same UTC-aware datetime for the same
    raw bytes regardless of the host TZ. Concrete example uses the epoch
    from a real ``sparus2_2026-05-04-09-03-30_0.bag``.
    """
    raw = struct.pack("<II", 1777885410, 739543000)

    saved_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "UTC"
        time.tzset()
        result_utc = _parse_time(raw)

        os.environ["TZ"] = "Europe/Madrid"
        time.tzset()
        result_cest = _parse_time(raw)
    finally:
        if saved_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved_tz
        time.tzset()

    assert result_utc == result_cest
    expected = datetime(2026, 5, 4, 9, 3, 30, 739543, tzinfo=UTC)
    # Float-precision slack: compare seconds and microseconds separately.
    assert result_utc.year == expected.year
    assert result_utc.month == expected.month
    assert result_utc.day == expected.day
    assert result_utc.hour == expected.hour
    assert result_utc.minute == expected.minute
    assert result_utc.second == expected.second
    assert abs(result_utc.microsecond - expected.microsecond) < 2
    assert result_utc.tzinfo is UTC
