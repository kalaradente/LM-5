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
- [x] Session mode selector (indoor/outdoor x ball type)
- [x] GSPro Open Connect adapter, wired into `run_iwr6843.py` via
      `--gspro-host`/`--gspro-port` (optional; connect failure is
      non-fatal, launch monitor runs fine without it)
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
