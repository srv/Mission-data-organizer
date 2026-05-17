"""Tests for the four filename timestamp dialects."""
from datetime import datetime

from mission_data_organizer import timestamp_parser as tp


def test_parse_bag_timestamp():
    assert tp.parse_bag_timestamp("sparus2_2026-05-04-09-03-30_0.bag") == datetime(2026, 5, 4, 9, 3, 30)
    assert tp.parse_bag_timestamp("sparus2_camera_2026-05-04-09-03-30_0.bag") == datetime(2026, 5, 4, 9, 3, 30)
    assert tp.parse_bag_timestamp("sparus2_basic_2026-05-04-08-06-06_0.bag.active") == datetime(2026, 5, 4, 8, 6, 6)
    assert tp.parse_bag_timestamp("not-a-bag.txt") is None


def test_parse_sensor_timestamp():
    assert tp.parse_sensor_timestamp("2026-04-20_08-35-26_0.s7k") == datetime(2026, 4, 20, 8, 35, 26)
    assert tp.parse_sensor_timestamp("2026-04-20_08-35-26_bathy_data_raw") == datetime(2026, 4, 20, 8, 35, 26)
    assert tp.parse_sensor_timestamp("2026-05-07_06-41-59_mission_report.md") == datetime(2026, 5, 7, 6, 41, 59)


def test_parse_compact_timestamp():
    assert tp.parse_compact_timestamp("20260504_113228_iquaview_server.log") == datetime(2026, 5, 4, 11, 32, 28)


def test_parse_date_only():
    assert tp.parse_date_only("bms_events_00004CFB_2026_05_04.log") == datetime(2026, 5, 4)
    assert tp.parse_date_only("bms_statistics_00004CFB_2026_05_04.csv") == datetime(2026, 5, 4)


def test_dialects_dont_cross_match():
    """Patterns must not bite into adjacent digit groups."""
    # The hex device-id 00004CFB right before YYYY_MM_DD must not throw off
    # the date_only parser.
    assert tp.parse_date_only("bms_events_00004CFB_2026_05_04.log") == datetime(2026, 5, 4)
    # A bag filename does not contain the sensor (underscore-in-middle) pattern.
    assert tp.parse_sensor_timestamp("sparus2_2026-05-04-09-03-30_0.bag") is None
    # A sensor filename does not contain the bag (all-dashes) pattern.
    assert tp.parse_bag_timestamp("2026-04-20_08-35-26_0.s7k") is None
    # Compact does not match anything that has separators in date or time.
    assert tp.parse_compact_timestamp("2026-05-04-09-03-30") is None


def test_parse_any_dispatches():
    assert tp.parse_any("sparus2_2026-05-04-09-03-30_0.bag") == datetime(2026, 5, 4, 9, 3, 30)
    assert tp.parse_any("2026-04-20_08-35-26_0.s7k") == datetime(2026, 4, 20, 8, 35, 26)
    assert tp.parse_any("20260504_113228_iquaview_server.log") == datetime(2026, 5, 4, 11, 32, 28)
    assert tp.parse_any("bms_events_00004CFB_2026_05_04.log") == datetime(2026, 5, 4)
    assert tp.parse_any("garbage.txt") is None


def test_invalid_dates_return_none():
    """Day-out-of-range and similar must not crash."""
    assert tp.parse_bag_timestamp("sparus2_2026-13-99-25-99-99_0.bag") is None
    assert tp.parse_sensor_timestamp("2026-13-99_25-99-99_0.s7k") is None


def test_folder_name_renderers():
    dt = datetime(2026, 5, 4, 9, 3, 30)
    assert tp.date_folder_name(dt) == "2026_05_04"
    assert tp.mission_folder_name(dt) == "09_03_30"
