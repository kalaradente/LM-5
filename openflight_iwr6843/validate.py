"""
validate.py — score pipeline output against launch-monitor truth data.

Usage:
  python -m openflight_iwr6843.validate captures/shots.jsonl truth.csv
  python -m openflight_iwr6843.validate shots.csv truth.csv

shots      — one row per shot from this pipeline. The pipeline writes this
             itself: shot_fusion logs every fused shot to
             captures/shots.jsonl (ball_speed_mph, launch_angle_deg,
             side_angle_deg, spin_rpm, spin_source, diagnostics, ...).
             A hand-made CSV with the same columns also works.
truth.csv  — export from Eye XO / Trackman with matching shot order and
             columns ball_speed, launch_angle, side_angle, spin (any common
             naming; see ALIASES).

Prints per-metric error stats (mean, std, RMSE, worst) split by spin_source,
which is the number that decides whether "measured" is beating "inferred".
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict

import numpy as np

ALIASES = {
    "ball_speed_mph": ["ball_speed_mph", "ball_speed", "ballspeed", "speed"],
    "launch_angle_deg": ["launch_angle_deg", "launch_angle", "launch",
                          "vla", "vert_launch"],
    "side_angle_deg": ["side_angle_deg", "side_angle", "azimuth", "hla",
                        "horz_launch", "direction"],
    "spin_rpm": ["spin_rpm", "spin", "total_spin", "backspin"],
}


def _read(path):
    if path.endswith(".jsonl"):
        # The pipeline's own local shot log (shot_fusion._log_shot writes
        # captures/shots.jsonl) -- one JSON dict per line.
        import json
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _col(rows, names):
    # Union of keys across ALL rows, and .get() per row (audit T-9): a
    # real shots.jsonl is heterogeneous -- swing records carry no launch/
    # side keys at all -- and first-row-keyed direct indexing crashed on
    # the first mixed-session file. A row without the column scores NaN
    # (excluded downstream), same as an empty CSV cell.
    keys = {}
    for r in rows:
        for k in r.keys():
            keys.setdefault(k.lower().strip(), k)
    for n in names:
        if n in keys:
            return [float(r[keys[n]])
                    if r.get(keys[n]) not in ("", None) else np.nan
                    for r in rows]
    return None


def main(shots_path: str, truth_path: str):
    shots, truth = _read(shots_path), _read(truth_path)
    # Speed-training swings have no truth counterpart (a truth unit only
    # logs ball flight) and their structural ball_speed 0.0 poisons every
    # aggregate if scored (audit T-9: one swing in a mixed session file
    # contributed a 95 mph "error"). Drop them BEFORE order-pairing.
    n_swings = sum(1 for s in shots if s.get("swing"))
    if n_swings:
        shots = [s for s in shots if not s.get("swing")]
        print(f"note: dropped {n_swings} speed-training swing record(s) -- "
              f"no truth counterpart; scoring ball shots only")
    n = min(len(shots), len(truth))
    if len(shots) != len(truth):
        print(f"warning: {len(shots)} shots vs {len(truth)} truth rows; "
              f"scoring first {n} of each (order must match)")
    shots, truth = shots[:n], truth[:n]
    sources = [s.get("spin_source", "") for s in shots]

    print(f"{n} paired shots\n")
    for metric, names in ALIASES.items():
        ours = _col(shots, names)
        theirs = _col(truth, names)
        if ours is None or theirs is None:
            print(f"{metric:>18}: missing column, skipped")
            continue
        err = np.array(ours) - np.array(theirs)
        groups = {"all": np.ones(n, bool)}
        if metric == "spin_rpm":
            groups["measured"] = np.array([s == "measured" for s in sources])
            groups["inferred"] = np.array([s == "inferred" for s in sources])
        for gname, mask in groups.items():
            e = err[mask & ~np.isnan(err)]
            if not len(e):
                continue
            print(f"{metric:>18} [{gname:>8}] n={len(e):3d}  "
                  f"mean {np.mean(e):+8.2f}  std {np.std(e):7.2f}  "
                  f"rmse {np.sqrt(np.mean(e**2)):7.2f}  "
                  f"worst {np.max(np.abs(e)):7.2f}")
    print("\nInterpretation: spin_rpm[measured] rmse must beat "
          "spin_rpm[inferred] rmse, or the K-MC1 channel isn't earning "
          "its place yet.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
