"""
spin_decoder.py — K-MC1 I/Q audio -> spin RPM, Kalman-smoothed carrier track.

Pipeline: stereo capture (I=left, Q=right) -> complex baseband -> spectrogram
ridge with Kalman smoothing + junk-frame gating -> carrier cancellation ->
residual envelope periodicity in the physical spin band -> RPM + confidence.

Bench mode (drill-spun ball, no translation): decode(z, bench=True) skips
carrier tracking and searches the raw envelope directly.

Run as a script with `python -m openflight_iwr6843.spin_decoder ...`
(the `-m` matters — this module uses package-relative imports).
Self-test after any wiring change: python -m openflight_iwr6843.spin_decoder --selftest
"""

from __future__ import annotations

import numpy as np
from scipy import signal as sig
from scipy.io import wavfile

from .kalman import FreqTracker

FS = 96_000
# K-MC1 transmit wavelength. Per the RFbeam K-MC1 / K-MC1_LP datasheet the
# transmitter frequency fTX is min/typ/max = 24.050 / 24.150 / 24.250 GHz, and
# the datasheet characterizes the Rx chain and antenna gain at its nominal
# "24.125 GHz" (also the block-diagram LO). We use that nominal 24.125 GHz:
#   lambda = c / f = 299792458 / 24.125e9 = 0.012427 m.
# (Was 0.0125 m, i.e. 24.0 GHz -- a ~0.6% high bias on every Doppler->speed
# and Doppler->spin-sideband number. The ~0.4% fTX min-max span and the
# 24.125-vs-24.150 nominal choice are both well inside other error sources.)
WAVELENGTH = 0.012427                  # 24.125 GHz (RFbeam K-MC1 datasheet)
SPIN_BAND = (25.0, 220.0)              # Hz rotation: ~1500-13000 rpm
CARRIER_BAND = (1_216.0, 16_000.0)     # Hz: plausible ball tones (outbound).
                                        # Lower edge = 17 mph (7.6 m/s), matching
                                        # iwr6843_source.BALL_MIN_SPEED. Upper
                                        # edge (16kHz ~ 224mph) sits just past the
                                        # K-MC1 AC output's 15kHz -3dB ceiling
                                        # (~210mph), so on AC wiring the very top
                                        # of the band rolls off — irrelevant, it's
                                        # above real shots. DC output (0-500kHz)
                                        # covers the whole band. See session.py.
MIN_TRACK_FRAMES = 4


MAINS_NOTCH_HZ = 60.0         # Mains hum frequency to notch out of the signal.
                               # 60.0 Hz = North America / most of the Americas.
                               # Flip to 50.0 Hz if you're building this outside
                               # North America (Europe, UK, most of Asia,
                               # Africa, Australia use 50Hz mains power).
MAINS_NOTCH_Q = 20.0          # narrow notch: kill the hum, spare neighbors


def clean_iq(z: np.ndarray, fs: int = FS) -> np.ndarray:
    """Strip mains hum before decoding. Wired to the K-MC1 AC output, the
    hardware already blocks DC and rolls off below its ~40Hz corner, so the
    only cleanup software needs is the mains notch: 60Hz hum passes the AC
    coupling (60Hz is above the 40Hz corner) and lands inside the spin band
    (~3600rpm), where it would masquerade as a rhythm.
    (Set MAINS_NOTCH_HZ=50 outside North America.)"""
    z = z - np.mean(z)                              # trivial on AC, harmless
    w0 = MAINS_NOTCH_HZ / (fs / 2)
    b, a = sig.iirnotch(w0, MAINS_NOTCH_Q)
    return sig.filtfilt(b, a, z)


def load_iq(path: str, fs: int = FS) -> np.ndarray:
    rate, data = wavfile.read(path)
    if rate != fs:
        raise ValueError(f"expected {fs} Hz wav, got {rate}")
    data = np.asarray(data, dtype=np.float64)
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError("need a stereo I/Q recording")
    peak = np.max(np.abs(data)) or 1.0
    return (data[:, 0] + 1j * data[:, 1]) / peak


def _ridge(z: np.ndarray, fs: int):
    """Per-frame strongest tone in CARRIER_BAND (the noisy measurements)."""
    nper = 2048
    f, t, S = sig.stft(z, fs=fs, nperseg=nper, noverlap=nper - 256,
                       return_onesided=False)
    f = np.fft.fftshift(f)
    S = np.fft.fftshift(np.abs(S), axes=0)
    band = (f >= CARRIER_BAND[0]) & (f <= CARRIER_BAND[1])
    fb, Sb = f[band], S[band]
    idx = np.argmax(Sb, axis=0)
    peak_f = fb[idx]
    peak_p = Sb[idx, np.arange(Sb.shape[1])]
    floor = np.median(Sb)
    ok = peak_p > 6.0 * floor
    return t[ok], peak_f[ok]


def track_carrier(z: np.ndarray, fs: int = FS):
    """Kalman-smoothed carrier history: (times, freq_hz) or (None, None)."""
    t, f_meas = _ridge(z, fs)
    if len(t) < MIN_TRACK_FRAMES:
        return None, None
    f_smooth, used = FreqTracker().smooth(t, f_meas)
    if used.sum() < MIN_TRACK_FRAMES:
        return None, None
    return t, f_smooth


def demodulate(z: np.ndarray, t_c, f_c, fs: int = FS) -> np.ndarray:
    n = np.arange(len(z)) / fs
    f_inst = np.interp(n, t_c, f_c)
    phase = 2 * np.pi * np.cumsum(f_inst) / fs
    base = z * np.exp(-1j * phase)
    b, a = sig.butter(4, 400 / (fs / 2))
    return sig.filtfilt(b, a, base)


def spin_from_residual(resid: np.ndarray, fs: int = FS, n_harmonics: int = 3,
                       step_rpm: float = 50.0):
    """Tap-along (harmonic-sum) spin estimate.

    Instead of grabbing the single loudest envelope frequency, score every
    candidate spin rate by summing spectral evidence at its fundamental AND
    its harmonics (a once-per-rev glint is a sharp pulse, so its energy is
    spread across multiples of the rotation rate). This pools weak clues,
    resists the missing-fundamental / octave-doubling trap, and the score
    profile across candidates exposes ambiguity instead of hiding it.

    Returns (rpm, confidence). Confidence blends peak prominence with the
    margin over the best non-harmonic rival: two rival candidates -> low
    confidence, honestly reported.
    """
    env = np.abs(resid)
    env = env - env.mean()
    n = len(env)
    spec = np.abs(np.fft.rfft(env * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, 1 / fs)
    df = freqs[1] - freqs[0]

    cand_rpm = np.arange(SPIN_BAND[0] * 60, SPIN_BAND[1] * 60 + 1, step_rpm)
    scores = np.zeros(len(cand_rpm))
    for i, rpm in enumerate(cand_rpm):
        f0 = rpm / 60.0
        s = 0.0
        for h in range(1, n_harmonics + 1):
            fh = f0 * h
            if fh >= freqs[-1]:
                break
            s += float(np.interp(fh, freqs, spec)) / np.sqrt(h)
        scores[i] = s

    floor = float(np.median(scores)) + 1e-12
    k_best = int(np.argmax(scores))
    prominence = scores[k_best] / floor

    # Parabolic interpolation between neighboring candidates for sub-step rpm.
    if 0 < k_best < len(scores) - 1:
        a, b, c = scores[k_best - 1], scores[k_best], scores[k_best + 1]
        denom = a - 2 * b + c
        offset = 0.5 * (a - c) / denom if abs(denom) > 1e-12 else 0.0
        rpm = float(cand_rpm[k_best] + np.clip(offset, -1, 1) * step_rpm)
    else:
        rpm = float(cand_rpm[k_best])

    # Ambiguity check: best rival that is NOT harmonically related (not near
    # 0.5x, 1x, or 2x of the winner). Close rival -> confidence collapses.
    f_best = rpm / 60.0
    rival = 0.0
    for i, r in enumerate(cand_rpm):
        f = r / 60.0
        if any(abs(f - m * f_best) < 3 * df for m in (0.5, 1.0, 2.0)):
            continue
        rival = max(rival, scores[i])
    margin = scores[k_best] / (rival + 1e-12)

    confidence = min(1.0, (prominence / 8.0)) * min(1.0, (margin - 1.0) / 0.5)
    confidence = float(np.clip(confidence, 0.0, 1.0))
    if confidence <= 0.0:
        return None, 0.0
    return rpm, round(confidence, 2)


def decode(z: np.ndarray, fs: int = FS, bench: bool = False) -> dict:
    """Full chain on one capture window. bench=True for a spinning,
    non-translating target (drill rig). clean_iq strips mains hum first."""
    z = clean_iq(z, fs)
    if bench:
        rpm, conf = spin_from_residual(z, fs)
        return {"ok": rpm is not None, "spin_rpm": rpm, "confidence": conf,
                "mode": "bench"}
    t_c, f_c = track_carrier(z, fs)
    if t_c is None:
        return {"ok": False, "reason": "no stable ball tone"}
    resid = demodulate(z, t_c, f_c, fs)
    rpm, conf = spin_from_residual(resid, fs)
    return {"ok": rpm is not None, "spin_rpm": rpm, "confidence": conf,
            "radial_speed_mps": round(float(np.median(f_c)) * WAVELENGTH / 2, 1),
            "dwell_ms": round(1000 * float(t_c[-1] - t_c[0]), 1),
            "mode": "flight"}


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        # Startup self-test: synthesize a known-good bench signal (3000rpm
        # marked ball) and confirm the pipeline recovers it. Run this once
        # after wiring changes or before a session to catch a dead channel,
        # swapped I/Q, or bad gain before spending real swings on it.
        t = np.arange(int(0.2 * FS)) / FS
        known = (1 + 0.3 * np.cos(2 * np.pi * 50 * t)) * np.exp(1j * 2 * np.pi * 40 * t)
        known += 0.1 * (np.random.default_rng(0).standard_normal(len(t))
                       + 1j * np.random.default_rng(1).standard_normal(len(t)))
        r = decode(known, bench=True)
        ok = r["ok"] and abs(r["spin_rpm"] - 3000) < 150
        print(f"[selftest] decoded {r.get('spin_rpm')} rpm "
              f"(expected ~3000), confidence {r.get('confidence')} "
              f"-> {'PASS' if ok else 'FAIL — check wiring/gain/I-Q swap'}")
        sys.exit(0 if ok else 1)
    print(decode(load_iq(sys.argv[1]), bench="--bench" in sys.argv))
