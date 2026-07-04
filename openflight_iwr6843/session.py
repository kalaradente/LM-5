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
    kmc1_output: KMC1OutputMode = "ac"
    # Which K-MC1 output pins feed the TRS cable — a wiring + provenance
    # choice ONLY; it does not change the software filtering (clean_iq runs
    # the same either way, so you can flip the physical AC/DC switch mid-
    # session with no software change). Also auto-detected per shot, see
    # spin_decoder.detect_kmc1_output — this default is just the fallback.
    #
    # AC is the default:
    #   - AC output (40Hz-15kHz): cleaner — no DC offset or near-DC drift to
    #     deal with. Its 40Hz low corner does NOT hurt real shots: in flight
    #     the ball translates, so spin rides as sidebands on the kHz Doppler
    #     carrier (a 2000rpm driver = 33Hz sidebands on an ~11kHz carrier),
    #     entirely inside AC's passband. The 40Hz corner only attenuates spin
    #     seen at DC baseband — i.e. the non-translating drill-rig bench test.
    #   - DC output (0Hz-500kHz): full baseband including that bench low-spin
    #     case, but carries DC offset + mains hum that clean_iq removes. Kept
    #     as the switchable alternative for drill-rig calibration.
    # (Datasheet-confirmed -3dB bandwidths.) Recorded as a shot tag, see tags().

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
