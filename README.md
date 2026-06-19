# mission_data_organizer

A CLI tool that reorganises the flat post-mission output of an AUV's onboard computer into a date-then-mission folder hierarchy.

After every mission, the vehicle drops bagfiles into `/home/user/bags/` and per-sensor logs into `/home/user/logs/<sensor>/`. This tool walks those locations, identifies which files belong to which mission (by reading each anchor bag's internal start/end timestamps with a built-in pure-Python ROS bag v2.0 parser — no ROS runtime needed), and moves each file into the correct `<date>/<time>/` subfolder. Runtime requirements: Python 3.8+ and `python-dateutil` (system package `python3-dateutil`, pre-installed on Ubuntu 20.04 / ROS Noetic). It runs on the vehicle.

## Final layout

```
/home/user/bags/
├── YYYY_MM_DD/                                  # date folder
│   ├── sparus2_basic_*.bag                      # boot/shutdown bags (per-day, not per-mission)
│   ├── <operator .txt notes (ondeck/onwater/readme)>   # from <bags-root>/, day from mtime
│   ├── <orphan files matched only by date>
│   ├── system_logs/                             # day-spanning daemon logs
│   │   ├── bms_<events|statistics>_<HEX>_YYYY_MM_DD.{log,csv}   # battery logs
│   │   └── YYYYMMDD_HHMMSS_iquaview_server.log                   # iquaview daemon log
│   └── HH_MM_SS/                                # mission folder, named in `--local-tz`
│       ├── sparus2_*.bag                        # main mission bag (the anchor)
│       ├── sparus2_camera_*.bag
│       ├── sparus2_multibeam_*.bag
│       ├── sparus2_sidescan_*.bag
│       ├── sparus2_stereo_camera_*_{0,1,...}.bag       # stereo splits (multiple parts share the mission)
│       ├── YYYY-MM-DD_HH-MM-SS_mission_report.md       # from /home/user/logs/mission_reports/
│       └── raw/                                 # native sonar recordings + camera image folders
│           ├── *.xtf, *.SDS                     # sidescan files from /home/user/logs/mk_ii/
│           ├── *.s7k                            # multibeam files from /home/user/logs/norbit_wbms_multibeam/
│           ├── *_bathy_data_raw                 # multibeam raw siblings (no extension), same source
│           ├── *_snippet_sidescan_raw
│           ├── *_water_column_raw
│           ├── YYYY-MM-DD-HH-MM-SS/             # stereo-image folder from /home/user/logs/blackfly_s/
│           ├── YYYY-MM-DD-HH-MM-SS/             # stereo-image folder from /home/user/logs/flir_spinnaker_camera/
│           └── YYYY-MM-DD-HH-MM-SS/             # stereo-image folder from /home/user/logs/flir_spinnaker_stereo_camera/
└── .organize_log/<run-timestamp>.log            # audit trail of every run
```

## Sources

| Source | Granularity | Where it ends up |
|---|---|---|
| `/home/user/bags/sparus2_*.bag` (no sensor suffix) | mission anchor | defines the mission |
| `/home/user/bags/sparus2_<camera|multibeam|sidescan|stereo_camera>_*.bag` | per-mission | mission folder |
| `/home/user/bags/sparus2_*.bag.active` | per-mission or per-date | mission/date folder; `.active` suffix is stripped on move and a warning is emitted to stderr (an `.active` file usually indicates a previous unclean shutdown) |
| `/home/user/bags/sparus2_basic_*.bag` | per-date | date folder |
| Operator `.txt` notes in `<bags-root>/` whose name (case-insensitive) contains `ondeck`, `onwater`, or `readme` | per-date | date folder (day from file mtime) |
| `/home/user/logs/blackfly_s/<YYYY-MM-DD-HH-MM-SS>/` | per-mission (whole folder) | mission folder, under `raw/` |
| `/home/user/logs/flir_spinnaker_camera/<YYYY-MM-DD-HH-MM-SS>/` | per-mission (whole folder) | mission folder, under `raw/` |
| `/home/user/logs/flir_spinnaker_stereo_camera/<YYYY-MM-DD-HH-MM-SS>/` | per-mission (whole folder) | mission folder, under `raw/` |
| `/home/user/logs/emus_bms/bms_*_<HEX>_YYYY_MM_DD.{log,csv}` | per-date | date `system_logs/` subfolder |
| `/home/user/logs/iquaview_server/YYYYMMDD_HHMMSS_*.log` | per-date | date `system_logs/` subfolder |
| `/home/user/logs/mission_reports/YYYY-MM-DD_HH-MM-SS_*.md` | per-mission | mission root |
| `/home/user/logs/mk_ii/*` (`.xtf`, `.SDS`, prefix `YYYY-MM-DD_HH-MM-SS_N`) | per-mission | mission folder, under `raw/` |
| `/home/user/logs/norbit_wbms_multibeam/*` (every file regardless of extension; prefix `YYYY-MM-DD_HH-MM-SS_*`) | per-mission | mission folder, under `raw/` |
| `/home/user/logs/cola2_log/shutdown_logger.txt` | continuous | **out of scope — never touched** |

The sonar recordings (`mk_ii/`, `norbit_wbms_multibeam/`) and camera image folders (`blackfly_s/`, `flir_spinnaker_camera/`, `flir_spinnaker_stereo_camera/`) are all grouped under a `raw/` subfolder inside each mission folder. The mission root holds only ROS bags and the mission report. The ROS bags are never moved into `raw/`.

## How sensor data is paired with missions

### Mission anchors

A **mission anchor** is every `sparus2_*.bag` file at the top level of `<bags-root>` whose name does *not* contain `_basic_`, `_camera_`, `_multibeam_`, `_sidescan_`, or `_stereo_camera_`. One anchor → one mission. Sensor companions (`sparus2_camera_*`, `sparus2_multibeam_*`, etc.) sharing the anchor's timestamp belong to the same mission but are not themselves anchors.

Each anchor plays two distinct roles, drawn from two different parts of the file:

| Source on the anchor | Used for |
|---|---|
| The anchor's **filename** time, e.g. `sparus2_2026-05-04-09-03-30_0.bag` → `09:03:30` UTC | naming the destination folder `<date>/<HH_MM_SS>/` (rendered in `--local-tz`) and keying companion-bag placement |
| The anchor's **internal** `start_time` / `end_time` (Unix epoch, UTC), read from inside the bag with the built-in pure-Python ROS bag v2.0 parser | defining the mission's time window, against which every non-bag sensor log is classified |

A stub anchor (4-KB header-only bag from an aborted `rosbag record`) cannot have its internal window read; a `WARNING:` is emitted and the mission is retained in the catalog with a zero-width window (`start = end = filename TS`) so its companion bags can still be paired by filename. A non-bag sensor log whose timestamp does not equal the stub's filename TS exactly cannot fall inside the zero-width window and is demoted to date-level; the (rare) exact-match case lands in the stub mission folder.

### Per-source matching rules

| Source | How it is paired with a mission |
|---|---|
| `sparus2_<TS>_<N>.bag` (anchor, no sensor marker) | Defines a mission. Folder named after the filename TS converted to `--local-tz`. |
| `sparus2_<sensor>_<TS>_<N>.bag` (camera / multibeam / sidescan / stereo_camera) | **Filename-match first** to the anchor with the closest filename TS, within ±1 s — these companions are siblings of the anchor by construction (same `rosbag record` launcher), but their filename TS can be ±1 s off when parallel process-start instants straddle a second boundary. Internal-time containment is used only as a fallback for split continuations (see next row). |
| `sparus2_<sensor>_<NEW-TS>_<N>.bag` where `N > 0` (split continuation) | Filename TS differs from any anchor's. Falls through to **internal-time containment**: the bag's own `start_time` (UTC) must lie inside some mission's `[start, end]` window. |
| `sparus2_basic_<TS>_<N>.bag` | Always at the date level (per-date), never inside a mission folder. |
| Operator `.txt` note (name contains `ondeck`, `onwater`, or `readme`, case-insensitive) | Day is derived from the file's **modification time (mtime)**; the file lands in the date folder (not in `system_logs/`). |
| `.xtf`, `.SDS`, `.s7k`, `*_bathy_data_raw`, `*_snippet_sidescan_raw` | Filename TS is parsed and **interpreted as UTC**. Every driver that writes these files (mk_ii sidescan, Norbit multibeam) runs on the AUV's onboard computer itself, whose clock is UTC; the filename string therefore carries a UTC face. After parsing, the TS is compared against the bag's internal UTC `[start, end]` window — both sides UTC, match is unambiguous. The window is matched with a small symmetric tolerance (≈2 s) for real missions, so a sonar file written in the brief gap between `rosbag record` starting and the bag's first recorded message still pairs with its mission rather than being demoted. These files land under the mission's `raw/` subfolder. |
| `mission_report*.md` | The report's `- Start time:` / `- End time:` header lines (format `YYYY/MM/DD HH:MM:SS`, UTC) are read and the report is placed in the mission whose bag-internal `[start, end]` window has the largest positive overlap with the report's `[Start, End]` span. The report lands at the mission root (not `raw/`). If no mission window overlaps (including zero-width stub/aborted missions), the report is demoted to the date folder. If the header cannot be read, falls back to matching by the report's filename TS. |
| `iquaview_server*.log` | Day-spanning daemon log. Always at the date level, under `system_logs/`. Never matched per-mission. |
| `blackfly_s/<YYYY-MM-DD-HH-MM-SS>/`, `flir_spinnaker_camera/<YYYY-MM-DD-HH-MM-SS>/`, `flir_spinnaker_stereo_camera/<YYYY-MM-DD-HH-MM-SS>/` (whole folders) | Folder name TS is **interpreted as UTC** (the camera daemon runs on Orat, whose clock is UTC). Matched against bag internal UTC windows the same way as sonar files. Land under the mission's `raw/` subfolder. |
| `bms_*_<HEX>_<YYYY_MM_DD>.{log,csv}` | Date-only (no time). Always at the date level, under `system_logs/`. |

### Why companions match by filename, not by internal time

Companion bags (`_camera_`, `_multibeam_`, `_sidescan_`, `_stereo_camera_`) are recorded by parallel `rosbag record` processes started by the same mission launcher; their first captured messages skew by tens of milliseconds relative to the anchor. On short / aborted missions this skew exceeds the anchor's internal window and internal-time containment fails (the symptom seen on the 2026-05-04 Porto Pi dataset: ~80 wrongly-demoted companion bags). Companions share the anchor's filename TS up to ±1 s (the launcher starts all the `rosbag record` processes together, but their individual filename-formation instants can straddle a second boundary), so filename matching with that tolerance is the correct key. Real missions are minutes apart, so the tolerance window cannot bind a companion to a neighbouring mission. Internal-time containment is preserved for **split continuations** (`_1`, `_2`, …) whose filename TS is generated mid-mission and therefore differs from every anchor's by far more than the tolerance.

### Demotion

Any per-mission file (excluding sensor companion bags — see below) whose timestamp falls inside no mission's `[start, end]` is **demoted** to per-date treatment: it lands in the date folder, not in any mission folder. The audit log records this as `demoted: timestamp outside any mission`.

For sensor companion bags specifically, the policy is **warn + skip**: if a companion fails both filename-match (no anchor with the same filename TS) and internal-time containment (its own internal start is outside every mission window), the script does NOT demote it. Instead a `WARNING:` line is emitted and the file is left at its original location for manual triage. The reasoning: a companion that has lost its anchor is more likely to indicate a missing or corrupted anchor than an orphan sensor recording.

**Bagless dates** are allowed: if a sensor log mentions a date for which no main bag exists, the date folder is created anyway and the log lands at the date level.

## Naming format reference

The tool understands the following timestamp dialects:

| Dialect | Example | Used by |
|---|---|---|
| `YYYY-MM-DD-HH-MM-SS` | `2026-05-04-09-03-30` | bag filenames; `blackfly_s/`, `flir_spinnaker_camera/`, `flir_spinnaker_stereo_camera/` folder names |
| `YYYY-MM-DD_HH-MM-SS` | `2026-05-04_09-03-30` | `mk_ii/`, `norbit_wbms_multibeam/`, `mission_reports/` |
| `YYYYMMDD_HHMMSS`     | `20260504_090330`   | `iquaview_server/` |
| `YYYY_MM_DD`          | `2026_05_04`        | `emus_bms/` (date-only) and the destination date folders |
| `YYYY/MM/DD HH:MM:SS` | `2026/05/04 09:03:30` | mission report `- Start time:` / `- End time:` header lines (content-based matching) |
| mtime (filesystem)    | —                   | operator `.txt` notes (no reliable filename timestamp) |

## Time handling

Three independent time sources flow through the script. Distinguishing them is the key to getting reproducible results on the AUV, on a developer laptop, and on a remote analysis host.

| Source | Timezone | How the script handles it |
|---|---|---|
| Bag-internal timestamps (Unix epoch inside the `.bag` file) | **UTC** (always — Unix time is UTC by definition) | Read as UTC-aware `datetime` via `datetime.fromtimestamp(epoch, tz=timezone.utc)`. Independent of the host's clock. |
| Bag filenames (anchor, sensor companions, `sparus2_basic_*`, `blackfly_s/<TS>/`) | **UTC** | All recorded on the AUV's onboard computer (Orat), whose system clock is UTC by deployment policy. Attached as `tzinfo=timezone.utc` at parse time. Hardcoded — no CLI option. |
| Non-bag sensor filenames (`.s7k`, `mission_reports/*`, `iquaview_server/*`, `mk_ii/*`, camera image folder names) | **UTC** | The driver for every non-bag source runs on the AUV's onboard computer (Orat), whose clock is UTC. Attached as `tzinfo=timezone.utc` at parse time, then converted to `--local-tz` for the demote-path date folder rendering. |

Comparisons across these sources happen between TZ-aware datetimes; Python normalises to UTC internally so the script's behaviour does not depend on the host's TZ setting.

**Mission folder names are rendered in `--local-tz`**: a mission whose anchor filename is `sparus2_2026-05-04-09-03-30_0.bag` (`09:03:30` UTC) lands under `2026_05_04/11_03_30/` when run with the default `--local-tz=Europe/Madrid` (CEST is UTC+2 in May). This matches the team's existing manual organising convention. To preserve the UTC face of the filename in the folder name instead, pass `--local-tz=UTC`.

**The `--local-tz` option only affects folder rendering.** Every input timestamp the script reads — bag filenames, bag-internal timestamps, and non-bag sensor filenames — is UTC, on this AUV. `--local-tz` is purely the rendering TZ for the date and mission folder names. So a different `--local-tz` changes how date / mission folders are *named*, but never changes the underlying time the script reasons with.

## What can go wrong

The script tolerates a handful of imperfect-input conditions, each with a specific operator-visible signal:

- **Aborted recording (header-only 4-KB stub bag)**: a `WARNING: Stub mission anchor <name> ...` line on stderr. The mission folder is created from the filename anyway; companion bags sharing the filename TS are still placed correctly; non-bag sensor logs that would have fallen inside the (now zero-width) internal window get demoted instead.
- **`.bag.active` unfinished file**: stripped to `.bag` on move; a `WARNING: ... has .bag.active suffix; will rename to .bag (likely from a previous unclean shutdown)` line is emitted.
- **Split continuation (`_1`, `_2`, …)**: matched to the mission whose internal window contains the split's own internal start. The split's filename TS is later than the anchor's by design.
- **Sensor companion with no matching anchor and no internal-time hit**: `WARNING: Skipping <name>: no anchor matches by filename and internal start <TS> falls outside every mission`. The file is left at its original location (not demoted) for manual triage — see the "warn + skip" policy in the matching rules.
- **Non-bag sensor file or camera image folder whose timestamp falls outside every mission window**: demoted to `<date>/<file>`. Appears in the audit log with `demoted: timestamp outside any mission`. Some demotions are legitimate (between-mission sensor activity, dates with no anchor); a high count is worth inspecting against the run's mental model of the input data.
- **Date with no anchor**: every per-mission sensor file for that date is demoted (correctly — no mission exists). Visible as a `<date>/` folder with files at the top level and no `<HH_MM_SS>/` subfolders.
- **Collision (two sources mapping to the same destination)**: hard error; the script refuses to apply any move from the plan. Both source files are listed.
- **Pre-existing destination**: hard error; refuses to overwrite.
- **Missing `python-dateutil` / unknown IANA zone passed to `--local-tz`**: clear `ERROR:` line on stderr at startup; script exits with code 2 before any plan is built.

## Installation on the vehicle

The script is plain Python with no ROS-tooling wrapping. Clone the repository and put its `src/` directory on `$PATH`:

```bash
git clone <repo-url> ~/mission_data_organizer
echo 'export PATH="$HOME/mission_data_organizer/src:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

After this, `organize_mission_data.py` is invocable from anywhere. The script imports the sibling `mission_data_organizer/` package directly — no `pip install` step is needed. Edits to the source tree take effect immediately.

Runtime requirements on the vehicle: Python 3.8+ and `python-dateutil` (system package `python3-dateutil`, pre-installed on Ubuntu 20.04 / ROS Noetic).

## Usage

```bash
# Dry-run (default): print summary + warnings, change nothing on disk
organize_bags.py

# Dry-run with the full per-move list, captured to a file for inspection.
# The terminal still shows the summary block (it's mirrored to stderr
# when stdout is redirected); the file gets everything.
organize_bags.py -v > plan.txt

# Apply: actually move the files
organize_bags.py --apply

# Undo the most recent run
organize_bags.py --undo

# Undo a specific run (path to its audit log)
organize_bags.py --undo /home/user/bags/.organize_log/2026-05-08T12-34-56Z.log

# Run against synthetic fixtures (used in tests)
organize_bags.py --bags-root /tmp/fake/bags --logs-root /tmp/fake/logs

# Override the local TZ (non-bag filename interpretation + folder rendering).
# Defaults to Europe/Madrid; pass any IANA zone name.
organize_bags.py --local-tz=UTC          # preserve UTC face of filenames in folder names
organize_bags.py --local-tz=Europe/Lisbon # different team / different deployment

# Count demoted entries in the audit log of the most recent run
grep -c 'demoted:' /home/user/bags/.organize_log/*.log | tail -1
```

Defaults: `--bags-root=/home/user/bags`, `--logs-root=/home/user/logs`, `--local-tz=Europe/Madrid`.

### Output streams

All output (warnings, per-move list, summary, footer) goes to **stdout**
in one stream, so a single `> file` redirect captures the entire record
of the dry-run in one file. The summary block and the `Dry-run only.`
footer are *additionally* mirrored to **stderr** when stdout is detected
as not being a TTY (i.e. when you have redirected it). The net effect:

| Invocation | Terminal sees | File contains |
|---|---|---|
| `organize_bags.py -v` | everything (one stream) | — |
| `organize_bags.py -v > plan.txt` | just the summary + footer | everything (warnings + per-move list + summary + footer) |

The summary appears at the bottom of stdout — after any warnings and
after the full per-move list — so jumping to the end of `plan.txt` always
shows the headline numbers next to the dry-run footer.

### Summary format

The summary is intentionally terse:

```
Plan: 960 move(s)
  127 into mission folders (<date>/<HH_MM_SS>/)
  239 into date folders (<date>/) by design (sparus2_basic_*, bms_*)
  594 demoted to date folders (<date>/) — per-mission files whose timestamp fell outside every mission window
  5 source(s) skipped (unreadable / unparseable — see WARNINGs above)
```

The first three sub-lines sum to the move count (healthy mission
placements, by-design per-date placements, and demoted orphans whose
timestamps found no mission window). The fourth line (only shown when
non-zero) counts sources discovered but rejected — each one corresponds
to a `WARNING:` line in the captured file. Demoted orphans are worth
investigating before `--apply` if the count is higher than your mental
model of the input data predicts.

## Safety

- **Dry-run by default.** Real moves require the explicit `--apply` flag.
- **Never deletes.** Every operation is `mv`; there is no `rm` anywhere in the code.
- **Refuses to overwrite.** If the destination already exists, the script aborts that move and reports the conflict at the end of the run. Files at conflict are left in place.
- **Atomic per-file moves.** `os.rename` when source and destination are on the same filesystem; otherwise copy → verify (size and checksum) → unlink.
- **Audit log per run.** Every planned and executed move is recorded under `<bags-root>/.organize_log/<UTC-timestamp>.log`. The log is the input to `--undo`.
- **Idempotent.** Files already inside a `YYYY_MM_DD/HH_MM_SS/` subtree are skipped, so the script can be re-run any number of times as new mission output arrives.
- **`.bag.active` warning.** When such a file is encountered it is treated as a regular `.bag` (active suffix stripped on move), and a warning is written to stderr noting that this usually indicates a previous unclean shutdown.

## Out of scope

- `/home/user/logs/cola2_log/shutdown_logger.txt` — a single ever-growing log of boot/shutdown events. It cannot be split per mission and is never touched.
- Anything outside `<bags-root>` and `<logs-root>`.

## Development

Source layout:

```
mission_data_organizer/
├── README.md                              # this file
├── pyproject.toml                         # project metadata + pytest config
├── src/
│   ├── organize_mission_data.py           # entry point (put src/ on $PATH to deploy)
│   └── mission_data_organizer/            # importable Python package
│       ├── config.py                      # default paths and constants
│       ├── timestamp_parser.py            # filename and content timestamp dialects
│       ├── bag_inspector.py               # pure-Python ROS bag v2.0 parser
│       ├── mission_catalog.py             # mission anchors → mission list
│       ├── classifier.py                  # source file → destination
│       ├── source_walker.py               # iterate sources
│       ├── planner.py                     # assemble + validate the move plan
│       ├── mover.py                       # apply moves, audit log, undo
│       └── runner.py                      # CLI orchestrator
└── tests/                                 # pytest unit tests + fixture generator
```

Run unit tests from the repo root:

```bash
python3 -m pytest tests/
```

The fixture generator (`tests/fixtures/generate_fixtures.py`) uses the `rosbag` Python module to write small valid bag files (real ROS bags with explicit UTC internal timestamps, so the smoke test is independent of the host's TZ). Running the full suite therefore requires a sourced ROS environment; without it, the bag-writing smoke tests skip and 39/43 pass.
