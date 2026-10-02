"""Shared defaults without Home Assistant dependencies."""

DOMAIN = "ha_tgen"
VERSION = "0.1.0"
STORAGE_VERSION = 1
STORAGE_KEY = "ha_tgen.data"
DEFAULT_OUTPUT_ROOT = "/media/ha_tgen"
DEFAULT_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
MODES = ("weekly", "monthly", "yearly", "custom")
SCHEDULE_MODES = MODES[:3]
MAX_PENDING_JOBS = 100
MAX_JOB_HISTORY = 500
MAX_WARNING_SAMPLES = 20
