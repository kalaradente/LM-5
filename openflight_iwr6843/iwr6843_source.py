"""
iwr6843_source.py — IWR6843ISK acquisition: TLV parsing, shot detection,
Kalman-smoothed trajectory -> geometry metrics.

Replaces OpenFlight's OPS243-A + dual K-LD7 acquisition layer. Emits a dict
of geometry metrics per shot; shot_fusion.py merges in the spin channel and
adapts to OpenFlight's Shot/on_shot() interface.
"""

from __future__ import annotations

import math
import struct
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import serial

from .kalman import BallTracker
from .session import SessionConfig

# Cross-checked against TI's "Understanding the Out of Box Demo Data Output"
# doc. Magic word, both TLV type IDs, and the Detected Points TLV layout
# (16 bytes/point: x,y,z,doppler as 4x float32, same field order) all match
# exactly. FRAME_HEADER_LEN is 32 bytes (+ the 8-byte magic word = 40 total).
# DECISION (2026-07-04): commit to 40. That is the value the mmWave community
# reports consistently across forum threads and third-party parsers, it is the
# de-facto standard OOB-demo header, and it matches summing that TI doc's own
# listed fields. The same doc separately calls the frame header 44 bytes -- an
# internal inconsistency most likely from an SDK-version difference (a field
# added in a later revision, e.g. numStaticDetectedObj); we go with 40 unless
# the board proves otherwise. Bring-up rung 2 (this parser against a live
# stream, positions must match the TI Demo Visualizer) is the empirical check:
# a wrong header length shows up as garbage/missing points, not a subtle
# numeric error. If rung 2 fails, diff against your flashed SDK's demo source
# and bump FRAME_HEADER_LEN to 36 (44 total) there.
MAGIC_WORD = b"\x02\x01\x04\x03\x06\x05\x08\x07"
FRAME_HEADER_FMT = "<8I"
FRAME_HEADER_LEN = 32
TLV_DETECTED_POINTS = 1
TLV_SIDE_INFO = 7
MPS_TO_MPH = 2.2369362921


@dataclass
class Frame:
    t: float                           # host monotonic ARRIVAL time. Absolute
                                       # anchor only (audio-ring alignment) --
                                       # NOT a per-frame clock: USB chunking
                                       # delivers several frames in one read()
                                       # and UART throttling delays others, so
                                       # inter-frame dt from this is jitter.
    points: np.ndarray                 # (N,4): x,y,z [m], v_radial [m/s]
    snr: Optional[np.ndarray] = None
    num: Optional[int] = None          # radar frameNumber (hdr[3]) -- the
                                       # real frame clock: num * framePeriod
                                       # is jitter-free relative time and
                                       # inherently accounts for skipped
                                       # frames. Used by analyze().


class IWR6843Source:
    BALL_MIN_SPEED = 7.6    # 17 mph — trigger threshold on FOLDED Doppler.
                            # Real speeds folding to under this (~152-186
                            # mph indoor, ~107-141 mph outdoor at the 3-TX
                            # v_max_ext) don't self-trigger; the clubhead's
                            # folded Doppler sweeps the readable band on
                            # its way up and trips the capture instead
                            # (audit V-3; pre-roll covers the ball birth).
    PRE_ROLL = 0.15
    MIN_BALL_FIXES = 4
    COOLDOWN = 2.0
    # NOTE: the range gate and capture window are NOT class constants any more
    # -- they come from the active SessionConfig (indoor/outdoor presets), set
    # per instance in __init__ as self.range_gate / self.capture_window.
    # Physical mount tilt (shimmed up at the front, see parts list wiring
    # summary) -- the sensor's own z axis is NOT vertical unless this is 0.
    # 10 deg centers the antenna's measured elevation beamwidth on
    # driver/mid-iron launch angles (~11-20 deg), at the cost of the most
    # extreme wedge shots (~30-35 deg) running closer to the edge of
    # characterized antenna gain -- see golf.cfg's aoaFovCfg comment.
    # CALIBRATE against the actual mount (inclinometer/level) once built;
    # this is a considered default, not a measurement.
    MOUNT_TILT_DEG = 10.0

    def __init__(self, cli_port: str, data_port: str, cfg_path: str,
                 on_geometry: Callable[[dict], None],
                 archive_dir: Optional[str] = "captures",
                 session: Optional[SessionConfig] = None):
        self.cli = serial.Serial(cli_port, 115200, timeout=1)
        self.data = serial.Serial(data_port, 921600, timeout=0.05)
        self.cfg_path = cfg_path
        self.on_geometry = on_geometry
        self.archive_dir = archive_dir
        # Session presets drive the geometry channel's environment-dependent
        # parameters. Default indoor config keeps prior hardcoded behaviour
        # (gate 0.3-6.0 m, 0.20 s window) so existing callers/self-tests are
        # unchanged.
        self.session = session or SessionConfig()
        self.range_gate = self.session.range_gate
        self.capture_window = self.session.capture_window_s
        # Frame period from the cfg's frameCfg (framePeriodicity, ms) -- the
        # radar's own frame clock. analyze() uses frameNumber * frame_period
        # for trajectory timing instead of host arrival times (audit F-1:
        # arrival times carry USB-chunking/UART-throttling jitter that skews
        # the Kalman fit's dt exactly when frames throttle -- mid-shot).
        self.frame_period = self._parse_frame_period(cfg_path)
        # Extended max unambiguous velocity, derived from the same cfg
        # (audit F-2): lambda/(4 * Ntx * Tc), x2 when extendedMaxVelocity
        # is on (the SDK UG 3.6 says the feature "corrects target
        # velocities up to (2*vmax)" -- exactly x2, primary-confirmed,
        # audit V-3). For the 3-TX golf.cfg: 4.9965mm/(4 * 3 * 22us) =
        # +/-18.9 m/s native, +/-37.9 m/s extended (+/-85 mph). Real shots
        # alias past this -- the radar folds their Doppler back into
        # [-v_max_ext, +v_max_ext). Ball SPEED is immune (it comes from
        # the position track, not Doppler), but anything touching raw
        # Doppler must handle folding: geometry_confidence folds its
        # expectation, and club speed is unfolded against the club
        # track's own range-rate (see analyze()).
        self.v_max_ext = self._parse_vmax_ext(cfg_path)
        self._buf = bytearray()
        self._pre_roll: deque[Frame] = deque()
        self._running = False
        self._last_frame_num = None

    @staticmethod
    def _parse_frame_period(cfg_path: str) -> float:
        """framePeriodicity (ms -> s) from the cfg's frameCfg line:
        frameCfg chirpStart chirpEnd loops numFrames periodicity(ms) ...
        Falls back to golf.cfg's 2 ms if unreadable (offline replay etc.)."""
        try:
            with open(cfg_path) as f:
                for line in f:
                    tok = line.split()
                    if tok and tok[0] == "frameCfg" and len(tok) >= 6:
                        return float(tok[5]) / 1000.0
        except OSError:
            pass
        return 0.002

    @staticmethod
    def _parse_vmax_ext(cfg_path: str) -> float:
        """Max unambiguous velocity the radar can REPORT, from the cfg:
        native v_max = lambda / (4 * Ntx * Tc) for TDM-MIMO (Tc = idle +
        rampEnd), doubled if extendedMaxVelocity is enabled. Fallback is
        golf.cfg's own numbers."""
        f0 = idle = ramp = None
        ntx, ext = 1, 1
        try:
            with open(cfg_path) as f:
                for line in f:
                    tok = line.split()
                    if not tok:
                        continue
                    if tok[0] == "profileCfg" and len(tok) >= 6:
                        f0 = float(tok[2]) * 1e9          # startFreq GHz
                        idle = float(tok[3]) * 1e-6       # idleTime us
                        ramp = float(tok[5]) * 1e-6       # rampEndTime us
                    elif tok[0] == "channelCfg" and len(tok) >= 3:
                        ntx = max(1, bin(int(tok[2])).count("1"))
                    elif tok[0] == "extendedMaxVelocity" and len(tok) >= 3:
                        ext = 2 if tok[2] == "1" else 1
        except (OSError, ValueError):
            pass
        if f0 is None or idle is None or ramp is None:
            return 37.9                                   # golf.cfg's value
        lam = 299792458.0 / f0
        return ext * lam / (4.0 * (idle + ramp) * ntx)

    # ---- bring-up --------------------------------------------------------

    def configure(self):
        with open(self.cfg_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("%"):
                    continue
                line = self._apply_session(line)
                self.cli.write((line + "\n").encode())
                time.sleep(0.02)
                self.cli.read(self.cli.in_waiting or 1)

    def _apply_session(self, line: str) -> str:
        """Rewrite the three golf.cfg CLI lines that depend on the session
        (indoor/outdoor) before they're sent to the chip; every other line
        passes through verbatim. This is the chip-side half of the range gate:
        the software gate in _parse() can only *tighten* what the chip emits,
        so an outdoor gate extension (6->15 m) is meaningless unless the
        chip's own cfarFovCfg range is widened here too. All three are
        re-checked at bring-up rung 3 against the flashed SDK's cfg format."""
        tok = line.split()
        if not tok:
            return line
        key = tok[0]
        # Range-direction FoV (procDirection 0) == the hardware range gate.
        if key == "cfarFovCfg" and len(tok) >= 5 and tok[2] == "0":
            rmin, rmax = self.range_gate
            tok[3], tok[4] = f"{rmin:g}", f"{rmax:g}"
            return " ".join(tok)
        # Static-clutter subtraction: OFF in both sessions (audit V-6 --
        # bin-0 removal deletes balls whose Doppler folds to ~0; see
        # session.clutter_removal). Kept as a session-driven rewrite so
        # the decision lives in one place.
        if key == "clutterRemoval" and len(tok) >= 3:
            tok[2] = "1" if self.session.clutter_removal else "0"
            return " ".join(tok)
        # CFAR thresholdScale (8th arg). Per the mmWave SDK User Guide 3.6 LTS
        # p.28: "Threshold scale in dB using float representation ... the CUT
        # comparison for log input is: CUT > (Threshold scale converted from dB
        # to Q8) + (noise sum / 2^x) ... Maximum value allowed is 100dB". So
        # the field is dB and the detection test is additive in the log domain:
        # nudging it by session offset dB shifts the required CUT by exactly
        # that many dB -- 0 indoor, looser (lower) outdoors. Clamp to [0,100]dB.
        # (The dB semantics are stable across mmWave SDK 3.x; only re-check if
        # the flashed SDK is a different major line -- see golf.cfg's note on
        # per-version arg formats.)
        if key == "cfarCfg" and len(tok) >= 9:
            base = float(tok[8])
            nudged = min(100.0, max(0.0, base + self.session.cfar_threshold_offset_db))
            tok[8] = f"{nudged:g}"
            return " ".join(tok)
        return line

    # ---- TLV stream ------------------------------------------------------

    def frames(self):
        """Generator of Frame objects; also checks frame-number continuity."""
        idle_reads = 0
        while self._running:
            chunk = self.data.read(4096)
            if chunk:
                self._buf.extend(chunk)
                idle_reads = 0
            else:
                # Stream-death guard (audit S-1): the port timeout is 50 ms,
                # so ~40 consecutive empty reads = ~2 s of total silence from
                # a sensor that should emit a frame every 2-2.5 ms. Without
                # this, a mid-capture unplug left run() busy-spinning FOREVER
                # inside its capture loop -- 100% CPU, shot lost, nothing
                # logged (proved with a synthesized dying UART stream).
                # Ending the generator lets run() finish the capture with
                # whatever it has and return to its caller.
                idle_reads += 1
                if idle_reads > 40:
                    print("[iwr6843] data stream silent for ~2 s -- sensor "
                          "dead/unplugged? ending acquisition")
                    return
            start = self._buf.find(MAGIC_WORD)
            if start < 0:
                if len(self._buf) > 1 << 16:
                    del self._buf[:-8]
                continue
            if len(self._buf) < start + 8 + FRAME_HEADER_LEN:
                continue
            hdr = struct.unpack_from(FRAME_HEADER_FMT, self._buf, start + 8)
            total_len = hdr[1]
            if total_len < 8 + FRAME_HEADER_LEN or total_len > 1 << 16:
                del self._buf[:start + 8]          # corrupt header: resync
                continue
            if len(self._buf) < start + total_len:
                continue
            raw = bytes(self._buf[start:start + total_len])
            del self._buf[:start + total_len]
            if self._last_frame_num is not None and hdr[3] not in (
                    self._last_frame_num + 1, self._last_frame_num):
                print(f"[iwr6843] frame skip {self._last_frame_num}->{hdr[3]} "
                      f"(UART throughput?)")
            self._last_frame_num = hdr[3]
            frame = self._parse(raw, hdr)
            if frame is not None:
                idle_reads = 0        # draining buffered frames is progress
                yield frame

    def _parse(self, raw: bytes, hdr) -> Optional[Frame]:
        num_obj, num_tlvs = hdr[5], hdr[6]
        # Corruption guards (audit F-3): a bad header/tlv_len must yield
        # None (frame dropped, stream resyncs on the next magic word) -- it
        # must NEVER raise, because frames() feeds run() with no handler
        # and one malformed frame would kill the acquisition thread.
        if num_obj > 500 or num_tlvs > 32:
            return None
        offset = 8 + FRAME_HEADER_LEN
        points, snr = None, None
        for _ in range(num_tlvs):
            if offset + 8 > len(raw):
                return None
            tlv_type, tlv_len = struct.unpack_from("<2I", raw, offset)
            body = raw[offset + 8: offset + 8 + tlv_len]
            if len(body) < tlv_len:
                return None                    # tlv_len runs past the frame
            if tlv_type == TLV_DETECTED_POINTS and num_obj:
                if len(body) < num_obj * 16:   # 4x float32 per point
                    return None
                pts = np.frombuffer(body, dtype=np.float32,
                                    count=num_obj * 4).reshape(num_obj, 4)
                points = pts.astype(np.float64)
            elif tlv_type == TLV_SIDE_INFO and num_obj:
                if len(body) < num_obj * 4:    # 2x uint16 per point
                    return None
                # snr, noise: both uint16_t per TI's spec (was wrongly int16
                # here; harmless in practice since real SNR/noise values
                # never approach the sign bit, but correct is correct).
                si = np.frombuffer(body, dtype=np.uint16,
                                   count=num_obj * 2).reshape(num_obj, 2)
                snr = si[:, 0].astype(np.float64)
            offset += 8 + tlv_len
        if points is None:
            return None
        r = np.linalg.norm(points[:, :3], axis=1)
        keep = (r > self.range_gate[0]) & (r < self.range_gate[1])
        return Frame(time.monotonic(), points[keep],
                     snr[keep] if snr is not None else None,
                     num=int(hdr[3]))

    # ---- shot loop -------------------------------------------------------

    def run(self):
        self._running = True
        self.configure()
        armed, last_shot = True, 0.0
        gen = self.frames()
        for frame in gen:
            self._pre_roll.append(frame)
            while self._pre_roll and \
                    frame.t - self._pre_roll[0].t > self.PRE_ROLL:
                self._pre_roll.popleft()
            if not armed:
                armed = frame.t - last_shot > self.COOLDOWN
                continue
            if frame.points.size and \
                    np.any(np.abs(frame.points[:, 3]) > self.BALL_MIN_SPEED):
                capture = list(self._pre_roll)
                deadline = frame.t + self.capture_window
                for f in gen:
                    capture.append(f)
                    if f.t >= deadline:
                        break
                capture_id = self._archive(capture)
                geom = self.analyze(capture)
                if geom is not None:
                    geom["capture_id"] = capture_id
                    self.on_geometry(geom)
                elif capture_id:
                    print(f"[iwr6843] trigger with no shot -> archived "
                          f"{capture_id} for replay/tuning")
                armed, last_shot = False, frame.t

    # ---- capture archive: every trigger becomes replayable data ----------

    def _archive(self, capture: list) -> Optional[str]:
        """Dump a triggered capture window to disk as .npz — success or
        failure. This is the dashcam habit: misses are exactly the shots
        the CFAR tuning phase and the ML bouncer need to replay."""
        if not self.archive_dir or not capture:
            return None
        import os
        os.makedirs(self.archive_dir, exist_ok=True)
        capture_id = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time()*1e3)%1000:03d}"
        path = os.path.join(self.archive_dir, f"radar_{capture_id}.npz")
        try:
            np.savez_compressed(
                path,
                t=np.array([f.t for f in capture]),
                num=np.array([f.num if f.num is not None else -1
                              for f in capture]),
                n_points=np.array([f.points.shape[0] for f in capture]),
                points=np.concatenate([f.points for f in capture]) if
                    any(f.points.size for f in capture) else np.zeros((0, 4)),
                snr=np.concatenate([f.snr if f.snr is not None
                                    else np.zeros(f.points.shape[0])
                                    for f in capture]) if capture else
                    np.zeros(0),
            )
            return capture_id
        except OSError as e:
            print(f"[iwr6843] archive failed: {e}")
            return None

    # ---- club/ball separation (audit F-7) --------------------------------
    #
    # Club and ball are inseparable in SPEED space (a driver clubhead at
    # 45 m/s outruns a chipped ball at 10 m/s), so the old point-level
    # speed-band split misclassified: real clubheads (40-55 m/s radial near
    # impact) landed in the "ball" band and could pollute the fit, while
    # the 4-7.6 m/s "club" band collected only swing-tail scraps. At the
    # TRACK level they are trivially different objects:
    #   ball -- range increases monotonically, gains meters, exits the gate;
    #   club -- swing arc loiters within ~1 m of the hitting zone, then the
    #           follow-through carries it up/back (range stalls, reverses).
    # So: cluster points into tracks by spatial continuity, classify tracks
    # by range-gain + monotonicity, fit ONLY the ball track, and read club
    # speed off the club track in the 50 ms before the ball is born. A
    # practice swing produces no ball-like track -> no shot (the old code
    # could report a phantom shot from club points alone).

    @staticmethod
    def _meas_sigma(p) -> np.ndarray:
        """Expected 1-sigma measurement noise PER AXIS at this point.
        The radar's noise is not isotropic (audit V-7): range comes from
        the beat frequency (bin-quantized but precise), azimuth from the
        8-element virtual row (fine), elevation from the SINGLE offset
        TX2 row -- by far the coarsest axis, and angle-derived errors
        grow linearly with range. Sensor axes: x ~ azimuth-driven,
        y ~ range-driven, z ~ elevation-driven (exact only at boresight;
        good enough for gating). Coefficients are array-geometry
        placeholders (0.9 deg az, 1.8 deg el) -- bench rung 5 owns them."""
        r = float(np.linalg.norm(p))
        return np.array([max(0.04, 0.015 * r),      # x: r * sigma_az
                         0.05,                       # y: range bin + jitter
                         max(0.06, 0.032 * r)])      # z: r * sigma_el

    def _cluster_tracks(self, moving: list) -> list:
        """Track builder with frame-wise best-error-first assignment.
        `moving` = time-sorted rows (t, x, y, z, s). Points are grouped per
        frame; all (track, point) prediction errors in that frame are
        assigned smallest-first, each track and each point used at most
        once -- point-order-greedy is order-sensitive exactly at impact,
        when club and ball are co-located and one steals the other's point.
        Association is ANISOTROPIC (audit V-7): errors are normalized by
        the per-axis expected noise at that range, so a CFAR false alarm
        one range bin off is correctly rejected even though the elevation
        axis alone would have tolerated it. Returns ndarrays."""
        tracks: list[dict] = []
        i = 0
        while i < len(moving):
            # group this frame's points (identical timestamps)
            j = i
            while j < len(moving) and moving[j][0] - moving[i][0] < 1e-9:
                j += 1
            frame_rows = moving[i:j]
            t = moving[i][0]
            # score every live (track, point) pair
            pairs = []
            for ti, tr in enumerate(tracks):
                dt = t - tr["t"]
                if not (1e-9 < dt <= 0.06):   # dead after 60 ms silent
                    continue
                immature = len(tr["pts"]) < 2
                # Immature tracks (no velocity yet) may only bridge a
                # couple of flicker frames (audit V-7): with the old open
                # 60 ms window plus a 90 m/s velocity-uncertainty gate,
                # pairs of RANDOM false alarms several frames apart could
                # chain into phantom "tracks" that later outbid the real
                # ball on range gain (267 mph phantoms in the hostile
                # simulator). Real objects at a ~2 ms frame period appear
                # on consecutive frames, flickering 1-2 at most.
                if immature and dt > 3.5 * self.frame_period:
                    continue
                pred = tr["pos"] + tr["vel"] * dt
                # A track predicted OUTSIDE the range gate is over: the
                # chip cannot see there, so anything it would grab is by
                # definition junk (audit V-7: a ball that exited at 6 m
                # coasted to a predicted 7.2 m and adopted a false alarm
                # 1.5 m behind it, bending the accel fit past its
                # threshold -- a lost shot).
                pred_r = float(np.linalg.norm(pred))
                if not (self.range_gate[0] - 0.3 < pred_r
                        < self.range_gate[1] + 0.3):
                    continue
                # Per-axis slack: measurement noise at this range plus
                # velocity uncertainty across the gap (capped -- a mature
                # track coasting through the UART burst gap must not
                # balloon into a half-meter grab-anything gate).
                v_unc = min((90.0 if immature else 25.0) * dt, 0.45)
                for pi, row in enumerate(frame_rows):
                    e = np.abs(np.array(row[1:4]) - pred)
                    sig = self._meas_sigma(row[1:4]) + v_unc
                    d = float(np.linalg.norm(e / sig))
                    # Doppler tie-break (audit V-3): a chip-speed ball and
                    # the club's follow-through separate at ~1 m/s --
                    # inside position noise for many frames, so
                    # position-only pairing interleaves their tracks (a
                    # mixed "ball" fit read 18% fast). Their DOPPLER
                    # differs though; a capped penalty at the scale of
                    # typical normalized error breaks exactly those ties
                    # without overriding genuine position evidence -- and
                    # stays harmless at fold discontinuities (penalty
                    # tops out at 1.0 vs a 3.5 gate). It counts toward
                    # ADMISSION too (audit V-7): a marginally-in-gate
                    # point with wildly wrong Doppler is junk, not a
                    # continuation -- ranking-only penalties let one
                    # such row bend a real ball track's accel fit past
                    # its threshold.
                    s_pen = min(abs(row[4] - tr["pts"][-1][4]), 3.0) / 3.0
                    if d + s_pen < 3.5:
                        pairs.append((d + s_pen, ti, pi))
            pairs.sort()
            used_t, used_p = set(), set()
            for err, ti, pi in pairs:
                if ti in used_t or pi in used_p:
                    continue
                used_t.add(ti); used_p.add(pi)
                tr, row = tracks[ti], frame_rows[pi]
                p = np.array(row[1:4])
                # Velocity over up to 3 rows back, not adjacent-row finite
                # difference: at a 2.2 ms frame period, two-point dp/dt
                # turns 3.5 cm position noise into ~40 m/s of velocity
                # noise, and one bad estimate right before a dropped frame
                # threw the prediction outside the gate and SPLIT a real
                # ball track (halving its range gain below the ballistic
                # classifier's floor). A 3-row baseline cuts that noise
                # ~3x while still tracking the club's real acceleration.
                back = tr["pts"][max(0, len(tr["pts"]) - 3)]
                tr["vel"] = (p - np.array(back[1:4])) / (t - back[0])
                tr["pts"].append(row)
                tr["pos"], tr["t"] = p, t
            for pi, row in enumerate(frame_rows):
                if pi not in used_p:          # unclaimed: new object (birth)
                    tracks.append({"pts": [row], "pos": np.array(row[1:4]),
                                   "vel": np.zeros(3), "t": t})
            i = j
        return [np.array(tr["pts"]) for tr in tracks]

    def _pick_ball_track(self, tracks: list, min_fixes: int):
        """Find the best BALLISTIC SUFFIX across all tracks; returns
        (track_index, start_index) or None.

        Suffixes, not whole tracks, because of impact handoff: at impact
        the ball is born ON the clubhead, so the club's track can seamlessly
        continue onto the ball -- the ball's life is then the suffix of a
        track whose prefix is the downswing. Three criteria per suffix:

        1. Range gain >= 1.2 m (a chip at 8 m/s gains 1.6 m in 0.2 s;
           a chip-speed club's visible follow-through tops out below it).
        2. Monotonic range over a LAG of ~1/8th track length (per-frame
           steps are noise-dominated for slow balls: a chip moves 16 mm
           /frame vs ~50 mm noise steps).
        3. Ballistic acceleration: quadratic-fit the 3D positions and
           require fitted |accel| < 150 m/s^2. A free ball's acceleration
           is g (~10); a clubhead's centripetal acceleration is v^2/R --
           ~450 (iron) to ~2000 (driver) m/s^2. The fit's noise floor on a
           driver-length window (~27 fixes / 54 ms) is ~50 m/s^2, so 150
           passes every real ball and rejects every full-swing arc. (This,
           not Doppler, is the discriminator: range-rate IS the radial
           velocity for any motion, so Doppler-vs-slope tests reject
           nothing. Curvature is what a swing arc cannot hide.)

        Earliest qualifying start in the largest-gain track wins, so
        t_birth lands at impact, not mid-flight."""
        best = None                        # (gain, track_idx, start_idx)
        tilt = math.radians(self.MOUNT_TILT_DEG)
        sin_t, cos_t = math.sin(tilt), math.cos(tilt)
        for ti, tr in enumerate(tracks):
            n = tr.shape[0]
            if n < min_fixes:
                continue                  # fragments: tee, turf, multipath
            r_all = np.linalg.norm(tr[:, 1:4], axis=1)
            # De-tilted world z, for the head trim below (same math as
            # analyze()'s trim, which becomes a no-op safety once the trim
            # happens here).
            zw = tr[:, 2] * sin_t + tr[:, 3] * cos_t
            z_smooth = np.convolve(zw, np.ones(3) / 3.0, mode="same")
            tried: set = set()
            for st0 in range(0, n - min_fixes + 1):
                # HEAD-TRIM AT THE Z-MINIMUM *before* judging the suffix
                # (audit V-7). Trimming used to happen after picking, and
                # that ordering broke both ways at once: a real driver's
                # only >=40 ms suffixes still carried club-handoff head
                # rows whose curvature blew the accel fit (lost shots),
                # while the clubhead's own arc-bottom sweep -- descending
                # z, then rising -- survived as a "ball" because its
                # z-kink was never cut (phantom shots). Trimmed first,
                # the ball candidate starts at the physical impact and
                # the club remnant shrinks below the span floor.
                # The trim fires ONLY when the segment genuinely DESCENDS
                # into the minimum (>6 cm) -- that is what a club head
                # looks like -- and the minimum is searched in the FIRST
                # HALF of the suffix only, the same first-half rule
                # analyze()'s own trim learned in V-3: a flat shot's apex
                # passes inside the window, so its GLOBAL z-minimum is
                # the descending tail, and anchoring there discarded the
                # entire shot (bump-and-run misses via dedupe collapse).
                half = st0 + max(1, (n - st0) // 2)
                k_min = st0 + int(np.argmin(z_smooth[st0:half]))
                descent = float(z_smooth[st0] - z_smooth[k_min])
                st = k_min if (descent > 0.06
                               and n - k_min >= min_fixes) else st0
                if st in tried:
                    continue
                tried.add(st)
                r, t = r_all[st:], tr[st:, 0]
                gain = float(r[-1] - r[0])
                if gain < 1.2 or (best is not None and gain <= best[0]):
                    continue
                # Physical rate ceiling (audit V-7): gain/span is the
                # suffix's implied mean radial speed. No golf ball moves
                # 105 m/s (235 mph); a chain of false alarms happily
                # "moves" much faster, and gain-first selection would
                # crown it (267 mph phantoms in the hostile simulator).
                # Minimum SPAN (audit V-7): every real ball's visible
                # flight lasts >= ~50 ms (the fastest ball, ~98 m/s,
                # needs 42 ms just to cross the 2->6.09 m gate; slower
                # balls stay longer, outdoor gates are longer still).
                # Shorter suffixes are also exactly where the
                # covariance-scaled accel test below loses its teeth
                # (quadratic-coefficient variance blows up as 1/T^4) --
                # the clubhead's ~40 ms arc-bottom sweep slipped through
                # BOTH holes at once and became a 97 mph phantom shot on
                # a practice swing, at confidence 0.94.
                span = float(t[-1] - t[0])
                if span < 0.04 or gain / span > 105.0:
                    continue
                # FILL RATIO (audit V-7): a ball inside the gate is a
                # strong coherent reflector -- the chip detects it nearly
                # every frame. The club's top-of-finish tail (7 sparse
                # rows across 88 ms of flickering glints, rising range,
                # arc-top accel too slow to trip the ballistic test)
                # passed everything else and published an 83 mph phantom
                # on a practice swing. Sparse candidates are glints or
                # false-alarm chains, never the ball.
                if len(r) / (span / self.frame_period + 1.0) < 0.5:
                    continue
                lag = max(1, len(r) // 8)
                diffs = r[lag:] - r[:-lag]
                if not len(diffs) or float(np.mean(diffs > 0)) < 0.8:
                    continue
                tt = t - t[0]
                acc, var_a = [], 0.0
                if len(tt) >= 6:
                    for ax in range(3):
                        c, cov = np.polyfit(tt, tr[st:, 1 + ax], 2, cov=True)
                        acc.append(2.0 * c[0])
                        var_a += 4.0 * float(cov[0, 0])
                else:
                    for ax in range(3):
                        acc.append(2.0 * np.polyfit(tt, tr[st:, 1 + ax], 2)[0])
                # Threshold scales with the fit's own noise floor (from the
                # polyfit covariance): a short driver track has ~50 m/s^2 of
                # acceleration uncertainty, and a FIXED 150 threshold false-
                # rejects ~10-15% of genuine drives on unlucky noise draws.
                # 4 sigma of headroom keeps that under ~1% while every
                # full-swing club arc (450-2000 m/s^2) stays far outside.
                # (The short-window regime where this covariance term
                # explodes and goes toothless is fenced off upstream by
                # the span floor + z-min head trim, not by capping here --
                # a cap tight enough to catch clubs false-rejected real
                # drives under honest elevation noise. Audit V-7.)
                a_thresh = max(150.0, 9.81 + 4.0 * math.sqrt(var_a))
                if float(np.linalg.norm(acc)) > a_thresh:
                    continue
                # ANTI-GRAVITY GATE (audit V-3): a free ball can never
                # accelerate UPWARD -- gravity only pulls down. A slow
                # club's follow-through, though, leaves the arc bottom
                # accelerating up at ~R*w^2 (+55 m/s^2 for a chip swing,
                # thousands for a driver), yet its |accel| can sneak under
                # the ballistic threshold above precisely for slow swings.
                # Fitted vertical acceleration is evaluated in WORLD z
                # (de-tilted); the allowance is the fit's own noise floor
                # (per-axis), so long clean tracks enforce this tightly
                # while short noisy ones aren't false-rejected.
                az_world = acc[1] * sin_t + acc[2] * cos_t
                if az_world > max(25.0, 4.0 * math.sqrt(var_a / 3.0)):
                    continue
                best = (gain, ti, st)
        return best

    def _unfold(self, s: float, slope: Optional[float]) -> float:
        """True |radial speed| candidates for a reported Doppler label are
        |s + k*v_max_ext|, k any integer (audit V-3, spacing corrected in
        V-7): the radar folds into [-v_max_ext, +v_max_ext) -- EVEN
        multiples of 2*v_max_native -- but the x2 extension can also pick
        the WRONG hypothesis (the SDK UG's own same-range-bin caveat),
        shifting the label by ODD multiples of 2*v_max_native. Since
        v_max_ext = 2*v_max_native, stepping candidates at v_max_ext
        covers both error modes; the original 2*v_max_ext spacing missed
        every wrong-hypothesis row, so a club row labeled 9.5 m/s at true
        ~46 m/s unfolded to 66 (a 148 mph 'clubhead'). The track's own
        range-rate -- coarse but fold-free, branches 18.9 m/s apart --
        picks the branch. Without a usable slope the raw reading is kept,
        which is correct whenever the true speed is inside +/-v_max_ext
        and the hypothesis was right (every chip/putt, most irons)."""
        if slope is None:
            return float(s)
        m = self.v_max_ext
        cands = [abs(s + k * m) for k in (-3, -2, -1, 0, 1, 2, 3)]
        return float(min(cands, key=lambda c: abs(c - slope)))

    def _capture_rows(self, capture: list) -> tuple[float, list]:
        """Front half of analyze(): flatten a capture
        into time-sorted (t, x, y, z, |v|) rows. Returns (t0, rows).

        Time base (audit F-1): radar frame numbers x framePeriodicity give
        jitter-free relative time and inherently account for skipped
        frames; host arrival times (f.t) carry USB-chunking jitter. Fall
        back to arrival times only if frame numbers are missing (old
        archives) or non-monotonic (sensor restart mid-capture).

        Collects EVERY point, static included -- classification happens
        at track level (audit F-7), and a Doppler-magnitude pre-filter
        is a TRAP under TDM folding (audit V-3): a real ball whose
        radial speed lands near a multiple of 2*v_max_ext folds to
        ~0 m/s (~160-178 mph indoors, ~115-133 mph outdoors), so any
        "must look fast" gate silently deletes exactly the best shots.
        Static clutter that survives the chip's own CFAR/clutter config
        just becomes loitering tracks with no ballistic suffix -- the
        classifier already rejects those."""
        t0 = capture[0].t
        nums = [f.num for f in capture]
        use_nums = (all(n is not None for n in nums)
                    and all(b >= a for a, b in zip(nums, nums[1:])))
        n0 = nums[0] if use_nums else None
        rows = []
        for f in capture:
            ft = ((f.num - n0) * self.frame_period if use_nums
                  else f.t - t0)
            for i in range(f.points.shape[0]):
                x, y, z, v = f.points[i]
                rows.append((ft, x, y, z, abs(v)))
        rows.sort(key=lambda r: r[0])
        return t0, rows

    def analyze(self, capture: list) -> Optional[dict]:
        if not capture:
            return None      # empty/corrupt archive replayed offline (E-1)
        t0, moving = self._capture_rows(capture)
        if len(moving) < self.MIN_BALL_FIXES:
            return None
        tracks = self._cluster_tracks(moving)
        picked = self._pick_ball_track(tracks, self.MIN_BALL_FIXES)
        if picked is None:
            return None      # no ball-like object (practice swing, noise)
        _, ball_ti, ball_st = picked
        ball_tr = tracks[ball_ti][ball_st:]
        # Head-trim at the z-minimum: the ball always launches UPWARD and
        # the club always arrives DESCENDING, so z(t) has a V-kink exactly
        # at impact. The suffix scan can start early when a slow club's arc
        # acceleration sneaks under the ballistic threshold (a chip swing
        # pulls ~44 m/s^2, well under 150) -- this trims those downswing
        # rows off the fit and pins t_birth to the physical impact. A pure
        # ball track has its z-minimum at row 0: no-op.
        # De-tilt first: in the SENSOR frame the mount tilt mixes downrange
        # distance into z (-y*sin(tilt)), which cancels a low ball's climb
        # -- a chip's V-kink only exists in world z.
        tilt_r = math.radians(self.MOUNT_TILT_DEG)
        z_world = (ball_tr[:, 2] * math.sin(tilt_r)
                   + ball_tr[:, 3] * math.cos(tilt_r))
        # Edge-pad before smoothing: convolve(mode="same") zero-pads, and
        # a phantom 0 averaged into the FIRST sample reads lower than any
        # real z whenever the track flies below ~2x the noise floor --
        # argmin then pins to index 0, silently disabling this trim (and
        # with it the directional gate's birth anchor). Latent since F-7;
        # exposed the day the suffix scan started handing this code
        # suffixes that begin mid-downswing (audit V-3).
        zp = np.concatenate([z_world[:1], z_world, z_world[-1:]])
        z_smooth = np.convolve(zp, np.ones(3) / 3.0, mode="valid")
        # Search the kink only in the FIRST HALF of the suffix: the V is a
        # head feature (descending club -> rising ball), and qualifying
        # suffixes are ball-majority so impact sits early. A GLOBAL argmin
        # is wrong for flat shots whose apex passes inside the window -- a
        # 6-deg bump-and-run dips below launch height ~190 ms in, so its
        # global z-minimum is the track END, and trimming there kept 4
        # tail rows and produced confident garbage (audit V-3, sweep
        # seeds 1/2/4).
        k_min = int(np.argmin(z_smooth[:max(1, ball_tr.shape[0] // 2)]))
        if ball_tr.shape[0] - k_min >= self.MIN_BALL_FIXES:
            ball_st += k_min
            ball_tr = ball_tr[k_min:]
        # DOPPLER-STEP birth trim (audit V-7), the flat-slow companion to
        # the z-kink: on a bump-and-run the club's approach prepends
        # seamlessly (range-monotonic, near-equal speed) and the z-kink
        # drowns in elevation noise (a 6-deg launch climbs ~5 cm per
        # 50 ms vs 6-9 cm of z noise) -- one hostile-sim seed blended
        # them into a 40-deg "flop shot" at chip speed. But impact leaves
        # a second signature: ball Doppler = smash x club Doppler (~1.5x
        # step UP), clean whenever nothing folds. Only applied in the
        # unfolded regime; folded regimes (driver/iron) have Doppler-HIGH
        # prefixes that this cannot touch, and their large z-kinks are
        # already handled above. Low rows are only searched in the first
        # half: a mid-track junk row must not amputate good ball rows.
        s_ser = ball_tr[:, 4]
        # 90th percentile, not max: one wrong-hypothesis Doppler row (the
        # SDK UG's own disambiguation caveat) must not disarm the test.
        if float(np.percentile(s_ser, 90)) < 0.8 * self.v_max_ext:
            tail_med = float(np.median(s_ser[len(s_ser) // 2:]))
            low = (s_ser < 0.75 * tail_med)
            low[len(s_ser) // 2:] = False
            if low.any():
                k_step = int(np.flatnonzero(low)[-1]) + 1
                if ball_tr.shape[0] - k_step >= self.MIN_BALL_FIXES:
                    ball_st += k_step
                    ball_tr = ball_tr[k_step:]
        t, xyz, v_rad = ball_tr[:, 0], ball_tr[:, 1:4], ball_tr[:, 4]
        t_birth = float(t[0])

        # DIRECTIONAL GATE: everything at-or-behind where the ball was
        # first detected is not the ball -- the ball only ever moves AWAY,
        # while the club enters from the golfer's side, bottoms out at the
        # ball, and exits back on its own arc. Fit ball kinematics only on
        # rows beyond the birth range (+10 cm noise margin): at-and-behind
        # birth is club country. Unlike a fixed exclusion radius this keeps
        # every genuine ball point from the first frame, so it can't starve
        # a slow chip's fit.
        r_all = np.linalg.norm(xyz, axis=1)
        r_birth = float(r_all[0])
        ahead = r_all > r_birth + 0.10
        if ahead.sum() >= self.MIN_BALL_FIXES:
            t_f, xyz_f, v_f = t[ahead], xyz[ahead], v_rad[ahead]
        else:
            t_f, xyz_f, v_f = t, xyz, v_rad

        # Club speed candidates: max clubhead radial speed occurs PRECISELY
        # where the ball is first detected -- the arc bottom, where the
        # head's velocity is fully radial (before that it's partly
        # perpendicular to the line of sight and reads low; after, the
        # ball exists). So the fastest pre-birth row IS the club speed --
        # no ramp fit or extrapolation needed. One trap: the first ball
        # detection sometimes lands in the club's track one frame before
        # the suffix (born ON the clubhead), and for an iron its Doppler
        # (~ball speed) exceeds the club's -- rows whose Doppler matches
        # the ball suffix's own median are excluded as stolen (both sides
        # of that comparison are FOLDED values, so it survives aliasing:
        # indoor driver ball folds to ~1.9 m/s vs club's folded ~26.7).
        ball_s_med = float(np.median(v_rad))
        # The ball suffix's own mean range-rate: fold-proof motion
        # signature used below to reject stolen ball rows by how they
        # MOVE, not how they're labeled (audit V-7).
        r_ball_sfx = np.linalg.norm(ball_tr[:, 1:4], axis=1)
        ball_rate = float((r_ball_sfx[-1] - r_ball_sfx[0])
                          / max(t[-1] - t_birth, 1e-6))
        # Doppler match tolerance floored at 1.5 quantization bins: the
        # demo reports Doppler on a 2*v_max_native/16 grid (= v_max_ext
        # /16), so a fractional tolerance of a small folded median (a
        # driver ball folds to ~2 m/s; 8% of that is a fifth of a bin)
        # excluded nothing in practice -- one jittered ball row then
        # became a 148 mph "clubhead" via its own ball-fast local slope.
        s_tol = max(0.08 * ball_s_med, 1.5 * self.v_max_ext / 16.0)
        club_cands = []
        for tj, tr in enumerate(tracks):
            # Per-row LOCAL range-rate of this track from its own
            # positions -- the fold-proof speed reference (audit V-3):
            # under 3-TX TDM a real driver head (~49 m/s at arc bottom)
            # reads ~26.7 m/s folded, so the raw "fastest row" is garbage.
            # Positions don't fold, but the slope must be LOCAL (+/-12 ms
            # around each row): a clubhead accelerates ~e^(8t) into
            # impact, so a 40 ms average reads less than half the
            # arc-bottom speed and picks the wrong unfolding branch. A
            # local fit is ~2-5 m/s accurate -- coarse, but the unfolding
            # branches sit >=13 m/s apart wherever they're distinguishable
            # (near v_max_ext they converge, and there picking either
            # branch is numerically harmless).
            t_tr = tr[:, 0]
            r_tr = np.linalg.norm(tr[:, 1:4], axis=1)
            pre_tr = t_tr < t_birth
            for ki in range(tr.shape[0]):
                if tj == ball_ti and ki >= ball_st:
                    continue
                if not (t_birth - 0.03 <= tr[ki, 0] < t_birth):
                    continue
                if abs(tr[ki, 4] - ball_s_med) < s_tol:
                    continue                   # stolen ball detection
                near = pre_tr & (np.abs(t_tr - tr[ki, 0]) <= 0.012)
                slope = None
                if near.sum() >= 3:
                    slope = abs(float(np.polyfit(t_tr[near],
                                                 r_tr[near], 1)[0]))
                # Motion-based stolen filter (audit V-7): a pre-birth row
                # whose LOCAL range-rate matches the ball suffix's own
                # rate IS the ball, however its Doppler label jittered --
                # slopes come from positions and cannot fold or quantize
                # away. (A real clubhead at arc bottom runs ~1/1.4 of
                # ball speed -- comfortably outside the 15% band.)
                if slope is not None and abs(slope - ball_rate) \
                        < 0.15 * ball_rate:
                    continue
                cand = self._unfold(tr[ki, 4], slope)
                # Physical ceiling (audit V-7): no human swings 150 mph
                # (67 m/s). A junk row + noisy local slope occasionally
                # unfolded onto an impossible branch and, because the
                # resulting smash factor still landed inside the 0.9-1.8
                # gate, published a 148 mph "clubhead" (+38 mph error in
                # the hostile sim). Impossible candidates are dropped,
                # not clamped -- a row that unfolds impossible is junk.
                if cand <= 67.0:
                    club_cands.append(cand)

        tilt_rad = math.radians(self.MOUNT_TILT_DEG)
        states, used = BallTracker(tilt_rad=tilt_rad).smooth(t_f, xyz_f)
        if used.sum() < self.MIN_BALL_FIXES:
            return None
        ui = np.flatnonzero(used)
        k0, km = int(ui[0]), int(ui[len(ui) // 2])
        vel = states[km, 3:].copy()                # mid-track: lowest variance,
                                                     # still in SENSOR frame
        # Back-extrapolate mid-track velocity to the LAUNCH instant --
        # t_birth, not the first fitted point, since reach-bubble gating
        # means fitting can start well after impact -- using gravity
        # decomposed into the sensor's own (tilted) y/z, the same physics
        # the Kalman filter itself uses (see kalman.py). Signs: gravity
        # REMOVED vz over [t_birth, t_mid], so going BACK to launch adds
        # it back (v_birth = v_mid - g_sensor*dt, and g_sensor is
        # negative-down). An earlier revision applied gravity FORWARD
        # here (+= -9.81*...), doubling the drop instead of undoing it --
        # error grows with track length, so it silently ate ~2 m/s of vz
        # on chip-length windows while staying invisible (~0.4 deg) on
        # drivers. That sign bug was the dominant share of the documented
        # "chip launch reads ~10 deg low" limitation and most of what
        # E-8's clamp was actually clamping. Audit V-3 (2026-07-06).
        dt_launch = t_f[km] - t_birth
        vel[1] += 9.81 * math.sin(tilt_rad) * dt_launch
        vel[2] += 9.81 * math.cos(tilt_rad) * dt_launch
        # Rotate sensor-frame velocity into world (gravity-aligned) frame
        # before computing launch angle -- the sensor's own z axis is tilted
        # MOUNT_TILT_DEG off true vertical, so atan2 against raw sensor-z
        # would report launch angle relative to the tilted mount, not level
        # ground (a systematic bias of roughly the tilt angle itself).
        cos_t, sin_t = math.cos(tilt_rad), math.sin(tilt_rad)
        vy_world = vel[1] * cos_t - vel[2] * sin_t
        vz_world = vel[1] * sin_t + vel[2] * cos_t
        speed = math.sqrt(vel[0]**2 + vy_world**2 + vz_world**2)
        launch = math.degrees(math.atan2(vz_world, math.hypot(vel[0], vy_world)))
        side = math.degrees(math.atan2(vel[0], vy_world))

        # Alias-aware agreement (audit F-2): the radar folds any radial
        # velocity beyond +/-v_max_ext back into that interval, so a real
        # drive's Doppler reads as some folded value -- comparing the
        # position-track's expected radial speed directly against it would
        # collapse confidence on exactly the fastest (best) shots. Fold the
        # expectation the same way the radar does, THEN compare.
        los = xyz_f[k0] / np.linalg.norm(xyz_f[k0])
        m = self.v_max_ext
        expected = float(vel @ los)                       # signed, sensor frame
        folded = abs((expected + m) % (2.0 * m) - m)      # what the radar reports
        # Denominator floored at 10% of v_max_ext (audit V-3): under the
        # 3-TX profile a fast ball's FOLDED Doppler can be ~2 m/s, and a
        # purely relative error would let sub-m/s noise crater the
        # confidence of exactly the best-measured shots. The floor keeps
        # the comparison relative for ordinary Doppler magnitudes and
        # absolute (in fold-space scale) near the fold zeros.
        agree = 1.0 - min(1.0, abs(folded - v_f[k0]) /
                          max(v_f[k0], 0.1 * m))

        # Physical floor (Johnny's rule): launch angle can never be < 0 --
        # the ball leaves the GROUND. A negative estimate is measurement
        # error (noise on a near-zero launch) or club-blend contamination
        # (chip-speed shots drag the fit downward), never reality. Clamp,
        # and use the violation as evidence: the further below zero the
        # raw fit landed, the less the rest of this fit deserves trust
        # (-2 deg barely dents it; -10 deg gates confidence hard). The
        # raw value is preserved for diagnostics/replay tuning.
        launch_raw = None
        if launch < 0.0:
            launch_raw = launch
            agree *= 1.0 / (1.0 + abs(launch) / 5.0)
            launch = 0.0

        ball_mph = speed * MPS_TO_MPH
        # Club speed = the fastest surviving pre-birth row (see the
        # candidate collection above): the arc-bottom reading is taken AT
        # the ball's first detection, where the head's velocity is fully
        # radial, so no fit/extrapolation is needed and the estimate is
        # nearly unbiased. Two rows minimum so a lone noise blip can't
        # invent a clubhead.
        club_mph = (float(max(club_cands)) * MPS_TO_MPH
                    if len(club_cands) >= 2 else None)
        smash = ball_mph / club_mph if club_mph else None
        # Physical smash tops out ~1.55 (COR limit); 1.8 leaves margin for
        # the residual cos(theta) low bias of a reading 1-2 frames before
        # exact impact, while still nulling nonsense pairings.
        if smash is not None and not (0.9 < smash < 1.8):
            club_mph = smash = None

        # Lateral-curvature hint for spin-axis inference (tier 2): quadratic
        # coefficient of x(t) after removing the linear term.
        ax = None
        if used.sum() >= 6:
            tt = t_f[used] - t_f[used][0]
            cx = np.polyfit(tt, xyz_f[used, 0], 2)
            ax = float(2 * cx[0])                  # lateral accel, m/s^2

        # t_impact = the ball track's birth (host-clock anchored): impact
        # to within ~a frame period. Sharper than the old window-start
        # anchor, so the audio slice ShotFuser cuts around it is better
        # centered on the actual strike (audit F-7).
        out = {"t_impact": t0 + t_birth, "ball_speed_mph": round(ball_mph, 1),
               "club_speed_mph": round(club_mph, 1) if club_mph else None,
               "launch_angle_deg": round(launch, 1),
               "side_angle_deg": round(side, 1),
               "smash_factor": round(smash, 2) if smash else None,
               "lateral_accel_mps2": round(ax, 2) if ax is not None else None,
               "n_fixes": int(used.sum()),
               "geometry_confidence": round(agree, 2)}
        if launch_raw is not None:
            out["launch_angle_raw_deg"] = round(launch_raw, 1)
        return out

    def stop(self):
        self._running = False
        try:
            self.cli.write(b"sensorStop\n")
        finally:
            self.cli.close()
            self.data.close()


def load_capture(path: str) -> list:
    """Rebuild a Frame list from an archived .npz for offline replay:
        frames = load_capture('captures/radar_20260703_101502_411.npz')
        geom = src.analyze(frames)   # re-run analysis with new parameters
    """
    d = np.load(path)
    frames, k = [], 0
    has_num = "num" in getattr(d, "files", [])       # old archives lack it
    for i in range(len(d["t"])):
        n = int(d["n_points"][i])
        num = int(d["num"][i]) if has_num and int(d["num"][i]) >= 0 else None
        f = Frame(t=float(d["t"][i]),
                  points=d["points"][k:k + n],
                  snr=d["snr"][k:k + n] if n else None,
                  num=num)
        frames.append(f)
        k += n
    return frames
