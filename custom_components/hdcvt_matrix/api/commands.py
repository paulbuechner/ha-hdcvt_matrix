"""Command vocabulary for the HDCVT matrix HTTP API.

Every request is a POST to ``CGI_INSTR`` whose body carries a ``comhead``
naming the command. Ports are one-based throughout; ``0`` usually means
"all ports".
"""

from __future__ import annotations

from typing import Final

CGI_INSTR: Final = "/cgi-bin/instr"
DEFAULT_PORT: Final = 80
DEFAULT_TIMEOUT: Final = 10

# The protocol names its command field this; every payload carries one.
KEY_COMHEAD: Final = "comhead"

# Reads are retried while the matrix is busy after a heavy command. Writes are
# not: they are not idempotent.
READ_ATTEMPTS: Final = 3
READ_RETRY_DELAY: Final = 0.4

CMD_LOGIN: Final = "login"
CMD_GET_STATUS: Final = "get status"
CMD_GET_VIDEO_STATUS: Final = "get video status"
CMD_GET_OUTPUT_STATUS: Final = "get output status"
CMD_GET_INPUT_STATUS: Final = "get input status"
CMD_GET_SYSTEM_STATUS: Final = "get system status"
CMD_GET_NETWORK: Final = "get network"
CMD_VIDEO_SWITCH: Final = "video switch"
CMD_SET_POWER: Final = "set poweronoff"
CMD_PRESET_SET: Final = "preset set"
CMD_PRESET_SAVE: Final = "preset save"
CMD_TX_STREAM: Final = "tx stream"
CMD_SET_AUDIO_MUTE: Final = "set output audio mute"
CMD_TX_HDCP: Final = "tx hdcp"
# The web UI's own command map says "video scaler", but the firmware rejects
# that and only answers to "set video scaler". Verified against the device.
CMD_SET_SCALER: Final = "set video scaler"
CMD_SET_PANEL_LOCK: Final = "set panel lock"
CMD_SET_BEEP: Final = "set beep"
CMD_CEC_COMMAND: Final = "cec command"
CMD_SET_ARC: Final = "set arc"
CMD_SET_EDID: Final = "set edid"
CMD_REBOOT: Final = "reboot"
CMD_GET_EXT_AUDIO: Final = "get ext-audio status"
CMD_EXT_AUDIO_SWITCH: Final = "ext-audio switch"
CMD_SET_EXT_AUDIO_OUT: Final = "set ext-audio out"
CMD_SET_EXT_AUDIO_MODE: Final = "set ext-audio mode"
CMD_PRESET_CLEAR: Final = "preset clear"
CMD_PRESET_NAME: Final = "preset name"
CMD_SET_INPUT_NAME: Final = "set input name"
CMD_SET_OUTPUT_NAME: Final = "set output name"
CMD_SET_BAUDRATE: Final = "set baudrate"
CMD_SET_LCD_ON_TIME: Final = "set lcd on time"

# The web UI caps port names at 32 characters and preset names at 49 bytes.
MAX_PORT_NAME: Final = 32
MAX_PRESET_NAME: Final = 49

# CEC targets. "port" is a mask over all ports, not a port number, and it is
# passed per command: it does not disturb the selection stored by
# "set cec index".
CEC_OBJECT_INPUT: Final = 0
CEC_OBJECT_OUTPUT: Final = 1

# Output CEC command ids. Inputs use a *different* numbering for the same
# actions (1 = on, 2 = off), so do not reuse these for CEC_OBJECT_INPUT.
CEC_OUTPUT_POWER_ON: Final = 0
CEC_OUTPUT_POWER_OFF: Final = 1
CEC_OUTPUT_MUTE: Final = 2
CEC_OUTPUT_VOLUME_DOWN: Final = 3
CEC_OUTPUT_VOLUME_UP: Final = 4
