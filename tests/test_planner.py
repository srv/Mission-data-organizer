"""Tests for the planner — collisions, missing destinations, dry-run safety."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mission_data_organizer.planner import build_plan

UTC = timezone.utc


def test_dry_run_no_side_effects(tmp_path):
    """Calling build_plan must not create or move any file on disk."""
    bags = tmp_path / "bags"
    logs = tmp_path / "logs"
    bags.mkdir()
    logs.mkdir()
    snapshot_before = sorted(p.name for p in tmp_path.rglob("*"))
    _ = build_plan(bags, logs, UTC)
    snapshot_after = sorted(p.name for p in tmp_path.rglob("*"))
    assert snapshot_before == snapshot_after


def test_empty_roots(tmp_path):
    bags = tmp_path / "bags"
    logs = tmp_path / "logs"
    bags.mkdir()
    logs.mkdir()
    plan = build_plan(bags, logs, UTC)
    assert plan.moves == []
    assert plan.errors == []


def test_missing_roots(tmp_path):
    """Non-existent roots produce an empty plan, not a crash."""
    plan = build_plan(tmp_path / "nope_bags", tmp_path / "nope_logs", UTC)
    assert plan.moves == []
    assert plan.errors == []


def test_logs_native_sonar_routed_to_raw_others_at_mission_root(tmp_path, monkeypatch):
    """Source-driver keying (todo #16): files from norbit_wbms_multibeam/ and
    mk_ii/ land under ``<mission>/raw/``; mission_reports/ and iquaview_server/
    stay at the mission root. Uses the pure-Python bag inspector with a
    monkeypatched window, so no rosbag is needed."""
    from mission_data_organizer import planner as pl
    from mission_data_organizer.bag_inspector import BagTimeRange

    bags_root = tmp_path / "bags"
    logs_root = tmp_path / "logs"
    bags_root.mkdir()
    for sub in ("norbit_wbms_multibeam", "mk_ii",
                "mission_reports", "iquaview_server"):
        (logs_root / sub).mkdir(parents=True)

    anchor = bags_root / "sparus2_2026-05-04-09-03-30_0.bag"
    anchor.write_bytes(b"#ROSBAG V2.0\n")

    s7k = logs_root / "norbit_wbms_multibeam" / "2026-05-04_09-03-32_0.s7k"
    xtf = logs_root / "mk_ii" / "2026-05-04_09-03-33_0.xtf"
    report = logs_root / "mission_reports" / "2026-05-04_09-03-30_mission_report.md"
    iqua = logs_root / "iquaview_server" / "20260504_090330_iquaview_server.log"
    for f in (s7k, xtf, report, iqua):
        f.touch()

    window = BagTimeRange(
        start=datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC),
        end=datetime(2026, 5, 4, 9, 5, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(pl, "inspect_bag", lambda _p: window)
    monkeypatch.setattr(
        "mission_data_organizer.mission_catalog.inspect_bag", lambda _p: window
    )

    plan = build_plan(bags_root, logs_root, UTC)
    by_src = {m.src.name: m.dst for m in plan.moves}
    mission = bags_root / "2026_05_04" / "09_03_30"

    # Native sonar → raw/
    assert by_src[s7k.name] == mission / "raw" / s7k.name
    assert by_src[xtf.name] == mission / "raw" / xtf.name
    # Non-sonar per-mission sources stay at the mission root
    assert by_src[report.name] == mission / report.name
    assert by_src[iqua.name] == mission / iqua.name


def test_unparseable_per_mission_filename_skipped(tmp_path, monkeypatch):
    """A per-mission source file with no parseable timestamp is skipped with a
    warning, never assigned. This is what makes a file-vs-directory clash on the
    ``raw/`` component unreachable: a file literally named ``raw`` (no timestamp)
    cannot reach the classifier, so it can never target ``<mission>/raw`` as a
    file while siblings use ``<mission>/raw/<name>`` as a directory."""
    from mission_data_organizer import planner as pl
    from mission_data_organizer.bag_inspector import BagTimeRange

    bags_root = tmp_path / "bags"
    logs_root = tmp_path / "logs"
    bags_root.mkdir()
    (logs_root / "norbit_wbms_multibeam").mkdir(parents=True)

    anchor = bags_root / "sparus2_2026-05-04-09-03-30_0.bag"
    anchor.write_bytes(b"#ROSBAG V2.0\n")
    # A norbit file whose name carries no timestamp.
    bad = logs_root / "norbit_wbms_multibeam" / "raw"
    bad.touch()

    window = BagTimeRange(
        start=datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC),
        end=datetime(2026, 5, 4, 9, 5, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(pl, "inspect_bag", lambda _p: window)
    monkeypatch.setattr(
        "mission_data_organizer.mission_catalog.inspect_bag", lambda _p: window
    )

    plan = build_plan(bags_root, logs_root, UTC)
    assert bad.name not in {m.src.name for m in plan.moves}
    assert any("raw" in w for w in plan.warnings)


# Other planner tests (collision detection, idempotent re-runs) are best
# exercised by the smoke test in test_smoke.py, which runs the full
# pipeline against generated fixtures with real bag files.
