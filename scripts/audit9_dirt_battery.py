#!/usr/bin/env python3
"""Audit #9 (T-series) dirt battery — LM-2 acquisition side.

Graduated from the audit-#9 scratchpad into the standing verification
loop (see HANDOFF §3): every probe here caught, or fences, a real
finding — T-4 (cfg-parser crash), T-5 (stale-ring ghost spin), T-6
(tiny-window decode crash), T-7 (NaN at the GSPro/jsonl boundaries) —
plus the verified-good dirt paths (NaN/Inf through _parse/analyze,
corrupt archives, garbage fuser dicts).

Each probe prints PASS/FINDING with evidence and the battery exits
nonzero if anything is not PASS. No probe may crash the battery itself;
unexpected exceptions are findings by definition.

Run from anywhere: python3 scripts/audit9_dirt_battery.py
"""
import json
import math
import struct
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflight_iwr6843.iwr6843_source import (Frame, IWR6843Source,
                                               MAGIC_WORD, load_capture)
from openflight_iwr6843.shot_fusion import AudioRing, ShotFuser, infer_spin
from openflight_iwr6843.spin_decoder import decode, clean_iq
from openflight_iwr6843.gspro_adapter import GSProClient
from openflight_iwr6843.session import from_selector

RESULTS = []


def probe(name):
    def deco(fn):
        def run():
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                RESULTS.append((name, f"FINDING (unexpected {type(e).__name__}: {e})"))
                return
        RESULTS.append((name, "registered"))
        return run
    return deco


def report(name, ok, detail=""):
    RESULTS.append((name, ("PASS " if ok else "FINDING ") + detail))


def make_source(frame_period=0.0022, v_max=37.9, gate=(0.3, 6.0)):
    src = object.__new__(IWR6843Source)
    src.frame_period = frame_period
    src.v_max_ext = v_max
    src.range_gate = gate
    src.capture_window = 0.20
    src.session = None
    return src


# ---------- P1: cfg-parser exception asymmetry ----------
def p1():
    import tempfile, os
    bad = "frameCfg 0 2 16 0 abc 1 0\nprofileCfg 0 60 7 x 22 0 0 197 1 256 8000 0 0 30\n"
    with tempfile.NamedTemporaryFile("w", suffix=".cfg", delete=False) as f:
        f.write(bad)
        path = f.name
    try:
        try:
            v = IWR6843Source._parse_vmax_ext(path)
            vm_ok = True
        except Exception as e:
            vm_ok = False
            v = e
        try:
            p = IWR6843Source._parse_frame_period(path)
            fp_ok = True
        except Exception as e:
            fp_ok = False
            p = e
        report("P1 corrupt-cfg parser asymmetry",
               vm_ok and fp_ok,
               f"(vmax_ext {'fell back' if vm_ok else 'CRASHED'}: {v}; "
               f"frame_period {'fell back' if fp_ok else 'CRASHED'}: {p})")
    finally:
        os.unlink(path)


# ---------- P2: NaN/Inf Doppler rows through analyze() ----------
def synth_ball_capture(src, nan_mode=None, n_frames=90):
    """Minimal clean driver-ish ball + optional NaN/Inf poisoning."""
    frames = []
    fp = src.frame_period
    v = 60.0  # m/s radial-ish
    for i in range(n_frames):
        t = i * fp
        pts = []
        r0 = 2.0 + v * t
        if r0 < 5.9:
            # ball point: y downrange, slight climb
            y = r0 * math.cos(math.radians(13))
            z = r0 * math.sin(math.radians(13)) - y * math.tan(math.radians(10))
            dop = 22.0  # folded label, arbitrary in-band
            if nan_mode == "doppler" and i % 7 == 3:
                dop = float("nan")
            if nan_mode == "inf_doppler" and i % 11 == 5:
                dop = float("inf")
            pts.append((0.02, y, z, dop))
            if nan_mode == "position" and i % 9 == 4:
                pts.append((float("nan"), y + 0.05, z, 8.0))
        arr = np.array(pts, dtype=np.float64).reshape(-1, 4)
        frames.append(Frame(t=100.0 + t, points=arr, snr=None, num=1000 + i))
    return frames


def p2():
    for mode in (None, "doppler", "inf_doppler", "position"):
        src = make_source()
        try:
            out = src.analyze(synth_ball_capture(src, mode))
        except Exception as e:  # noqa: BLE001
            report(f"P2 analyze survives nan_mode={mode}", False,
                   f"(raised {type(e).__name__}: {e})")
            continue
        bad = []
        if out is not None:
            for k, val in out.items():
                if isinstance(val, float) and not math.isfinite(val):
                    bad.append(k)
        report(f"P2 analyze survives nan_mode={mode}", not bad,
               f"(out={'None' if out is None else {k: out[k] for k in ('ball_speed_mph','launch_angle_deg')}}"
               f"{' NON-FINITE: ' + str(bad) if bad else ''})")


# ---------- P3: TLV frame carrying NaN bytes through _parse ----------
def tlv_frame(points, frame_num=7):
    n = len(points)
    body = b"".join(struct.pack("<4f", *p) for p in points)
    tlv = struct.pack("<2I", 1, len(body)) + body
    payload_len = 8 + 32 + len(tlv)
    hdr = struct.pack("<8I", 0x0102, payload_len, 0x36, frame_num, 0, n, 1, 0)
    return MAGIC_WORD + hdr + tlv


def p3():
    src = make_source()
    raw = tlv_frame([(0.1, 3.0, 0.3, float("nan")),
                     (float("inf"), 2.0, 0.1, 9.0),
                     (0.05, 2.5, 0.2, 12.0)])
    hdr = struct.unpack_from("<8I", raw, 8)
    f = src._parse(raw, hdr)
    ok = f is not None and f.points.shape[0] >= 1
    finite_xyz = f is not None and np.isfinite(f.points[:, :3]).all()
    report("P3 _parse with NaN/Inf floats", ok and finite_xyz,
           f"(kept {0 if f is None else f.points.shape[0]} pts, "
           f"xyz finite={finite_xyz}; NaN-doppler row kept="
           f"{bool(f is not None and not np.isfinite(f.points[:, 3]).all())})")


# ---------- P4: AudioRing dead-stream stale window ----------
def p4():
    ring = AudioRing(seconds=2.0)
    # paint a strong fake carrier into the whole ring (an old shot's tone)
    t = np.arange(ring.n) / ring.fs
    tone = 0.4 * np.cos(2 * np.pi * 5000 * t)
    ring.buf[:, 0] = tone.astype(np.float32)
    ring.buf[:, 1] = (0.4 * np.sin(2 * np.pi * 5000 * t)).astype(np.float32)
    ring.write = ring.n // 2
    ring.t_last = time.monotonic() - 30.0     # stream died 30 s ago
    t_impact = time.monotonic()               # radar triggers NOW
    z = ring.window(t_impact, 0.01, 0.15)
    r = decode(z)
    report("P4 dead audio stream -> stale-window spin", not r.get("ok"),
           f"(decode on 30s-stale ring: ok={r.get('ok')}, "
           f"spin={r.get('spin_rpm')}, conf={r.get('confidence')}) "
           "— a dead stream must not produce a confident 'measured' spin from old audio")


# ---------- P5: decode on pathological windows ----------
def p5():
    cases = {
        "len8": np.zeros(8, dtype=complex),
        "len0": np.zeros(0, dtype=complex),
        "nan": np.full(4096, np.nan, dtype=complex),
        "inf": np.full(4096, np.inf, dtype=complex),
    }
    for name, z in cases.items():
        try:
            r = decode(z)
            conf = r.get("confidence", 0)
            sus = r.get("ok") and (conf or 0) > 0
            report(f"P5 decode({name})", not sus, f"(-> {r})")
        except Exception as e:  # noqa: BLE001
            report(f"P5 decode({name})", False, f"(raised {type(e).__name__}: {e})")


# ---------- P6: GSPro adapter with NaN fields ----------
def p6():
    c = GSProClient(host="127.0.0.1")
    sent = {}
    c._send = lambda msg, expect_reply=True: sent.update(msg) or {"Code": 200}
    shot = {"ball_speed_mph": float("nan"), "launch_angle_deg": 13.0,
            "side_angle_deg": 1.0, "spin_rpm": 2600}
    c.send_shot(shot)
    try:
        payload = json.dumps(sent)
        strict_ok = True
        try:
            json.loads(payload, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        except ValueError:
            strict_ok = False
        report("P6 GSPro NaN passthrough", strict_ok,
               f"(payload BallData={sent.get('BallData')}; strict-JSON parseable={strict_ok})")
    except ValueError:
        report("P6 GSPro NaN passthrough", False, "(json.dumps refused)")


# ---------- P7: fuser with garbage geometry dicts ----------
def p7():
    published = []
    fuser = ShotFuser(publish=published.append, audio=None)
    dirt = [
        {"swing": True},                                   # minimal swing
        {"t_impact": 1.0, "ball_speed_mph": 50.0},         # missing most keys
        {"t_impact": 1.0, "ball_speed_mph": None,
         "launch_angle_deg": None},                        # Nones
    ]
    for d in dirt:
        try:
            fuser.on_geometry(dict(d))
        except Exception as e:  # noqa: BLE001
            report("P7 fuser garbage-geometry", False,
                   f"(dict {d} raised {type(e).__name__}: {e})")
            return
    report("P7 fuser garbage-geometry", True,
           f"({len(published)} published without crash)")


# ---------- P8: load_capture with corrupt archive ----------
def p8():
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
        path = f.name
    np.savez_compressed(path,
                        t=np.array([1.0, 2.0]),
                        num=np.array([5, 6]),
                        n_points=np.array([3, 2]),          # claims 5 points
                        points=np.zeros((2, 4)),            # only has 2
                        snr=np.zeros(2))
    try:
        frames = load_capture(path)
        shapes = [f.points.shape[0] for f in frames]
        src = make_source()
        out = src.analyze(frames)
        report("P8 corrupt archive round-trip", True,
               f"(frame point counts {shapes} vs claimed [3,2]; analyze -> {out})")
    except Exception as e:  # noqa: BLE001
        report("P8 corrupt archive round-trip", False,
               f"(raised {type(e).__name__}: {e})")
    finally:
        os.unlink(path)


# ---------- P9: _log_shot json safety with numpy scalar types ----------
def p9():
    import tempfile, os
    fuser = ShotFuser(publish=lambda s: None, audio=None)
    d = tempfile.mkdtemp()
    shot = {"t_impact": np.float64(1.5), "ball_speed_mph": np.float32(150.0),
            "n_fixes": np.int64(21), "swing": np.bool_(False),
            "nan_field": float("nan")}
    fuser._log_shot(dict(shot), directory=d)
    p = os.path.join(d, "shots.jsonl")
    if not os.path.exists(p):
        report("P9 _log_shot numpy types", False, "(nothing written — swallowed)")
        return
    line = open(p).read().strip()
    try:
        json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        report("P9 _log_shot numpy types", True, "(strict-JSON clean)")
    except ValueError as e:
        report("P9 _log_shot numpy types", False,
               f"(line not strict JSON: {e}; line={line[:120]})")


def main():
    for fn in (p1, p2, p3, p4, p5, p6, p7, p8, p9):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            RESULTS.append((fn.__name__, f"FINDING battery-level {type(e).__name__}: {e}"))
    findings = 0
    for name, res in RESULTS:
        if res != "registered":
            print(f"{name:45s} {res}")
            if not res.startswith("PASS"):
                findings += 1
    print(f"[battery] {len([r for _, r in RESULTS if r != 'registered'])} "
          f"probes, {findings} findings")
    return findings


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
