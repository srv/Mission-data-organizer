"""Top-level orchestrator + CLI entry point.

Default mode is **dry-run**: the planner runs, a summary plus any warnings
are printed (pass ``-v`` to also list every planned move), and no audit log
is written. ``--apply`` triggers the actual moves. ``--undo`` reverses a
previous run.
"""
import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

_HH_MM_SS_RE = re.compile(r"^\d{2}_\d{2}_\d{2}$")

from .config import (
    AUDIT_LOG_DIRNAME,
    DEFAULT_BAGS_ROOT,
    DEFAULT_LOGS_ROOT,
)
from .mover import (
    MoveError,
    apply_plan,
    find_latest_log,
    undo_from_log,
)
from .planner import build_plan


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="organize_bags.py",
        description=(
            "Reorganise the flat post-mission output of an AUV's onboard "
            "computer into a date/mission folder hierarchy. "
            "Default mode is dry-run; pass --apply to execute."
        ),
    )
    parser.add_argument(
        "--bags-root",
        default=DEFAULT_BAGS_ROOT,
        help="Root path for bag files (default: %(default)s)",
    )
    parser.add_argument(
        "--logs-root",
        default=DEFAULT_LOGS_ROOT,
        help="Root path for sensor logs (default: %(default)s)",
    )
    parser.add_argument(
        "--local-tz",
        default="Europe/Madrid",
        metavar="IANA_NAME",
        help=(
            "IANA timezone of the team's local time. Used both as the TZ in "
            "which non-bag sensor filenames are interpreted (sonar PC, "
            "iquaview PC, mk_ii PC) and as the TZ used to render mission "
            "folder names. Bag filenames (anchor + sensor companions + "
            "blackfly_s/ folder names) are always attached as UTC because "
            "the AUV's onboard computer (Orat) runs on UTC by deployment "
            "policy. Bag-internal timestamps are UTC by definition. "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "Also print the full per-move list. Default output is just the "
            "summary, warnings, and the dry-run footer."
        ),
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument(
        "--apply",
        action="store_true",
        help="Actually perform the moves (default: dry-run only)",
    )
    g.add_argument(
        "--undo",
        nargs="?",
        const="LATEST",
        default=None,
        metavar="LOG_PATH",
        help=(
            "Undo a previous run. With no argument, undoes the most "
            "recent run (latest file under <bags-root>/.organize_log/). "
            "With a path, undoes that specific log."
        ),
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Parse CLI arguments and dispatch.

    Exit codes: 0 success, 1 plan errors or apply/undo failure, 2 usage error.
    """
    args = _build_argparser().parse_args(argv)

    bags_root = Path(args.bags_root).resolve()
    logs_root = Path(args.logs_root).resolve()

    try:
        from dateutil import tz as _dateutil_tz
    except ImportError:
        print(
            "ERROR: python-dateutil is required (typically pre-installed via "
            "the python3-dateutil system package on Ubuntu / ROS Noetic).",
            file=sys.stderr,
        )
        return 2
    if not args.local_tz or not args.local_tz.strip():
        # dateutil.tz.gettz("") returns the host's local TZ, which would
        # silently re-introduce host-TZ-dependent behaviour. Force the
        # operator to be explicit.
        print(
            "ERROR: --local-tz must be a non-empty IANA zone name "
            "(e.g. Europe/Madrid, UTC).",
            file=sys.stderr,
        )
        return 2
    local_tz = _dateutil_tz.gettz(args.local_tz)
    if local_tz is None:
        print(
            f"ERROR: unknown timezone {args.local_tz!r}. Check the IANA "
            f"zone name and that system tz data (/usr/share/zoneinfo) is "
            f"available.",
            file=sys.stderr,
        )
        return 2

    # ---- undo path ----
    if args.undo is not None:
        if args.undo == "LATEST":
            try:
                log_path = find_latest_log(bags_root / AUDIT_LOG_DIRNAME)
            except FileNotFoundError as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return 1
        else:
            log_path = Path(args.undo)
        print(f"Undoing from log: {log_path}", file=sys.stderr)
        try:
            undo_from_log(log_path)
        except (MoveError, FileNotFoundError, OSError) as e:
            print(f"ERROR: undo failed: {e}", file=sys.stderr)
            return 1
        print("Undo complete.", file=sys.stderr)
        return 0

    # ---- plan ----
    plan = build_plan(bags_root, logs_root, local_tz)

    # All status output (warnings, per-move list, summary, footer) goes to
    # stdout so a single `> file` redirect captures the whole record.
    # The summary + footer are *also* mirrored to stderr when stdout is
    # not a TTY, so the operator still sees the headline numbers on
    # the terminal even when stdout has been captured to a file.
    stdout_redirected = not sys.stdout.isatty()

    def emit_dual(line: str) -> None:
        print(line)
        if stdout_redirected:
            print(line, file=sys.stderr)

    for w in plan.warnings:
        print(f"WARNING: {w}")
    for e in plan.errors:
        print(f"ERROR: {e}", file=sys.stderr)
    if plan.errors:
        return 1

    if not plan.moves:
        emit_dual("Nothing to do.")
        return 0

    mission_count = 0
    date_count = 0
    demoted_count = 0
    for m in plan.moves:
        if m.note and "active_suffix_stripped" in m.note:
            print(
                f"WARNING: {m.src.name} has .bag.active suffix; will rename "
                f"to .bag (likely from a previous unclean shutdown)."
            )
        if m.note and "demoted" in m.note:
            demoted_count += 1
        rel_parts = m.dst.relative_to(bags_root).parts
        if len(rel_parts) >= 3 and _HH_MM_SS_RE.match(rel_parts[1]):
            mission_count += 1
        else:
            date_count += 1

    if args.verbose:
        for m in plan.moves:
            marker = "  [demoted]" if (m.note and "demoted" in m.note) else ""
            print(f"  {m.src} -> {m.dst}{marker}")

    by_design_count = date_count - demoted_count
    emit_dual("")
    emit_dual(f"Plan: {len(plan.moves)} move(s)")
    emit_dual(f"  {mission_count} into mission folders (<date>/<HH_MM_SS>/)")
    emit_dual(
        f"  {by_design_count} into date folders (<date>/) "
        f"by design (sparus2_basic_*, bms_*)"
    )
    emit_dual(
        f"  {demoted_count} demoted to date folders (<date>/) — "
        f"per-mission files whose timestamp fell outside every mission window"
    )
    if plan.warnings:
        emit_dual(
            f"  {len(plan.warnings)} source(s) skipped "
            f"(unreadable / unparseable — see WARNINGs above)"
        )

    if not args.apply:
        emit_dual("Dry-run only. Pass --apply to execute.")
        return 0

    # ---- apply ----
    audit_log_path = (
        bags_root
        / AUDIT_LOG_DIRNAME
        / (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + ".log")
    )
    print(f"\nApplying. Audit log: {audit_log_path}", file=sys.stderr)
    try:
        apply_plan(plan.moves, audit_log_path)
    except MoveError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print(
            f"Earlier moves are recorded in {audit_log_path}; "
            f"use --undo {audit_log_path} to roll back.",
            file=sys.stderr,
        )
        return 1
    print(f"Applied {len(plan.moves)} move(s) successfully.", file=sys.stderr)
    return 0
