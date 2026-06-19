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


def _stub_window(monkeypatch, start, end):
    """Monkeypatch the bag inspector (planner + catalog) to a fixed window so
    no real bag parsing / rosbag is needed."""
    from mission_data_organizer import planner as pl
    from mission_data_organizer.bag_inspector import BagTimeRange

    window = BagTimeRange(start=start, end=end)
    monkeypatch.setattr(pl, "inspect_bag", lambda _p: window)
    monkeypatch.setattr(
        "mission_data_organizer.mission_catalog.inspect_bag", lambda _p: window
    )


def _report_text(start, end):
    return (
        "# Mission reports 00:00:00 01/01/2026\n## Mission1\n"
        f"- Start time: {start}\n- End time:   {end}\n"
    )


def test_logs_routing_raw_reports_system_logs(tmp_path, monkeypatch):
    """Source-driver routing: norbit/mk_ii → ``<mission>/raw/``; a
    mission_report whose header overlaps the window → mission root (content
    aware); iquaview_server (now per-date) → ``<date>/system_logs/``."""
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
    for f in (s7k, xtf, iqua):
        f.touch()
    report.write_text(_report_text("2026/05/04 09:03:30", "2026/05/04 09:05:00"))

    _stub_window(monkeypatch,
                 datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC),
                 datetime(2026, 5, 4, 9, 5, 0, tzinfo=UTC))

    plan = build_plan(bags_root, logs_root, UTC)
    by_src = {m.src.name: m.dst for m in plan.moves}
    date_dir = bags_root / "2026_05_04"
    mission = date_dir / "09_03_30"

    # Native sonar → raw/
    assert by_src[s7k.name] == mission / "raw" / s7k.name
    assert by_src[xtf.name] == mission / "raw" / xtf.name
    # Report → mission root (content-aware overlap)
    assert by_src[report.name] == mission / report.name
    # iquaview daemon log → day-level system_logs/
    assert by_src[iqua.name] == date_dir / "system_logs" / iqua.name


def test_mission_report_paired_despite_pre_bag_filename(tmp_path, monkeypatch):
    """The #8 fix: a report whose *filename* TS is well before the bag window
    (so filename matching would demote it) still lands in the mission because
    its header [Start, End] overlaps the bag window."""
    bags_root = tmp_path / "bags"
    logs_root = tmp_path / "logs"
    bags_root.mkdir()
    (logs_root / "mission_reports").mkdir(parents=True)

    (bags_root / "sparus2_2026-05-04-09-03-30_0.bag").write_bytes(b"#ROSBAG V2.0\n")
    # Filename TS 09:02:30 — a full minute before the bag window's start.
    report = logs_root / "mission_reports" / "2026-05-04_09-02-30_mission_report.md"
    report.write_text(_report_text("2026/05/04 09:02:30", "2026/05/04 09:05:00"))

    _stub_window(monkeypatch,
                 datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC),
                 datetime(2026, 5, 4, 9, 5, 0, tzinfo=UTC))

    plan = build_plan(bags_root, logs_root, UTC)
    by_src = {m.src.name: m.dst for m in plan.moves}
    assert by_src[report.name] == bags_root / "2026_05_04" / "09_03_30" / report.name


def test_unreadable_report_falls_back_to_filename(tmp_path, monkeypatch):
    """An empty/headerless report is never lost: it falls back to filename-TS
    matching (mission root) and a warning is emitted."""
    bags_root = tmp_path / "bags"
    logs_root = tmp_path / "logs"
    bags_root.mkdir()
    (logs_root / "mission_reports").mkdir(parents=True)

    (bags_root / "sparus2_2026-05-04-09-03-30_0.bag").write_bytes(b"#ROSBAG V2.0\n")
    report = logs_root / "mission_reports" / "2026-05-04_09-03-30_mission_report.md"
    report.touch()   # empty → no header

    _stub_window(monkeypatch,
                 datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC),
                 datetime(2026, 5, 4, 9, 5, 0, tzinfo=UTC))

    plan = build_plan(bags_root, logs_root, UTC)
    by_src = {m.src.name: m.dst for m in plan.moves}
    assert by_src[report.name] == bags_root / "2026_05_04" / "09_03_30" / report.name
    assert any("report header unreadable" in w for w in plan.warnings)


def test_image_folders_routed_to_raw(tmp_path, monkeypatch):
    """blackfly_s and flir_spinnaker_* image folders both move whole into the
    matching mission's raw/ subfolder (todo #18; blackfly→raw per decision)."""
    bags_root = tmp_path / "bags"
    logs_root = tmp_path / "logs"
    bags_root.mkdir()

    (bags_root / "sparus2_2026-05-04-09-03-30_0.bag").write_bytes(b"#ROSBAG V2.0\n")
    bf = logs_root / "blackfly_s" / "2026-05-04-09-03-30"
    flir = logs_root / "flir_spinnaker_stereo_camera" / "2026-05-04-09-04-00"
    for d in (bf, flir):
        d.mkdir(parents=True)
        (d / "x_port.jpg").touch()

    _stub_window(monkeypatch,
                 datetime(2026, 5, 4, 9, 3, 30, tzinfo=UTC),
                 datetime(2026, 5, 4, 9, 5, 0, tzinfo=UTC))

    plan = build_plan(bags_root, logs_root, UTC)
    by_src = {m.src.name: m.dst for m in plan.moves}
    mission = bags_root / "2026_05_04" / "09_03_30"
    assert by_src["2026-05-04-09-03-30"] == mission / "raw" / "2026-05-04-09-03-30"
    assert by_src["2026-05-04-09-04-00"] == mission / "raw" / "2026-05-04-09-04-00"


def test_day_text_filed_by_mtime(tmp_path):
    """A root-level operator .txt note is filed into the day folder by file
    mtime, regardless of (irregular/absent) filename date."""
    import os
    bags_root = tmp_path / "bags"
    logs_root = tmp_path / "logs"
    bags_root.mkdir()
    logs_root.mkdir()

    note = bags_root / "readme.txt"   # dateless name
    note.write_text("operator note\n")
    mtime = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC).timestamp()
    os.utime(note, (mtime, mtime))

    plan = build_plan(bags_root, logs_root, UTC)
    by_src = {m.src.name: m.dst for m in plan.moves}
    assert by_src["readme.txt"] == bags_root / "2026_05_04" / "readme.txt"


def test_folder_sources_all_route_to_raw():
    """Invariant: every camera image-folder source is also a RAW source, so
    image folders always land under raw/. Guards against list drift where a new
    folder source would silently route to the mission root instead."""
    from mission_data_organizer.config import (
        LOG_SOURCES_FOLDER_PER_MISSION,
        RAW_NATIVE_SOURCES,
    )
    assert set(LOG_SOURCES_FOLDER_PER_MISSION) <= set(RAW_NATIVE_SOURCES)


def test_emus_bms_grouped_under_system_logs(tmp_path):
    """emus_bms battery logs (per-date) land under <date>/system_logs/."""
    bags_root = tmp_path / "bags"
    logs_root = tmp_path / "logs"
    bags_root.mkdir()
    (logs_root / "emus_bms").mkdir(parents=True)
    bms = logs_root / "emus_bms" / "bms_events_00004CFB_2026_05_04.log"
    bms.touch()

    plan = build_plan(bags_root, logs_root, UTC)
    by_src = {m.src.name: m.dst for m in plan.moves}
    assert by_src[bms.name] == bags_root / "2026_05_04" / "system_logs" / bms.name


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
