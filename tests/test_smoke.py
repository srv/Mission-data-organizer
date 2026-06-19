"""End-to-end smoke test against generated fixtures.

Generates a synthetic flat input tree (real tiny bag files + empty log
placeholders) inside tmp_path, runs build_plan, then applies the plan and
asserts the on-disk layout matches what the team's manual organizing
convention produces. Requires ``rosbag`` (i.e. run inside the ROS container).
"""
import os
import sys
from datetime import timezone
from pathlib import Path

import pytest

# Make the fixture generator importable.
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(_FIXTURES_DIR))


@pytest.fixture
def generated(tmp_path):
    """Generate the flat fixture tree inside tmp_path."""
    pytest.importorskip("rosbag")
    pytest.importorskip("genpy")
    pytest.importorskip("std_msgs.msg")
    import generate_fixtures
    generate_fixtures.main(tmp_path)
    return tmp_path / "flat"


def test_build_plan_produces_expected_layout(generated):
    from mission_data_organizer.planner import build_plan

    bags_root = generated / "bags"
    logs_root = generated / "logs"

    plan = build_plan(bags_root, logs_root, timezone.utc)
    assert plan.errors == [], plan.errors

    # Convert to a {src.name: dst} map for ergonomic asserts.
    by_src = {m.src.name: m.dst for m in plan.moves}

    # --- Mission 1 anchor and its sensor bags ---
    m1 = bags_root / "2026_05_04" / "09_03_30"
    assert by_src["sparus2_2026-05-04-09-03-30_0.bag"] == m1 / "sparus2_2026-05-04-09-03-30_0.bag"
    assert by_src["sparus2_camera_2026-05-04-09-03-30_0.bag"] == m1 / "sparus2_camera_2026-05-04-09-03-30_0.bag"
    assert by_src["sparus2_multibeam_2026-05-04-09-03-31_0.bag"] == m1 / "sparus2_multibeam_2026-05-04-09-03-31_0.bag"
    assert by_src["sparus2_sidescan_2026-05-04-09-03-30_0.bag"] == m1 / "sparus2_sidescan_2026-05-04-09-03-30_0.bag"
    assert by_src["sparus2_stereo_camera_2026-05-04-09-03-30_0.bag"] == m1 / "sparus2_stereo_camera_2026-05-04-09-03-30_0.bag"
    # Mission 1 sensor logs. Native sonar recordings (mk_ii sidescan,
    # Norbit multibeam) land under the raw/ subfolder; the mission report and
    # iquaview server log stay at the mission root.
    assert by_src["2026-05-04_09-03-31_0.xtf"] == m1 / "raw" / "2026-05-04_09-03-31_0.xtf"
    assert by_src["2026-05-04_09-04-00_0.SDS"] == m1 / "raw" / "2026-05-04_09-04-00_0.SDS"
    assert by_src["2026-05-04_09-03-32_0.s7k"] == m1 / "raw" / "2026-05-04_09-03-32_0.s7k"
    assert by_src["2026-05-04_09-03-32_bathy_data_raw"] == m1 / "raw" / "2026-05-04_09-03-32_bathy_data_raw"
    assert by_src["2026-05-04_09-03-32_snippet_sidescan_raw"] == m1 / "raw" / "2026-05-04_09-03-32_snippet_sidescan_raw"
    assert by_src["2026-05-04_09-03-30_mission_report.md"] == m1 / "2026-05-04_09-03-30_mission_report.md"
    assert by_src["20260504_090330_iquaview_server.log"] == m1 / "20260504_090330_iquaview_server.log"
    # blackfly_s folder for mission 1 (whole folder moves)
    assert by_src["2026-05-04-09-03-30"] == m1 / "2026-05-04-09-03-30"

    # --- Mission 2 anchor + stereo split ---
    m2 = bags_root / "2026_05_04" / "10_50_33"
    assert by_src["sparus2_2026-05-04-10-50-33_0.bag"] == m2 / "sparus2_2026-05-04-10-50-33_0.bag"
    assert by_src["sparus2_camera_2026-05-04-10-50-33_0.bag"] == m2 / "sparus2_camera_2026-05-04-10-50-33_0.bag"
    assert by_src["sparus2_stereo_camera_2026-05-04-10-50-33_0.bag"] == m2 / "sparus2_stereo_camera_2026-05-04-10-50-33_0.bag"
    # Stereo split (different filename time, but its internal start_time
    # falls inside mission 2's [start, end]) — must land in mission 2.
    assert by_src["sparus2_stereo_camera_2026-05-04-10-52-00_1.bag"] == m2 / "sparus2_stereo_camera_2026-05-04-10-52-00_1.bag"
    # Mission 2 sensor logs — sonar under raw/, report at the mission root.
    assert by_src["2026-05-04_10-51-00_0.xtf"] == m2 / "raw" / "2026-05-04_10-51-00_0.xtf"
    assert by_src["2026-05-04_10-51-30_0.s7k"] == m2 / "raw" / "2026-05-04_10-51-30_0.s7k"
    assert by_src["2026-05-04_10-50-33_mission_report.md"] == m2 / "2026-05-04_10-50-33_mission_report.md"

    # --- Per-date items (basic bags, emus_bms) ---
    date_dir = bags_root / "2026_05_04"
    assert by_src["sparus2_basic_2026-05-04-08-00-00_0.bag"] == date_dir / "sparus2_basic_2026-05-04-08-00-00_0.bag"
    # .bag.active gets the .active stripped on move.
    active_assignment = next(m for m in plan.moves
                             if m.src.name == "sparus2_basic_2026-05-04-07-30-00_0.bag.active")
    assert active_assignment.dst == date_dir / "sparus2_basic_2026-05-04-07-30-00_0.bag"
    assert active_assignment.note == "active_suffix_stripped"
    assert by_src["bms_events_00004CFB_2026_05_04.log"] == date_dir / "bms_events_00004CFB_2026_05_04.log"
    assert by_src["bms_statistics_00004CFB_2026_05_04.csv"] == date_dir / "bms_statistics_00004CFB_2026_05_04.csv"


def test_apply_plan_then_idempotent_rerun(generated):
    """Apply once, verify on-disk layout, then run again and confirm it's a no-op."""
    from mission_data_organizer.mover import apply_plan
    from mission_data_organizer.planner import build_plan

    bags_root = generated / "bags"
    logs_root = generated / "logs"

    plan = build_plan(bags_root, logs_root, timezone.utc)
    assert plan.errors == []
    n_moves = len(plan.moves)

    log_path = bags_root / ".organize_log" / "smoke.log"
    apply_plan(plan.moves, log_path)

    # Top-level should now be empty (except organized subdirs and audit log).
    top = sorted(p.name for p in bags_root.iterdir() if not p.name.startswith("."))
    assert top == ["2026_05_04"]

    # Idempotent re-run: nothing left at top level → empty plan.
    plan2 = build_plan(bags_root, logs_root, timezone.utc)
    assert plan2.moves == []
    assert plan2.errors == []
    assert n_moves > 0   # sanity: first run did do work


def test_out_of_scope_dirs_not_touched(generated):
    """cola2_log/shutdown_logger.txt and the empty Spinnaker dirs must be
    invisible to the planner."""
    from mission_data_organizer.planner import build_plan

    plan = build_plan(generated / "bags", generated / "logs", timezone.utc)
    src_paths = {str(m.src) for m in plan.moves}
    assert not any("cola2_log" in s for s in src_paths)
    assert not any("flir_spinnaker_camera" in s for s in src_paths)
    assert not any("flir_spinnaker_stereo_camera" in s for s in src_paths)


def test_undo_round_trip(generated):
    """Apply, then --undo, must restore the original flat layout."""
    from mission_data_organizer.mover import apply_plan, undo_from_log
    from mission_data_organizer.planner import build_plan

    bags_root = generated / "bags"
    logs_root = generated / "logs"

    snapshot_before = sorted(p.relative_to(generated).as_posix()
                             for p in generated.rglob("*") if p.is_file())

    plan = build_plan(bags_root, logs_root, timezone.utc)
    log_path = bags_root / ".organize_log" / "smoke.log"
    apply_plan(plan.moves, log_path)

    undo_from_log(log_path)

    snapshot_after = sorted(p.relative_to(generated).as_posix()
                            for p in generated.rglob("*") if p.is_file())
    # The audit log itself is the only addition.
    extra = set(snapshot_after) - set(snapshot_before)
    assert extra == {log_path.relative_to(generated).as_posix()}
    missing = set(snapshot_before) - set(snapshot_after)
    assert missing == set()
