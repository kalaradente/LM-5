"""
spin_capture_simulator.py — generate a synthetic K-MC1 I/Q capture for ANY
shot you specify, run it through spin_decoder.decode(), and print the result.

This tests the SPIN-DECODER signal path (raw radar audio -> recovered spin).
For the flight-physics side (ball speed/spin/launch -> carry/apex/curve via
the OpenFlight engine), see shot_simulator.py instead.

No hardware needed. Runs entirely offline. This is how you test "what if"
scenarios (high ball speed + low spin, wedge spin, noisy capture, etc.)
without spending time/tokens asking someone else to run it.

USAGE (from the folder containing openflight_iwr6843/):

    python spin_capture_simulator.py --speed 175 --spin 2200
    python spin_capture_simulator.py --speed 90 --spin 9500 --noise 0.3
    python spin_capture_simulator.py --speed 175 --spin 2200 --missing-fundamental
    python spin_capture_simulator.py --sweep    # runs a grid of speed x spin combos

Flags:
  --speed     ball speed in mph (radar-relative closing speed)
  --spin      true spin rate in rpm
  --marker    modulation depth 0-1 (how strong the once-per-rev glint is;
              ~0.35 = decent foil dot, ~0.05-0.1 = plausible plain-ball dimple
              signature, 0 = perfectly smooth sphere / no signal at all)
  --noise     noise amplitude relative to signal (0.15 = typical, 0.5 = bad)
  --clutter   amplitude of an unrelated slow-moving clutter tone
  --dwell     capture window length in seconds (0.20 = short/indoor,
              0.45 = long/outdoor, matches session.py presets)
  --decel     how much the ball decelerates over the window, in mph over
              the dwell (radar-relative deceleration; try 0-20)
  --missing-fundamental   zero out the fundamental, keep only harmonics 2 & 3
              (stress-tests the octave-trap defense)
  --sweep     ignore other flags; run a grid and print a results table
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

# Make the package importable whether you run this from the repo root or
# from inside the unzipped openflight_iwr6843/ folder's parent.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from openflight_iwr6843.spin_decoder import decode, FS  # noqa: E402

WAVELENGTH = 0.0125          # 24GHz, meters
MPH_TO_MPS = 0.44704


def synth_capture(speed_mph: float, spin_rpm: float, marker: float = 0.35,
                  noise: float = 0.15, clutter: float = 0.4,
                  dwell_s: float = 0.20, decel_mph: float = 12.0,
                  missing_fundamental: bool = False,
                  seed: int = 0) -> np.ndarray:
    """Build a synthetic K-MC1 I/Q stream for one shot."""
    rng = np.random.default_rng(seed)
    n = int(dwell_s * FS)
    t = np.arange(n) / FS

    v0 = speed_mph * MPH_TO_MPS
    v1 = max(v0 - decel_mph * MPH_TO_MPS, 1.0)
    v = v0 + (v1 - v0) * (t / dwell_s)              # linear decel over window
    f_carrier = 2 * v / WAVELENGTH                  # Doppler tone, Hz
    phase = 2 * np.pi * np.cumsum(f_carrier) / FS

    rot_hz = spin_rpm / 60.0
    if missing_fundamental:
        # Suppress the fundamental; leave 2nd and 3rd harmonics — this is
        # the stress test for the tap-along bank's octave-trap defense.
        mod = (0.15 * marker * np.cos(2 * np.pi * rot_hz * t)
              + 1.0 * marker * np.cos(2 * np.pi * 2 * rot_hz * t)
              + 0.6 * marker * np.cos(2 * np.pi * 3 * rot_hz * t))
    else:
        mod = marker * np.cos(2 * np.pi * rot_hz * t)

    ball = (1.0 + mod) * np.exp(1j * phase)
    clut = clutter * np.exp(1j * 2 * np.pi * rng.uniform(150, 400) * t)
    noise_sig = noise * (rng.standard_normal(n) + 1j * rng.standard_normal(n))

    return ball + clut + noise_sig


def run_one(speed, spin, marker, noise, clutter, dwell, decel,
           missing_fundamental, seed=0, verbose=True):
    z = synth_capture(speed, spin, marker, noise, clutter, dwell, decel,
                      missing_fundamental, seed)
    result = decode(z)
    if verbose:
        print(f"\n--- Simulated shot: {speed} mph, {spin} rpm true spin ---")
        print(f"  marker={marker} noise={noise} clutter={clutter} "
              f"dwell={dwell}s decel={decel}mph "
              f"missing_fundamental={missing_fundamental}")
        print(f"  Decoder output: {result}")
        if result.get("ok"):
            err = result["spin_rpm"] - spin
            print(f"  Spin error: {err:+.0f} rpm  "
                  f"({100*err/spin:+.1f}%)  confidence={result['confidence']}")
        else:
            print(f"  Decoder could not find a stable read: "
                  f"{result.get('reason')}")
    return result


def sweep():
    speeds = [80, 110, 140, 175]
    spins = [2200, 3000, 6000, 9000]
    print(f"{'speed(mph)':>10} {'true_rpm':>9} {'decoded_rpm':>12} "
          f"{'err%':>7} {'conf':>6}")
    for s in speeds:
        for r in spins:
            res = run_one(s, r, marker=0.35, noise=0.15, clutter=0.4,
                          dwell=0.20, decel=12.0, missing_fundamental=False,
                          verbose=False)
            if res.get("ok"):
                err = 100 * (res["spin_rpm"] - r) / r
                print(f"{s:>10} {r:>9} {res['spin_rpm']:>12.0f} "
                      f"{err:>6.1f}% {res['confidence']:>6}")
            else:
                print(f"{s:>10} {r:>9} {'FAILED':>12} {'--':>7} {'--':>6}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--speed", type=float, default=150.0)
    p.add_argument("--spin", type=float, default=6000.0)
    p.add_argument("--marker", type=float, default=0.35)
    p.add_argument("--noise", type=float, default=0.15)
    p.add_argument("--clutter", type=float, default=0.4)
    p.add_argument("--dwell", type=float, default=0.20)
    p.add_argument("--decel", type=float, default=12.0)
    p.add_argument("--missing-fundamental", action="store_true")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--sweep", action="store_true")
    args = p.parse_args()

    if args.sweep:
        sweep()
    else:
        run_one(args.speed, args.spin, args.marker, args.noise,
               args.clutter, args.dwell, args.decel,
               args.missing_fundamental, args.seed)
