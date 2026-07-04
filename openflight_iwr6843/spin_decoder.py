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
WAVELENGTH = 0.0125                    # 24GHz
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


HIGHPASS_CUTOFF_HZ = 20.0     # below your lowest spin case (25Hz); safe margin
MAINS_NOTCH_HZ = 60.0         # Mains hum frequency to notch out of the signal.
                               # 60.0 Hz = North America / most of the Americas.
                               # Flip to 50.0 Hz if you're building this outside
                               # North America (Europe, UK, most of Asia,
                               # Africa, Australia use 50Hz mains power).
MAINS_NOTCH_Q = 20.0          # narrow notch: kill the hum, spare neighbors

# --- K-MC1 AC/DC-wiring auto-detect (provenance tag only) ---
KMC1_LOWBAND_HZ = 35.0        # probe band 0<f<35Hz: safely inside the AC output's
                               # 40Hz -3dB stopband, so real AC captures have ~no
                               # signal here while DC captures do.
KMC1_DC_RATIO = 6.0           # sub-35Hz mean level > this x the spectral floor
                               # => DC wiring. Placeholder — CALIBRATE against a
                               # known AC capture and a known DC capture; see
                               # detect_kmc1_output().


def detect_kmc1_output(z: np.ndarray, fs: int = FS,
                       cutoff_hz: float = KMC1_LOWBAND_HZ,
                       dc_ratio: float = KMC1_DC_RATIO) -> str:
    """Infer whether the K-MC1's AC or DC output pins are wired, from the
    capture itself — the DC output passes content below 40Hz, the AC output
    rolls it off. Returns "dc" or "ac". Provenance tag ONLY; does not affect
    decoding (filtering is unconditional, see clean_iq / session.py).

    Measures mean spectral level in 0<f<cutoff_hz relative to the broadband
    median floor: broadband ADC noise sits at ~1x the floor there regardless
    of wiring, so real low-frequency signal (present on DC, rolled off on AC)
    is what pushes the ratio up.

    Caveat — needs bench calibration: the HiFiBerry line-in is itself
    AC-coupled, BUT as a hi-fi audio input its corner is only a few Hz (it has
    to pass 20Hz+ bass) — nothing like the K-MC1 AC output's 40Hz corner. So
    it blocks just the DC output's true 0Hz bias and passes the rest.
    Detection therefore uses the wide (~few Hz .. 35Hz) window, whose signal
    strength on a real DC capture is an empirical question. A too-clean DC
    capture can read as "ac" — a benign miss, since it's metadata only.
    """
    z = z - np.mean(z)                              # measure band energy, not offset
    n = len(z)
    spec = np.abs(np.fft.fft(z * np.hanning(n)))
    freqs = np.fft.fftfreq(n, 1 / fs)
    low = (np.abs(freqs) < cutoff_hz) & (freqs != 0)
    floor = float(np.median(spec)) + 1e-12
    low_level = float(np.mean(spec[low])) if low.any() else 0.0
    return "dc" if low_level > dc_ratio * floor else "ac"


def clean_iq(z: np.ndarray, fs: int = FS, highpass: bool = True,
            notch_mains: bool = True) -> np.ndarray:
    """Pre-clean raw I/Q before decoding. Makes the DC-output wiring usable
    (recovers the full low end AC would have rolled off, per the K-MC1
    AC/DC bandwidth discussion) and strips electrical mains hum that would
    otherwise sit inside the spin band and masquerade as a rhythm.
    No-op-safe on already-clean AC-output captures.
    """
    z = z - np.mean(z)                              # DC offset removal
    if highpass:
        b, a = sig.butter(4, HIGHPASS_CUTOFF_HZ / (fs / 2), btype="high")
        z = sig.filtfilt(b, a, z)
    if notch_mains:
        w0 = MAINS_NOTCH_HZ / (fs / 2)
        b, a = sig.iirnotch(w0, MAINS_NOTCH_Q)
        z = sig.filtfilt(b, a, z)
    return z


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


def decode(z: np.ndarray, fs: int = FS, bench: bool = False,
          highpass: bool = True, notch_mains: bool = True) -> dict:
    """Full chain on one capture window. bench=True for a spinning,
    non-translating target (drill rig). highpass/notch_mains clean the
    signal first (see clean_iq) — safe defaults for either AC or DC
    wiring off the K-MC1."""
    z = clean_iq(z, fs, highpass=highpass, notch_mains=notch_mains)
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
