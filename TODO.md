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

- [ ] Resolve Pi 5 active-cooler vs. HAT stacking geometry before drilling
      the base plate (cooler sits under the HAT; may need a tall header,
      or mount Pi and HAT side-by-side with a short GPIO ribbon instead).

- [ ] Re-check mounting distance: plan for ~2m behind the ball (swing
      clearance + radar near-field), not the earlier 1-1.5m estimate.

- [ ] Solve K-MC1 power: confirm chosen USB battery pack has a low-current
      "trickle" mode, or switch to powering the module off the Pi's own 5V
      GPIO pin (module only draws ~90mA; many power banks auto-shutoff
      below ~100-150mA and will drop the module mid-session).

## Software

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
