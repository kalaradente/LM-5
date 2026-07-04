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

# Cross-checked against TI's "Understanding the Out of Box Demo Data Output"
# doc. Magic word, both TLV type IDs, and the Detected Points TLV layout
# (16 bytes/point: x,y,z,doppler as 4x float32, same field order) all match
# exactly. FRAME_HEADER_LEN below is the one open question: our 32 bytes
# (+ the 8-byte magic word = 40 total) matches summing that doc's own listed
# fields, but the SAME doc separately states the frame header is 44 bytes
# total -- an internal inconsistency in that source, most likely explained
# by an SDK-version difference (a field added in some later SDK revision,
# e.g. numStaticDetectedObj) rather than either number being simply wrong.
# NOT resolved from documentation alone -- but bring-up rung 2 (this parser
# against a live stream, positions must match the TI Demo Visualizer) is
# exactly the empirical check that catches a wrong header length: it would
# show up as garbage/missing points, not a subtle numeric error. Diff this
# against your specific flashed SDK version's demo source if rung 2 fails.
MAGIC_WORD = b"\x02\x01\x04\x03\x06\x05\x08\x07"
FRAME_HEADER_FMT = "<8I"
FRAME_HEADER_LEN = 32
TLV_DETECTED_POINTS = 1
TLV_SIDE_INFO = 7
MPS_TO_MPH = 2.2369362921


@dataclass
class Frame:
    t: float
    points: np.ndarray                 # (N,4): x,y,z [m], v_radial [m/s]
    snr: Optional[np.ndarray] = None


class IWR6843Source:
    BALL_MIN_SPEED = 7.6    # 17 mph — chip/putt shots trigger and classify as ball
    CLUB_MIN_SPEED = 4.0    # ~9 mph, kept below BALL_MIN_SPEED so slow-shot
                            # points still classify as club rather than ball
    CAPTURE_WINDOW = 0.20
    PRE_ROLL = 0.15
    MIN_BALL_FIXES = 4
    RANGE_GATE = (0.3, 6.0)
    COOLDOWN = 2.0
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
                 archive_dir: Optional[str] = "captures"):
        self.cli = serial.Serial(cli_port, 115200, timeout=1)
        self.data = serial.Serial(data_port, 921600, timeout=0.05)
        self.cfg_path = cfg_path
        self.on_geometry = on_geometry
        self.archive_dir = archive_dir
        self._buf = bytearray()
        self._pre_roll: deque[Frame] = deque()
        self._running = False
        self._last_frame_num = None

    # ---- bring-up --------------------------------------------------------

    def configure(self):
        with open(self.cfg_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("%"):
                    continue
                self.cli.write((line + "\n").encode())
                time.sleep(0.02)
                self.cli.read(self.cli.in_waiting or 1)

    # ---- TLV stream ------------------------------------------------------

    def frames(self):
        """Generator of Frame objects; also checks frame-number continuity."""
        while self._running:
            chunk = self.data.read(4096)
            if chunk:
                self._buf.extend(chunk)
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
                yield frame

    def _parse(self, raw: bytes, hdr) -> Optional[Frame]:
        num_obj, num_tlvs = hdr[5], hdr[6]
        offset = 8 + FRAME_HEADER_LEN
        points, snr = None, None
        for _ in range(num_tlvs):
            if offset + 8 > len(raw):
                return None
            tlv_type, tlv_len = struct.unpack_from("<2I", raw, offset)
            body = raw[offset + 8: offset + 8 + tlv_len]
            if tlv_type == TLV_DETECTED_POINTS and num_obj:
                pts = np.frombuffer(body, dtype=np.float32,
                                    count=num_obj * 4).reshape(num_obj, 4)
                points = pts.astype(np.float64)
            elif tlv_type == TLV_SIDE_INFO and num_obj:
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
        keep = (r > self.RANGE_GATE[0]) & (r < self.RANGE_GATE[1])
        return Frame(time.monotonic(), points[keep],
                     snr[keep] if snr is not None else None)

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
                deadline = frame.t + self.CAPTURE_WINDOW
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

    def analyze(self, capture: list) -> Optional[dict]:
        t0 = capture[0].t
        ball, club_speeds = [], []
        for f in capture:
            for i in range(f.points.shape[0]):
                x, y, z, v = f.points[i]
                s = abs(v)
                if s > self.BALL_MIN_SPEED:
                    ball.append((f.t - t0, x, y, z, s))
                elif s > self.CLUB_MIN_SPEED:
                    club_speeds.append(s)
        if len(ball) < self.MIN_BALL_FIXES:
            return None
        b = np.array(ball)
        order = np.argsort(b[:, 0])
        t, xyz, v_rad = b[order, 0], b[order, 1:4], b[order, 4]

        tilt_rad = math.radians(self.MOUNT_TILT_DEG)
        states, used = BallTracker(tilt_rad=tilt_rad).smooth(t, xyz)
        if used.sum() < self.MIN_BALL_FIXES:
            return None
        ui = np.flatnonzero(used)
        k0, km = int(ui[0]), int(ui[len(ui) // 2])
        vel = states[km, 3:].copy()                # mid-track: lowest variance,
                                                     # still in SENSOR frame
        # Back-extrapolate mid-track velocity to the launch instant (k0),
        # using gravity decomposed into the sensor's own (tilted) y/z --
        # same physics the Kalman filter itself now uses (see kalman.py).
        dt_launch = t[km] - t[k0]
        vel[1] += -9.81 * math.sin(tilt_rad) * dt_launch
        vel[2] += -9.81 * math.cos(tilt_rad) * dt_launch
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

        los = xyz[k0] / np.linalg.norm(xyz[k0])
        agree = 1.0 - min(1.0, abs(abs(float(vel @ los)) - v_rad[k0]) /
                          max(v_rad[k0], 1e-6))

        ball_mph = speed * MPS_TO_MPH
        club_mph = (float(np.percentile(club_speeds, 90)) * MPS_TO_MPH
                    if len(club_speeds) >= 3 else None)
        smash = ball_mph / club_mph if club_mph else None
        if smash is not None and not (0.9 < smash < 1.7):
            club_mph = smash = None

        # Lateral-curvature hint for spin-axis inference (tier 2): quadratic
        # coefficient of x(t) after removing the linear term.
        ax = None
        if used.sum() >= 6:
            tt = t[used] - t[used][0]
            cx = np.polyfit(tt, xyz[used, 0], 2)
            ax = float(2 * cx[0])                  # lateral accel, m/s^2

        return {"t_impact": t0, "ball_speed_mph": round(ball_mph, 1),
                "club_speed_mph": round(club_mph, 1) if club_mph else None,
                "launch_angle_deg": round(launch, 1),
                "side_angle_deg": round(side, 1),
                "smash_factor": round(smash, 2) if smash else None,
                "lateral_accel_mps2": round(ax, 2) if ax is not None else None,
                "n_fixes": int(used.sum()),
                "geometry_confidence": round(agree, 2)}

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
    for i in range(len(d["t"])):
        n = int(d["n_points"][i])
        f = Frame(t=float(d["t"][i]),
                  points=d["points"][k:k + n],
                  snr=d["snr"][k:k + n] if n else None)
        frames.append(f)
        k += n
    return frames
