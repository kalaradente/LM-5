# TODO

Running list of open items. Newest relevant item first per section.

## Hardware

- [ ] **AC/DC switch for the K-MC1.** Need a physical switch (not just a
      software toggle) to select which pair of output pins (AC or DC) feeds
      the TRS cable — the two are different physical pins on the module, so
      this is a wiring decision, not just a config value.
      - Requirement: **low-noise part.** This sits directly in the analog
        signal path before any amplification downstream, so switch quality
        matters — a noisy/high-resistance switch adds noise right where the
        signal is weakest.
      - Candidate part class: a small-signal RF/audio-grade slide or toggle
        switch (gold-plated contacts, low contact resistance) rather than a
        generic hardware-store switch. A mechanical DPDT (double-pole,
        double-throw) switch could route both I and Q simultaneously with
        one physical action. Needs a specific part picked and added to the
        parts list — not yet sourced.
      - Software side is done: `session.py`'s `kmc1_output` field
        ("ac"/"dc") already drives the right filter settings in
        `spin_decoder.decode()` via `spin_filter_kwargs`. Once the switch
        part is chosen, just flip that session setting to match.

- [ ] Pin the audio-capture thread to its own CPU core on the Pi (e.g. via
      `taskset` or `sched_setaffinity`) so real-time capture never drops
      samples under load from the rest of the pipeline. Needs real hardware
      under real load to test meaningfully — can't verify this from a
      synthetic test, only on the Pi once it arrives.

- [ ] Confirm HiFiBerry DAC+ADC Pro's current Pi 5 overlay/compatibility
      status directly on hifiberry.com before ordering (Pi 5 changed kernel
      overlay conventions since earlier Pi generations).

- [ ] Verify K-MC1 IF output level / DC bias against HiFiBerry's max input
      level and AC-coupling, per datasheet, before first power-on.

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
- [x] DC-offset removal + high-pass + mains notch filter (`clean_iq`)
- [x] Self-test CLI (`python -m openflight_iwr6843.spin_decoder --selftest`)
- [x] Raw capture archiving on every trigger (radar + audio, replayable)
- [x] Session mode selector (indoor/outdoor x ball type x AC/DC output)
- [x] GSPro Open Connect adapter, tested against a mock server
- [ ] Wire `SessionConfig` into `IWR6843Source` (currently the geometry
      side still uses hardcoded class constants for range gate / capture
      window rather than reading from session config — only the spin side
      is fully wired through `ShotFuser`).
- [ ] Fit real coefficients for `shot_fusion.infer_spin()` (currently a
      placeholder surface) once truth data exists.
- [ ] Fit real per-ball-type `spin_conf_floor` values in `session.py`
      (currently placeholders) from rung-3 drill-rig results.
- [ ] One-time audio/radar timestamp latency calibration (clap test:
      compare piezo trigger time vs. audio arrival time) so the
      `AUDIO_PRE`/`AUDIO_POST` window in `shot_fusion.py` is centered
      correctly rather than just generously padded.

## Process

- [ ] Diff `golf.cfg` against the actual `profile_*.cfg` shipped with
      whatever mmWave SDK version ends up flashed on the board — CLI
      argument counts vary by SDK release.
- [ ] Read OpenFlight's actual source/README once repo access happens, to
      confirm (rather than infer) the real reason for the sound trigger
      and rolling buffer, before posting anything publicly that
      characterizes his design.
- [ ] git init the repo (AGPL-3.0 to match OpenFlight, `.gitignore`
      excluding `captures/` and `__pycache__/`) before first bench session.
- [ ] Confirm mains frequency in `spin_decoder.MAINS_NOTCH_HZ` matches your
      country (60Hz North America, 50Hz most everywhere else — already
      documented inline in the code).

## Deferred (revisit only if bench data says so)

- [ ] 4-channel HAT upgrade to capture AC and DC simultaneously instead of
      switching between them (only worth it if the AC/DC switch + software
      filtering approach proves insufficient on real low-spin captures).
- [ ] DCA1000 raw-ADC capture for true micro-Doppler spin on the 6843
      (only if the K-MC1 channel's bench results say the spin thesis needs
      it).
- [ ] RFbeam K-MC3 (larger antenna) if range/SNR proves insufficient.
- [ ] Titleist RCT balls (only if plain/foil-marked balls underperform in
      the rung-3 drill-rig test).
