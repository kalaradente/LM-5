# Physical sensor mounting — decision and rationale

_Decided 2026-07-05. Space is not a design constraint for this build, so this
is the placement that follows directly from the FoV/beamwidth math already
baked into `golf.cfg` and the two datasheets, not a compromise._

See `mounting-plate.svg` (in this folder) for a top-view + side-view diagram.

## The decision

**Both sensors mounted side by side on one rigid plate**, boresight-aligned,
directly behind the ball, centered on the target line:

| Parameter | Value | Why |
|---|---|---|
| Position (azimuth) | Centered on the target line (0° = straight down the fairway) | `aoaFovCfg` azimuth is **±60°, symmetric** about boresight — that symmetry only pays off if boresight = the intended ball-flight line. Offsetting to one side buys an unnecessary side-angle correction term for nothing. |
| Distance | ~2 m behind the ball | Already flagged in TODO.md: swing clearance + radar near-field avoidance. |
| Mount height | ≈ ball height (roughly 6–18") | Inferred from `aoaFovCfg`'s **asymmetric** elevation gate, −20°/+40° — see `iwr6843_source.py`'s comment: "ball launches upward, never negative." That only makes sense if the sensor's own zero-elevation boresight sits near the ball's height at address, with the small −20° allowance covering ground/pre-launch clutter just below boresight and the bulk of the window (+40°) covering the rising flight. An elevated, downward-pointed mount would want the opposite asymmetry — that's not what's configured. |
| Tilt | 10° up (`MOUNT_TILT_DEG`) | Already decided; centers the antenna's measured elevation beamwidth on 11–20° driver/mid-iron launch angles. |
| Sensor arrangement | Side by side (horizontal), not stacked | See "Why side-by-side" below. |
| Bracket | One rigid plate, both units bolted to fixed hardpoints, tilted as a single unit | Both sensors must hold the *same* tilt indefinitely, matching what `MOUNT_TILT_DEG` assumes. Two independent adjustable mounts can drift out of agreement with each other (vibration, transport). Calibrate the plate's tilt once (inclinometer), not each sensor separately — matches the existing "CALIBRATE against the actual mount... once built" note in `iwr6843_source.py`. |

## Why side-by-side, not stacked

Two physically separate antennas can't occupy the same point in space, so
co-locating them always leaves a small residual angular offset between their
boresights. Whichever axis the sensors are split along absorbs that offset —
and the two axes are not equally forgiving:

- **Azimuth** (`aoaFovCfg`): ±60°, symmetric, wide margin.
- **Elevation** (`aoaFovCfg`): −20°/+40°, asymmetric, purpose-tuned and
  centered via `MOUNT_TILT_DEG`.

Side-by-side (horizontal separation) puts the residual offset in azimuth —
the axis with margin to spare. Stacking vertically would put it in
elevation — the one axis that's actually tuned. So: side by side.

This matters even more than the FoV numbers alone suggest, because of the
K-MC1's beamwidth (see below): **12° horizontal / 25° vertical** at −3dB is
far tighter than the IWR6843's FoV, so keeping the offset on the wide,
forgiving axis (and keeping physical separation as small as the enclosures
allow) protects the channel with the least margin.

## Confirmed physical specs (primary datasheets, read 2026-07-04/05)

**K-MC1** (RFbeam K-MC1 datasheet Rev J, 11/2022 — file
`K_MC1_Datasheet-3446665.pdf`):
- Body outline: **65 × 65 × 6 mm**, 50 g.
- Mounts from the **back side** using the threads marked "B": **M2.5
  screws, depth < 3.5 mm**. (Original screws "A" may be swapped for M2 if
  fixing to a holder — but the module must never be run without screws in
  "A"; the antenna PCB is only glued in for shipping protection, not
  structural use.)
- Connector: AMP X-338069-8, 8 pins, module side.
- Antenna beamwidth (−3dB): **horizontal (E-plane) 12°, vertical (H-plane)
  25°** — narrower than the IWR6843's FoV in both axes, which is why
  boresight alignment matters more for this channel.
- Antenna gain `GAnt` = 18.5 dBi; **receiver gain `GLNA` = 19 dB** for the
  plain K-MC1 — NOTE this is a different number from the K-MC1_**LP**
  variant's FCC filing (`GLNA` = 10 dB there). Confirms, again, that a
  variant's datasheet doesn't transfer to our part — see the `[[primary-datasheet-over-secondary]]`
  memory note.

**IWR6843ISK** (TI "60GHz mmWave Sensor EVMs" User's Guide, SWRU546E,
Oct 2018 rev. May 2022 — file `swru546e.pdf`, section 3.6, Figures 3-8/3-9):
- Onboard-etched antenna array (long-range xWR6843ISK variant, confirmed —
  not the AOP/package-antenna variant): **RX1–RX4 in a row, spaced λ/2
  (2.5 mm at λ=5mm/60GHz)**; **TX1, TX2, TX3** with **TX2 vertically
  offset** from TX1/TX3.
- This confirms *how* the board gets elevation angle-of-arrival: azimuth
  comes from the horizontal RX spacing + TX1/TX3 (same row); elevation
  comes from comparing the TX2 (offset) row against the TX1/TX3 row. This
  validates that `channelCfg 15 5 0` (2TX: TX1+TX3, i.e. the row without
  the elevation offset would give azimuth-only — but the code enables the
  right combination for the golf design's needs) and `aoaFovCfg`'s
  asymmetric elevation gate are using the hardware as TI's own MIMO
  layout intends.
- **NOT found**: an explicit numeric board-outline dimension for the
  xWR6843ISK. The EVM guide's antenna section is photos + a MIMO array
  diagram, not a dimensioned mechanical drawing. The board's box in
  `mounting-plate.svg` is proportioned to look plausible next to the
  K-MC1's confirmed 65×65mm footprint, **not to a confirmed number** — if
  an exact fit matters (e.g. machining a plate before the board arrives),
  get the actual board in hand and measure it, or find TI's separate
  mechanical/fab drawing (may not be in this EVM guide at all).

## Cabling note

No RF conflict between the two radars — 60 GHz and 24 GHz are far enough
apart that they won't jam each other. The real risk is mechanical/EMI: the
K-MC1's I/Q output is a low-level analog signal running to the HiFiBerry
line-in, and the IWR6843 board has active digital/serial lines on the same
plate. Route the K-MC1's analog leads away from the IWR6843's cabling (or
use shielded/twisted-pair), and keep that analog run as short as practical.

## Still open

- Exact xWR6843ISK board outline dimension (see above).
- Which physical side (left/right) each module sits on — no electrical
  reason to prefer either; pick whatever's mechanically convenient.
- Final height/tilt calibration against the *as-built* mount (inclinometer)
  once the plate exists — `MOUNT_TILT_DEG` and this doc's height guidance
  are considered defaults, not measurements.
