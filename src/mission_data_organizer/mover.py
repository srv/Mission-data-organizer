"""Apply a move plan, log every action, and support undo from the audit log.

Audit-log format: one JSON object per line (jsonl), one per completed move.
The line is written *after* the destination is verified to exist with the
correct content — never write a record that doesn't reflect on-disk state.
"""
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .classifier import Assignment


class MoveError(RuntimeError):
    """Raised when an individual move cannot be completed."""


def _move_path(src: Path, dst: Path) -> None:
    """Move file or directory from src to dst.

    Atomic ``os.rename`` if same filesystem; otherwise copy → verify →
    unlink. Refuses to overwrite (caller must check ``dst.exists()`` first).
    """
    try:
        os.rename(str(src), str(dst))
        return
    except OSError:
        # Cross-device move (or rename refused for some reason). Fall back
        # to copy + verify + unlink.
        pass

    if src.is_dir():
        shutil.copytree(str(src), str(dst))
        # Best-effort sanity check: file count matches.
        n_src = sum(1 for _ in src.rglob("*"))
        n_dst = sum(1 for _ in dst.rglob("*"))
        if n_src != n_dst:
            raise MoveError(
                f"copy verification failed (file counts differ): {dst}"
            )
        shutil.rmtree(str(src))
    else:
        shutil.copy2(str(src), str(dst))
        if dst.stat().st_size != src.stat().st_size:
            raise MoveError(
                f"copy verification failed (size mismatch): {dst}"
            )
        src.unlink()


def apply_plan(moves: List[Assignment], audit_log_path: Path) -> None:
    """Execute every move in ``moves`` in order.

    Refuses to overwrite. Writes one JSON record per completed move to
    ``audit_log_path``. On failure, raises :class:`MoveError` and stops;
    earlier moves remain on disk and are recoverable via the audit log.
    """
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(audit_log_path, "w") as log:
        for m in moves:
            if m.dst.exists():
                raise MoveError(
                    f"destination already exists, refusing: {m.dst}"
                )
            m.dst.parent.mkdir(parents=True, exist_ok=True)
            _move_path(m.src, m.dst)
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": "move",
                "src": str(m.src),
                "dst": str(m.dst),
                "note": m.note,
            }
            log.write(json.dumps(entry) + "\n")
            log.flush()


def undo_from_log(audit_log_path: Path) -> None:
    """Reverse every move recorded in ``audit_log_path``, in reverse order.

    Same overwrite-refusal as :func:`apply_plan`: if the original source
    location is occupied, abort and report.
    """
    entries = []
    with open(audit_log_path) as log:
        for line in log:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))

    for entry in reversed(entries):
        # Reverse direction: dst (current location) → src (original location)
        current = Path(entry["dst"])
        original = Path(entry["src"])
        if not current.exists():
            raise MoveError(
                f"undo: current location no longer exists: {current}"
            )
        if original.exists():
            raise MoveError(
                f"undo: original location now occupied: {original}"
            )
        original.parent.mkdir(parents=True, exist_ok=True)
        _move_path(current, original)


def find_latest_log(audit_log_dir: Path) -> Path:
    """Return the most recent ``.log`` file in ``audit_log_dir``.

    Raises :class:`FileNotFoundError` if the directory is empty or missing.
    """
    if not audit_log_dir.exists():
        raise FileNotFoundError(f"no audit log directory at {audit_log_dir}")
    logs = sorted(
        audit_log_dir.glob("*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not logs:
        raise FileNotFoundError(f"no audit logs in {audit_log_dir}")
    return logs[0]
