"""Default paths and constants for mission_data_organizer.

These are the production defaults used on the vehicle. CLI flags
(``--bags-root``, ``--logs-root``) override them — tests use that override
to point the tool at synthetic fixtures.
"""

# Default roots on the vehicle.
DEFAULT_BAGS_ROOT = "/home/user/bags"
DEFAULT_LOGS_ROOT = "/home/user/logs"

# Subdirectories under <logs-root> whose contents are filed per mission.
LOG_SOURCES_PER_MISSION = (
    "blackfly_s",
    "iquaview_server",
    "mission_reports",
    "mk_ii",
    "norbit_wbms_multibeam",
)

# Per-mission log sources whose files are native sonar recordings (Norbit
# multibeam, mk_ii sidescan). Their files are grouped under a raw/ subfolder
# inside the mission folder, leaving derived products at the mission root.
RAW_NATIVE_SOURCES = (
    "norbit_wbms_multibeam",
    "mk_ii",
)

# Subdirectories under <logs-root> whose contents are filed per date (no time).
LOG_SOURCES_PER_DATE = (
    "emus_bms",
)

# Subdirectories under <logs-root> deliberately ignored (continuous log or empty).
LOG_SOURCES_OUT_OF_SCOPE = (
    "cola2_log",
    "flir_spinnaker_camera",
    "flir_spinnaker_stereo_camera",
)

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
