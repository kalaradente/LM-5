"""
session.py — session-level mode selection: indoor/outdoor x ball type.

Declared once at startup (CLI flags, config file, or a UI toggle in the
OpenFlight front end), a SessionConfig maps to concrete parameter presets
for both channels and tags every shot record for honest validation.

Nothing per-shot lives here; if a value would change between swings, it
does not belong in this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Environment = Literal["indoor", "outdoor"]
BallType = Literal["plain", "marked", "rct"]


@dataclass(frozen=True)
class SessionConfig:
    environment: Environment = "indoor"
    ball_type: BallType = "plain"
    # K-MC1 is wired to its AC output (40Hz-15kHz). That's cleaner (no DC
    # offset/hum) and it reads every real shot: in flight the ball translates,
    # so spin rides as sidebands on the kHz Doppler carrier (a 2000rpm driver
    # = 33Hz sidebands on an ~11kHz carrier), well inside AC's passband. No
    # AC/DC selection in software — see openflight_iwr6843/README.md.

    # ---- geometry channel presets ------------------------------------

    @property
    def range_gate(self) -> tuple[float, float]:
        # Indoor: flight ends at the net; beyond it is wall/net clutter.
        # Outdoor: 10 m, matching golf-outdoor.cfg's actual reach (R_max
        # 10.71 m at 140 MHz/us + 10 Msps -- audit D-5 resolved: the old
        # 15 m gate exceeded what any legal chirp under the 10 MHz IF cap
        # could deliver at indoor-grade range resolution). ~36 driver
        # fixes at 333 Hz vs ~25 indoors at 454.5 Hz (3-TX profiles,
        # audits V-1/V-4). run_iwr6843.py auto-selects the outdoor cfg
        # for outdoor sessions unless --cfg overrides.
        return (0.3, 6.0) if self.environment == "indoor" else (0.3, 10.0)

    @property
    def capture_window_s(self) -> float:
        # Outdoor: ball stays observable longer; more fixes, better fit,
        # and more dwell for the spin channel.
        return 0.20 if self.environment == "indoor" else 0.45

    @property
    def clutter_removal(self) -> bool:
        # OFF in BOTH environments (audit V-6, 2026-07-06). The chip's
        # static-clutter subtraction erases Doppler bin 0 BEFORE detection
        # -- and TDM folding parks real balls there: radial speeds near
        # every multiple of 2*v_max_ext (~85 mph and ~169 mph at the 3-TX
        # indoor profile) fold to bin 0. Simulated with drag: drives
        # launched 170-174 mph were missed on 8/8 seeds (the ball never
        # decelerates out of the band inside the 6 m gate); ~85 mph irons
        # and ~85 mph clubheads sit in the second band. With clutter
        # removal off, the same sweep measures every speed (|err| <= 3 mph,
        # ~21 fixes). Bay statics instead ride through as loitering tracks
        # and die in the classifier (proven: the geometry simulator plants
        # static reflectors). If a real bay floods the UART with static
        # detections at rung 3, raise the indoor CFAR threshold via
        # cfar_threshold_offset_db -- do NOT re-enable clutter removal.
        return False

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
        # (the rung-4 drill-rig experiment produces exactly this table).
        return {"plain": 0.55, "marked": 0.40, "rct": 0.30}[self.ball_type]

    @property
    def spin_audio_window_s(self) -> tuple[float, float]:
        # (pre, post) seconds around impact for the I/Q slice. Outdoors,
        # extend post-roll: the carrier stays trackable further out.
        # Pre is a 10 ms CLOCK-ALIGNMENT GUARD only, not a data window
        # (audit E-9): everything before impact is the descending clubhead
        # -- bigger RCS, in-band Doppler, poison for the carrier tracker.
        # The old 50 ms pre-pad existed because t_impact was sloppy; F-7
        # pinned it to +/- a frame, so the pad's only remaining job is
        # absorbing USB-chunking jitter on the host-clock anchor (the
        # clap-test TODO tightens even that).
        return (0.01, 0.15) if self.environment == "indoor" else (0.01, 0.35)

    # ---- record keeping ----------------------------------------------

    def tags(self) -> dict:
        """Fields merged into every shot record for validation grouping."""
        return {"environment": self.environment, "ball_type": self.ball_type}

    def summary(self) -> str:
        return (f"{self.environment}, {self.ball_type} balls | "
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
