# LM-2 — Session Handoff / State of Affairs

_Written 2026-07-04, last updated 2026-07-05 (after audits #1-#5). Read
this first, then `openflight_iwr6843/docs/audit-log.md` (the running audit
record — REQUIRED reading before assuming anything about open issues),
`TODO.md`, and `openflight_iwr6843/README.md`. Auto-memory also carries
project context across sessions (repo layout, pypdf-for-PDFs, the audit
framework, "physics first when tuning stalls")._

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
  page rendering; for figures/mechanical drawings that are images rather
  than text, pull the embedded image objects directly via pypdf's
  `page.images` — this does NOT need poppler, unlike full-page rendering).
- **Primary datasheets**: all live at `~/Desktop/datasheets/` (external,
  git-ignored — vendor PDFs, not committed). See
  `openflight_iwr6843/docs/datasheets-manifest.md` for the full catalog and
  what's been confirmed from each. Check there before re-fetching anything
  from the web — web fetches of these exact PDFs have repeatedly timed out.
- **Verification loop after any change** (all pass today):
  ```bash
  python3 -m py_compile openflight_iwr6843/*.py *.py
  python3 -m openflight_iwr6843.spin_decoder --selftest      # expect ~3000rpm PASS
  python3 spin_capture_simulator.py --speed 165 --spin 2600  # synthetic spin path
  python3 geometry_capture_simulator.py           # geometry path: club/ball classifier
  python3 geometry_capture_simulator.py --sweep   # ...across 6 noise seeds
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
| `openflight_iwr6843/golf.cfg` | IWR6843 chirp profile, indoor (heavily commented re: antenna FoV). R_max 6.09 m. |
| `openflight_iwr6843/golf-outdoor.cfg` | Outdoor chirp profile (D-5): 10 m gate at indoor-grade range res, ~43 driver fixes; auto-selected by run_iwr6843.py for --outdoor. |
| `run_iwr6843.py` | Runs real hardware against the real OpenFlight server/UI. `--gspro-host` optional. |
| `shot_simulator.py` | Type ball speed/spin/launch → RK4 flight sim. `--live` renders in real UI. |
| `spin_capture_simulator.py` | Synthesize raw K-MC1 I/Q → test `spin_decoder.decode()`. No hardware. |
| `geometry_capture_simulator.py` | Synthesize IWR6843 captures (swing-arc club + ballistic ball) → test `analyze()`'s track-based club/ball classifier (F-7). No hardware. |
| `scripts/setup_wizard.sh` | One-command Pi bring-up (clone+patch upstream, deps, Node/UI, HiFiBerry overlay, dialout, port auto-detect+udev, gain, writes `hardware.env`). |
| `patches/simulate_custom_shot.patch` | The one additive change to upstream `server.py` that `--live` needs; wizard auto-applies. |
| `openflight_iwr6843/docs/firmware-flashing.md` | Uniflash flashing guide + real SOP switch table + flash-vs-config explainer. |
| `openflight_iwr6843/docs/kmc1-harness.md` | K-MC1 buy-and-solder reference: order -00D (5V), Pin 1 /Enable → GND (internal pullup trap!), pin table, supply filtering, clip-risk budget. |
| `openflight_iwr6843/docs/mounting.md` | Physical sensor mounting decision + rationale (side-by-side, one rigid plate, ~2m/height≈ball-height/10° tilt) and confirmed K-MC1/IWR6843ISK physical specs. |
| `openflight_iwr6843/docs/mounting-plate.svg` | Top-view + side-view diagram of the mounting plate. |
| `openflight_iwr6843/docs/datasheets-manifest.md` | Catalog of all primary datasheets at `~/Desktop/datasheets/` (external, git-ignored) and what's been confirmed from each. |
| `openflight_iwr6843/docs/audit-log.md` | **Running audit log** — five-stage (physical/trigger/processing/output/upstream) top-down audits per channel; findings F-1…F-7 (code audits) and D-1…D-9 (datasheet audit) with statuses. Read this before assuming anything about open issues. As of 2026-07-05: F-1…F-7, D-1, D-2 all FIXED/RESOLVED; D-3 downgraded (CW vs FMCW + link budget) with the `audio_clipped` software guard landed. Still open: D-8 (K-MC1 rotation at build) and placing the actual -00D order — everything else is closed (D-5 via golf-outdoor.cfg; D-6 via the DAC2 ADC Pro + PCM1863 sheets, which also surfaced the ADC input-mux requirement the wizard now sets). Known measurement limits (chip launch ~10° low, driver launch ±2° scatter) documented in the log. |

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

5. **Physical mounting decided (2026-07-05)**: both sensors on one rigid
   plate, side by side, centered on the target line, ~2m behind the ball,
   mount height ≈ ball height, 10° tilt. Full rationale (why side-by-side
   beats stacking, why the height is inferred from `aoaFovCfg`'s asymmetric
   elevation gate) in `openflight_iwr6843/docs/mounting.md`. K-MC1's real
   beamwidth (12°H/25°V, datasheet-confirmed) is narrower than the
   IWR6843's, which is why boresight alignment matters most for that
   channel. SDK version also pinned to **3.6**, confirmed from a Demo
   Visualizer printout (matches the User Guide already used for the
   golf.cfg CLI-arg audit).

6. **Working method the user values**: read **primary datasheets, not web
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
- **ttyUSB → ttyACM (650ceb1) — REVERSED 2026-07-05 (audit finding D-1)**:
  that commit was a fix in the wrong direction. The XDS110 lives on the
  MMWAVEICBOOST carrier only; the standalone ISK (our topology) uses a
  SiLabs **CP2105** bridge → `/dev/ttyUSB*` via `cp210x` on the Pi, SiLabs
  CP210x VCP driver on Windows. All prose corrected back; the wizard's
  detection machinery was device-class-agnostic all along. See
  `docs/audit-log.md` D-1.
- **Side-info dtype** (acf1fc3): SNR/noise are `uint16` per TI spec, was
  `int16`. Harmless in practice, fixed for correctness.
- **K-MC1 wavelength off by 24.0 vs 24.125 GHz**: `WAVELENGTH` was `0.0125` m
  (24.0 GHz); RFbeam datasheet nominal is 24.125 GHz -> `0.012427` m. ~0.6%
  high bias on every Doppler->speed number (spin RPM unaffected). Fixed in
  `spin_decoder.py` + `spin_capture_simulator.py`. Found via a "pull the
  datasheet for our educated assumptions" pass (same pass that verified the
  cfarCfg-in-dB semantics and audited golf.cfg's CLI arg counts).
- **golf.cfg compRangeBiasAndRxChanPhase nulled 11/12 channels**: placeholder
  was `0.0 1 0 0 0 ...` = unity on virtual antenna 0, ZERO gain on the other
  11 -> would kill AoA (side/launch angle). Fixed to TI's identity default
  (`0.0` + twelve `1 0` pairs). NB the 25-value count is correct for xwr6843
  (12 virtual antennas, fixed by 3TX*4RX regardless of enabled TX) -- an
  earlier "arg-count mismatch" flag was a false alarm, corrected. Still
  replace with the board's measured string at bring-up.

---

## 7. Standing state after audits #1-#5 (2026-07-05)

**Five audits run, four methodologies, all findings closed** (full detail:
`docs/audit-log.md`): F-series (code reading), D-series (datasheet
verification), E-series (execution — "every button pressable"), S-series
(synthesized real stimuli: TLV byte streams, painted audio ring, live TCP
+ SocketIO wires). Audit #4 is recorded as FAILED (interrupted, no
findings) — superseded by #5. Highlights a fresh session should know:

- **The classifier is track-based** (F-7): ball = ballistic suffix, club =
  fastest pre-birth row; two of Johnny's rules are enforced invariants —
  everything at-or-behind ball birth is not the ball, and **launch angle
  can never be < 0** (E-8: clamp + confidence penalty + raw preserved).
- **The spin channel is sealed against the descending clubhead** (E-9:
  10 ms guard window + median-seeded carrier tracker) and never
  self-triggers — decode runs only on the 6843's shot callback. No
  post-impact clubhead movement contributes to any metric.
- **A dead/unplugged UART no longer wedges acquisition** (S-1: idle-read
  guard ends the stream loudly instead of spinning at 100% CPU forever).
- **Security property S-2**: in hardware posture a web client cannot
  inject fake shots (`simulate_custom_shot` is mock-only by design); both
  postures pressed against a LIVE SocketIO server.
- **Known measurement limits, documented not hidden**: chip-class launch
  reads ~10° low (club/ball blend below the sensor's separability floor —
  confidence correctly collapses); driver launch scatters ±2° (27 fixes in
  the 6 m gate; the outdoor profile's ~43 fixes is the lever).
- Every shot is fully logged locally: `captures/radar_<id>.npz` +
  `audio_<id>.npy` + one JSON line in `captures/shots.jsonl` (feeds
  `validate.py` directly).

**Still open (all hardware-gated):**
- **Place the K-MC1-RFB-00D order** (5V variant! see
  `docs/kmc1-harness.md` — Pin 1 /Enable must be hardwired to GND, ADC
  input mux must be set, PGA starts at 0 dB).
- **D-8 at build**: K-MC1 rotation — 25° beam axis vertical.
- Bench-owned numbers: real departing-ball signal level, `infer_spin`
  coefficients, `spin_conf_floor` per ball type, audio/radar clap-test
  latency, plateau-clip threshold, chip launch accuracy.
- TLV 40-byte header + `compRangeBias` identity string + both chirp cfgs:
  final confirmation at bring-up rungs 2-3 vs the flashed SDK 3.6.
- Exact xWR6843ISK board outline (measure the real board before machining
  the plate); board rev C-or-later check.

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

## 9. Changelog

`git log` is the changelog — ~30 commits through 2026-07-05, each message
written to carry the full WHY so the audit trail reconstructs from history
alone. The five audit entries in `docs/audit-log.md` index the big arcs.
