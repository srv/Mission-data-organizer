"""Default paths and constants for mission_data_organizer.

These are the production defaults used on the vehicle. CLI flags
(``--bags-root``, ``--logs-root``) override them — tests use that override
to point the tool at synthetic fixtures.
"""

# Default roots on the vehicle.
DEFAULT_BAGS_ROOT = "/home/user/bags"
DEFAULT_LOGS_ROOT = "/home/user/logs"

# Subdirectories under <logs-root> whose contents are filed per mission
# (one file at a time). Camera image folders (blackfly_s, flir_spinnaker_*)
# are handled separately as whole-folder sources — see
# LOG_SOURCES_FOLDER_PER_MISSION.
LOG_SOURCES_PER_MISSION = (
    "mission_reports",
    "mk_ii",
    "norbit_wbms_multibeam",
)

# Subdirectories under <logs-root> that are camera image *folders*: each
# first-level subfolder (named YYYY-MM-DD-HH-MM-SS) is a mission's worth of
# paired stereo images and is moved as a whole. They are placed per mission;
# being raw sensor data, they all route under raw/ (see RAW_NATIVE_SOURCES).
LOG_SOURCES_FOLDER_PER_MISSION = (
    "blackfly_s",
    "flir_spinnaker_camera",
    "flir_spinnaker_stereo_camera",
)

# Sources whose contents are raw sensor data and are therefore grouped under a
# raw/ subfolder inside the mission folder, leaving derived products (bags,
# reports) at the mission root. Covers native sonar recordings (Norbit
# multibeam, mk_ii sidescan) and the camera image folders. Source-driver
# keyed: matched against the file's parent directory name.
RAW_NATIVE_SOURCES = (
    "norbit_wbms_multibeam",
    "mk_ii",
    "blackfly_s",
    "flir_spinnaker_camera",
    "flir_spinnaker_stereo_camera",
)

# Subdirectories under <logs-root> whose contents are filed per date (no time).
# The IQUAview server daemon log spans the whole operating day, so it is
# per-date, not per-mission. Both per-date log families are grouped under a
# <date>/system_logs/ subfolder (see SYSTEM_LOG_SUBDIR).
LOG_SOURCES_PER_DATE = (
    "emus_bms",
    "iquaview_server",
)

# Subdirectories under <logs-root> deliberately ignored (continuous log).
LOG_SOURCES_OUT_OF_SCOPE = (
    "cola2_log",
)

# Lowercased substrings that mark a root-level <bags-root>/*.txt operator note
# (auto-generated ondeck/onwater summaries; a free-form readme). Filed into the
# day folder by file mtime — their filename dates are irregular/absent.
DAY_TEXT_MARKERS = (
    "ondeck",
    "onwater",
    "readme",
)

# Day-level subfolder grouping the per-date system logs (emus_bms, iquaview).
SYSTEM_LOG_SUBDIR = "system_logs"

# The audit-log dir name, created lazily under <bags-root>.
AUDIT_LOG_DIRNAME = ".organize_log"

# Sensor-bag filename markers. A bag is considered the "main mission anchor"
# only if NONE of these markers appears in its name.
BAG_SENSOR_MARKERS = (
    "_basic_",
    "_camera_",
    "_multibeam_",
    "_sidescan_",
    "_stereo_camera_",
)

# Sensor-bag markers that are filed per mission (everything except basic).
BAG_SENSOR_MARKERS_PER_MISSION = (
    "_camera_",
    "_multibeam_",
    "_sidescan_",
    "_stereo_camera_",
)

# Sensor-bag marker that's filed per date.
BAG_SENSOR_MARKER_PER_DATE = "_basic_"
