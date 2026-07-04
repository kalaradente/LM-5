"""
kalman.py — small Kalman filters shared by the spin decoder and trajectory fit.

Two trackers:
  FreqTracker  — 1D constant-drift tracker for the K-MC1 carrier ridge,
                 with gating (junk-frame rejection) and RTS smoothing.
  BallTracker  — 3D constant-velocity + gravity tracker for IWR6843 point
                 fixes, with RTS smoothing. Velocity state gives launch
                 angle / side angle directly.

No dependencies beyond numpy. Both are offline smoothers: run on a captured
window after the shot trigger, not sample-by-sample live.
"""

from __future__ import annotations

import numpy as np

G = 9.81  # m/s^2


def _rts(xs, Ps, xps, Pps, Fs):
    """Rauch-Tung-Striebel backward pass. Inputs are the forward-filter
    posterior (xs, Ps) and prior (xps, Pps) sequences plus transition mats."""
    n = len(xs)
    xs_s, Ps_s = xs.copy(), Ps.copy()
    for k in range(n - 2, -1, -1):
        C = Ps[k] @ Fs[k].T @ np.linalg.inv(Pps[k + 1])
        xs_s[k] = xs[k] + C @ (xs_s[k + 1] - xps[k + 1])
        Ps_s[k] = Ps[k] + C @ (Ps_s[k + 1] - Pps[k + 1]) @ C.T
    return xs_s, Ps_s


class FreqTracker:
    """Track a slowly drifting tone frequency through noisy per-frame peaks.

    State: [f, f_dot]. Measurements: peak frequency per spectrogram frame.
    Frames whose measurement falls outside `gate` sigmas of the prediction
    are treated as junk: the filter coasts on its prediction.
    """

    def __init__(self, q_drift=2000.0, r_meas=40.0**2, gate=4.0):
        self.q = q_drift      # drift-rate process noise (Hz/s)^2 per s
        self.r = r_meas       # measurement variance, Hz^2
        self.gate = gate

    def smooth(self, t: np.ndarray, f_meas: np.ndarray):
        """Returns (f_smoothed, used_mask). t in seconds, f_meas in Hz."""
        n = len(t)
        x = np.array([f_meas[0], 0.0])
        P = np.diag([self.r, 200.0**2])
        H = np.array([[1.0, 0.0]])
        xs, Ps, xps, Pps, Fs = [], [], [], [], []
        used = np.zeros(n, dtype=bool)
        for k in range(n):
            dt = t[k] - t[k - 1] if k else 0.0
            F = np.array([[1.0, dt], [0.0, 1.0]])
            Q = self.q * np.array([[dt**3 / 3, dt**2 / 2],
                                   [dt**2 / 2, dt]]) if dt else np.zeros((2, 2))
            xp = F @ x
            Pp = F @ P @ F.T + Q
            innov = f_meas[k] - (H @ xp)[0]
            S = (H @ Pp @ H.T)[0, 0] + self.r
            if innov**2 <= self.gate**2 * S:          # gated update
                K = (Pp @ H.T / S).ravel()
                x = xp + K * innov
                P = Pp - np.outer(K, H @ Pp)
                used[k] = True
            else:                                      # junk frame: coast
                x, P = xp, Pp + np.diag([self.r, 0.0])
            xps.append(xp); Pps.append(Pp); xs.append(x); Ps.append(P)
            Fs.append(F)
        xs_s, _ = _rts(np.array(xs), np.array(Ps),
                       np.array(xps), np.array(Pps), np.array(Fs))
        return xs_s[:, 0], used


class BallTracker:
    """3D constant-velocity + gravity tracker over IWR6843 point fixes.

    State: [x, y, z, vx, vy, vz] in the sensor frame (x lateral, y boresight,
    z up). Gravity enters as a known control input on vz. Returns the RTS-
    smoothed state sequence; the velocity at the first tracked fix is the
    launch vector.
    """

    def __init__(self, q_accel=6.0**2, r_pos=0.06**2, gate=5.0):
        self.q = q_accel
        self.r = r_pos
        self.gate = gate

    def smooth(self, t: np.ndarray, xyz: np.ndarray):
        n = len(t)
        H = np.hstack([np.eye(3), np.zeros((3, 3))])
        R = self.r * np.eye(3)
        v0 = (xyz[min(2, n - 1)] - xyz[0]) / max(t[min(2, n - 1)] - t[0], 1e-3)
        x = np.concatenate([xyz[0], v0])
        P = np.diag([self.r] * 3 + [25.0] * 3)
        xs, Ps, xps, Pps, Fs = [], [], [], [], []
        used = np.zeros(n, dtype=bool)
        for k in range(n):
            dt = t[k] - t[k - 1] if k else 0.0
            F = np.eye(6)
            F[:3, 3:] = dt * np.eye(3)
            Q = self.q * np.block([
                [dt**3 / 3 * np.eye(3), dt**2 / 2 * np.eye(3)],
                [dt**2 / 2 * np.eye(3), dt * np.eye(3)]]) if dt \
                else np.zeros((6, 6))
            u = np.array([0, 0, -0.5 * G * dt**2, 0, 0, -G * dt])
            xp = F @ x + u
            Pp = F @ P @ F.T + Q
            innov = xyz[k] - H @ xp
            S = H @ Pp @ H.T + R
            md2 = float(innov @ np.linalg.inv(S) @ innov)
            if md2 <= self.gate**2:
                K = Pp @ H.T @ np.linalg.inv(S)
                x = xp + K @ innov
                P = Pp - K @ H @ Pp
                used[k] = True
            else:
                x, P = xp, Pp
            xps.append(xp); Pps.append(Pp); xs.append(x); Ps.append(P)
            Fs.append(F)
        xs_s, _ = _rts(np.array(xs), np.array(Ps),
                       np.array(xps), np.array(Pps), np.array(Fs))
        return xs_s, used
