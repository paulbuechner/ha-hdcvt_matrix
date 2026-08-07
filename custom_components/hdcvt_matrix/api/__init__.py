"""Client for HDCVT web-controlled HDMI matrices.

Split by job rather than by layer:

* :mod:`commands` -- the wire vocabulary, one constant per ``comhead``
* :mod:`options` -- firmware value to label maps for the enumerated settings
* :mod:`models` -- what the matrix reports about itself
* :mod:`exceptions` -- the four failure modes callers distinguish
* :mod:`client` -- the HTTP client itself

Everything the integration needs is re-exported here, so importing from
``.api`` stays the one entry point.
"""

from __future__ import annotations

from .client import HdcvtMatrixClient, MatrixSession
from .commands import (
    CEC_OBJECT_INPUT,
    CEC_OBJECT_OUTPUT,
    CEC_OUTPUT_MUTE,
    CEC_OUTPUT_POWER_OFF,
    CEC_OUTPUT_POWER_ON,
    CEC_OUTPUT_VOLUME_DOWN,
    CEC_OUTPUT_VOLUME_UP,
    MAX_PORT_NAME,
    MAX_PRESET_NAME,
    READ_ATTEMPTS,
    READ_RETRY_DELAY,
)
from .exceptions import (
    MatrixAuthError,
    MatrixConnectionError,
    MatrixError,
    MatrixResponseError,
)
from .models import MatrixInfo, MatrixState
from .options import (
    BAUD_RATES,
    CEC_INPUT_COMMANDS,
    CEC_OUTPUT_COMMANDS,
    EDID_PROFILES,
    EXT_AUDIO_MODE_MATRIX,
    EXT_AUDIO_MODES,
    HDCP_MODES,
    LCD_ON_TIMES,
    SCALER_MODES,
)

__all__ = [
    "BAUD_RATES",
    "CEC_INPUT_COMMANDS",
    "CEC_OBJECT_INPUT",
    "CEC_OBJECT_OUTPUT",
    "CEC_OUTPUT_COMMANDS",
    "CEC_OUTPUT_MUTE",
    "CEC_OUTPUT_POWER_OFF",
    "CEC_OUTPUT_POWER_ON",
    "CEC_OUTPUT_VOLUME_DOWN",
    "CEC_OUTPUT_VOLUME_UP",
    "EDID_PROFILES",
    "EXT_AUDIO_MODES",
    "EXT_AUDIO_MODE_MATRIX",
    "HDCP_MODES",
    "LCD_ON_TIMES",
    "MAX_PORT_NAME",
    "MAX_PRESET_NAME",
    "READ_ATTEMPTS",
    "READ_RETRY_DELAY",
    "SCALER_MODES",
    "HdcvtMatrixClient",
    "MatrixAuthError",
    "MatrixConnectionError",
    "MatrixError",
    "MatrixInfo",
    "MatrixResponseError",
    "MatrixSession",
    "MatrixState",
]
