# LM-2 — Session Handoff / State of Affairs

_Written 2026-07-04, last updated 2026-07-06 (after audits #1-#7). Read
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
| `openflight_iwr6843/session.py` | `SessionConfig` presets (indoor/outdoor/speed × ball type); `from_selector()` is the web mode picker's entry point. |
| `openflight_iwr6843/gspro_adapter.py` | GSPro Open Connect client. |
| `openflight_iwr6843/gain.py` | HiFiBerry capture-gain via pyalsaaudio (Linux only). |
| `openflight_iwr6843/golf.cfg` | IWR6843 chirp profile, indoor (heavily commented re: antenna FoV). 3 TX (elevation!, audit V-1), 454.5 Hz, R_max 6.09 m. |
| `openflight_iwr6843/golf-outdoor.cfg` | Outdoor chirp profile (D-5, reworked V-1/V-4): 10 m gate at indoor-grade range res, 3 TX, 333 Hz, ~36 driver fixes; auto-selected by run_iwr6843.py for --outdoor. |
| `run_iwr6843.py` | Runs real hardware against the real OpenFlight server/UI. `--gspro-host` optional. |
| `shot_simulator.py` | Type ball speed/spin/launch → RK4 flight sim. `--live` renders in real UI. |
| `spin_capture_simulator.py` | Synthesize raw K-MC1 I/Q → test `spin_decoder.decode()`. No hardware. |
| `geometry_capture_simulator.py` | Synthesize IWR6843 captures (swing-arc club + ballistic ball) through a HOSTILE observation model (V-7: anisotropic elevation noise, bin quantization, wrong-hypothesis Doppler, statics, swaying golfer, false alarms, impact merge, burst gaps — all default-on, with ablation knobs) → test `analyze()`'s track-based classifier against measured 20-seed envelopes. No hardware. |
| `scripts/setup_wizard.sh` | One-command Pi bring-up (clone+patch upstream, deps, Node/UI, HiFiBerry overlay, dialout, port auto-detect+udev, gain, writes `hardware.env`). |
| `patches/simulate_custom_shot.patch` | Additive change to upstream `server.py` that `--live` needs; wizard auto-applies. |
| `patches/session_mode.patch` | Second additive upstream patch (order-independent with the first): `set/get_session_mode` SocketIO events, `mode` in `shot_to_dict`, and the React mode picker (indoor/outdoor/speed) + `SwingDisplay` speed-training view. Wizard applies all `patches/*.patch`. |
| `openflight_iwr6843/docs/firmware-flashing.md` | Uniflash flashing guide + real SOP switch table + flash-vs-config explainer. |
| `openflight_iwr6843/docs/kmc1-harness.md` | K-MC1 buy-and-solder reference: order -00D (5V), Pin 1 /Enable → GND (internal pullup trap!), pin table, supply filtering, clip-risk budget. |
| `openflight_iwr6843/docs/mounting.md` | Physical sensor mounting decision + rationale (side-by-side, one rigid plate, ~2m/height≈ball-height/10° tilt) and confirmed K-MC1/IWR6843ISK physical specs. |
| `openflight_iwr6843/docs/mounting-plate.svg` | Top-view + side-view diagram of the mounting plate. |
| `openflight_iwr6843/docs/datasheets-manifest.md` | Catalog of all primary datasheets at `~/Desktop/datasheets/` (external, git-ignored) and what's been confirmed from each. |
| `openflight_iwr6843/docs/audit-log.md` | **Running audit log — REQUIRED reading.** Seven audits: #1 F-series (code reading), #2 D-series (datasheets), #3 E-series (every-button execution), #4 FAILED (interrupted), #5 S-series (synthesized real stimuli: TLV byte streams, painted audio ring, live TCP/SocketIO wires), #6 V-series (chip config vs Demo Visualizer + SDK User Guide — caught the missing-elevation-TX config, seven missing mandatory CLI commands, and a gravity sign bug that had been masquerading as a sensor limitation), #7 M-series (speed-training/mode-switch surface with dirt — caught balls-in-speed-mode publishing as fake swings, slow practice swings publishing phantom SHOTS through analyze(), the empty-frame drop that could stall mode switches indefinitely, and the touch-drag/scroll latch). ALL findings closed as of 2026-07-06. Johnny's rules are enforced invariants (E-8 launch≥0, E-9 spin-window guard, F-7 directional gate, V-3 anti-gravity gate, M-1 ball-in-speed-mode rejection). Known measurement limits documented in the log, not hidden. See HANDOFF §7 for the standing-state summary. |

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

## 7. Standing state after audits #1-#6 (2026-07-06)

**Six audits run, five methodologies, all findings closed** (full detail:
`docs/audit-log.md`): F-series (code reading), D-series (datasheet
verification), E-series (execution — "every button pressable"), S-series
(synthesized real stimuli: TLV byte streams, painted audio ring, live TCP
+ SocketIO wires), V-series (chip configuration vs the Demo Visualizer +
mmWave SDK User Guide 3.6, both now in `~/Desktop/datasheets/`). Audit #4
is recorded as FAILED (interrupted, no findings) — superseded by #5.
Highlights a fresh session should know:

- **Audit #6 rewrote both chirp cfgs and parts of analyze()** (2026-07-06):
  the old cfgs enabled only the two AZIMUTH TX antennas (launch angle
  would have been structurally zero on real hardware — V-1), omitted
  seven mandatory CLI commands (sensorStart would be refused — V-2), and
  ran over the demo's 50% duty ceiling once fixed (V-4). The 3-TX rework
  shrank v_max_ext to ±37.9/±27.8 m/s, which cascaded through analyze()
  (V-3: Doppler pre-filter removed, club-speed unfolding via track
  range-rate, confidence denominator floor, Doppler tie-break in
  clustering) and flushed out a **pre-existing gravity back-extrapolation
  sign bug (V-3b)** that had been eating ~2 m/s of vz on chip-length
  tracks — the documented "chip launch ~10° low" limit is retracted; the
  simulator now recovers chip launch to within ~0.5°. Chirp order and the
  mandatory-command values were then CONFIRMED against Visualizer-generated
  cfgs Johnny exported (V-5; `3TX CONFIG.cfg`). Finally, **clutterRemoval
  is now OFF in both sessions (V-6)**: the chip's bin-0 erasure silently
  deleted balls whose Doppler folds to ~0 — dragged-ball sim showed
  170–174 mph drives missed 8/8 seeds and a second dead band at ~85 mph;
  off, every speed 150–180 measures at ≤3 mph error. Statics ride through
  to the track classifier, which was built for exactly that (V-3). Then
  **V-7 rebuilt the simulator hostile-by-default** (anisotropic elevation
  noise, bin quantization, wrong-hypothesis extension, false alarms,
  swaying golfer, impact merge, burst gaps) and the honest dirt exposed
  five more pipeline defects — phantom shots from the club's arc-bottom
  sweep at confidence 0.94, 267 mph false-alarm chains, a poisoned
  BallTracker velocity seed, the flat-slow club/ball blend, isotropic-R
  over-trust — all fixed and ablation-proven; final hostile envelopes:
  driver ±1 mph/±1°, zero phantoms in 20 seeds. Residual limits are now
  MEASURED numbers in the audit log ("Residual honest limits after V-7"),
  not estimates.

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
- **Known measurement limits, documented not hidden**: driver launch
  scatters ±2° from position noise (~25 fixes in the 6 m gate at 454.5 Hz;
  the outdoor profile's ~36 fixes is the lever). The old "chip launch
  ~10° low" limit was retracted in audit #6 (it was the V-3b sign bug,
  not physics). Elevation is expected to be the noisiest axis on real
  hardware (single λ/2 elevation baseline) — bench rung 5 owns it.
- Every shot is fully logged locally: `captures/radar_<id>.npz` +
  `audio_<id>.npy` + one JSON line in `captures/shots.jsonl` (feeds
  `validate.py` directly).
- **Speed-training mode (2026-07-06)**: 3-way session mode
  (indoor/outdoor/speed), live-switchable from the web UI's header picker
  (`set_session_mode` SocketIO event → monitor queues → acquisition thread
  re-streams the chirp cfg between captures). Speed mode = club-head speed
  ONLY, ball-less swings riding the same stream as shots
  (`analyze_swing()`, ball_speed structurally 0, `mode="speed-training"`,
  no spin/GSPro). Known limit, self-flagged: fold-shoulder band swings
  (~84 mph arc-bottom radial indoors) are ±10 mph fold-ambiguous
  (`speed_fold_ambiguous`); everywhere else ≤6 mph, ~2 typical (20-seed
  hostile envelope). See TODO's Software entry + README "Session modes".
  **Audited same day (audit #7, M-series, all closed)**: ball strikes in
  speed mode are now rejected as reps (M-1, was publishing a 120 mph ball
  as a 116 mph "swing"); slow practice swings no longer publish phantom
  shots through analyze() in ANY mode (M-3: rate-consistency gate + 0.6
  fill floor — 0 phantoms across 140 hostile bare swings, 70–125 mph);
  empty frames now keep the switch check alive in quiet scenes (M-4); the
  mode-switch machinery is execution-proven end to end over synthesized
  TLV wires (swing and shot published across live switches, cfg
  re-streams line-verified, rapid switches coalesce).
- **Placement wiggle + teed-ball auto-detection (2026-07-06, M-7)**: the
  unit works anywhere 5–7 ft behind the ball. `_find_teed_balls()` locks
  balls at rest (persistent zero-Doppler clusters that VANISH at impact)
  and the ballistic-suffix judge consumes the locks (resting-row
  excision + anchored-birth relaxation of the anti-phantom fences, which
  were all implicitly sized at 2.0 m and ate drives at 7 ft).
  `tee_range_m` rides every shot record. Best-effort: no lock = old
  behavior exactly. Envelopes across placements: 2/320 misses (one
  brutal seed), 0/160 phantoms, 0/240 swing failures. Rung-3 question:
  does a real static ball clear CFAR against the mat at all.

**Still open (all hardware-gated):**
- **Place the K-MC1-RFB-00D order** (5V variant! see
  `docs/kmc1-harness.md` — Pin 1 /Enable must be hardwired to GND, ADC
  input mux must be set, PGA starts at 0 dB).
- **D-8 at build**: K-MC1 rotation — 25° beam axis vertical.
- Bench-owned numbers: real departing-ball signal level, `infer_spin`
  coefficients, `spin_conf_floor` per ball type, audio/radar clap-test
  latency, plateau-clip threshold, chip launch accuracy.
- TLV 40-byte header + `compRangeBias` identity string + both chirp cfgs:
  final confirmation at bring-up rungs 2-3 vs the flashed SDK 3.6. The
  V-5 chirp-order question is already CLOSED (Visualizer-generated 3-TX
  cfg matches ours exactly — see `3TX CONFIG.cfg` in the datasheets
  folder); the z-axis sign check (hand above boresight, rung 2) remains.
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
