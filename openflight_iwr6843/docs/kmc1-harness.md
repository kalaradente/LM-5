# K-MC1 ordering + harness (resolves audit D-2, mitigates D-3)

_Decided 2026-07-05 from the K-MC1 Rev J datasheet (see
`datasheets-manifest.md`). This is the buy-and-solder reference; the
rationale lives in `audit-log.md` D-2/D-3._

## What to order

**K-MC1-RFB-00D — the 5V version.** (The -00C is 3.3V; they are different
part numbers, not a jumper.) Two reasons:

1. Power comes from the Pi's 5V header pin as planned (Icc 90–100 mA,
   trivial against the 5A PSU).
2. The IF amp's output swing scales with Vcc: ±2.5V-ish rails vs ±1.65V on
   the 3.3V part = **+3.6 dB of in-module clipping headroom**, which
   directly buys margin against the D-3 clipping concern (club-face
   specular glints at impact).

## Pin table (module connector, AMP X-338069-8, 8 pins)

| Pin | Name | Our wiring | Why |
|---|---|---|---|
| 1 | **/Enable** | **→ GND, hardwired** | Internal **10kΩ pullup**: left floating the module is silently OFF (7–10 mA RSW sleep, no output). GND = active. A GPIO could control sleep later (boot-floating fails quiet, not on) — v1 is a solder joint, not software. |
| 2 | VCC | 5V from Pi header, through **ferrite bead + 10 µF ∥ 100 nF at the module** | Datasheet Note 1 wants a low-noise supply; supply rejection is −50 dB. Most Pi rail junk is low-frequency (below the spin carrier band) — the bead+caps cover the rest; mains hum is notched in software. |
| 3 | GND | Pi GND | Common ground with the HiFiBerry. |
| 4 | Q_AC | HiFiBerry input **right** | High-gain IF output, typical load 1 kΩ — the 20 kΩ input loads it negligibly (~0.04 dB). |
| 5 | I_AC | HiFiBerry input **left** | I=left / Q=right is what `shot_fusion.AudioRing` assumes when building I + jQ. Swapping them mirrors the Doppler sign — **harmless since audit #12 (A12-1)**: the decoder searches both spectral signs (the datasheet's ±90° I/Q convention never says which sign is receding, so sign-immunity is required, not optional), and `--selftest` now proves both orientations decode. |
| 6 | VCO in | **Leave open** | 5V version has an internal 4.7 kΩ pullup; open = CW operation somewhere within 24.05–24.25 GHz (Note 3). Worst-case ±0.4% speed-scale error vs the 24.125 GHz assumed in `spin_decoder.WAVELENGTH` — bench-checkable against a truth unit; not worth extra hardware. |
| 7/8 | I_DC / Q_DC | **Unconnected** (documented DC-fallback only) | The low-gain (0 dB) outputs "hardly enter into a saturation state" per the datasheet — this is the escape hatch if rung-4 bench captures show in-module clipping on the AC path. |

## HiFiBerry input side (DAC2 ADC Pro sheet, verified 2026-07-05 — audit D-6 closed)

- **Physical input**: either the onboard 3.5 mm input jack (I→tip/left,
  Q→ring/right, sleeve→GND — simplest) or the 6-pin **J4 header**
  (`R− R+ / GND GND / L+ L−`). J4 wired differentially (K-MC1 signal → +,
  K-MC1 GND → −) buys common-mode rejection over the analog run — the
  better option if the cable must pass near the IWR6843's digital lines.
- **ADC input mux MUST match the wiring** (wizard step 6 sets this):
  single-ended jack → `ADC Left Input = VINL1[SE]`, `ADC Right Input =
  VINR1[SE]`; J4 differential → the `{VINxP, VINxM}[DIFF]` selects. Wrong
  mux setting = silent capture that looks exactly like a dead radar.
- **Mic bias OFF, twice**: the mixer control (`ADC Mic Bias = off`) AND the
  board's mic-bias **jumpers left open** — bias voltage would inject DC
  into the K-MC1's output stage.
- **PGA start at 0 dB, not −12** (refined by the sheet's 2.1 Vrms max
  input): the K-MC1's own output clips at ~±2.5 V peak, *below* the ADC's
  0 dB full scale (±3.0 V peak) — the module always clips first, so
  negative PGA gain protects nothing and just discards 12 dB of level.

## Mechanical reminders (from mounting.md / audit D-8)

- Mount from the back with **M2.5 screws, depth < 3.5 mm** (threads "B").
  Never run the module without screws in "A".
- **Confirm rotation at build**: the 25° beam axis must be vertical, 12°
  horizontal (check the datasheet's antenna diagram for which edge is up —
  getting this wrong clips high wedge launches).

## Why the D-3 clipping fear is now bounded (summary)

- The datasheet attributes saturation to **FMCW** use (strong static
  returns, radomes). We run **CW**: static clutter lands at near-DC and the
  AC path's 40 Hz corner removes it entirely.
- Link budget for the ball (EIRP +16.5 dBm, G_rx 18.5 dBi, σ≈−25 dBsm,
  2 m): ≈ −73 dBm received → ≈ ±100 mV at the AC output vs ±2 V rails =
  **~24 dB headroom. The ball alone cannot clip** (and sits ~50 dB above
  sensitivity — good spin SNR).
- Residual risk: **club-face specular glints** (σ spikes 20–30 dB for a few
  ms around impact) can eat that headroom briefly. The golfer's body is
  ~19° off boresight — outside the 6° horizontal half-beam, −20 dB
  sidelobes — so body motion is antenna-rejected.
- Software now records a per-shot clip flag (`audio_clipped`, see
  `shot_fusion.py`) so a glint-corrupted capture can't masquerade as a
  high-confidence spin read. Bench rung 4 keeps the eyeball check; the DC
  outputs remain the documented fallback.
