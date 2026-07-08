#!/usr/bin/env python3
"""Short-game floor probe: how far DOWN can the trigger gate go?

The pipeline's minimum shot today is set by BALL_MIN_SPEED = 7.6 m/s
(17 mph on folded Doppler) — a 2-yd chip leaves the face at ~12-13 mph
and never triggers a capture. This module answers, empirically, how far
that floor can be pushed and what it costs:

  SYNTHETIC (runs now, no hardware) — sweeps chip-class ball speeds
  against candidate trigger gates through geometry_capture_simulator's
  FULL hostile observation model (golfer body, CFAR false alarms, static
  clutter, folding, quantization) and the REAL IWR6843Source.analyze():

      python3 shortgame_probe.py

  LIVE (bench rung, when hardware arrives) — runs the real radar with a
  lowered gate and counts idle false-triggers, then real-chip detections:

      python3 shortgame_probe.py --live --gate 4.5 --minutes 5

The physics box the sweep operates inside (can't be tuned away):

  - Doppler bin width at the 3-TX indoor profile is ~2.4 m/s (~5.3 mph):
    a ball under ~2 bins (~11 mph) competes with static clutter leakage
    around bin 0 (clutter removal is OFF by design, audit V-6).
  - At chip speeds, smash factor is ~1.1: the CLUB swings at nearly ball
    speed, so a lower gate triggers on the swing itself. That's fine in a
    short-game context (the ballistic-suffix classifier sorts club from
    ball) but it raises the phantom-shot stakes — measured below.
  - The K-MC1 spin carrier band bottoms at 1223 Hz = 17 mph: below that
    there is NO measured spin at any gate (CW physics). Chips get
    club-typical fallback spin regardless of this probe's outcome.
  - Launch angle at chip speeds reads -3.6±3.8 deg (worst 13.6 low) under
    full dirt — the F-7 separability floor as MEASURED after audit V-7
    (the older "~10 deg low" figure was retracted in V-3b; it was a sign
    bug, not physics). Chip-class angles stay informational; speed is the
    trustworthy read.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from geometry_capture_simulator import make_source, synth_capture  # noqa: E402

# Candidate trigger gates, m/s of folded Doppler. 7.6 is today's floor.
GATES_MPS = [7.6, 6.0, 5.0, 4.0, 3.0]
# Chip-class ball speeds to probe, mph. 17 ≈ today's floor; 25 ≈ 10 yd pitch.
BALL_SPEEDS_MPH = [8.0, 10.0, 12.0, 14.0, 17.0, 20.0, 25.0]
CHIP_LAUNCH_DEG = 22.0
SEEDS = range(6)
MPH_PER_MPS = 2.23694
# A gate is "reliable" at a speed when at least this fraction of seeds
# both trigger and analyze to a ball.
RELIABLE = 5 / 6


def capture_triggers(capture, gate_mps: float) -> bool:
    """Mirror of the stream loop's arm condition: any point in any frame
    above the gate on |folded Doppler|."""
    for frame in capture:
        pts = frame.points
        if pts.size and np.any(np.abs(pts[:, 3]) > gate_mps):
            return True
    return False


def synthetic_sweep() -> None:
    src = make_source()
    print(__doc__.split("\n\n")[0])
    print(f"\n{'gate':>10} | " + " | ".join(f"{b:>4.0f}mph" for b in BALL_SPEEDS_MPH)
          + " | phantom/trigger on ball-less swings")
    print("-" * 100)

    floors = {}
    for gate in GATES_MPS:
        src.BALL_MIN_SPEED = gate  # instance override, shadows the class attr
        cells = []
        for ball in BALL_SPEEDS_MPH:
            club = ball / 1.12  # chip-class smash ~1.1
            hits, errs = 0, []
            for seed in SEEDS:
                cap = synth_capture(ball, club, CHIP_LAUNCH_DEG, 0.0, seed=seed)
                if not capture_triggers(cap, gate):
                    continue
                geom = src.analyze(cap)
                if geom is None:
                    continue
                hits += 1
                errs.append(abs(geom["ball_speed_mph"] - ball))
            frac = hits / len(list(SEEDS))
            cells.append((frac, np.mean(errs) if errs else None))

        # Ball-less practice swings at chip club speed: phantom-shot and
        # nuisance-trigger rates for this gate.
        phantoms, nuisance = 0, 0
        n_idle = 12
        for seed in range(n_idle):
            cap = synth_capture(None, 15.0, seed=seed)
            if capture_triggers(cap, gate):
                nuisance += 1
                if src.analyze(cap) is not None:
                    phantoms += 1

        floor = next((b for b, (f, _) in zip(BALL_SPEEDS_MPH, cells) if f >= RELIABLE), None)
        floors[gate] = (floor, phantoms, nuisance, n_idle)
        row = " | ".join(
            f"{f * 100:3.0f}%" + (f"±{e:3.1f}" if e is not None else "    ")
            for f, e in cells
        )
        print(f"{gate:>4.1f} m/s   | {row} | "
              f"{phantoms}/{n_idle} phantom, {nuisance}/{n_idle} trigger")

    print("\nFloor per gate (lowest ball speed with ≥5/6 detect+analyze):")
    for gate, (floor, phantoms, nuisance, n) in floors.items():
        carry = ""
        if floor is not None:
            # Rough chip carry at that ball speed (RK4-derived: ~13 mph ≈ 2.9 yd,
            # ~17 mph ≈ 4.5 yd, ~25 mph ≈ 10.5 yd)
            approx = {8: 1, 10: 1.4, 12: 2.3, 14: 3.4, 17: 4.5, 20: 6.5, 25: 10.5}
            carry = f" (≈{approx.get(floor, '?')} yd carry)"
        print(f"  gate {gate:>4.1f} m/s ({gate * MPH_PER_MPS:4.1f} mph): "
              f"floor {floor if floor is not None else '—'} mph{carry}, "
              f"phantoms {phantoms}/{n}")
    print("""
READ THE TABLE HONESTLY (synthetic findings, 2026-07-07):
- The gate column barely changes anything because the simulator's CFAR
  false alarms (random Doppler) arm the capture at ANY gate — synthetic
  trigger rates are noise-dominated. The real trigger story is kinematic:
  a chip's CLUB (~ball/1.12) must cross the gate itself, so reliable
  self-arming for a 10-14 mph chip needs gate ≈ 4.0-4.5 m/s (9-10 mph).
- The classifier floor is the real limit: analyze() reads 14 mph balls at
  ~83% and 17 mph at 100% under full dirt (speed error ≤1.6 mph); 12 mph
  is a coin flip; 8 mph is invisible (inside Doppler-bin clutter).
- BLOCKER before enabling any short-game mode: ball-less CHIP-SPEED
  practice swings phantom ~58% here — the ballistic-suffix classifier
  was tuned for full swings and a slow gentle arc fools it. Full-speed
  practice swings still reject fine (main sim suite). A short-game mode
  needs a chip-regime classifier pass; quantify on real hardware with
  --live before trusting any of this.
Hard physics regardless of gate: no measured spin below 17 mph (K-MC1
carrier band), chip launch angles scatter low (−3.6±3.8°, informational
only — see the audit-log V-7 residual table), Doppler bin ≈ 5.3 mph, no
rollout model.""")


def live_bench(gate_mps: float, minutes: float) -> None:
    """Bench-rung mode for real hardware: run the radar with a lowered
    gate; phase 1 counts idle false-triggers (DON'T swing), phase 2 you
    chip real balls and compare detections to your count."""
    sys.path.insert(0, str(REPO_ROOT))
    from openflight_iwr6843.iwr6843_source import IWR6843Source  # noqa: E402
    from openflight_iwr6843.session import SessionConfig  # noqa: E402

    env: dict = {}
    hw = REPO_ROOT / "hardware.env"
    if hw.exists():
        for line in hw.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    # Same keys the wizard writes and run_iwr6843.py reads (audit T-8: this
    # path originally read IWR_CLI_PORT/IWR_DATA_PORT, names nothing ever
    # wrote -- the live mode would have refused to start even after a
    # successful wizard run).
    cli, data = env.get("CLI_PORT"), env.get("GEOM_PORT")
    if not (cli and data):
        sys.exit("hardware.env missing CLI_PORT/GEOM_PORT — run the "
                 "setup wizard first (this mode needs the real radar).")

    events = {"shots": 0}

    def on_geometry(geom):
        events["shots"] += 1
        print(f"[{time.strftime('%H:%M:%S')}] DETECTION #{events['shots']}: "
              f"ball {geom.get('ball_speed_mph', '—')} mph, "
              f"launch {geom.get('launch_angle_deg', '—')}°")

    session = SessionConfig(environment="indoor")
    src = IWR6843Source(cli, data, str(REPO_ROOT / "openflight_iwr6843" / "golf.cfg"),
                        on_geometry=on_geometry, session=session)
    src.BALL_MIN_SPEED = gate_mps
    print(f"Gate {gate_mps} m/s ({gate_mps * MPH_PER_MPS:.1f} mph), "
          f"{minutes} min. Phase 1: stand still (idle false-trigger count). "
          f"Phase 2: chip real balls and note your own count vs detections.")
    # run() is the blocking acquisition loop (there is no start(); audit
    # T-8 -- the original call here was an AttributeError waiting for
    # hardware day). Same daemon-thread pattern IWR6843Monitor uses.
    import threading
    t = threading.Thread(target=src.run, daemon=True)
    t.start()
    try:
        time.sleep(minutes * 60)
    finally:
        src.stop()
        t.join(timeout=5.0)
    print(f"Detections: {events['shots']}. Compare to reality; log the gate "
          f"and both counts in the audit log (bench rung).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="hardware bench mode")
    ap.add_argument("--gate", type=float, default=4.5, help="trigger gate, m/s (live mode)")
    ap.add_argument("--minutes", type=float, default=5.0, help="bench duration (live mode)")
    args = ap.parse_args()
    if args.live:
        live_bench(args.gate, args.minutes)
    else:
        synthetic_sweep()
