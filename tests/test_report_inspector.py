"""Tests for the mission_report.md header window reader."""
from datetime import datetime, timezone

from mission_data_organizer.report_inspector import parse_report_window

UTC = timezone.utc

_REAL_HEADER = (
    "# Mission reports 09:41:08 18/06/2026\n"
    "## Mission1\n"
    "- Mission name: porto_pi_lawnmower.xml\n"
    "- Mission completed on 2026/06/18 at 09:44:28\n"
    "- Start time: 2026/06/18 09:41:08\n"
    "- End time:   2026/06/18 09:44:28\n"
    "## Mission2\n"
    "- Start time: 2026/06/18 10:00:00\n"
    "- End time:   2026/06/18 10:05:00\n"
)


def test_parses_first_mission_window(tmp_path):
    p = tmp_path / "r.md"
    p.write_text(_REAL_HEADER)
    win = parse_report_window(p)
    assert win == (
        datetime(2026, 6, 18, 9, 41, 8, tzinfo=UTC),
        datetime(2026, 6, 18, 9, 44, 28, tzinfo=UTC),
    )


def test_missing_end_time_returns_none(tmp_path):
    p = tmp_path / "r.md"
    p.write_text(
        "## Mission1\n- Start time: 2026/06/18 09:41:08\n- Notes: aborted\n"
    )
    assert parse_report_window(p) is None


def test_empty_file_returns_none(tmp_path):
    p = tmp_path / "r.md"
    p.touch()
    assert parse_report_window(p) is None


def test_incomplete_first_block_does_not_cross(tmp_path):
    """A first block missing its End must NOT borrow the next block's End —
    the parser bails (returns None) rather than fabricate a cross-block span."""
    p = tmp_path / "r.md"
    p.write_text(
        "## Mission1\n- Start time: 2026/06/18 09:41:08\n"
        "## Mission2\n- Start time: 2026/06/18 10:00:00\n"
        "- End time:   2026/06/18 10:05:00\n"
    )
    assert parse_report_window(p) is None


def test_out_of_range_timestamp_returns_none(tmp_path):
    """A regex-matching but invalid timestamp must fall back (None), not crash."""
    p = tmp_path / "r.md"
    p.write_text(
        "- Start time: 2026/13/40 25:61:99\n"
        "- End time:   2026/06/18 10:00:00\n"
    )
    assert parse_report_window(p) is None


def test_does_not_misparse_completed_on_line(tmp_path):
    """The 'Mission completed on YYYY/MM/DD at HH:MM:SS' line must not be read
    as the Start/End window (it uses ' at ', not a space, between date/time)."""
    p = tmp_path / "r.md"
    p.write_text(
        "- Mission completed on 2026/06/18 at 09:44:28\n"
        "- Start time: 2026/06/18 09:41:08\n"
        "- End time:   2026/06/18 09:44:28\n"
    )
    win = parse_report_window(p)
    assert win[0] == datetime(2026, 6, 18, 9, 41, 8, tzinfo=UTC)
