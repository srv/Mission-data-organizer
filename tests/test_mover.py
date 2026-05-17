"""Tests for the mover: refuse-overwrite, audit log, undo round-trip."""
import json
from pathlib import Path

import pytest

from mission_data_organizer.classifier import Assignment
from mission_data_organizer.mover import (
    MoveError,
    apply_plan,
    find_latest_log,
    undo_from_log,
)


def _make_file(p: Path, content: str = "data"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_apply_then_undo_round_trips(tmp_path):
    src = tmp_path / "src" / "file.txt"
    dst = tmp_path / "dst" / "subdir" / "file.txt"
    _make_file(src, "hello")
    log = tmp_path / "audit.log"

    apply_plan([Assignment(src=src, dst=dst)], log)
    assert dst.exists()
    assert not src.exists()
    assert log.exists()
    # Audit log has one JSON line.
    entries = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    assert len(entries) == 1
    assert entries[0]["action"] == "move"
    assert entries[0]["src"] == str(src)
    assert entries[0]["dst"] == str(dst)

    undo_from_log(log)
    assert src.exists()
    assert not dst.exists()
    assert src.read_text() == "hello"


def test_refuse_to_overwrite(tmp_path):
    src = tmp_path / "src" / "file.txt"
    dst = tmp_path / "dst" / "file.txt"
    _make_file(src, "new")
    _make_file(dst, "existing")
    log = tmp_path / "audit.log"

    with pytest.raises(MoveError):
        apply_plan([Assignment(src=src, dst=dst)], log)

    # Source preserved, destination not clobbered.
    assert src.exists() and src.read_text() == "new"
    assert dst.exists() and dst.read_text() == "existing"


def test_find_latest_log(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    a = d / "2026-01-01.log"
    b = d / "2026-02-01.log"
    a.write_text("")
    b.write_text("")
    # Make b newer than a explicitly.
    import os
    os.utime(a, (1000, 1000))
    os.utime(b, (2000, 2000))
    assert find_latest_log(d) == b


def test_find_latest_log_empty(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_latest_log(tmp_path / "does_not_exist")


def test_apply_partial_failure_logs_completed(tmp_path):
    """If the second move's destination already exists, the first move's
    record must be in the audit log so undo can roll it back."""
    src1 = tmp_path / "src" / "a.txt"
    src2 = tmp_path / "src" / "b.txt"
    dst1 = tmp_path / "dst" / "a.txt"
    dst2 = tmp_path / "dst" / "b.txt"
    _make_file(src1, "a")
    _make_file(src2, "b")
    _make_file(dst2, "blocker")    # this one already exists
    log = tmp_path / "audit.log"

    with pytest.raises(MoveError):
        apply_plan([
            Assignment(src=src1, dst=dst1),
            Assignment(src=src2, dst=dst2),
        ], log)

    # First move completed.
    assert not src1.exists() and dst1.exists()
    # Second move did not happen.
    assert src2.exists() and dst2.read_text() == "blocker"

    # Undo the partial run.
    undo_from_log(log)
    assert src1.exists() and not dst1.exists()
