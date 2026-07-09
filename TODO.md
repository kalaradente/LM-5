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

## From the 2026-07-05/06 chip-config audit #6 (V-series, see audit-log.md)

- [x] **V-1 (CRITICAL, fixed): both cfgs now enable all 3 TX** (`channelCfg
      15 7 0` + third chirpCfg). The old 0x5 mask was the two AZIMUTH
      antennas only — no elevation estimation, z=0 on every point, launch
      angle structurally dead. Primary source: mmWave SDK UG 3.6, channelCfg
      ISK example (0x5 = azimuth pair, 0x7 = azimuth + elevation).
- [x] **V-2 (HIGH, fixed): seven mandatory CLI commands added** to both
      cfgs in stock disabled form (bpmCfg, lvdsStreamCfg, CQRxSatMonitor,
      CQSigImgMonitor, analogMonitor, measureRangeBiasAndRxChanPhase,
      calibData) — the demo refuses sensorStart when any is missing.
- [x] **V-3/V-3b (HIGH, fixed): fold-aware analyze() + gravity sign bug.**
      v_max_ext is now ±37.9 (indoor) / ±27.8 (outdoor): Doppler pre-filter
      removed (balls folding to ~0 were deleted), club speed unfolded via
      per-row track range-rate, confidence denominator floored, Doppler
      tie-break in clustering, z-trim edge/first-half fixes — and the
      launch back-extrapolation applied gravity with the WRONG SIGN
      (dominant cause of the retracted "chip launch ~10° low" limit).
- [x] **V-5 chirp order: CONFIRMED 2026-07-06** — Johnny exported the
      Visualizer's generated 3-TX cfg (`3TX CONFIG.cfg` in
      `~/Desktop/datasheets/`): chirps emit in exactly our order (TX1,
      TX3, TX2 = masks 1, 4, 2), `channelCfg 15 7 0`, `frameCfg 0 2 16`.
      One divergence adopted from it: `bpmCfg -1 0 0 1` (disable range =
      azimuth chirps only), replacing our generalized `0 0 2`.
- [ ] **V-5 at rung 2**: confirm the z-axis SIGN with the board in its
      final mounting orientation (hand above boresight → z must go
      positive; if inverted, MOUNT_TILT_DEG geometry and launch angle
      flip sign).
- [x] **V-6 (was a "documented limit" under V-5 — promoted and FIXED
      2026-07-06): clutterRemoval OFF in both sessions.** The chip-side
      bin-0 erasure wasn't a 10–25 ms nuisance: dragged-ball simulation
      showed 170–174 mph drives missed on 8/8 seeds (ball never leaves
      the band inside the 6 m gate), plus a SECOND band at ~83–87 mph
      (irons, and driver clubheads). Off → every speed measures (≤3 mph
      err, ~21 fixes). Statics are handled by the track classifier
      (sim-proven).
- [ ] **V-6 rung-3 watch**: with clutterRemoval off, watch indoor
      points-per-frame / UART frame-skips in a real bay. If statics flood
      the link, raise the indoor CFAR threshold via the session's
      `cfar_threshold_offset_db` knob — do NOT re-enable clutterRemoval.
      (UART arithmetic: ~5 detections/frame sustainable at 454.5 Hz /
      921600 baud with points+SNR+stats enabled; beyond that the demo
      throttles and frames() logs skips — F-1 timing survives skips.)
- [x] **V-7 (2026-07-06): hostile-world stress hardening.** Simulator
      rebuilt with default-on dirt (anisotropic elevation noise, bin
      quantization, wrong-hypothesis Doppler extension, statics, swaying
      golfer, CFAR false alarms, impact merge, burst gaps); five pipeline
      defects it exposed are fixed (phantom club-sweep shots, false-alarm
      chains, poisoned tracker seed, flat-slow blend, isotropic-R
      over-trust). Hostile 20-seed envelopes: driver ±1 mph/±1°, zero
      phantoms. Residual measured limits + retractions in audit-log.md.

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
      10 MHz IF cap, sweep 3.78 GHz inside the band). Session outdoor gate
      aligned 15→10 m; run_iwr6843.py auto-selects the cfg per session
      unless --cfg overrides; frame period/v_max derive from the cfg
      automatically. NUMBERS SUPERSEDED by audit #6 (V-1/V-4): now 3 TX,
      333 Hz at 48% duty, ~36 driver fixes, v_max_ext ±27.8 m/s (see the
      V-series section above). UNVERIFIED on hardware like everything
      else — rung 3 diffs both cfgs against the flashed SDK.
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

- [x] **Automatic CFAR threshold -- "the compressor" (2026-07-06,
      Johnny's request, audit M-9)**: idle-scene detection density
      (points/frame, armed only -- captures never feed the sidechain)
      drives cfarCfg thresholdScale inside a 1-8 pts/frame corridor:
      flooded -> +1.5 dB steps (automates the V-6 escape hatch), starved
      -> -1.5 dB (sensitivity for the teed-ball lock), clamp -6..+12 dB,
      4 s windows / 10 s cooldown, +3 dB limiter on UART frame-skips
      that bypasses cooldown. Actuates via the mode-switch safe-point
      cfg re-stream; mode switch resets the term; records carry
      cfar_auto_db; --no-auto-cfar kills it. Closed-loop verified
      against a responsive fake chip (converge/hold/limiter/reset/rail).
      BENCH (rung 3): the corridor numbers (1-8 pts/frame) and step/
      cooldown tempo are placeholders -- measure a real bay's idle
      density and retune; also confirm the demo tolerates frequent
      sensorStop/Start cycles over hours (retunes are rare by design,
      but power-cycling wear on the chip's calibration is a real
      question).

- [x] **Placement wiggle (5-7 ft) + teed-ball auto-detection (2026-07-06,
      Johnny's request, audit M-7)**: sensor placement anywhere in the
      5-7 ft band now measured-good (accuracy held; what broke were the
      anti-phantom fences, all implicitly sized at 2.0 m -- driver misses
      at 7 ft, a 37.7-deg bump corruption from the teed-ball static
      stitching onto flight). _find_teed_balls() locks balls at rest
      (compact + persistent + zero-Doppler + VANISHES at impact -- the
      vanish is unfakeable by walls/golfer) and the suffix judge consumes
      the locks: no suffix may start on a resting-ball row, and a suffix
      born at a lock as it vanishes gets relaxed span/fill/gain floors
      (kinematic gates stay full). tee_range_m rides every shot record
      for placement validation. Best-effort BY DESIGN: no lock = exactly
      the old pipeline. Envelopes across 4 placements x 20 seeds: misses
      2/320 (both one brutal merge seed, V-7-class residual), phantoms
      0/160, swings 0/240, M-1 leaks 0. Sweep now cycles TEE_SWEEP.
      BENCH (rung 3): does a static teed ball clear CFAR against the mat
      at all? If not, everything still works -- locks just never form.
      If yes, tune teeball detectability + the 0.9-3.2 m tee zone against
      reality. UI surfacing of tee_range_m: DONE 2026-07-08 (audit #9
      follow-on) -- a "Tee Range" card (feet, matching the Peak Height
      convention) renders whenever a shot carries a lock; hardware-only
      by design (the mock never forms locks), pinned by
      ShotDisplay.test.tsx + a shot_to_dict round-trip check.

- [~] **Auto-start OpenFlight on Pi boot** — AUTHORED 2026-07-08 (wizard
      step 9): `openflight-lm2.service` rendered + enabled by the wizard
      (opt-out prompt). After=network.target sound.target,
      WorkingDirectory=repo root, ExecStart=repo venv python
      run_iwr6843.py --ballistics (ports/audio from hardware.env as
      always), Restart=on-failure with backoff. Deliberate: the S-1
      dead-UART guard keeps the web server alive (UI reachable, says
      what happened) rather than flap-restarting the radar; unit starts
      in indoor play mode — all modes live-switchable from the UI, so no
      --speed-training default. Headless by design (upstream's
      start-kiosk.sh launches a desktop browser; ours is viewed from a
      phone). REMAINING (hardware-gated): boot-ordering vs the HiFiBerry
      overlay + USB enumeration on the real Pi — enable, power-cycle,
      swing.

- [x] **Speed-training mode + live 3-way mode switching (2026-07-06,
      Johnny's request)**: club-head-speed-only mode for ball-less
      overspeed training, riding the EXACT same stream as shots
      (analyze_swing() -> fuser -> publish -> on_shot_detected -> "shot"
      emit -> UI) with ball_speed structurally 0, no spin decode, no GSPro
      forward, mode="speed-training" tag. The web UI grew a header mode
      picker (indoor/outdoor/speed) that emits set_session_mode over
      SocketIO; the monitor queues the switch and the acquisition thread
      applies it BETWEEN captures by re-streaming the chirp cfg (cfgs
      carry their own sensorStop/flushCfg/sensorStart -- the Visualizer's
      own live-reconfigure flow), so indoor<->outdoor profile swaps work
      live too. Speed mode always uses the indoor profile (clubhead is
      ~2-3 m out whatever the venue; 454.5 Hz maximizes arc-bottom fixes).
      Upstream side lives in patches/session_mode.patch (additive,
      order-independent with the simulate patch, wizard applies both).
      Verified: 20-seed hostile swing envelope (~2 mph typical, <=6 mph,
      fold-shoulder band +/-10 mph SELF-FLAGGED via speed_fold_ambiguous
      -- a folded bottom and a just-under-v_max bottom are observationally
      identical there, see analyze_swing()); live SocketIO press test
      (valid/junk/malformed modes, unsupported-monitor posture, swing
      riding the real shot stream); tsc + eslint clean. S-2 posture holds:
      the new ingress is control-plane only, whitelisted by from_selector.
      AUDITED 2026-07-06 (audit #7, M-series, all findings closed — see
      audit-log.md): M-1 ball-strike-in-speed-mode now rejected as a rep,
      M-3 slow-practice-swing phantom shots killed in play mode too
      (rate-consistency gate + 0.6 fill floor, 0/140 wide scan), M-4
      empty frames keep switches applying in quiet scenes, M-2 native
      touchmove guard for hold-to-drag, plus end-to-end execution proof
      of the switch machinery over synthesized TLV wires.
      BENCH (rung 5): confirm the fold-shoulder ambiguity band against a
      real swing at known speed; one minute of real-phone drag (M-2
      confirmation); radar-vs-real-clock latency of the mode switch is a
      nicety, not a correctness item.

- [x] **Physical invariant: launch angle >= 0** (2026-07-05, Johnny's
      rule — E-8 in audit-log.md): analyze() clamps negative launch fits
      to 0, cuts geometry_confidence in proportion to the violation, and
      logs the raw value (`launch_angle_raw_deg`) for replay tuning.
      Guarded by geometry_capture_simulator on every scenario x seed +
      the new bump_and_run worst-case scenario.

- [x] **F-7 fixed (2026-07-05): track-based club/ball classification** —
      see audit-log.md F-7 for the full design. Ball = best ballistic
      suffix across spatially-clustered tracks; everything at-or-behind
      the ball's first-detection range is excluded from the ball fit, and
      club speed = fastest pre-birth row (max clubhead radial occurs
      precisely at ball birth). Verified by the new
      `geometry_capture_simulator.py` (swing-arc club model + FoV gate +
      folded Doppler + USB-chunked timestamps): 4 scenarios x 6 noise
      seeds, 0 failures; no phantom practice-swing shots. Real captures
      replayed through analyze() re-test this for free once hardware
      exists. (The old known-limit notes here — "chip launch ~10 deg low,
      driver ±2 deg scatter" — are both superseded: the chip bias was
      mostly the V-3b gravity sign bug, and V-7's hostile simulator
      replaced estimates with measured envelopes. Current truth lives in
      audit-log.md "Residual honest limits after V-7".)

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
      (currently placeholders) from rung-4 drill-rig results.
- [ ] One-time audio/radar timestamp latency calibration (clap test:
      compare piezo trigger time vs. audio arrival time) so the session's
      `spin_audio_window_s` pre/post window is centered correctly rather
      than just generously padded.

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
      NB (audit #6): this arg-count audit checked only commands that were
      PRESENT — it missed both the wrong TX mask (V-1) and seven missing
      mandatory commands (V-2). Completeness now audited against the SDK
      UG's full mandatory list (the UG PDF is now on disk in
      `~/Desktop/datasheets/mmwave visualizer user guide/`).
- [x] Read OpenFlight's actual source/README to confirm (rather than
      infer) the real reason for the sound trigger and rolling buffer —
      **confirmed 2026-07-08 from the upstream docs themselves**
      (`docs/rolling_buffer_spin_detection.md`, based on OmniPreSense
      guidance Jan 2026; `docs/sound-trigger-wiring.md`): (1) the
      OPS243-A's streaming mode emits processed speeds at ~56 Hz with no
      raw I/Q, so SPIN is impossible there — rolling-buffer mode (G1)
      exists to capture raw 4096-sample I/Q (~136 ms @ 30 ksps) for
      overlapping-FFT post-processing that extracts spin from Doppler
      micro-variations (50-60% success, their number); (2) the buffer
      dump needs a trigger, and the SEN-14262 sound sensor wired to
      HOST_INT gives ~10 µs latency vs ~5-6 ms for radar-speed
      triggering, keeping impact centered in the short buffer; (3) the
      persistent-mode requirement (`A!` + power cycle) works around an
      OPS243-A firmware bug (per OmniPreSense) where the HOST_INT pin
      mode switches when changing modes at runtime. Safe to characterize
      publicly now. (Our IWR6843/K-MC1 design needs none of this: the
      6843 streams point clouds continuously and self-triggers on
      Doppler, and the K-MC1 channel records audio continuously.)
- [x] git init the repo (AGPL-3.0-or-later, matching OpenFlight; `.gitignore`
      excludes `captures/` and `__pycache__/`) — done, see LICENSE.
- [ ] Confirm mains frequency in `spin_decoder.MAINS_NOTCH_HZ` matches your
      country (60Hz North America, 50Hz most everywhere else — already
      documented inline in the code).

## Deferred (revisit only if bench data says so)

- [ ] **Strike location + angle of attack (AoA)** — future metrics Johnny
      wants eventually. The data is ALREADY captured per shot: the
      pre-impact club track (the ball track's downswing prefix + club
      tracks) is archived in every radar .npz, so AoA (club descent angle
      at impact) and strike location (club path vs ball birth position)
      can be developed offline against archived captures later — no new
      capture format needed. Post-impact club data stays excluded from all
      metrics (see E-9 / club_cands window).

- [ ] DC output (or a 4-ch HAT to capture AC+DC) — revisit ONLY if real
      low-spin drill-rig bench captures prove AC-only insufficient. AC is the
      committed default otherwise.
- [ ] DCA1000 raw-ADC capture for true micro-Doppler spin on the 6843
      (only if the K-MC1 channel's bench results say the spin thesis needs
      it).
- [ ] RFbeam K-MC3 (larger antenna) if range/SNR proves insufficient.
- [ ] Titleist RCT balls (only if plain/foil-marked balls underperform in
      the rung-3 drill-rig test).
- [ ] **Short-game floor bench (rung 5)** — run `shortgame_probe.py --live
      --gate 4.5` when hardware lands: phase 1 idle false-trigger count,
      phase 2 real chips vs detections. Synthetic answer (2026-07-07,
      updated 2026-07-08): classifier floor 17 mph ball (≈4.5 yd) at
      100%, 14 mph at ~67-80%. The old BLOCKER (chip-speed practice
      swings phantoming ~58% — and, measured during the fix, 22-35 mph
      rehearsal swings phantoming 65-80% in ORDINARY play mode) is
      CLOSED by the T-14 chip-regime decay gate (audit #9 addendum):
      phantoms 0 at every probe gate, 1/220 residual across a 12-65 mph
      swing scan. A short-game session mode is now unblocked software-
      wise; what remains is the trigger-gate choice + these bench
      numbers. Hard walls regardless: no measured spin <17 mph, chip
      angles informational, no rollout model. Full list:
      openflight_iwr6843/docs/hardware-physics-limits.md.
