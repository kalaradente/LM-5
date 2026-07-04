# LM-2 — Session Handoff / State of Affairs

_Written 2026-07-04 to hand off to a fresh Claude instance. Read this first,
then `README.md`, `TODO.md`, and `openflight_iwr6843/README.md`._

---

## 1. What this project is

A DIY golf launch monitor. Two radar channels feed a Raspberry Pi 5:

- **Geometry** — TI **IWR6843ISK** (60GHz FMCW mmWave, 3TX/4RX) over USB
  serial. Gives ball speed, launch angle, side angle, club speed via a
  point cloud → Kalman trajectory fit.
- **Spin** — RFbeam **K-MC1** (24GHz CW radar) analog I/Q → **HiFiBerry
  DAC2 ADC Pro** stereo line-in → spin RPM via carrier tracking + a
  harmonic-sum ("tap-along") spin search.

Downstream it plugs into **OpenFlight** (github.com/jewbetcha/openflight —
an existing open-source launch monitor with a Flask/SocketIO server, RK4
drag+Magnus physics engine, and React UI). This project is a drop-in
**acquisition layer** replacing OpenFlight's own OPS243/K-LD7 radar stack.

**Status: nothing has touched real hardware yet.** All verification so far
is synthetic (compile checks, self-tests, synthetic captures/trajectories).
Everything marked UNVERIFIED or "bench-test question" is genuinely unproven
until the parts arrive.

---

## 2. Repo layout — TWO repos, read this carefully

- **LM-2** (`~/Desktop/LM-2`, github.com/kalaradente/LM-2, **public**,
  AGPL-3.0) — **the only actively-updated repo.** All new work goes here.
- **LM-1** (`~/Desktop/OPENFLIGHT`, github.com/kalaradente/LM-1) — **frozen
  snapshot** of where LM-2 branched from. Do NOT modify it. (Note its local
  working tree is dirty from a parallel session; that's expected, ignore it.
  Its committed state is the real LM-1.)

`openflight_upstream/` (the OpenFlight clone) is **git-ignored** in both —
it has its own git history. The setup wizard clones it and applies our one
patch. On a dev machine, symlink it for testing:
`ln -sfn ~/Desktop/OPENFLIGHT/openflight_upstream openflight_upstream`
(remove the symlink before committing).

---

## 3. How to work in this repo

- **venv**: shared at `~/Desktop/OPENFLIGHT/.venv` this session
  (`source ~/Desktop/OPENFLIGHT/.venv/bin/activate`). `requirements.txt`
  lists deps. `pyalsaaudio` is Linux-only (gated in requirements).
- **This machine's environment**: macOS, Python 3.14, **Homebrew is broken**
  (Node was installed via `nvm` as a workaround; `poppler`/`pdftoppm` is
  unavailable — read PDFs via `pypdf` text extraction, not the Read tool's
  page rendering).
- **Verification loop after any change** (all pass today):
  ```bash
  python3 -m py_compile openflight_iwr6843/*.py *.py
  python3 -m openflight_iwr6843.spin_decoder --selftest      # expect ~3000rpm PASS
  python3 spin_capture_simulator.py --speed 165 --spin 2600  # synthetic spin path
  bash -n scripts/setup_wizard.sh
  # with openflight_upstream symlinked:
  python3 shot_simulator.py --ball-speed 165 --spin 2600 --launch-angle 13 --side-spin 900
  ```
- **Commit style**: detailed messages explaining the WHY; end with
  `Co-Authored-By: Claude <model> <noreply@anthropic.com>`. Only commit/push
  when the user asks (they have consistently asked to push each round).

---

## 4. Key files

| File | Role |
|---|---|
| `openflight_iwr6843/iwr6843_source.py` | IWR6843 serial + TLV point-cloud parser + shot detection + geometry (launch/side angle). Has `MOUNT_TILT_DEG=10.0`. |
| `openflight_iwr6843/kalman.py` | `BallTracker` (3D CV+gravity, tilt-aware) and `FreqTracker` (spin carrier). |
| `openflight_iwr6843/spin_decoder.py` | K-MC1 I/Q → spin RPM. `clean_iq` (mains notch only, AC-only), `decode()`, `--selftest`. |
| `openflight_iwr6843/shot_fusion.py` | Merges geometry+spin, `AudioRing`, `ShotFuser`, `infer_spin` fallback. |
| `openflight_iwr6843/session.py` | `SessionConfig` presets (indoor/outdoor × ball type). |
| `openflight_iwr6843/gspro_adapter.py` | GSPro Open Connect client. |
| `openflight_iwr6843/gain.py` | HiFiBerry capture-gain via pyalsaaudio (Linux only). |
| `openflight_iwr6843/golf.cfg` | IWR6843 chirp profile (heavily commented re: antenna FoV). |
| `run_iwr6843.py` | Runs real hardware against the real OpenFlight server/UI. `--gspro-host` optional. |
| `shot_simulator.py` | Type ball speed/spin/launch → RK4 flight sim. `--live` renders in real UI. |
| `spin_capture_simulator.py` | Synthesize raw K-MC1 I/Q → test `spin_decoder.decode()`. No hardware. |
| `scripts/setup_wizard.sh` | One-command Pi bring-up (clone+patch upstream, deps, Node/UI, HiFiBerry overlay, dialout, port auto-detect+udev, gain, writes `hardware.env`). |
| `patches/simulate_custom_shot.patch` | The one additive change to upstream `server.py` that `--live` needs; wizard auto-applies. |
| `openflight_iwr6843/docs/firmware-flashing.md` | Uniflash flashing guide + real SOP switch table + flash-vs-config explainer. |

---

## 5. Decisions made this session, and WHY (hard to re-derive)

1. **AC-only K-MC1 wiring.** The K-MC1 has AC (40Hz–15kHz) and DC (0–500kHz)
   outputs. We wire **AC only**. Reason: for real (flight) shots the ball
   translates, so spin appears as **sidebands on the kHz Doppler carrier**
   (a 2000rpm driver = ~33Hz sidebands on an ~11kHz carrier), fully inside
   AC's passband — AC's 40Hz low corner only hurts the non-translating
   drill-rig bench test. AC is also cleaner (no DC offset/hum). All the
   AC/DC-switching machinery (mode field, auto-detector, dual filters) was
   built then deliberately **removed** for simplicity. `clean_iq` is now
   just a 60Hz mains notch (60Hz survives AC coupling and lands in the spin
   band). DC is kept as a documented "revisit only if bench data says so".

2. **DAC2 ADC Pro** (not the older DAC+ ADC Pro): current-gen, same overlay
   & PGA range (−12 to +32dB), PCM1863. **Pi 5 needs `force_eeprom_read=0`**
   in config.txt or the overlay won't load — wizard handles it.

3. **MOUNT_TILT_DEG = 10°**: centers the antenna's ~±20° measured elevation
   beamwidth on driver/mid-iron launch angles. See `golf.cfg` aoaFovCfg
   comment. Drives the tilt correction (see bug #1 below).

4. **Impedance verified**: K-MC1 100Ω out vs DAC2 20kΩ/pin in = ~200:1,
   negligible loss. No matching needed.

5. **Working method the user values**: read **primary datasheets, not web
   search summaries** (a search summary gave a wrong 47dB K-MC1 gain figure
   — real value is 32dB — caught only by reading the actual datasheet).
   Verify fixes with **synthetic tests** before trusting them. Flag what's
   unverified honestly rather than papering over it.

---

## 6. Real bugs found & fixed this session

- **Launch-angle tilt bias** (commit 155adfb): launch angle was computed
  against the sensor's own z-axis, which isn't vertical once the mount is
  tilted 10°. Biased EVERY launch angle by ~the tilt (synthetic test: old
  code off by −9.98 to −10.00° across 11/20/35°; fixed code within 0.5°).
  Fixed in `BallTracker` (gravity decomposed into tilted frame) AND
  `analyze()` (velocity rotated to world frame before atan2).
- **ttyUSB → ttyACM** (650ceb1): IWR6843's XDS110 probe is CDC-ACM class,
  enumerates as `/dev/ttyACM*`, not `ttyUSB*`. Fixed across docs/help text.
  No driver needed on Pi (`cdc_acm` built in); Windows needs TI's XDS110
  driver (Uniflash/CCS).
- **Side-info dtype** (acf1fc3): SNR/noise are `uint16` per TI spec, was
  `int16`. Harmless in practice, fixed for correctness.

---

## 7. Biggest OPEN / UNVERIFIED items (see TODO.md for full list)

- **TLV frame-header length is unresolved**: code assumes 40 bytes (8 magic
  + 32 header). TI's OOB-demo doc internally contradicts itself (lists
  fields summing to 40, but states 44 total) — likely an SDK-version diff.
  **Bring-up rung 2 (parser vs TI Demo Visualizer on a live stream) is the
  check that resolves this** — wrong length = garbage/missing points.
- **Gain amplitude** for a real departing ball is unknown (datasheet gives
  impedance/gain but not real-target signal level). Bench-test question.
- **`infer_spin` coefficients** and **`spin_conf_floor`** are placeholders
  awaiting real truth data.
- **`SessionConfig` not wired into `IWR6843Source`** (geometry side uses
  hardcoded constants).
- **SOP switch settings ARE now confirmed** from TI docs (see
  firmware-flashing.md): only S1.1 changes between flash/functional; SOP is
  boot-sensed (must reset after flipping).

---

## 8. The bring-up ladder (the plan for when hardware arrives)

0. Flash IWR6843 firmware on **Windows** via Uniflash (see
   firmware-flashing.md — SOP table is filled in).
1. TI mmWave Demo Visualizer + stock config: wave hand, prove board.
2. Our parser vs that same stream: positions must match (resolves the TLV
   header-length question).
3. Load `golf.cfg` (diff against flashed SDK version first); roll balls.
4. K-MC1 side: `arecord` capture → pull to Mac → Audacity eyeball →
   drill-spun ball at known RPM via `spin_decoder --bench`.
5. Real swings; validate against a truth unit (`validate.py`).

Then on the Pi: `git clone` LM-2 → `./scripts/setup_wizard.sh` →
`python3 run_iwr6843.py --ballistics`.

---

## 9. Changelog (git history, newest first)

See the table on the next page / `git log`. 14 commits, all 2026-07-03/04.
