"""Constants for the Pill Pal integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "pill_pal"
PLATFORMS: list[Platform] = [
    Platform.LIGHT, Platform.EVENT, Platform.SENSOR, Platform.BINARY_SENSOR
]

DEFAULT_PORT = 8080

CONF_DEVICE_ID = "device_id"
CONF_GRANT_ID = "grant_id"
CONF_GRANT_KEY = "grant_key"
CONF_GENERATION = "ownership_generation"

# What the lamp shows as this connection's name in the app, and on its grant.
INTEGRATION_NAME = "Home Assistant"

# The version of the lamp's integrations.md this integration speaks, from mDNS `api`.
SUPPORTED_API = "1"

# Transient commands expire this long after they are sent (README, "Durable and
# transient"). Long enough for a slow Wi-Fi round trip, short enough that a command held
# up somewhere does not arrive minutes later.
COMMAND_LIFETIME_MS = 30_000

# How often the pending approval is polled, and for how long.
APPROVAL_POLL_SECONDS = 2
APPROVAL_TIMEOUT_SECONDS = 600

# The event stream. The lamp sends a keepalive every 15 seconds.
STREAM_LIVENESS_SECONDS = 45
STREAM_RECONNECT_INITIAL_SECONDS = 2
STREAM_RECONNECT_MAX_SECONDS = 60

# A safety net under the stream, not the way state arrives.
POLL_INTERVAL_SECONDS = 300

SIGNAL_TOUCH = f"{DOMAIN}_touch_{{device_id}}"
SIGNAL_AVAILABILITY = f"{DOMAIN}_availability_{{device_id}}"

# The lamp's built-in ambient scenes, in its order (controller.h). Custom is a colour.
SCENES = ["warm_white", "candle", "ocean", "sunrise", "forest"]
SCENE_CUSTOM = 5

# A snooze always lasts this long from the moment it is taken (README, "Occurrence
# lifecycle"), so a snoozed occurrence's deadline also says when it was snoozed.
SNOOZE_MS = 10 * 60 * 1000

NOTIFY_PATTERNS = ["flash", "pulse", "sweep", "rainbow"]
STATUS_PATTERNS = ["solid", "pulse"]
PRIORITIES = ["low", "normal", "high"]
GESTURES = ["tap", "double_tap", "long_press"]
