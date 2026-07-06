"""
geometry_capture_simulator.py — synthesize IWR6843 point-cloud captures for
a full swing (arcing club + ballistic ball) and run them through
IWR6843Source.analyze(), verifying the track-based club/ball classifier
(audit F-7) and the whole geometry chain (F-1 frame timing, tilt correction,
alias-aware confidence) without hardware.

This is the geometry-channel counterpart of spin_capture_simulator.py.

The club is the hard part and the whole point: it's modeled as a clubhead on
a swing-arc circle (radius ~1.15 m around the hands), sweeping through the
hitting zone at realistic speed with post-impact angular decay — so its
radar track genuinely loiters near the tee and stalls/reverses in range,
exactly the signature the classifier keys on. A lazy straight-line "club"
would make this test meaningless.

Physics conventions match analyze(): sensor 2 m behind the tee on the
target line, MOUNT_TILT_DEG pitched up, points synthesized in the SENSOR
frame with Doppler folded into +/-v_max_ext exactly like the radar folds it.

Since audit V-7 every capture goes through a HOSTILE observation model by
default -- anisotropic noise (elevation coarsest, range-scaled), range and
Doppler bin quantization, wrong-hypothesis velocity extension, static
clutter, a swaying golfer, CFAR false alarms, club/ball merging at impact,
and bursty frame loss (see synth_capture). Assertion tolerances are the
measured 20-seed envelopes of that world, and the per-element knobs
(body_p/merge_p/falarm_p, module-level SIGMA_* constants) exist so a
regression can be ablated back to its cause.

Scenarios (all assertions must pass; exit code 1 otherwise):
    driver          165 mph ball / 110 mph club — fast ball aliases Doppler
    seven_iron      120 mph ball, 19 deg launch
    wedge_chip      18 mph ball — bottom of the speed range, where the old
                    speed-band classifier was weakest
    bump_and_run    20 mph ball at 6 deg — flat AND slow, the geometric
                    worst case; exercises the launch>=0 physical floor and
                    its confidence penalty on every noise seed
    practice_swing_80  slow club only, NO ball -> None (audit M-3: slow
                    swings linger at arc bottom where range-rate is
                    ball-flat; the rate-consistency gate + fill floor
                    own this regime)
    practice_swing  club only, NO ball -> analyze() must return None (the
                    old code could fabricate a phantom shot from club points)

Usage:
    python3 geometry_capture_simulator.py            # run all scenarios
    python3 geometry_capture_simulator.py --verbose  # per-scenario detail
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from openflight_iwr6843.iwr6843_source import Frame, IWR6843Source  # noqa: E402

MPH_TO_MPS = 0.44704
FRAME_PERIOD = 0.0022       # golf.cfg frameCfg: 2.2 ms (the 50%-duty floor
                            # for 48 chirps x 22 us -- audit V-4)
FRAME_HZ = 1.0 / FRAME_PERIOD
TILT_DEG = IWR6843Source.MOUNT_TILT_DEG
V_MAX_EXT = 37.85           # golf.cfg's extended unambiguous velocity, m/s:
                            # lambda/(4*3*22us) x2 for the 3-TX profile
                            # (audit V-1/V-3). A 165 mph ball folds to
                            # ~1.9 m/s and a 110 mph clubhead to ~26.7 --
                            # the driver scenario now exercises both the
                            # no-Doppler-prefilter rule and the club-speed
                            # unfold for real.
V_MAX_NATIVE = V_MAX_EXT / 2.0
DOPPLER_BIN = 2.0 * V_MAX_NATIVE / 16.0   # 16 Doppler bins (frameCfg loops)
RANGE_BIN = 0.0476                        # golf.cfg range resolution, m

# Measurement-noise model (audit V-7): the radar does NOT have isotropic
# position noise. Range is bin-quantized but precise; azimuth comes from
# the 8-element virtual row (fine); elevation comes from ONE lambda/2
# offset row (TX2) -- the coarsest axis by far, and its position error
# grows linearly with range. Placeholder sigmas from array geometry
# (bench rung 5 owns the real numbers): 0.7 deg azimuth, 1.7 deg
# elevation, 2.5 cm range jitter on top of the bin quantization.
SIGMA_AZ = math.radians(0.7)
SIGMA_EL = math.radians(1.7)
SIGMA_R = 0.025

TEE_WORLD = np.array([0.0, 2.0, 0.10])      # sensor at origin, 2 m back
HANDS_WORLD = np.array([0.0, 2.0, 1.25])    # arc center: golfer's hands
ARC_R = 1.15                                 # clubhead arc radius, m


def world_to_sensor(p_world: np.ndarray) -> np.ndarray:
    """Rotate a world-frame vector into the tilted sensor frame (inverse of
    the sensor->world rotation analyze() applies)."""
    tr = math.radians(TILT_DEG)
    c, s = math.cos(tr), math.sin(tr)
    x, y, z = p_world
    return np.array([x, y * c + z * s, -y * s + z * c])


def fold(v: float) -> float:
    """Fold a radial velocity into +/-V_MAX_EXT like the radar does."""
    m = V_MAX_EXT
    return (v + m) % (2.0 * m) - m


def observe(p_sensor: np.ndarray, v_radial: float, rng,
            wrong_hyp_p: float = 0.02):
    """One point through the REAL observation model (audit V-7):
    spherical-coordinate noise (elevation coarsest, range-scaled), range
    bin quantization, then Doppler exactly as the demo produces it --
    folded at NATIVE v_max, quantized to the 16-bin grid, then extended
    x2 by the disambiguation hypothesis, which is occasionally WRONG
    (the SDK UG's own caveat: unreliable when two objects share a range
    bin close in azimuth -- callers raise wrong_hyp_p near impact).
    Returns (position, doppler) or None if the point left the FoV/gate
    after noise."""
    r = float(np.linalg.norm(p_sensor))
    az = math.atan2(p_sensor[0], p_sensor[1])
    el = math.asin(p_sensor[2] / r)
    r_n = round((r + rng.normal(0, SIGMA_R)) / RANGE_BIN) * RANGE_BIN
    az_n = az + rng.normal(0, SIGMA_AZ)
    el_n = el + rng.normal(0, SIGMA_EL)
    p = np.array([r_n * math.cos(el_n) * math.sin(az_n),
                  r_n * math.cos(el_n) * math.cos(az_n),
                  r_n * math.sin(el_n)])
    if not (0.3 < r_n < 6.0 and in_fov(p)):
        return None
    m = V_MAX_NATIVE
    v_native = (v_radial + m) % (2.0 * m) - m
    v_q = round(v_native / DOPPLER_BIN) * DOPPLER_BIN
    v_ext = fold(v_radial)
    # Rebuild the extended label from the quantized native reading using
    # the (possibly wrong) hypothesis branch.
    branch = round((v_ext - v_native) / (2.0 * m))
    if rng.uniform() < wrong_hyp_p:
        branch = branch + (1 if rng.uniform() < 0.5 else -1)
    v_out = v_q + branch * 2.0 * m
    if v_out >= V_MAX_EXT:
        v_out -= 2.0 * V_MAX_EXT
    elif v_out < -V_MAX_EXT:
        v_out += 2.0 * V_MAX_EXT
    return p, float(v_out)


def club_state(tau: float, club_mps: float) -> tuple[np.ndarray, np.ndarray]:
    """Clubhead world position/velocity at time tau relative to impact.
    Circular arc around HANDS_WORLD in the y-z plane; exponentially
    ACCELERATING angular speed into impact (downswing), exponential decay
    after (follow-through). theta=0 at impact (arc bottom)."""
    w0 = club_mps / ARC_R
    if tau <= 0:
        k = 8.0                              # downswing ramp, 1/s
        theta = -(w0 / k) * (1.0 - math.exp(k * tau))
        w = w0 * math.exp(k * tau)
    else:
        k = 6.0                              # follow-through decay, 1/s
        theta = (w0 / k) * (1.0 - math.exp(-k * tau))
        w = w0 * math.exp(-k * tau)
    pos = HANDS_WORLD + ARC_R * np.array([0.0, math.sin(theta),
                                          -math.cos(theta)])
    vel = ARC_R * w * np.array([0.0, math.cos(theta), math.sin(theta)])
    return pos, vel


def in_fov(p_sensor: np.ndarray) -> bool:
    """The aoaFovCfg gate the real firmware applies (golf.cfg: azimuth
    +/-60 deg, elevation -20/+40 deg, sensor frame). Without this the
    simulated clubhead would be 'visible' high in the swing arc where the
    real radar cannot see it -- unphysical tracks the classifier should
    never be asked to handle."""
    x, y, z = p_sensor
    horiz = math.hypot(x, y)
    az = math.degrees(math.atan2(x, y))
    el = math.degrees(math.atan2(z, horiz))
    return abs(az) <= 60.0 and -20.0 <= el <= 40.0


def ball_state(tau: float, ball_mps: float, launch_deg: float,
               side_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Ball world position/velocity at time tau since impact (drag-free
    ballistics is plenty over <=0.25 s)."""
    la, sa = math.radians(launch_deg), math.radians(side_deg)
    horiz = ball_mps * math.cos(la)
    v0 = np.array([horiz * math.sin(sa), horiz * math.cos(sa),
                   ball_mps * math.sin(la)])
    g = np.array([0.0, 0.0, -9.81])
    return TEE_WORLD + v0 * tau + 0.5 * g * tau**2, v0 + g * tau


def synth_capture(ball_mph: float | None, club_mph: float,
                  launch_deg: float = 13.0, side_deg: float = 0.0,
                  seed: int = 0,
                  t_impact: float = 0.15, t_end: float = 0.35,
                  body_p: float = 0.9, merge_p: float = 0.7,
                  falarm_p: float = 0.12) -> list:
    """Build a Frame list like frames() would deliver — through the FULL
    hostile observation model (audit V-7), all of it on by default:

      - spherical noise, elevation coarsest and range-scaled (observe())
      - range-bin + Doppler-bin quantization, native fold, x2 extension
        with occasional wrong hypothesis (raised near impact, where club
        and ball share a range bin — the SDK UG's own caveat)
      - two static clutter reflectors (bay wall, tee box)
      - the GOLFER: a big slow-swaying body track with a downswing lateral
        surge — a loitering, moving, always-visible object the classifier
        must never call a ball
      - CFAR false alarms: random position, random Doppler, ~12% of frames
      - club/ball MERGE at impact: while the two are within a range bin,
        the detector usually reports only the club (bigger RCS)
      - dropped frames (5%) plus one multi-frame UART burst gap
      - USB-chunked host timestamps (frame numbers are the clock, F-1)
    """
    rng = np.random.default_rng(seed)
    club_mps = club_mph * MPH_TO_MPS
    frames = []
    n_frames = int(t_end * FRAME_HZ)
    statics = [np.array([0.6, 5.2, -0.1]), np.array([-0.9, 2.3, -0.25])]
    # Golfer's torso: ~0.85 m toward the golfer side of the target line,
    # centered near hip height. Sways at ~1.2 Hz; the downswing adds a
    # brief lateral weight-shift surge peaking at impact.
    body_base = np.array([0.85, 2.05, 0.95])
    gap_start = rng.integers(int(0.05 * n_frames), int(0.8 * n_frames))
    gap_len = int(rng.integers(4, 9))         # one UART throttle burst
    for k in range(n_frames):
        if rng.uniform() < 0.05 or gap_start <= k < gap_start + gap_len:
            continue
        t_true = k * FRAME_PERIOD
        pts = []
        ball_obs = club_obs = None
        for sp in statics:
            if rng.uniform() > 0.3:           # statics flicker too (CFAR)
                ob = observe(sp, rng.normal(0.0, 0.05), rng)
                if ob:
                    pts.append([*ob[0], ob[1]])
        # -- golfer body: always in view, never ballistic
        if rng.uniform() < body_p:
            tau = t_true - t_impact
            sway = np.array([0.06 * math.sin(2 * math.pi * 1.2 * t_true),
                             0.04 * math.sin(2 * math.pi * 1.2 * t_true + 1.1),
                             0.02 * math.sin(2 * math.pi * 0.6 * t_true)])
            surge_v = 1.2 * math.exp(-((tau + 0.03) / 0.09) ** 2)
            surge = np.array([-surge_v * 0.09, 0.0, 0.0])
            bpos = world_to_sensor(body_base + sway + surge)
            bvel = world_to_sensor(
                np.array([0.06 * 2 * math.pi * 1.2 *
                          math.cos(2 * math.pi * 1.2 * t_true) - surge_v,
                          0.04 * 2 * math.pi * 1.2 *
                          math.cos(2 * math.pi * 1.2 * t_true + 1.1), 0.0]))
            r = np.linalg.norm(bpos)
            ob = observe(bpos, float(bvel @ (bpos / r)), rng)
            if ob:
                pts.append([*ob[0], ob[1]])
        # -- club point (visible pre-impact and through follow-through)
        if rng.uniform() > 0.15:              # RCS flicker
            cp_w, cv_w = club_state(t_true - t_impact, club_mps)
            cp = world_to_sensor(cp_w)
            cv = world_to_sensor(cv_w)
            r = np.linalg.norm(cp)
            if r > 1e-6:
                club_obs = observe(cp, float(cv @ (cp / r)), rng,
                                   wrong_hyp_p=0.02)
        # -- ball point (exists only after impact)
        if ball_mph is not None and t_true >= t_impact + FRAME_PERIOD:
            bp_w, bv_w = ball_state(t_true - t_impact, ball_mph * MPH_TO_MPS,
                                    launch_deg, side_deg)
            bp = world_to_sensor(bp_w)
            bv = world_to_sensor(bv_w)
            r = np.linalg.norm(bp)
            # Near impact club and ball share a range bin: wrong-hypothesis
            # risk up (SDK UG caveat), and usually only ONE detection
            # survives — the club's (bigger RCS).
            near = (club_obs is not None and
                    abs(np.linalg.norm(cp) - r) < 2 * RANGE_BIN)
            ob = observe(bp, float(bv @ (bp / r)), rng,
                         wrong_hyp_p=0.4 if near else 0.02)
            if ob and near and rng.uniform() < merge_p:
                ob = None                     # merged into the club return
            ball_obs = ob
        if club_obs:
            pts.append([*club_obs[0], club_obs[1]])
        if ball_obs:
            pts.append([*ball_obs[0], ball_obs[1]])
        # -- CFAR false alarm: anywhere in the gate, any Doppler
        if rng.uniform() < falarm_p:
            fr = rng.uniform(0.5, 6.0)
            faz = math.radians(rng.uniform(-50, 50))
            fel = math.radians(rng.uniform(-15, 35))
            pts.append([fr * math.cos(fel) * math.sin(faz),
                        fr * math.cos(fel) * math.cos(faz),
                        fr * math.sin(fel),
                        rng.uniform(-V_MAX_EXT, V_MAX_EXT)])
        points = np.array(pts) if pts else np.zeros((0, 4))
        # Host stamps arrive in bursts of 4 frames (USB chunking) + jitter;
        # frame numbers are the clean clock (F-1).
        t_host = 500.0 + (k // 4) * 4 * FRAME_PERIOD + rng.uniform(0, 0.004)
        frames.append(Frame(t=t_host, points=points, num=7000 + k))
    return frames


def make_source() -> IWR6843Source:
    """Bare IWR6843Source for offline analyze() — no serial ports."""
    src = object.__new__(IWR6843Source)
    src.frame_period = FRAME_PERIOD
    src.v_max_ext = V_MAX_EXT
    src.range_gate = (0.3, 6.0)
    src.capture_window = 0.20
    src.session = None
    return src


# Assertion classes -- what each scenario is entitled to expect:
#   full  : full swing, well-separated -- speed, angles, club all asserted
#   chip  : sub-separability speeds but lofted (z separates club/ball) --
#           speed asserted tight, angles informational, club loose-or-None
#   floor : flat AND slow (bump-and-run) -- club and ball hug in EVERY
#           axis, the geometric worst case. Assert the launch>=0 physical
#           invariant, speed in the ballpark (25%), and that a flat shot
#           is never reported LOFTED (launch within +8 deg of truth --
#           catches tail-fragment fits masquerading as real shots).
#           HISTORY: this class used to assert geometry_confidence <= 0.6
#           ("the pipeline must know it's blended") because raw launch
#           fits ran ~10 deg low here on every seed -- audit V-3 found
#           most of that was a gravity back-extrapolation SIGN BUG, not
#           club blend; with it fixed the floor class fits accurately and
#           confidently, and the old ceiling assertion became wrong.
SCENARIOS = [
    # name,            ball_mph, club_mph, launch, side,  class
    ("driver",          165.0,    110.0,    13.0,   2.0,  "full"),
    ("seven_iron",      120.0,     85.0,    19.0,  -1.5,  "full"),
    ("wedge_chip",       18.0,     16.0,    22.0,   0.0,  "chip"),
    # bump-and-run: true launch 6 deg at chip speed -- flat AND slow, the
    # worst separability case; also the scenario whose apex passes inside
    # the capture window (guards the z-kink trim against trimming at the
    # global minimum, audit V-3).
    ("bump_and_run",     20.0,     18.0,     6.0,   0.0,  "floor"),
    ("practice_swing",   None,    105.0,     0.0,   0.0,  "none"),
    # Slow practice swing (audit M-3): a slower swing lingers longer at
    # arc bottom, where its range-rate is genuinely ball-flat -- the V-7
    # fences were sized at 105 mph and 80/70 mph swings slipped phantom
    # "shots" through analyze() (67 mph @ conf 0.58, 63 mph @ 0.87) until
    # the rate-consistency gate + 0.6 fill floor landed.
    ("practice_swing_80", None,     80.0,     0.0,   0.0,  "none"),
]


def run(verbose: bool = False) -> bool:
    src = make_source()
    ok_all = True
    print(f"{'scenario':>15} {'ball(true/meas)':>18} {'launch':>13} "
          f"{'side':>12} {'club(true/meas)':>18}  result")
    for name, ball, club, launch, side, cls in SCENARIOS:
        geom = src.analyze(synth_capture(ball, club, launch, side))
        if ball is None:
            ok = geom is None
            print(f"{name:>15} {'—':>18} {'—':>13} {'—':>12} "
                  f"{f'{club:.0f}/—':>18}  "
                  f"{'PASS (no phantom shot)' if ok else 'FAIL: phantom shot ' + str(geom)}")
            ok_all &= ok
            continue
        if geom is None:
            print(f"{name:>15}  FAIL: analyze() returned None")
            ok_all = False
            continue
        # Physical invariant (Johnny's rule), every scenario: a golf ball
        # leaves the ground -- reported launch can NEVER be negative.
        if geom["launch_angle_deg"] < 0:
            print(f"{name:>15}  FAIL: negative launch {geom['launch_angle_deg']}")
            ok_all = False
            continue
        sp_err = abs(geom["ball_speed_mph"] - ball)
        la_err = abs(geom["launch_angle_deg"] - launch)
        sa_err = abs(geom["side_angle_deg"] - side)
        cl = geom["club_speed_mph"]
        # Club read under full dirt: quantized Doppler + the track-slope
        # unfold occasionally misses a branch or loses the pre-birth rows
        # to merge/flicker -- None or a 15% read is honest here (the
        # fine-elevation ablation recovers clean club numbers, so this is
        # a dirt envelope, not an estimator defect).
        if ball < 30:
            cl_ok = cl is None or abs(cl - club) / club < 0.25
        else:
            cl_ok = cl is None or abs(cl - club) / club < 0.15
        # Tolerances are the measured 20-seed HOSTILE-WORLD envelopes
        # (audit V-7), not aspirations: launch scatter is elevation-noise
        # limited (single TX2 row; the fine-elevation ablation collapses
        # full-class launch error to ±0.5 deg), so the honest tolerance at
        # SIGMA_EL=1.7 deg is 6 deg for full swings. Chip-class angles are
        # asserted LOOSELY (worst 13.6 deg): club and ball separate at
        # ~1 m/s and their detections interleave within position noise --
        # the physical separability floor (F-7), now quantified under
        # honest noise instead of estimated. Bench rung 5 owns the real
        # sigma_el; retune these when it lands.
        if ball < 30:
            ok = sp_err < max(0.06 * ball, 2.2) and la_err < 16.0 and cl_ok
        else:
            ok = sp_err < max(0.04 * ball, 1.5) and la_err < 6.0 \
                and sa_err < 2.5 and cl_ok
        ok_all &= ok
        col_ball = f"{ball:.0f}/{geom['ball_speed_mph']:.1f}"
        col_la = f"{launch:.0f}/{geom['launch_angle_deg']:.1f}"
        col_sa = f"{side:+.1f}/{geom['side_angle_deg']:+.1f}"
        col_cl = f"{club:.0f}/{cl:.1f}" if cl else f"{club:.0f}/None"
        print(f"{name:>15} {col_ball:>18} {col_la:>13} {col_sa:>12} "
              f"{col_cl:>18}  {'PASS' if ok else 'FAIL'}")
        if verbose:
            print(f"{'':>15}   full: {geom}")
    ok_all &= speed_training_run(verbose)
    return ok_all


# Speed-training mode: analyze_swing() reads peak club-head speed from the
# SAME ball-less hostile captures the phantom-shot guard uses (swing-arc
# club through the full V-7 dirt model, no ball). Truth = the arc-bottom
# speed the synthesizer was told to produce.
SWING_SPEEDS = [80.0, 95.0, 105.0, 120.0]
# Measured tolerances, not aspirations (same policy as the shot envelopes,
# 20-seed hostile characterization): ~90% of swings measure within 2.2 mph;
# fold-regime unfolds (>= ~90 mph vs v_max_ext 37.9 m/s) carry Doppler-bin
# noise up to +/-5.5 mph; and inside the fold-shoulder band itself the
# KNOWN fold limit applies (see analyze_swing: a folded bottom and a
# just-under-v_max bottom are observationally identical there) with
# measured worst cases -10.3/+10.0 mph -- but the estimator self-flags
# that band via speed_fold_ambiguous. So: within 6 mph, OR self-flagged
# and within 12.
SWING_TOL_MPH = 6.0
SWING_AMBIG_TOL_MPH = 12.0


def _swing_ok(g, club: float) -> bool:
    if g is None:
        return False
    err = abs(g["club_speed_mph"] - club)
    if err < SWING_TOL_MPH:
        return True
    return bool(g.get("speed_fold_ambiguous")) and err < SWING_AMBIG_TOL_MPH


def speed_training_run(verbose: bool = False) -> bool:
    src = make_source()
    ok_all = True
    print(f"\n{'swing(true)':>15} {'measured':>10}  result   (speed-training "
          f"mode: analyze_swing)")
    for club in SWING_SPEEDS:
        g = src.analyze_swing(synth_capture(None, club, 0.0, 0.0))
        if g is None:
            print(f"{club:>15.0f} {'None':>10}  FAIL: missed swing")
            ok_all = False
            continue
        # Structural contract: a swing record must be recognizable as one
        # downstream (fuser branch, GSPro skip, UI card) without inference.
        if not (g.get("swing") is True and g.get("ball_speed_mph") == 0.0):
            print(f"{club:>15.0f}  FAIL: malformed swing record {g}")
            ok_all = False
            continue
        err = g["club_speed_mph"] - club
        ok = _swing_ok(g, club)
        ok_all &= ok
        tag = " (fold-ambiguous)" if g.get("speed_fold_ambiguous") else ""
        print(f"{club:>15.0f} {g['club_speed_mph']:>10.1f}  "
              f"{'PASS' + tag if ok else f'FAIL ({err:+.1f} mph)'}")
        if verbose:
            print(f"{'':>15}   full: {g}")
    # Floor: a waggle-speed sweep (below the 17 mph trigger threshold) must
    # never publish as a swing, mirroring E-8's "no phantom shots" posture.
    g = src.analyze_swing(synth_capture(None, 10.0, 0.0, 0.0))
    ok = g is None
    ok_all &= ok
    print(f"{'10 (waggle)':>15} {'—':>10}  "
          f"{'PASS (no phantom swing)' if ok else 'FAIL: published ' + str(g)}")
    # Ball strike in speed mode (audit M-1): NOT a rep -- must be rejected,
    # never published as a swing (a 120 mph ball once became a 116 mph
    # "swing"; a fragmented 18 mph chip once unfolded to 84.7).
    for bname, ball, club, launch in [("iron ball", 120.0, 85.0, 19.0),
                                      ("chip ball", 18.0, 16.0, 22.0)]:
        g = src.analyze_swing(synth_capture(ball, club, launch, 0.0))
        ok = g is None
        ok_all &= ok
        print(f"{bname:>15} {'—':>10}  "
              f"{'PASS (rep ignored)' if ok else 'FAIL: published ' + str(g)}")
    return ok_all


def sweep(n_seeds: int = 6) -> bool:
    """Robustness across noise seeds: never a phantom shot, never a missed
    real shot, speed always in tolerance; angles asserted for full swings
    only (chip angles are blend-limited, see run())."""
    src = make_source()
    fails = 0
    for seed in range(n_seeds):
        for name, ball, club, launch, side, cls in SCENARIOS:
            g = src.analyze(synth_capture(ball, club, launch, side, seed=seed))
            if ball is None:
                ok = g is None
            elif g is None:
                ok = False                       # missed a real shot
            else:
                ok = g["launch_angle_deg"] >= 0         # physical invariant
                if cls == "floor":
                    ok &= abs(g["ball_speed_mph"] - ball) < max(0.25 * ball, 2.0)
                    # A flat shot must never be reported lofted: catches
                    # tail-fragment/blend fits posing as clean shots.
                    ok &= g["launch_angle_deg"] < launch + 8.0
                elif cls == "chip":
                    ok &= abs(g["ball_speed_mph"] - ball) < max(0.06 * ball, 2.2)
                else:
                    ok &= abs(g["ball_speed_mph"] - ball) < max(0.04 * ball, 1.5)
                if cls == "full":
                    # Hostile-world envelopes (see run()): elevation noise
                    # owns launch scatter.
                    ok &= abs(g["launch_angle_deg"] - launch) < 6.0
                    ok &= abs(g["side_angle_deg"] - side) < 2.5
            if not ok:
                fails += 1
                print(f"  FAIL seed {seed} {name}: {g}")
        # Speed-training mode across the same seeds: every swing measured
        # in tolerance, waggle never published.
        for club in SWING_SPEEDS:
            g = src.analyze_swing(synth_capture(None, club, 0.0, 0.0,
                                                seed=seed))
            if not _swing_ok(g, club):
                fails += 1
                print(f"  FAIL seed {seed} swing {club:.0f} mph: {g}")
        if src.analyze_swing(synth_capture(None, 10.0, 0.0, 0.0,
                                           seed=seed)) is not None:
            fails += 1
            print(f"  FAIL seed {seed}: waggle published as swing")
        # Ball strikes in speed mode rejected on every seed (audit M-1).
        for ball, club, launch in [(120.0, 85.0, 19.0), (18.0, 16.0, 22.0)]:
            if src.analyze_swing(synth_capture(ball, club, launch, 0.0,
                                               seed=seed)) is not None:
                fails += 1
                print(f"  FAIL seed {seed}: ball ({ball} mph) published "
                      f"as swing")
    print(f"[sweep] {n_seeds} seeds x {len(SCENARIOS)} scenarios "
          f"+ {len(SWING_SPEEDS) + 3} swing checks: {fails} failures")
    return fails == 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--sweep", action="store_true",
                    help="run all scenarios across multiple noise seeds")
    args = ap.parse_args()
    if args.sweep:
        sys.exit(0 if sweep() else 1)
    sys.exit(0 if run(args.verbose) else 1)
