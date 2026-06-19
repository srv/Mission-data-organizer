"""Read the time window from an iquaview ``mission_report.md`` header.

Mirrors :mod:`bag_inspector`'s file-reading role: it extracts the planned
mission span so the classifier can pair the report with the mission whose
bag-internal window overlaps it (content-aware matching — see
:func:`classifier.assign_mission_report`).

Real report header (first lines of every file)::

    # Mission reports HH:MM:SS DD/MM/YYYY
    ## Mission1
    - Mission name: <plan>.xml
    - Mission completed on YYYY/MM/DD at HH:MM:SS
    - Start time: YYYY/MM/DD HH:MM:SS
    - End time:   YYYY/MM/DD HH:MM:SS

The driver runs on Orat, whose clock is UTC, so the header times are UTC.
Only the first mission block's ``Start``/``End`` is used (one ``## Mission1``
per file in real data).
"""
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

# Date+time of the form ``YYYY/MM/DD HH:MM:SS`` (whitespace-separated). The
# "Mission completed on ... at ..." line uses " at " between date and time, so
# this pattern does not match it; we additionally anchor on the line prefix.
_HEADER_TS_RE = re.compile(
    r"(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})"
)

# Read at most this many lines — the window lives in the header.
_MAX_LINES = 30


def _match_to_utc(m: "re.Match") -> datetime:
    return datetime(
        int(m.group(1)), int(m.group(2)), int(m.group(3)),
        int(m.group(4)), int(m.group(5)), int(m.group(6)),
        tzinfo=timezone.utc,
    )


def parse_report_window(path: Path) -> Optional[Tuple[datetime, datetime]]:
    """Return ``(start, end)`` UTC-aware datetimes from the report header.

    Returns ``None`` if the file is unreadable or either the ``Start time``
    or ``End time`` line is missing/unparseable, so the caller can fall back
    to filename-TS matching and never lose the file.
    """
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= _MAX_LINES:
                    break
                low = line.strip().lower()
                # Confine parsing to the first mission block: if a second
                # ``## MissionN`` header arrives before the first block's window
                # is complete, do not pair a Start from one block with an End
                # from another — bail so the caller falls back to filename TS.
                if low.startswith("##"):
                    if start is not None or end is not None:
                        return None
                    continue
                if start is None and low.startswith("- start time:"):
                    m = _HEADER_TS_RE.search(line)
                    if m:
                        start = _match_to_utc(m)
                elif end is None and low.startswith("- end time:"):
                    m = _HEADER_TS_RE.search(line)
                    if m:
                        end = _match_to_utc(m)
                if start is not None and end is not None:
                    break
    except OSError:
        return None
    except ValueError:
        # A regex-matching but out-of-range timestamp (e.g. 2026/13/40) raised
        # from datetime(). Treat as unreadable and fall back, never crash.
        return None
    if start is None or end is None:
        return None
    return start, end
