"""
shot_fusion.py — merge the geometry channel (IWR6843) and spin channel
(K-MC1 audio) into one shot with per-field provenance, shaped for
OpenFlight's on_shot() interface.

Wiring: IWR6843Source.on_geometry fires with a geometry dict; the fuser
slices the matching window out of the audio ring buffer, runs the spin
decoder, merges, and calls the OpenFlight publish callback.

Spin provenance:
  "measured"  — K-MC1 decoder returned a confident RPM
  "inferred"  — fallback lookup from club-speed/launch regression
  None        — no estimate available
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import numpy as np

try:
    import sounddevice as sd
except (ImportError, OSError):                        # allow offline replay
    sd = None

from .spin_decoder import decode, detect_kmc1_output, FS

SPIN_CONF_FLOOR = 0.35        # below this, fall back to inference
AUDIO_PRE = 0.05              # s of audio before impact to include
AUDIO_POST = 0.15             # s after


class AudioRing:
    """Continuous stereo ring buffer with monotonic timestamps."""

    def __init__(self, seconds: float = 5.0, fs: int = FS, device=None):
        self.fs = fs
        self.n = int(seconds * fs)
        self.buf = np.zeros((self.n, 2), dtype=np.float32)
        self.write = 0
        self.t_last = time.monotonic()
        self.lock = threading.Lock()
        self.stream = None
        self.device = device

    def start(self):
        if sd is None:
            raise RuntimeError("sounddevice not installed")
        self.stream = sd.InputStream(samplerate=self.fs, channels=2,
                                     device=self.device,
                                     callback=self._cb, blocksize=1024)
        self.stream.start()

    def _cb(self, indata, frames, t_info, status):
        with self.lock:
            end = self.write + frames
            if end <= self.n:
                self.buf[self.write:end] = indata
            else:
                k = self.n - self.write
                self.buf[self.write:] = indata[:k]
                self.buf[:end - self.n] = indata[k:]
            self.write = end % self.n
            self.t_last = time.monotonic()

    def window(self, t_center: float, pre: float, post: float) -> np.ndarray:
        """Complex I/Q slice covering [t_center-pre, t_center+post]."""
        with self.lock:
            age = self.t_last - t_center
            n_back = int((age + pre) * self.fs)
            n_len = int((pre + post) * self.fs)
            start = (self.write - n_back) % self.n
            idx = (start + np.arange(n_len)) % self.n
            seg = self.buf[idx].astype(np.float64)
        peak = np.max(np.abs(seg)) or 1.0
        seg /= peak
        return seg[:, 0] + 1j * seg[:, 1]


def infer_spin(geom: dict) -> Optional[float]:
    """Tier-1 fallback: crude launch-condition regression. Replace the
    coefficients with your Eye XO-fitted model as data accumulates."""
    bs, la = geom.get("ball_speed_mph"), geom.get("launch_angle_deg")
    if bs is None or la is None:
        return None
    rpm = 12_000 - 55.0 * bs + 260.0 * la          # placeholder surface
    return float(np.clip(rpm, 1500, 12_000))


class ShotFuser:
    def __init__(self, publish: Callable[[dict], None],
                 audio: Optional[AudioRing] = None,
                 session=None):
        self.publish = publish
        self.audio = audio
        # Reserved for future session-driven presets (spin_conf_floor,
        # capture window — see TODO). No longer used for filter selection:
        # cleaning is unconditional now (see on_geometry).
        self.session = session          # session.SessionConfig, optional

    def on_geometry(self, geom: dict):
        shot = dict(geom)
        shot["spin_rpm"], shot["spin_source"], shot["spin_confidence"] = \
            None, None, 0.0
        if self.audio is not None:
            z = self.audio.window(geom["t_impact"], AUDIO_PRE, AUDIO_POST)
            self._archive_audio(z, geom.get("capture_id"))
            # Cleaning is unconditional and identical for either K-MC1 output:
            # on an AC capture, clean_iq's DC-removal + 20Hz high-pass are
            # no-ops (nothing below the 40Hz corner) and only its 60Hz notch
            # acts — which is wanted, since 60Hz hum survives AC coupling and
            # sits in the spin band. So the AC/DC switch needs no software
            # change; see session.py.
            result = decode(z)
            # Auto-detect AC vs DC wiring from the capture and tag the shot
            # (provenance only; the switch doesn't change decoding). Overrides
            # any static session.kmc1_output with what the signal actually shows.
            shot["kmc1_output"] = detect_kmc1_output(z)
            if result.get("ok") and \
                    result.get("confidence", 0) >= SPIN_CONF_FLOOR:
                shot.update(spin_rpm=round(result["spin_rpm"]),
                            spin_source="measured",
                            spin_confidence=result["confidence"])
        if shot["spin_rpm"] is None:
            est = infer_spin(geom)
            if est is not None:
                shot.update(spin_rpm=round(est), spin_source="inferred",
                            spin_confidence=0.2)
        # Spin axis from lateral curvature (tier 2): a = spin-induced lateral
        # accel; crude axis-tilt proxy until fitted against truth data.
        ax = geom.get("lateral_accel_mps2")
        shot["spin_axis_hint_deg"] = round(np.degrees(np.arctan2(ax, 9.81)), 1) \
            if ax is not None else None
        self.publish(shot)

    def _archive_audio(self, z, capture_id, directory="captures"):
        """Save the I/Q slice next to its radar capture (same capture_id),
        so every shot is replayable through decode() offline."""
        if capture_id is None:
            return
        try:
            import os
            os.makedirs(directory, exist_ok=True)
            np.save(os.path.join(directory, f"audio_{capture_id}.npy"), z)
        except OSError:
            pass


def openflight_publish_adapter(shot: dict):
    """Match this to the field names in openflight's shot dataclass and call
    its server publish path. Kept as a print for standalone bring-up."""
    print(f"[shot] {shot['ball_speed_mph']} mph | "
          f"launch {shot['launch_angle_deg']} | side {shot['side_angle_deg']} | "
          f"spin {shot['spin_rpm']} ({shot['spin_source']}, "
          f"conf {shot['spin_confidence']})")
