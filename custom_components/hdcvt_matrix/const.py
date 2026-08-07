"""Constants for the HDCVT HDMI Matrix integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "hdcvt_matrix"
MANUFACTURER: Final = "HDCVT"

# Factory credentials for the matrix web interface. Published by the vendor and
# offered as a one-click default in the config flow, so this is deliberate
# rather than a leaked secret.
DEFAULT_USERNAME: Final = "Admin"
DEFAULT_PASSWORD: Final = "admin"  # noqa: S105
CONF_USE_DEFAULT_CREDENTIALS: Final = "use_default_credentials"

# Flow error and abort reasons. Named so a typo cannot silently drift away from
# the matching key in strings.json.
ERROR_CANNOT_CONNECT: Final = "cannot_connect"
ERROR_INVALID_AUTH: Final = "invalid_auth"
ERROR_UNKNOWN: Final = "unknown"
ERROR_UNSUPPORTED_DEVICE: Final = "unsupported_device"

DEFAULT_PORT: Final = 80
DEFAULT_TIMEOUT: Final = 10

# Seconds between polls. The CGI backend is single threaded, so the floor is
# deliberately not 1: hammering it makes it drop replies.
DEFAULT_SCAN_INTERVAL: Final = 10
MIN_SCAN_INTERVAL: Final = 5
MAX_SCAN_INTERVAL: Final = 300

PLATFORMS: Final[list[Platform]] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.TEXT,
]
