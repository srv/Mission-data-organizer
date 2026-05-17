"""Parse the four filename timestamp dialects used across vehicle outputs.

Dialects:
    - ``YYYY-MM-DD-HH-MM-SS`` — bag filenames; ``blackfly_s/<folder>`` names.
    - ``YYYY-MM-DD_HH-MM-SS`` — ``mk_ii/``, ``norbit_wbms_multibeam/``, ``mission_reports/``.
    - ``YYYYMMDD_HHMMSS``     — ``iquaview_server/``.
    - ``YYYY_MM_DD``          — ``emus_bms/`` (date only).

Patterns are anchored with negative-lookbehind/lookahead on digits so they
do not accidentally bite into adjacent digit groups (e.g. the hex device-id
``00004CFB`` next to ``2026_05_04`` in ``bms_events_00004CFB_2026_05_04.log``).
"""
import re
from datetime import datetime
from typing import Optional


_BAG_RE = re.compile(
    r"(?<!\d)(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})(?!\d)"
)
_SENSOR_RE = re.compile(
    r"(?<!\d)(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})(?!\d)"
)
_COMPACT_RE = re.compile(
    r"(?<!\d)(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(?!\d)"
)
_DATE_ONLY_RE = re.compile(
    r"(?<!\d)(\d{4})_(\d{2})_(\d{2})(?!\d)"
)


def _to_datetime(groups) -> Optional[datetime]:
    try:
        return datetime(*[int(g) for g in groups])
    except (TypeError, ValueError):
        return None


def parse_bag_timestamp(filename: str) -> Optional[datetime]:
    """Parse ``YYYY-MM-DD-HH-MM-SS`` from a bag filename.

    Example input: ``sparus2_2026-05-04-09-03-30_0.bag``.
    Returns ``None`` if no timestamp is present.
    """
    m = _BAG_RE.search(filename)
    return _to_datetime(m.groups()) if m else None


def parse_sensor_timestamp(filename: str) -> Optional[datetime]:
    """Parse ``YYYY-MM-DD_HH-MM-SS`` from a sensor-log filename.

    Example input: ``2026-04-20_08-35-26_0.s7k``.
    Returns ``None`` if no timestamp is present.
    """
    m = _SENSOR_RE.search(filename)
    return _to_datetime(m.groups()) if m else None


def parse_compact_timestamp(filename: str) -> Optional[datetime]:
    """Parse ``YYYYMMDD_HHMMSS`` from filenames like
    ``20260504_113228_iquaview_server.log``.

    Returns ``None`` if no timestamp is present.
    """
    m = _COMPACT_RE.search(filename)
    return _to_datetime(m.groups()) if m else None


def parse_date_only(filename: str) -> Optional[datetime]:
    """Parse ``YYYY_MM_DD`` from filenames like
    ``bms_events_00004CFB_2026_05_04.log``.

    Returns a datetime at midnight on that date, or ``None``.
    """
    m = _DATE_ONLY_RE.search(filename)
    return _to_datetime(m.groups()) if m else None


def parse_any(filename: str) -> Optional[datetime]:
    """Try every parser in turn; return the first hit, else ``None``.

    The order matters because dialects partially overlap on substrings: the
    sensor and bag patterns are tried before compact and date-only since
    they carry more information (full timestamp, not just date).
    """
    for parser in (
        parse_sensor_timestamp,
        parse_bag_timestamp,
        parse_compact_timestamp,
        parse_date_only,
    ):
        result = parser(filename)
        if result is not None:
            return result
    return None


def date_folder_name(dt: datetime) -> str:
    """Render ``YYYY_MM_DD`` from a datetime."""
    return dt.strftime("%Y_%m_%d")


def mission_folder_name(dt: datetime) -> str:
    """Render ``HH_MM_SS`` from a datetime."""
    return dt.strftime("%H_%M_%S")
