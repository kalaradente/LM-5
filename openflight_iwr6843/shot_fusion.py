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

from .session import SessionConfig
from .spin_decoder import decode, FS


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
        self.last_clip: dict = {}     # clip diagnostics of the last window()

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
            # Staleness guard (audit F-5): if the request reaches further
            # back than the ring holds, the modulo math would silently wrap
            # and return unrelated newer samples as if they were the shot.
            # Clamp to the oldest real history and say so -- a shifted
            # window degrades gracefully; a wrapped one lies.
            if n_back > self.n:
                print(f"[audio] window request {n_back / self.fs:.2f}s back "
                      f"exceeds ring depth {self.n / self.fs:.2f}s -- clamped "
                      f"(late trigger?)")
                n_back = self.n
            n_len = min(n_len, self.n)
            start = (self.write - n_back) % self.n
            idx = (start + np.arange(n_len)) % self.n
            seg = self.buf[idx].astype(np.float64)
        # Clip detection BEFORE peak-normalization destroys the level
        # evidence (audit D-3). Two mechanisms, two tests:
        #   - ADC clipping: peak at the converter's full scale (~1.0).
        #   - IN-MODULE clipping (K-MC1's own 32dB IF amp -- the HiFiBerry
        #     PGA can't prevent or undo it): flat-topping at some arbitrary
        #     ADC level. Signature: CONSECUTIVE samples pinned at the
        #     window's own peak. Consecutive matters: a kHz carrier at
        #     96 kHz has only ~6-12 samples/cycle, so single crest samples
        #     sit at the observed peak on a perfectly clean tone (a
        #     fraction-near-peak test false-alarms at ~17%); only a real
        #     plateau produces runs of them. Threshold is a bench-tunable
        #     heuristic (rung 4), not gospel.
        # A clipped carrier smears harmonics across the spin band, so
        # confident-looking spin from a clipped capture is fake evidence
        # -- ShotFuser reads this and halves the measured confidence.
        peak = float(np.max(np.abs(seg))) or 1.0
        pinned = np.abs(seg) >= 0.995 * peak
        runs = float(np.mean(pinned[1:] & pinned[:-1]))
        self.last_clip = {
            "adc_full_scale": peak >= 0.98,
            "plateau_frac": round(runs, 4),
            "clipped": peak >= 0.98 or runs > 0.02,
        }
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
                 session: Optional[SessionConfig] = None):
        self.publish = publish
        self.audio = audio
        # Spin-side session presets: measured-spin confidence floor (per ball
        # type) and the audio slice window (widens outdoors; pre stays a
        # 10 ms clock-slack guard -- audit E-9). Every value comes from the
        # session; callers that pass none get SessionConfig()'s indoor/plain
        # defaults.
        self.session = session or SessionConfig()
        self.spin_conf_floor = self.session.spin_conf_floor
        self.audio_pre, self.audio_post = self.session.spin_audio_window_s

    def set_session(self, session: SessionConfig) -> None:
        """Live session switch (web UI mode picker). Cheap and atomic-enough:
        the three derived fields are plain reads on the fusion path, and a
        single boundary shot fused under the old floor/window is harmless.
        (The radar side switches at its own safe point -- see
        IWR6843Source.request_session -- so a capture already in flight may
        pair old-chirp geometry with these new spin presets; same one-shot
        boundary blur, same verdict.)"""
        self.session = session
        self.spin_conf_floor = session.spin_conf_floor
        self.audio_pre, self.audio_post = session.spin_audio_window_s

    def on_geometry(self, geom: dict):
        # Speed-training swings ride the same stream but carry no ball and
        # therefore no spin question: no audio slice, no decode, no inferred
        # fallback -- club-head speed is the only metric that exists. The
        # K-MC1's descending-clubhead exclusion (E-9) is preserved trivially:
        # the spin channel isn't consulted at all.
        if geom.get("swing"):
            swing = dict(geom)
            swing.update(spin_rpm=None, spin_source=None, spin_confidence=0.0,
                         spin_axis_hint_deg=None)
            swing.update(self.session.tags())
            self._log_shot(swing)
            self.publish(swing)
            return
        shot = dict(geom)
        shot["spin_rpm"], shot["spin_source"], shot["spin_confidence"] = \
            None, None, 0.0
        if self.audio is not None:
            z = self.audio.window(geom["t_impact"], self.audio_pre,
                                  self.audio_post)
            self._archive_audio(z, geom.get("capture_id"))
            result = decode(z)
            # Clip handling (audit D-3): a clipped capture smears harmonics
            # into the spin band -- its "confidence" is fake evidence.
            # Flag every shot and halve measured confidence when clipped,
            # so borderline reads fall through to the inferred fallback
            # instead of masquerading as clean measurements.
            clip = dict(self.audio.last_clip)
            shot["audio_clipped"] = clip.get("clipped", False)
            if shot["audio_clipped"] and result.get("ok"):
                result["confidence"] = result.get("confidence", 0) * 0.5
            # Cross-sensor diagnostic (audit F-6): the spin decoder's carrier
            # frequency implies a radial speed; the IWR6843's position track
            # implies ball speed. Record their agreement on every shot --
            # free evidence for whether both channels saw the same ball.
            # Diagnostic only (no gating) until real data says where the
            # cosine/geometry losses actually put this ratio.
            radial = result.get("radial_speed_mps")
            if radial and shot.get("ball_speed_mph"):
                ball_mps = shot["ball_speed_mph"] * 0.44704
                shot["spin_radial_speed_mps"] = radial
                shot["radar_speed_agreement"] = round(
                    min(radial, ball_mps) / max(radial, ball_mps), 2)
            if result.get("ok") and \
                    result.get("confidence", 0) >= self.spin_conf_floor:
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
        # Stamp environment/ball_type onto every record for validation grouping.
        shot.update(self.session.tags())
        self._log_shot(shot)
        self.publish(shot)

    def _log_shot(self, shot: dict, directory: str = "captures"):
        """Every fused shot -> one JSON line in captures/shots.jsonl,
        independent of any upstream logger. The raw archives (radar .npz +
        audio .npy, same capture_id) hold the INPUTS; this holds the
        computed OUTPUTS plus the diagnostics upstream's Shot dataclass has
        no fields for (radar_speed_agreement, audio_clipped, session tags,
        geometry_confidence...). Also the missing producer for
        validate.py's shots file. Best-effort: logging must never take
        down shot processing."""
        try:
            import json
            import os
            os.makedirs(directory, exist_ok=True)
            rec = dict(shot)
            rec["logged_at"] = time.time()       # wall clock; t_impact is
                                                 # host-monotonic, not epoch
            with open(os.path.join(directory, "shots.jsonl"), "a") as f:
                f.write(json.dumps(rec, default=float) + "\n")
        except (OSError, TypeError, ValueError):
            pass

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
