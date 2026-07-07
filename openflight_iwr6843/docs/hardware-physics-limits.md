# Hardware & physics limits — the honest list

What this build CANNOT do, or cannot do well, for reasons that are **not
tuning**: antenna geometry, wavelength physics, RCS, sampling theory, and
missing sensors. Tuning-class items live in the audit log; this file is
the standing "don't be surprised" reference. Dated claims cite the audit
or probe that established them.

Companion: `shortgame_probe.py` (repo root) measures the short-game slice
of these limits synthetically today and on real hardware later (`--live`).

---

## 1. Geometry channel (IWR6843ISK, 60 GHz FMCW)

**Observation window is short and fixed by the range gate.**
Indoor gate is 0.3–6 m (IF-bandwidth-limited; outdoor ~0.3–10 m, still
IF-limited at ~7.6 m for full SNR — audit D-5). A driver crosses the
indoor gate in ~54 ms ≈ 27 fixes at 454 Hz. Every launch quantity is a
fit through that keyhole:

- **Driver-class launch angle scatter: ±2°** (position noise across ~27
  fixes; audit #7 known limitations). More window = outdoor profile, not
  a parameter.
- **Chip-class launch angle reads ~10° low, systematically** (audit F-7):
  at ~1 m/s club-ball separation the two objects interleave inside
  position noise and the angle fit blends them. Chip angles are
  informational, full stop. Speed is unaffected (±1.3 mph).
- **Elevation is the coarsest axis** (single TX2 row drives it): the
  fine-elevation ablation collapses launch error to ±0.5°, i.e. the
  error is antenna geometry, not code.

**TDM Doppler folding creates blind speed bands.**
v_max_ext at the 3-TX indoor profile folds real radial speeds near
multiples of ~85 mph (indoor) / ~107–141 mph (outdoor) toward bin 0 —
where static clutter lives. Clutter removal is OFF by design (audit V-6:
the chip's static subtraction erased folded balls before detection), and
auto-CFAR (M-9) compresses around it, but shots whose radial speed sits
near a fold multiple are genuinely harder detections — simulated drives
at 170–174 mph were missed 8/8 before the mitigations; the mitigation
narrows, not removes, the band.

**Doppler quantization: ~2.4 m/s (~5.3 mph) per bin.**
Raw per-point speed resolution before track fitting. Fitting sharpens the
estimate across fixes, but nothing below ~2 bins from DC (~11 mph radial)
separates cleanly from clutter leakage — this is the detection floor of
the radar itself (`shortgame_probe`: 8 mph balls invisible at any gate,
12 mph a coin flip, 14 mph ~83%, 17 mph 100%).

**Radial-only measurement, cosine error.**
Both radars measure speed along the line of sight. Placement behind the
ball (5–7 ft, M-7 wiggle) keeps the cosine near 1 for the launch segment,
but misalignment or a hard push/pull reads speed low by cos(θ) and biases
HLA. The teed-ball auto-detection narrows the aim assumption; it cannot
remove it.

**Club data is inferred, minimal, and radial.**
Club speed = fastest pre-birth radial return (arc bottom). There is no
face sensor: **no face angle, no loft delivery, no strike location, no
dynamic lie**. Face-to-path (why the ball faded) is inferred from spin
axis, which is itself inferred (below). Chip-class club reads carry 25%
tolerance under dirt.

**Single-target assumption.**
One golfer, one ball. A second mover in the gate (person, pet, second
ball rolling) is dirt the classifier must reject, not a supported case.

## 2. Spin channel (K-MC1, 24 GHz CW + HiFiBerry ADC)

**Hard floor: no measured spin below 17 mph ball speed.**
The Doppler carrier at 24.125 GHz is 1223 Hz at 7.6 m/s — the bottom of
`CARRIER_BAND`. Below that the tone sits in the mains-hum/low-frequency
mud. This is wavelength arithmetic, not a threshold to tune: every chip
and most pitches get **club-typical fallback spin, never measured spin**.

**Spin = amplitude-modulation sidebands; range- and dwell-limited.**
Dimple modulation depth falls fast with range; the usable dwell is
~200 ms of flight through the beam. Marginal shots produce honest
low-confidence decodes (the decoder reports quality; the UI shows
provenance) — but "measured, high-confidence, every shot" is not
achievable with one CW module at these geometries.

**Spin AXIS is not measured at all.**
A single CW radar sees total spin rate only. Axis (fade/draw tilt) is
estimated from flight geometry and fusion, and drives the tracer's curve
— treat axis as an inference with model error, not an instrument reading.

**Mains hum shares the low band.**
The decoder notches it (60 Hz harmonics cleanup), but hum is why the
carrier band floor can't just be lowered; pushing the 17 mph floor means
hardware (different mixer/output, higher carrier SNR), not code.

## 3. Flight model (RK4 drag+Magnus)

**One global Cd/Cl curve for one ball.**
Tuned to the TrackMan tour table at ISA sea level (2.2% carry / 3.2% apex
mean). Residual structure is physics we don't model per-shot:

- **Ball type unknown.** Range balls fly 5–8% shorter and spin lower than
  premium; the session `ball_type` tag exists but no per-ball aero
  profile does. A range-ball session reads systematically "LOW" against
  tour numbers and there is no way to know from radar alone.
- **Driver residual −7% carry**: a single curve can't nail both ends of
  the bag; documented, guarded by the golden test.
- **Atmosphere fixed at sea level / 15 °C** by explicit decision (raw
  carry). Altitude is ~6%/1000 m of carry; wind is unmodeled entirely.
  `simulate(air_density=...)` plumbing exists, unused.
- **No rollout model.** Carry only. The `total_yards` heuristic
  (30·cos(land angle)) is labeled non-physical and correctly not
  displayed — it computes +27 yd of "roll" for a 2-yd chip. Real rollout
  needs surface state (stimp/firmness) we cannot sense.
- **Spin axis fixed through flight** (no gyroscopic precession); spin
  decay is a fitted exponential. Second-order for display purposes.

## 4. System-level

**Latency floor is the capture window: 0.20 s indoor / 0.45 s outdoor**
plus ~0.1–0.3 s processing on the Pi. Physics: the flight must be
observed before it can be reported. Sub-200 ms "instant" display is not
achievable with this architecture and there is no reason to want it.

**Shot-to-shot floor: 2.0 s trigger cooldown** (rapid-fire rejection).

**Putting: out of scope.** Below the Doppler separability floor, no spin
channel, no rollout model — three independent walls.

**Short game (the 2-yd chip question, probed 2026-07-07):**
today's realistic floor is **~14 mph ball ≈ 3.5 yd carry at ~83%
reliability** (17 mph / ~4.5 yd at 100%), speed-only quality (angles
informational, spin fallback). Below that: 12 mph is a coin flip, 8 mph
invisible. Pushing the trigger to catch chip clubheads means gate ≈
4.0–4.5 m/s AND a chip-regime classifier pass first — ball-less
chip-speed practice swings currently phantom ~58% in synthetic dirt
(full-speed swings reject fine). `shortgame_probe.py --live` is the
bench-day script that turns these synthetic numbers into real ones.

---

*If a limit above ever moves, it moves because hardware changed (second
elevation row, face camera, different spin module, outdoor profile) or a
model gained an input (stimp, wind, ball profile) — not because a
constant got nudged. Constants live under golden tests now.*
