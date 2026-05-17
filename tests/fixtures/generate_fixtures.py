#!/usr/bin/env python3
"""Build a synthetic ``flat/`` fixture tree for the smoke test.

Generates real (tiny) ROS bags via the rosbag Python API with controlled
internal start/end timestamps so ``rosbag info`` returns predictable values,
plus empty placeholder files for the other sensor sources (the tool inspects
their filenames only).

Run inside the dev container (where ``rosbag`` is importable):

    python3 generate_fixtures.py <output-dir>

The output layout is::

    <output-dir>/flat/bags/   # 2 missions + 1 basic + 1 .bag.active
    <output-dir>/flat/logs/   # mk_ii, multibeam, mission_reports, iquaview, emus_bms, blackfly_s, cola2_log

The ``expected/`` tree is NOT produced by this script — the smoke test
encodes the expected layout as assertions and compares the planner's output
directly.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def _write_bag(path: Path, msg_unix_times: Iterable[float]) -> None:
    """Write a bag with one std_msgs/String message per Unix timestamp."""
    import genpy
    import rosbag
    from std_msgs.msg import String

    path.parent.mkdir(parents=True, exist_ok=True)
    with rosbag.Bag(str(path), "w") as bag:
        for unix_ts in msg_unix_times:
            t = genpy.Time.from_sec(unix_ts)
            msg = String(data=f"test message at {unix_ts}")
            bag.write("/chatter", msg, t=t)


def _utc_unix(year, month, day, h, m, s) -> float:
    """Return the Unix-epoch seconds for a UTC wall clock.

    The fixture simulates Orat (UTC) — bag-internal times are UTC by
    construction, independent of the host running the test. The smoke
    test runs ``build_plan`` with ``local_tz=timezone.utc`` so filename
    TSs and folder names stay aligned with the fixture's UTC choice.
    """
    return datetime(year, month, day, h, m, s, tzinfo=timezone.utc).timestamp()


def main(out_dir: Path) -> int:
    flat = out_dir / "flat"
    flat_bags = flat / "bags"
    flat_logs = flat / "logs"

    # --- Mission 1: 2026-05-04, anchor at 09:03:30, 2-minute span ---
    m1_anchor_filename = "2026-05-04-09-03-30"
    m1_start = _utc_unix(2026, 5, 4, 9, 3, 30)
    m1_end = _utc_unix(2026, 5, 4, 9, 5, 30)

    _write_bag(flat_bags / f"sparus2_{m1_anchor_filename}_0.bag",
               [m1_start, m1_end])
    # Sensor bags within the mission window.
    _write_bag(flat_bags / f"sparus2_camera_{m1_anchor_filename}_0.bag",
               [m1_start + 0.5, m1_end])
    _write_bag(flat_bags / f"sparus2_multibeam_2026-05-04-09-03-31_0.bag",
               [m1_start + 1.0, m1_end])
    _write_bag(flat_bags / f"sparus2_sidescan_{m1_anchor_filename}_0.bag",
               [m1_start, m1_end])
    _write_bag(flat_bags / f"sparus2_stereo_camera_{m1_anchor_filename}_0.bag",
               [m1_start, m1_end - 60])

    # --- Mission 2: 2026-05-04, anchor at 10:50:33, 5-minute span, with stereo split ---
    m2_anchor_filename = "2026-05-04-10-50-33"
    m2_start = _utc_unix(2026, 5, 4, 10, 50, 33)
    m2_end = _utc_unix(2026, 5, 4, 10, 55, 33)
    m2_split_filename = "2026-05-04-10-52-00"   # part 1 starts mid-mission
    m2_split_start = _utc_unix(2026, 5, 4, 10, 52, 0)

    _write_bag(flat_bags / f"sparus2_{m2_anchor_filename}_0.bag",
               [m2_start, m2_end])
    _write_bag(flat_bags / f"sparus2_camera_{m2_anchor_filename}_0.bag",
               [m2_start, m2_end])
    _write_bag(flat_bags / f"sparus2_stereo_camera_{m2_anchor_filename}_0.bag",
               [m2_start, m2_split_start - 0.5])
    _write_bag(flat_bags / f"sparus2_stereo_camera_{m2_split_filename}_1.bag",
               [m2_split_start, m2_end])

    # --- Basic bag (per-date) ---
    _write_bag(flat_bags / "sparus2_basic_2026-05-04-08-00-00_0.bag",
               [_utc_unix(2026, 5, 4, 8, 0, 0),
                _utc_unix(2026, 5, 4, 8, 5, 0)])

    # --- A .bag.active (renamed on move; warning emitted) ---
    _write_bag(flat_bags / "sparus2_basic_2026-05-04-07-30-00_0.bag.active",
               [_utc_unix(2026, 5, 4, 7, 30, 0),
                _utc_unix(2026, 5, 4, 7, 32, 0)])

    # --- Logs (empty placeholders; planner only reads filenames) ---
    log_files = [
        # Mission 1
        ("mk_ii", "2026-05-04_09-03-31_0.xtf"),
        ("mk_ii", "2026-05-04_09-04-00_0.SDS"),
        ("norbit_wbms_multibeam", "2026-05-04_09-03-32_0.s7k"),
        ("norbit_wbms_multibeam", "2026-05-04_09-03-32_bathy_data_raw"),
        ("norbit_wbms_multibeam", "2026-05-04_09-03-32_snippet_sidescan_raw"),
        ("mission_reports", "2026-05-04_09-03-30_mission_report.md"),
        ("iquaview_server", "20260504_090330_iquaview_server.log"),
        # Mission 2
        ("mk_ii", "2026-05-04_10-51-00_0.xtf"),
        ("norbit_wbms_multibeam", "2026-05-04_10-51-30_0.s7k"),
        ("mission_reports", "2026-05-04_10-50-33_mission_report.md"),
        # Per-date
        ("emus_bms", "bms_events_00004CFB_2026_05_04.log"),
        ("emus_bms", "bms_statistics_00004CFB_2026_05_04.csv"),
    ]
    for sub, name in log_files:
        f = flat_logs / sub / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()

    # blackfly_s — a whole folder for mission 1.
    bf = flat_logs / "blackfly_s" / "2026-05-04-09-03-30"
    bf.mkdir(parents=True, exist_ok=True)
    (bf / "1700000000000000000_port.jpg").touch()
    (bf / "1700000000000000000_starboard.jpg").touch()

    # Out-of-scope sources — present but the walker should ignore them.
    (flat_logs / "cola2_log").mkdir(parents=True, exist_ok=True)
    (flat_logs / "cola2_log" / "shutdown_logger.txt").write_text(
        "boot_2026_05_04_07:30:00\nshutdown_2026_05_04_11:00:00\n"
    )
    (flat_logs / "flir_spinnaker_camera").mkdir(parents=True, exist_ok=True)
    (flat_logs / "flir_spinnaker_stereo_camera").mkdir(parents=True, exist_ok=True)

    print(f"Wrote fixtures to {flat}")
    return 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: generate_fixtures.py <output_dir>", file=sys.stderr)
        raise SystemExit(2)

    raise SystemExit(main(Path(sys.argv[1]).resolve()))
