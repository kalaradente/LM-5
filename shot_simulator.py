#!/usr/bin/env python3
"""
shot_simulator.py — plaintext ball-flight simulator.

Type in ball speed, spin, and launch angle; get a full flight simulation
back. Two engines run on every shot you enter:

  1. openflight_iwr6843 (this repo): infer_spin() runs the same launch
     conditions through our own club-typical spin fallback model, so you
     can see what our sensor stack would have guessed if spin hadn't been
     measured — a sanity check on the number you typed.
  2. openflight (github.com/jewbetcha/openflight, vendored in
     ./openflight_upstream/): resolve_launch() + simulate() run the actual
     RK4 drag+Magnus physics engine used by the real launch monitor to
     produce carry, apex, lateral drift, flight time, and landing conditions.

Usage:
    python3 shot_simulator.py                  # interactive prompts
    python3 shot_simulator.py --ball-speed 165 --spin 2600 --launch-angle 13
    python3 shot_simulator.py --live           # also push the shot into a
                                                # running OpenFlight server
                                                # so it shows up in the real
                                                # UI (see --live-help)

Run with no arguments for an interactive loop that keeps prompting for
shots until you enter a blank line or "q".
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent
UPSTREAM_SRC = REPO_ROOT / "openflight_upstream" / "src"

sys.path.insert(0, str(REPO_ROOT))
if UPSTREAM_SRC.is_dir():
    sys.path.insert(0, str(UPSTREAM_SRC))
else:
    sys.exit(
        f"error: {UPSTREAM_SRC} not found.\n"
        "Clone the upstream OpenFlight project there first:\n"
        "  git clone https://github.com/jewbetcha/openflight.git openflight_upstream\n"
    )

from openflight_iwr6843.shot_fusion import infer_spin  # noqa: E402

from openflight.ballistics import resolve_launch, simulate  # noqa: E402
from openflight.launch_monitor import ClubType, Shot  # noqa: E402


@dataclass
class TypedShot:
    ball_speed_mph: float
    spin_rpm: float
    launch_angle_deg: float
    side_angle_deg: float
    side_spin_rpm: float
    club: ClubType


def spin_axis_deg(spin_rpm: float, side_spin_rpm: float) -> float:
    """Tilt of the spin axis implied by a side spin component, in
    ballistics.py's convention (0 = pure backspin, + = fade/slice axis,
    - = draw/hook axis). Total spin is the full vector magnitude; side
    spin is its component perpendicular to backspin, so it can't exceed
    the total (clamped rather than raising on a bad input)."""
    if spin_rpm <= 0:
        return 0.0
    ratio = max(-1.0, min(1.0, side_spin_rpm / spin_rpm))
    return math.degrees(math.asin(ratio))


def build_shot(typed: TypedShot) -> Shot:
    """Shape a typed-in shot exactly like a manually-entered shot from the
    live server's MockLaunchMonitor.simulate_shot(): full confidence, so
    resolve_launch() treats the spin as measured rather than falling back
    to a club-typical value."""
    return Shot(
        ball_speed_mph=typed.ball_speed_mph,
        timestamp=datetime.now(),
        club=typed.club,
        spin_rpm=typed.spin_rpm,
        spin_confidence=1.0,
        launch_angle_vertical=typed.launch_angle_deg,
        launch_angle_horizontal=typed.side_angle_deg,
        spin_axis_deg=spin_axis_deg(typed.spin_rpm, typed.side_spin_rpm),
        mode="manual",
    )


def ascii_trajectory(points, width: int = 60, height: int = 15) -> str:
    """Side-view ASCII plot: distance (yd) across, height (yd) up."""
    max_x = max(p.x for p in points) or 1.0
    max_z = max(p.z for p in points) or 1.0
    grid = [[" "] * width for _ in range(height)]
    for p in points:
        col = min(width - 1, int(p.x / max_x * (width - 1)))
        row = height - 1 - min(height - 1, int(p.z / max_z * (height - 1)))
        grid[row][col] = "*"
    ground = "-" * width
    lines = ["".join(row) for row in grid] + [ground]
    lines[0] = lines[0][:-6] + f"{max_z:5.0f}y"
    lines[-1] = ground[:-8] + f"0y -> {max_x:.0f}y"
    return "\n".join(lines)


def ascii_curve(points, width: int = 60, height: int = 11) -> str:
    """Top-down ASCII plot: distance (yd) across, lateral curve (yd) up/down.
    Only worth drawing when there's meaningful side spin/curve to see."""
    max_x = max(p.x for p in points) or 1.0
    max_y = max(abs(p.y) for p in points) or 1.0
    grid = [[" "] * width for _ in range(height)]
    mid = height // 2
    for c in range(width):
        grid[mid][c] = "-"
    for p in points:
        col = min(width - 1, int(p.x / max_x * (width - 1)))
        row = mid - round(p.y / max_y * mid)
        row = max(0, min(height - 1, row))
        grid[row][col] = "*"
    lines = ["".join(row) for row in grid]
    lines[0] = lines[0][:-13] + f"{max_y:5.0f}y right"
    lines[-1] = lines[-1][:-12] + f"{max_y:5.0f}y left"
    return "\n".join(lines)


def run_shot(typed: TypedShot) -> None:
    geom = {
        "ball_speed_mph": typed.ball_speed_mph,
        "launch_angle_deg": typed.launch_angle_deg,
    }
    fallback_spin = infer_spin(geom)

    shot = build_shot(typed)
    conditions = resolve_launch(shot)
    if conditions is None:
        print("error: resolve_launch() returned None (no launch angle?)")
        return
    traj = simulate(conditions)

    axis = conditions.spin_axis_deg
    curve = "draw/hook" if axis < -0.5 else "fade/slice" if axis > 0.5 else "straight"

    print()
    print(f"  ball speed     {typed.ball_speed_mph:6.1f} mph")
    print(f"  spin           {typed.spin_rpm:6.0f} rpm  "
          f"(our openflight_iwr6843 fallback model guesses "
          f"{fallback_spin:.0f} rpm from speed+angle alone)")
    print(f"  side spin      {typed.side_spin_rpm:+6.0f} rpm  "
          f"(spin axis {axis:+.1f} deg -> {curve})")
    print(f"  launch angle   {typed.launch_angle_deg:6.1f} deg")
    print(f"  side angle     {typed.side_angle_deg:6.1f} deg")
    print(f"  club           {typed.club.value}")
    print("  " + "-" * 40)
    print(f"  carry          {traj.carry_yards:6.1f} yd")
    print(f"  total (+roll)  {traj.total_yards:6.1f} yd")
    print(f"  apex           {traj.apex_yards:6.1f} yd")
    print(f"  lateral        {traj.lateral_yards:+6.1f} yd")
    print(f"  flight time    {traj.flight_time_s:6.2f} s")
    print(f"  landing speed  {traj.landing_speed_mph:6.1f} mph")
    print(f"  landing angle  {traj.landing_angle_deg:6.1f} deg")
    print()
    print(ascii_trajectory(traj.points))
    print()
    print(ascii_curve(traj.points))
    print()


def prompt_float(label: str, default: Optional[float] = None) -> Optional[float]:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{label}{suffix}: ").strip()
        if not raw:
            return default
        if raw.lower() in ("q", "quit", "exit"):
            raise SystemExit
        try:
            return float(raw)
        except ValueError:
            # A typo must not kill the whole interactive session (audit
            # T-10: any non-numeric input used to crash the loop).
            print(f"  '{raw}' isn't a number -- try again (or 'q' to quit)")


def interactive_loop(club: ClubType, live) -> None:
    print("OpenFlight plaintext shot simulator. Blank ball speed or 'q' to quit.\n")
    while True:
        try:
            ball_speed = prompt_float("ball speed (mph)")
            if ball_speed is None:
                break
            spin = prompt_float("spin (rpm)", default=2500.0)
            launch = prompt_float("launch angle (deg)", default=13.0)
            side = prompt_float("side angle (deg)", default=0.0)
            side_spin = prompt_float("side spin (rpm, + = fade/right, - = draw/left)", default=0.0)
        except (SystemExit, EOFError, KeyboardInterrupt):
            break
        typed = TypedShot(ball_speed, spin, launch, side, side_spin, club)
        run_shot(typed)
        if live is not None:
            live.send(typed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ball-speed", type=float, help="ball speed in mph")
    parser.add_argument("--spin", type=float, help="spin rate in rpm")
    parser.add_argument("--launch-angle", type=float, help="vertical launch angle in deg")
    parser.add_argument("--side-angle", type=float, default=0.0,
                         help="initial horizontal launch/aim direction in deg (push/pull)")
    parser.add_argument("--side-spin", type=float, default=0.0,
                         help="side spin in rpm, + = fade/slice (right), - = draw/hook (left); "
                              "drives the curve, separate from --side-angle")
    parser.add_argument("--club", default="driver", help="club type, e.g. driver, 7-iron, pw")
    parser.add_argument("--live", action="store_true",
                         help="also push the shot to a running OpenFlight server over "
                              "WebSocket so it shows up in the real GUI")
    parser.add_argument("--live-url", default="http://localhost:8080",
                         help="OpenFlight server URL for --live (default: %(default)s)")
    args = parser.parse_args()

    try:
        club = ClubType(args.club)
    except ValueError:
        sys.exit(f"error: unknown club '{args.club}'. See ClubType in launch_monitor.py.")

    live = None
    if args.live:
        from live_client import LiveClient  # noqa: E402  (local helper, see below)

        live = LiveClient(args.live_url)

    if args.ball_speed is not None:
        typed = TypedShot(args.ball_speed, args.spin or 2500.0,
                           args.launch_angle if args.launch_angle is not None else 13.0,
                           args.side_angle, args.side_spin, club)
        run_shot(typed)
        if live is not None:
            live.send(typed)
    else:
        interactive_loop(club, live)


if __name__ == "__main__":
    main()
