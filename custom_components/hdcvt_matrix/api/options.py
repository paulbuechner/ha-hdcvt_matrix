"""Enumerations the firmware exposes, lifted from its web interface.

Values are not always contiguous and do not always start at zero, so
these map by value rather than by list position.
"""

from __future__ import annotations

from typing import Final

from .commands import (
    CEC_OUTPUT_MUTE,
    CEC_OUTPUT_POWER_OFF,
    CEC_OUTPUT_POWER_ON,
    CEC_OUTPUT_VOLUME_DOWN,
    CEC_OUTPUT_VOLUME_UP,
)

# Displays accept only these. The web UI hides the rest and refuses to send
# anything above 6 to an output.
CEC_OUTPUT_COMMANDS: Final[dict[str, int]] = {
    "power_on": CEC_OUTPUT_POWER_ON,
    "power_off": CEC_OUTPUT_POWER_OFF,
    "mute": CEC_OUTPUT_MUTE,
    "volume_down": CEC_OUTPUT_VOLUME_DOWN,
    "volume_up": CEC_OUTPUT_VOLUME_UP,
    "source": 5,
}

# Source devices get the full remote. Note power is 1/2 here where an output
# uses 0/1 for the same two actions.
CEC_INPUT_COMMANDS: Final[dict[str, int]] = {
    "power_on": 1,
    "power_off": 2,
    "up": 3,
    "left": 4,
    "enter": 5,
    "right": 6,
    "menu": 7,
    "down": 8,
    "back": 9,
    "previous": 10,
    "play": 11,
    "next": 12,
    "rewind": 13,
    "pause": 14,
    "fast_forward": 15,
    "stop": 16,
    "mute": 17,
    "volume_down": 18,
    "volume_up": 19,
}

# Firmware value -> option key. Labels live in the translation files.
HDCP_MODES: Final[dict[int, str]] = {
    1: "hdcp_1_4",
    2: "hdcp_2_2",
    3: "follow_sink",
    4: "follow_source",
    5: "off",
}
# EDID profiles the firmware accepts, lifted from the web UI. Ids 37-39 are
# the user-uploaded slots and 40+ copy the EDID from an output.
EDID_PROFILES: Final[dict[int, str]] = {
    1: "1080P,2.0CH",
    2: "1080P,5.1CH",
    3: "1080P,7.1CH",
    4: "4K30,2.0CH",
    5: "4K30,5.1CH",
    6: "4K30,7.1CH",
    7: "4K60(420),2.0CH",
    8: "4K60(420),5.1CH",
    9: "4K60(420),7.1CH",
    10: "4K60(444),2.0CH",
    11: "4K60(444),5.1CH",
    12: "4K60(444),7.1CH",
    13: "1080P_HDR,2.0CH",
    14: "1080P_HDR,5.1CH",
    15: "1080P_HDR,7.1CH",
    16: "4K30_HDR,2.0CH",
    17: "4K30_HDR,5.1CH",
    18: "4K30_HDR,7.1CH",
    19: "4K60(420)_HDR,2.0CH",
    20: "4K60(420)_HDR,5.1CH",
    21: "4K60(420)_HDR,7.1CH",
    22: "4K60(444)_HDR,2.0CH",
    23: "4K60(444)_HDR,5.1CH",
    24: "4K60(444)_HDR,7.1CH",
    25: "4K120(420)_HDR,2.0CH",
    26: "4K120(420)_HDR,5.1CH",
    27: "4K120(420)_HDR,7.1CH",
    28: "4K120(444)_HDR,2.0CH",
    29: "4K120(444)_HDR,5.1CH",
    30: "4K120(444)_HDR,7.1CH",
    31: "FRL10G_8K_HDR,2.0CH",
    32: "FRL10G_8K_HDR,5.1CH",
    33: "FRL10G_8K_HDR,7.1CH",
    34: "FRL12G_8K_HDR,2.0CH",
    35: "FRL12G_8K_HDR,5.1CH",
    36: "FRL12G_8K_HDR,7.1CH",
    37: "User1_EDID",
    38: "User2_EDID",
    39: "User3_EDID",
    40: "COPY_FROM_OUTPUT_1",
    41: "COPY_FROM_OUTPUT_2",
    42: "COPY_FROM_OUTPUT_3",
    43: "COPY_FROM_OUTPUT_4",
    44: "COPY_FROM_OUTPUT_5",
    45: "COPY_FROM_OUTPUT_6",
    46: "COPY_FROM_OUTPUT_7",
    47: "COPY_FROM_OUTPUT_8",
}

# How the de-embedded audio outputs are driven. In the bind modes the audio
# follows a video port; only in matrix mode is it routed independently.
EXT_AUDIO_MODES: Final[dict[int, str]] = {
    0: "bind_to_input",
    1: "bind_to_output",
    2: "audio_matrix",
}
EXT_AUDIO_MODE_MATRIX: Final = 2

# RS-232 rate for the serial control port. Ids start at 1, not 0.
BAUD_RATES: Final[dict[int, str]] = {
    1: "4800",
    2: "9600",
    3: "19200",
    4: "38400",
    5: "57600",
    6: "115200",
}

# Front panel backlight timeout. Reported as "mode" in get system status,
# which is not obvious from the field name.
LCD_ON_TIMES: Final[dict[int, str]] = {
    0: "always_on",
    1: "5_seconds",
    2: "10_seconds",
    3: "30_seconds",
    4: "1_minute",
    5: "5_minutes",
    6: "10_minutes",
}

# The web UI offers only 0, 1 and 3. Modes 2 and 4 are real regardless:
# enumerated over the telnet CLI against the reference unit (fw V1.00.19),
# which names them "8k/4k->1080p" and "audio only".
SCALER_MODES: Final[dict[int, str]] = {
    0: "bypass",
    1: "downscale_4k_to_1080p",
    2: "downscale_8k_4k_to_1080p",
    3: "auto",
    4: "audio_only",
}
