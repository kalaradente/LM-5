"""
session.py — session-level mode selection: indoor/outdoor x ball type.

Declared once at startup (CLI flags, config file, or a UI toggle in the
OpenFlight front end), a SessionConfig maps to concrete parameter presets
for both channels and tags every shot record for honest validation.

Nothing per-shot lives here; if a value would change between swings, it
does not belong in this file.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

Environment = Literal["indoor", "outdoor"]
BallType = Literal["plain", "marked", "rct"]
KMC1OutputMode = Literal["ac", "dc"]


@dataclass(frozen=True)
class SessionConfig:
    environment: Environment = "indoor"
    ball_type: BallType = "plain"
    kmc1_output: KMC1OutputMode = "dc"
    # Bandwidths below are datasheet-confirmed K-MC1 -3dB figures.
    # "ac"  — wired to the K-MC1's AC output pins (40Hz-15kHz, -3dB).
    #         Hardware already rolls off near-DC clutter; software filtering
    #         mostly redundant, but the AC path attenuates spin tones below
    #         ~2400rpm (40Hz) — the K-MC1's amplifier does this in analog,
    #         before your ADC ever sees the signal, so software can't undo it.
    # "dc"  — wired to the K-MC1's DC output pins (0Hz-500kHz, -3dB).
    #         Full spin band intact including low-driver-spin cases, but
    #         carries DC offset + mains hum that software must remove
    #         (see spin_decoder.clean_iq). This is the default: it's the
    #         complete-spectrum choice, and the cleanup is well-understood,
    #         cheap, and already wired into decode().

    @property
    def spin_filter_kwargs(self) -> dict:
        """Passed to spin_decoder.decode(). AC wiring already band-limited
        by the module itself, so skip redundant software filtering; DC
        wiring needs both stages to recover a clean signal."""
        if self.kmc1_output == "ac":
            return {"highpass": False, "notch_mains": False}
        return {"highpass": True, "notch_mains": True}

    # ---- geometry channel presets ------------------------------------

    @property
    def range_gate(self) -> tuple[float, float]:
        # Indoor: flight ends at the net; beyond it is wall/net clutter.
        # Outdoor: extend to harvest more trajectory fixes.
        return (0.3, 6.0) if self.environment == "indoor" else (0.3, 15.0)

    @property
    def capture_window_s(self) -> float:
        # Outdoor: ball stays observable longer; more fixes, better fit,
        # and more dwell for the spin channel.
        return 0.20 if self.environment == "indoor" else 0.45

    @property
    def clutter_removal(self) -> bool:
        # Static-background subtraction earns its keep in a bay; outdoors
        # the scene is sparse and sensitivity is worth more.
        return self.environment == "indoor"

    @property
    def cfar_threshold_offset_db(self) -> float:
        # Relative nudge applied to the golf.cfg baseline CFAR threshold.
        # Indoor bays are cluttered (tighter); outdoors can run looser.
        return 0.0 if self.environment == "indoor" else -3.0

    # ---- spin channel presets ----------------------------------------

    @property
    def spin_conf_floor(self) -> float:
        # Below this confidence, fall back to inferred spin. Placeholder
        # values; replace with bench-calibrated numbers per ball type
        # (the rung-3 drill-rig experiment produces exactly this table).
        return {"plain": 0.55, "marked": 0.40, "rct": 0.30}[self.ball_type]

    @property
    def spin_audio_window_s(self) -> tuple[float, float]:
        # (pre, post) seconds around impact for the I/Q slice. Outdoors,
        # extend post-roll: the carrier stays trackable further out.
        return (0.05, 0.15) if self.environment == "indoor" else (0.05, 0.35)

    # ---- record keeping ----------------------------------------------

    def tags(self) -> dict:
        """Fields merged into every shot record for validation grouping."""
        return {"environment": self.environment, "ball_type": self.ball_type,
                "kmc1_output": self.kmc1_output}

    def summary(self) -> str:
        return (f"{self.environment}, {self.ball_type} balls, "
                f"K-MC1 {self.kmc1_output.upper()} output | "
                f"gate {self.range_gate}m, window {self.capture_window_s}s, "
                f"spin floor {self.spin_conf_floor}")


def from_args(argv=None) -> SessionConfig:
    """CLI helper: --outdoor / --ball plain|marked|rct"""
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--outdoor", action="store_true")
    p.add_argument("--ball", choices=["plain", "marked", "rct"],
                   default="plain")
    a = p.parse_args(argv)
    cfg = SessionConfig("outdoor" if a.outdoor else "indoor", a.ball)
    print(f"[session] {cfg.summary()}")
    return cfg
