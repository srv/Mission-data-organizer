"""Tests for the planner — collisions, missing destinations, dry-run safety."""
from datetime import timezone
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


# Other planner tests (collision detection, idempotent re-runs) are best
# exercised by the smoke test in test_smoke.py, which runs the full
# pipeline against generated fixtures with real bag files.
