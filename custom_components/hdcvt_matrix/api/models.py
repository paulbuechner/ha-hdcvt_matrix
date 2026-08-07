"""What the matrix reports about itself."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MatrixInfo:
    """Identity of the matrix, read once during setup."""

    model: str
    hostname: str
    mac_address: str
    firmware: str


@dataclass(slots=True)
class MatrixState:
    """Mutable state of the matrix, refreshed on every poll."""

    power: bool
    # Index is the zero-based output, value is the one-based input feeding it.
    routes: list[int] = field(default_factory=list)
    input_names: list[str] = field(default_factory=list)
    output_names: list[str] = field(default_factory=list)
    preset_names: list[str] = field(default_factory=list)
    # A source is detected on this input / a sink is detected on this output.
    input_active: list[bool] = field(default_factory=list)
    output_connected: list[bool] = field(default_factory=list)
    # Output stream enabled, and output audio muted.
    output_enabled: list[bool] = field(default_factory=list)
    audio_muted: list[bool] = field(default_factory=list)
    # Raw per-output mode values; see HDCP_MODES and SCALER_MODES.
    hdcp_modes: list[int] = field(default_factory=list)
    scaler_modes: list[int] = field(default_factory=list)
    # ARC on the output, and the EDID profile id on each input.
    arc_enabled: list[bool] = field(default_factory=list)
    input_edids: list[int] = field(default_factory=list)
    # De-embedded audio: mode, per-output source, per-output enable.
    ext_audio_mode: int = 0
    ext_audio_routes: list[int] = field(default_factory=list)
    ext_audio_enabled: list[bool] = field(default_factory=list)
    ext_audio_output_names: list[str] = field(default_factory=list)
    # Front panel state.
    panel_locked: bool = False
    beep_enabled: bool = False
    baud_rate: int = 0
    lcd_on_time: int = 0

    def names_for(self, kind: str) -> list[str]:
        """Return the device's names for a port kind.

        The three name lists are addressed the same way by entities and by
        renaming, so the mapping lives here rather than in each caller.
        """
        return {
            "input": self.input_names,
            "output": self.output_names,
            "preset": self.preset_names,
            # The de-embedded audio outputs carry their own names, which the
            # firmware reports separately from the video outputs.
            "ext_audio": self.ext_audio_output_names,
        }[kind]

    @property
    def input_count(self) -> int:
        """Number of physical inputs."""
        return len(self.input_names)

    @property
    def output_count(self) -> int:
        """Number of physical outputs."""
        return len(self.output_names)
