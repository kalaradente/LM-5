# TODO

Running list of open items. Newest relevant item first per section.

## Hardware

- K-MC1 wiring is settled: **AC output only** (see
  openflight_iwr6843/README.md). No AC/DC switch, no software selection —
  AC reads every real shot since spin rides as sidebands on the kHz Doppler
  carrier.

- [ ] Pin the audio-capture thread to its own CPU core on the Pi (e.g. via
      `taskset` or `sched_setaffinity`) so real-time capture never drops
      samples under load from the rest of the pipeline. Needs real hardware
      under real load to test meaningfully — can't verify this from a
      synthetic test, only on the Pi once it arrives.

- [x] HiFiBerry board decision + Pi 5 compatibility: get the **DAC2 ADC Pro**
      (current-gen part, same `dtoverlay=hifiberry-dacplusadcpro` and PGA
      range as the older DAC+ ADC Pro, PCM1863-based). Confirmed Pi 5 needs
      `force_eeprom_read=0` in config.txt alongside the dtoverlay line, or
      the card's onboard ID EEPROM can conflict with the overlay and it
      won't load. See scripts/setup_wizard.sh step 3.

- [x] K-MC1 <-> DAC2 ADC Pro impedance/level compatibility, verified against
      both datasheets (RFbeam K-MC1 Rev J 11/2022; TI PCM1863): K-MC1 output
      impedance 100 ohm vs DAC2 ADC Pro input impedance 20kOhm per pin --
      ~200:1, loading loss ~0.04dB, no concern. K-MC1 AC output DC offset
      (Vcc/2 +/-0.5V) is irrelevant to clipping risk since the HiFiBerry
      line-in is itself AC-coupled and removes it before the ADC ever sees
      it. NOT yet verified: actual signal AMPLITUDE for a real departing
      ball at real range/RCS -- that's a bench-test question, not a
      datasheet one (see gain.py's docstring, corrected 32dB AC gain figure
      -- was wrongly stated as 47dB earlier).

- [ ] Confirm IWR6843ISK board revision is C or later (needed for direct
      DCA1000 connection later, skipping the MMWAVEICBOOST carrier).

- [x] Pi 5 active-cooler vs. HAT stacking geometry: **resolved by case
      choice** (2026-07-05) — found a case that fits the active cooler on
      top with the Pi and HAT still stacked normally. No tall header or
      side-by-side GPIO ribbon workaround needed.

- [x] **Physical sensor mounting decided** (2026-07-05, see
      `openflight_iwr6843/docs/mounting.md` + `mounting-plate.svg` for the
      full rationale and diagram): both sensors on **one rigid plate, side
      by side** (not stacked — a horizontal split puts the unavoidable
      residual boresight offset in azimuth, the axis with margin (±60°),
      not elevation, the axis that's tuned (`aoaFovCfg` −20/+40 asymmetric,
      centered via `MOUNT_TILT_DEG`)); **centered on the target line**
      (matches azimuth's symmetric FoV); **~2m behind the ball** (swing
      clearance + near-field, superseding the earlier 1-1.5m estimate);
      **mount height ≈ ball height** (inferred from the elevation FoV's
      asymmetry — implies a low, near-ground mount looking up at the rising
      ball, not an elevated mount looking down); **10° tilt** (already
      decided). K-MC1's confirmed narrow beam (12°H/25°V, see below) is why
      alignment + minimal separation matter more than FoV numbers alone
      suggest. STILL OPEN: exact xWR6843ISK board dimension (not in the EVM
      guide's text, only an unscaled photo) — measure the real board or
      find TI's mechanical/fab drawing before machining an exact-fit plate.

- [x] **K-MC1 physical specs confirmed from the primary datasheet** (Rev J,
      11/2022): body 65×65×6mm, 50g; mounts via M2.5 screws from the back
      (M2 alt for a holder; never run without screws in "A" — antenna PCB
      is only glued in for shipping, not structural); connector AMP
      X-338069-8, 8 pins; antenna beamwidth 12°(H)/25°(V) at −3dB (narrower
      than the IWR6843's FoV in both axes); `GAnt`=18.5dBi, `GLNA`=19dB.
      Note `GLNA`=19dB here is a DIFFERENT number from the K-MC1_LP
      variant's FCC filing (10dB) — same "variant datasheets don't
      transfer" lesson as the earlier 47dB/32dB IF-gain question.

- [x] **IWR6843ISK antenna array physically confirmed** (TI SWRU546E EVM
      guide, Figures 3-8/3-9, extracted as images and viewed directly):
      RX1-4 in a row spaced λ/2 (2.5mm), TX1/TX2(vertically offset)/TX3 —
      confirms azimuth AoA comes from the horizontal RX+TX1/TX3 spacing and
      elevation AoA from TX2's vertical offset vs the TX1/TX3 row. Validates
      that `channelCfg`/`aoaFovCfg`'s design assumptions match the real
      hardware, not just the datasheet's prose.

- [x] **SDK version pinned**: the "DEFAULT SETTINGS FOR 6843 FLASH" printout
      (TI mmWave Demo Visualizer) confirms **SDK 3.6** and antenna config
      `4Rx,2Tx(15°)` — exactly matching `channelCfg 15 5 0`. This confirms
      the golf.cfg CLI-arg audit (see Process section below) was checked
      against the *correct* SDK User Guide version, not a guess. See
      `openflight_iwr6843/docs/datasheets-manifest.md`.

- [ ] All primary datasheets now live at `~/Desktop/datasheets/` (external,
      git-ignored — see `openflight_iwr6843/docs/datasheets-manifest.md` for
      the full catalog + what's been extracted from each). Two files in
      that folder are NOT yet cross-checked against the pipeline:
      `Datasheet DAC2 Pro – HiFiBerry.pdf` beyond the PGA/impedance figures
      already in `gain.py`, and the DAC+/ADC Pro mechanical STEP file
      (relevant to the Pi5-cooler-vs-HAT-stacking item below).

- [ ] Solve K-MC1 power: confirm chosen USB battery pack has a low-current
      "trickle" mode, or switch to powering the module off the Pi's own 5V
      GPIO pin (module only draws ~90mA; many power banks auto-shutoff
      below ~100-150mA and will drop the module mid-session).

## From the 2026-07-05 datasheet audit (see openflight_iwr6843/docs/audit-log.md)

- [x] **D-1 (HIGH): fix the serial-port story across all docs/help text.**
      DONE 2026-07-05 — all five files swept (see audit-log.md D-1/FIXED).
      Standalone ISK (our topology) = SiLabs **CP2105** bridge → `ttyUSB*`
      via `cp210x`, Windows needs the SiLabs VCP driver. XDS110/`ttyACM*`/
      `cdc_acm` applies ONLY on an MMWAVEICBOOST carrier (we don't use one).
      Commit 650ceb1 fixed this backwards. Prose-only fix in:
      `run_iwr6843.py` (docstring/help/error), `scripts/setup_wizard.sh`
      (comments/error hints), `openflight_iwr6843/README.md`,
      `docs/firmware-flashing.md` (Windows driver section), `HANDOFF.md`
      (bug list). The wizard's auto-detect/udev machinery already works for
      both device classes — no logic change needed.
- [x] **D-2 resolved (2026-07-05)** — see `openflight_iwr6843/docs/
      kmc1-harness.md` for the full buy-and-solder reference. Order
      **K-MC1-RFB-00D** (5V): matches the Pi-5V-header power plan AND buys
      +3.6dB in-module clipping headroom (couples with D-3). Harness: Pin 1
      (/Enable) **hardwired to GND** — it has an internal 10k PULLUP, so a
      floating pin = radar silently OFF; ferrite+10uF/100nF at the module;
      I_AC->left / Q_AC->right; VCO open (<=0.4% speed-scale error,
      bench-checkable). STILL TO DO: actually place the order.
- [~] **D-3 downgraded + software guard landed (2026-07-05)**: the
      datasheet attributes clipping to FMCW/static-clutter use; we run CW
      and the AC path's 40Hz corner removes static returns. Link budget
      (EIRP +16.5dBm, ball σ≈−25dBsm @2m): ~±100mV at the output vs ±2V
      rails = **~24dB headroom — the ball alone cannot clip**. Residual
      risk = club-face specular glints (~ms around impact). `AudioRing`
      now detects clipping per shot (consecutive-pinned-sample plateau
      test + ADC-full-scale test, BEFORE peak normalization), tags
      `audio_clipped`, and halves measured spin confidence on clipped
      captures. REMAINS for rung 4: eyeball real captures, tune the
      plateau threshold, and only then judge the DC-outputs fallback.
- [x] **D-5 resolved (2026-07-05): golf-outdoor.cfg** — 10 m outdoor
      profile at indoor-grade range resolution (140 MHz/us slope + 10 Msps
      -> R_max 10.71 m, gate 10.0 m, res 4.78 cm, beat 9.34 MHz inside the
      10 MHz IF cap, sweep 3.78 GHz inside the band). ~43 driver fixes vs
      ~27 indoors (+60% observation -> tighter launch angles); 400 Hz
      frames at 38% duty. v_max_ext drops to ±41.6 m/s — more Doppler
      folding, by design (positions carry speed; confidence folds; one
      corner: ~186 mph balls fold to ~0 and the CLUB triggers the capture
      instead). Session outdoor gate aligned 15→10 m; run_iwr6843.py
      auto-selects the cfg per session unless --cfg overrides; frame
      period/v_max derive from the cfg automatically. UNVERIFIED on
      hardware like everything else — rung 3 diffs both cfgs against the
      flashed SDK.
- [x] **D-6 closed (2026-07-05)** — DAC2 ADC Pro datasheet now in
      `~/Desktop/datasheets/`. gain.py's figures verified (−12…+32dB, 96kHz,
      overlay). Two NEW bring-up requirements it surfaced, both handled:
      ADC input mux must be `VINL1[SE]`/`VINR1[SE]` for our unbalanced
      wiring (wizard step 6 now sets it + mic bias off — wrong mux = silent
      capture that looks like a dead radar), and PGA should start at 0dB
      not −12dB (module clips internally below ADC full scale; negative
      gain protects nothing). See kmc1-harness.md + datasheets-manifest.md.
- [ ] **D-8: at build, confirm K-MC1 rotation** so the 25° beam axis is
      vertical (labels in the spec table assume one specific module
      orientation — check the mechanical drawing, then pin the correct
      edge-up into docs/mounting.md).

## Software

- [x] **F-7 fixed (2026-07-05): track-based club/ball classification** —
      see audit-log.md F-7 for the full design. Ball = best ballistic
      suffix across spatially-clustered tracks; everything at-or-behind
      the ball's first-detection range is excluded from the ball fit, and
      club speed = fastest pre-birth row (max clubhead radial occurs
      precisely at ball birth). Verified by the new
      `geometry_capture_simulator.py` (swing-arc club model + FoV gate +
      folded Doppler + USB-chunked timestamps): 4 scenarios x 6 noise
      seeds, 0 failures; no phantom practice-swing shots. Known limits
      documented in the audit log (chip launch ~10 deg low, driver launch
      +/-2 deg scatter). Real captures replayed through analyze() re-test
      this for free once hardware exists.

- [x] Kalman-smoothed carrier tracker + 3D ballistic tracker (`kalman.py`)
- [x] Harmonic-sum ("tap-along") spin bank replacing naive peak-pick
- [x] Mains notch filter (`clean_iq`) -- simplified to just this + trivial
      mean-removal once we committed to AC-only K-MC1 wiring (AC's own
      40Hz hardware corner already does what the old DC-era high-pass did)
- [x] Self-test CLI (`python -m openflight_iwr6843.spin_decoder --selftest`)
- [x] Raw capture archiving on every trigger (radar + audio, replayable)
- [x] Session mode selector (indoor/outdoor x ball type)
- [x] GSPro Open Connect adapter, wired into `run_iwr6843.py` via
      `--gspro-host`/`--gspro-port` (optional; connect failure is
      non-fatal, launch monitor runs fine without it)
- [x] **Fixed a real bug**: launch angle was computed directly from the
      sensor's own z-axis, which isn't vertical once the mount is
      physically tilted up (10-15 deg per the wiring summary). This biased
      every launch angle reading by ~the tilt angle (confirmed via synthetic
      test: uncorrected code was off by -9.98 to -10.00 deg across three
      test angles). Fixed in two places: `kalman.BallTracker` now takes
      `tilt_rad` and decomposes gravity into the sensor's own tilted y/z
      instead of assuming sensor-z=vertical; `iwr6843_source.analyze()`
      rotates the final sensor-frame velocity into world frame before
      computing launch/side angle. `MOUNT_TILT_DEG = 10.0` is a considered
      default (see golf.cfg's aoaFovCfg comment for the antenna-beamwidth
      reasoning) -- CALIBRATE against the actual built mount.
- [x] Wire `SessionConfig` into `IWR6843Source` and `ShotFuser`, end to end.
      `IWR6843Source` now takes a `session=`: the software range gate (`_parse`)
      and capture window (`run`) read from it, AND `configure()` rewrites the
      three session-dependent golf.cfg CLI lines before sending them to the
      chip (`cfarFovCfg` range = the hardware gate, `clutterRemoval`,
      `cfarCfg` thresholdScale offset) — otherwise an outdoor gate extension
      would be silently discarded at the chip. `ShotFuser` now takes a
      `session=` too, so its measured-spin confidence floor (per ball type)
      and audio slice window come from the session, and every published shot
      is stamped with `environment`/`ball_type` tags. `run_iwr6843.py` builds
      the session from new `--outdoor` / `--ball {plain,marked,rct}` flags and
      threads it through `IWR6843Monitor`. Verified synthetically: cfg-line
      rewriting for indoor vs outdoor+rct, and fuser floor/window/tags.
      The `cfarCfg` thresholdScale dB semantics are **confirmed against the
      primary TI source** (mmWave SDK User Guide 3.6 LTS p.28: "Threshold
      scale in dB ... CUT > (Threshold scale converted from dB to Q8) + noise",
      float, max 100 dB) -- so the field is dB and the log-domain detection
      test is additive, making the `12 -> 9` (-3 dB) outdoor nudge a genuine
      -3 dB loosen. Stable across mmWave SDK 3.x; only re-check if a different
      major SDK line gets flashed (same caveat as golf.cfg's arg formats).
- [x] **Corrected the K-MC1 wavelength constant** (`spin_decoder.WAVELENGTH`
      and `spin_capture_simulator.WAVELENGTH`): was `0.0125` m (= 24.0 GHz),
      now `0.012427` m (= 24.125 GHz), per the RFbeam K-MC1/K-MC1_LP datasheet
      (fTX min/typ/max 24.050/24.150/24.250 GHz; Rx/antenna gain characterized
      at nominal 24.125 GHz). The old value put a ~0.6% high bias on every
      Doppler->speed number (`radial_speed_mps`). Spin RPM is unaffected (it
      comes from envelope periodicity, not the carrier) — self-test still
      PASSes at ~3000 rpm. Both files kept in sync so the sim round-trip holds.
- [x] **"47 dB?" question raised during the datasheet pass — resolved, no
      change needed.** The plain K-MC1 (our part) AC-output IF gain is **32 dB,
      datasheet-confirmed** (RFbeam K-MC1 Rev J 11/2022 electrical-characteristics
      table: `GIF_AC = 32 dB` for the _AC outputs, `GIF_DC = 0 dB` DC unbuffered).
      The "47 dB" I flagged appears only in the K-MC1_**LP** variant's FCC block
      diagram — a different part's annotation, and a block diagram does not
      override our part's own spec table. "47" was never a real figure for the
      K-MC1: it originated from an unverified web-search summary earlier and was
      corrected by reading the primary datasheet (this is *the* incident behind
      the "read primary datasheets, not search summaries" rule). `gain.py`'s
      32 dB stands and its gain-staging note already reasons from it correctly.
      (Real departing-ball signal LEVEL is still the open bench question — that
      is a measurement, not a datasheet figure; see the gain-amplitude item.)
- [ ] Fit real coefficients for `shot_fusion.infer_spin()` (currently a
      placeholder surface) once truth data exists.
- [ ] Fit real per-ball-type `spin_conf_floor` values in `session.py`
      (currently placeholders) from rung-3 drill-rig results.
- [ ] One-time audio/radar timestamp latency calibration (clap test:
      compare piezo trigger time vs. audio arrival time) so the
      `AUDIO_PRE`/`AUDIO_POST` window in `shot_fusion.py` is centered
      correctly rather than just generously padded.

## Process

- [x] TLV frame-header length: **committed to 40 bytes** (32-byte header +
      8-byte magic word), 2026-07-04. Rationale: it's the value the mmWave
      community reports consistently across forums/third-party parsers, it's
      the de-facto standard OOB-demo header, and it matches summing TI's own
      listed fields. TI's doc separately says 44 — treated as a later-SDK
      variant. `FRAME_HEADER_LEN = 32` already encoded this; comment updated
      to record the decision. Empirical check remains bring-up rung 2 (parser
      vs TI Demo Visualizer); bump to 36 (44 total) only if rung 2 shows
      garbage/missing points.

- [~] Diff `golf.cfg` against the actual `profile_*.cfg` shipped with
      whatever mmWave SDK version ends up flashed on the board — CLI
      argument counts vary by SDK release. **Partially done 2026-07-04:**
      audited all 16 commands against the mmWave SDK User Guide 3.6 LTS. 15
      match the documented arg lists for our 2-TX x 4-RX design (channelCfg
      15 5 0, adcCfg 2 1, adcbufCfg -1 0 1 1 1, profileCfg 14 args, chirpCfg
      8 args x2, frameCfg 7, guiMonitor 7, cfarCfg 9, cfarFovCfg/aoaFovCfg/
      multiObjBeamForming/clutterRemoval/calibDcRangeSig/extendedMaxVelocity
      all as documented). All arg COUNTS check out, including
      `compRangeBiasAndRxChanPhase`: I initially (wrongly) flagged its 25
      values as a 3-TX/2-TX mismatch, but the xwr6843 mmw demo ALWAYS expects
      12 (Re,Im) pairs = 25 values because the count is fixed by the device's
      physical 3 TX x 4 RX = 12 virtual antennas, NOT by enabled TX (mmWave SDK
      User Guide 3.6 LTS; and a stock xwr6843 config pairs the same 12-pair
      line with channelCfg 15 5 0 = 2 TX). So the count is correct and would
      NOT be rejected. **But the VALUES were a real bug:** our placeholder was
      `0.0 1 0 0 0 ...` = unity on virtual antenna 0 and ZERO gain on the other
      11, which nulls 11/12 channels and wrecks angle estimation. Fixed to TI's
      identity/no-compensation default (`0.0` + twelve `1 0` pairs). Still
      REPLACE with the board's own measured rangeBias/rxChanPhase string at
      bring-up. Final per-SDK-version diff still pending once the board flashes.
- [ ] Read OpenFlight's actual source/README once repo access happens, to
      confirm (rather than infer) the real reason for the sound trigger
      and rolling buffer, before posting anything publicly that
      characterizes his design.
- [x] git init the repo (AGPL-3.0-or-later, matching OpenFlight; `.gitignore`
      excludes `captures/` and `__pycache__/`) — done, see LICENSE.
- [ ] Confirm mains frequency in `spin_decoder.MAINS_NOTCH_HZ` matches your
      country (60Hz North America, 50Hz most everywhere else — already
      documented inline in the code).

## Deferred (revisit only if bench data says so)

- [ ] DC output (or a 4-ch HAT to capture AC+DC) — revisit ONLY if real
      low-spin drill-rig bench captures prove AC-only insufficient. AC is the
      committed default otherwise.
- [ ] DCA1000 raw-ADC capture for true micro-Doppler spin on the 6843
      (only if the K-MC1 channel's bench results say the spin thesis needs
      it).
- [ ] RFbeam K-MC3 (larger antenna) if range/SNR proves insufficient.
- [ ] Titleist RCT balls (only if plain/foil-marked balls underperform in
      the rung-3 drill-rig test).
