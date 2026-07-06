# openflight_iwr6843

Drop-in acquisition layer for [OpenFlight] replacing the OPS243-A + dual
K-LD7 rig with two channels:

- **Geometry**: TI IWR6843ISK (60GHz FMCW, 3TX/4RX) over USB — ball speed,
  launch angle, side angle, club speed, shot trigger.
- **Spin**: RFbeam K-MC1 (24GHz CW, amplified I/Q) into a HiFiBerry
  DAC2 ADC Pro (stereo line-in HAT on the Pi) — measured spin RPM with
  confidence, falling back to inferred spin from launch conditions.

Everything downstream of OpenFlight's `on_shot()` (Flask, WebSocket, physics
engine, React UI) is untouched.

## Files

| File | Role |
|---|---|
| `iwr6843_source.py` | Serial bring-up, TLV point-cloud parser, shot detection, Kalman-smoothed trajectory → geometry metrics |
| `spin_decoder.py` | I/Q audio → Kalman-tracked carrier → demodulation → harmonic-sum ("tap-along") candidate bank → spin RPM + confidence. Pools evidence across harmonics, resists the missing-fundamental/octave trap, reports ambiguity honestly |
| `kalman.py` | Shared filters: `FreqTracker` (1D carrier, gated + RTS-smoothed), `BallTracker` (3D constant-velocity + gravity) |
| `session.py` | Session mode selector: indoor/outdoor × ball type (plain/marked/rct) → parameter presets for both channels + shot-record tags |
| `shot_fusion.py` | Audio ring buffer, geometry+spin merge with per-field provenance, OpenFlight publish adapter |
| `gspro_adapter.py` | GSPro Open Connect client (TCP JSON + heartbeat), fed by `run_iwr6843.py --gspro-host` |
| `gain.py` | HiFiBerry capture-gain control via pyalsaaudio (Pi/Linux only) |
| `validate.py` | Scores pipeline CSV output against an Eye XO / Trackman truth export |
| `golf.cfg` | IWR6843 chirp profile, indoor (design intent — diff against your SDK's demo profile before use) |
| `golf-outdoor.cfg` | Outdoor chirp profile: 10 m gate at indoor-grade range resolution; auto-selected by `run_iwr6843.py --outdoor` |
| `docs/` | Audit log (**required reading**), firmware flashing, K-MC1 harness, mounting decision, datasheets manifest |

## Wiring

Full buy-and-solder reference: `docs/kmc1-harness.md`. The short version:

- IWR6843ISK → one micro-USB to the Pi (CP2105 bridge → two `/dev/ttyUSB*`
  ports: CLI 115200, data 921600).
- K-MC1 (**order the -00D 5V variant**): wire the **AC output** pins —
  I → left line input, Q → right line input, same gain both channels;
  5V from the Pi's header through a ferrite bead + decoupling caps; and
  **Pin 1 (/Enable) hardwired to GND** — it has an internal pullup, so left
  floating the radar is silently OFF. AC is all you need: it's cleaner (no
  DC offset/hum) and reads every real flight shot, including low-spin
  drivers, because spin rides as sidebands on the kHz Doppler carrier (all
  inside AC's 40Hz–15kHz band).
- No custom PCB, no soldering beyond five header wires on the K-MC1
  (I, Q, 5V, GND, /Enable-to-GND).

## Bring-up ladder

(Same numbering as `HANDOFF.md` §8.)

0. Flash the IWR6843 firmware on Windows via Uniflash — see
   `docs/firmware-flashing.md`. The Pi never flashes the board.
1. TI mmWave Demo Visualizer + stock config: wave your hand (proves board).
2. This parser against the same stream: positions must match the visualizer.
3. Load `golf.cfg` (after diffing argument formats against your SDK version);
   roll balls through the beam with `BALL_MIN_SPEED` temporarily lowered.
4. K-MC1 side: hand-wave in Audacity → box fan (blade micro-Doppler) →
   drill-spun ball at known RPM: `python -m openflight_iwr6843.spin_decoder
   capture.wav --bench`.
5. Real swings; record everything (see Validation).

## Integration

```python
from openflight_iwr6843.iwr6843_source import IWR6843Source
from openflight_iwr6843.shot_fusion import ShotFuser, AudioRing

audio = AudioRing(); audio.start()
fuser = ShotFuser(publish=my_openflight_publish, audio=audio)
src = IWR6843Source("/dev/ttyUSB0", "/dev/ttyUSB1", "golf.cfg",
                    on_geometry=fuser.on_geometry)
src.run()
```

Match the dict fields in `shot_fusion.openflight_publish_adapter` to the
shot dataclass in your OpenFlight checkout.

## Validation

The pipeline logs everything it needs locally, per shot, on its own:

- `captures/radar_<id>.npz` — every triggered radar capture (hits AND
  misses), replayable through `analyze()`
- `captures/audio_<id>.npy` — the matching K-MC1 I/Q slice, replayable
  through `decode()`
- `captures/shots.jsonl` — one JSON line per fused shot: ball/club speeds,
  angles, spin + provenance, and the diagnostics upstream's Shot has no
  fields for (`geometry_confidence`, `radar_speed_agreement`,
  `audio_clipped`, session tags)

Against a truth unit's export, score it directly:

```
python -m openflight_iwr6843.validate captures/shots.jsonl truth.csv
```

The line that matters: `spin_rpm [measured]` RMSE must beat
`spin_rpm [inferred]` RMSE, per club. Until it does, the K-MC1 channel is
research, not product. Replace the placeholder coefficients in
`shot_fusion.infer_spin` with a regression fitted on your truth data.

## Status / honesty

Synthetic end-to-end tests pass (exact spin recovery at 6000/3000rpm through
noise and clutter; launch angle within 0.5° over 40 noise seeds; junk-fix
rejection). Nothing here has yet seen a real golf ball: `golf.cfg` CFAR
thresholds, the per-ball-type spin confidence floors in `session.py`,
tracker noise parameters, and the spin inference surface all need tuning
against real captures. Known open items:
plain-ball spin modulation depth at driver speeds (bench rung 4 — the old
"sub-revolution dwell" concern here was stale math: even the indoor 0.15 s
window sees ~6.5 revolutions at 2600 rpm), UART frame-skip monitoring at
high frame rates (logged automatically), per-unit RX phase calibration.
