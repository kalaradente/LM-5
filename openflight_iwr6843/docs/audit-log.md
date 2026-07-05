# Pipeline audit log

Running log of top-down system audits. One entry per audit, newest first.
Each audit walks **five stages per radar channel** (the "air/spark/fuel"
framework): **physical input → trigger mechanism → processing → output →
upstream**. Findings get IDs (`F-n` for the 2026-07-04 code audit, `D-n`
for datasheet-driven findings) and carry forward between entries until
closed — an audit isn't just what's newly broken, it's the standing state
of everything found so far.

Primary sources live at `~/Desktop/datasheets/` — see
`datasheets-manifest.md` in this folder.

---

## Audit #3 — 2026-07-06 (every-button execution audit)

New emphasis per Johnny: don't re-read the code paths, PRESS them — every
CLI entry point and flag, every failure path, every cross-interface object
constructed for real. 45 buttons pressed (34 hardware-free + 11 requiring
the upstream symlink). Findings E-1…E-5, **all fixed same session**.

| ID | Sev | Button | Defect |
|----|-----|--------|--------|
| E-1 | MED | `analyze([])` (offline replay of an empty/corrupt archive) | IndexError crash instead of returning None. Guarded. |
| E-2 | MED | `decode()` on a short window (truncated audio archive, tiny capture) | scipy stft ValueError ("noverlap must be less than nperseg") — scipy shrinks nperseg to the input but our fixed noverlap didn't follow. `_ridge` now clamps both (identical hop in the normal case) and returns no-carrier below 64 samples. Verified graceful at 16/64/300/2000 samples; selftest bit-identical. |
| E-3 | MED | `IWR6843Monitor(...)` keyword construction | Parameter names read `(geom_port, data_port)` while main() passed `(cli_port, geom_port)` — positional wiring was correct by accident; any keyword caller following the names would have swapped the serial ports. Renamed to match reality. |
| E-4 | LOW | run_iwr6843 docstring | Referenced flags that don't exist (`--data-port`, `--control`). Corrected to the real ones. |
| E-5 | LOW | `AUDIO_DEVICE=2` in hardware.env | sounddevice treats a numeric STRING as a device-name substring, not an index — "2" would match any device with a 2 in its name. main() now converts digit-strings to int. |
| E-6 | ✔ verified | `ofserver.on_shot_detected()` with OUR hardware-mode Shots | The real-swing ingress (distinct from the socket ingress that Johnny's fake shots already proved live): pressed in-process with a full shot and a Nones-heavy chip shot, ballistics ON and table-fallback, session logger disabled AND enabled — 5/5 clean. Intel: the upstream logger writes to `~/openflight_sessions/` (absolute home path — that's where Pi session records will land). Only remaining unpressed transport: `socketio.run()` under run_iwr6843, which is the same flask app + emit path the fake-shot sessions exercised. |
| E-7 | LOW | `run_iwr6843 --club shovel` (side-effect ordering) | main() initialized the session logger BEFORE validating the club argument, so a rejected run still littered `~/openflight_sessions/` with empty session/radar-log files (audit #3's own button-press left a pair behind). Validation now precedes all side effects; re-pressed — file count unchanged on rejected runs. |
| E-9 | **MED, RULE (2026-07-05, Johnny)** | Spin decode window vs the descending clubhead | The K-MC1 never self-triggers (AudioRing only buffers; decode runs on the 6843's shot callback) — but the decode window opened 50 ms BEFORE impact, and that pre-window is the descending clubhead: bigger RCS than the ball, Doppler squarely inside the carrier band (~7 kHz for a driver club). Pressed with a synthetic club tone: decode FAILED OUTRIGHT (ok=False, no spin at all) at every contamination level — and the root cause was double: the window contained club frames AND `FreqTracker` seeded from the window's FIRST frame, locking onto the club then gating every genuine ball tone as junk. Two fixes, both verified across an 18-case matrix (3 shots × 2 windows × 3 club amplitudes, all now correct): (1) FreqTracker seeds from the MEDIAN measurement — the ball owns most window frames, so a minority of club frames gets gated instead of crowned; (2) the pre-window shrank 50 → 10 ms, now a clock-slack guard rather than a data window (justified by F-7's sharp birth anchor). Post-impact club overlap (~40 ms of beam-exit) is handled by the same median seed + junk gating. |
| E-8 | RULE (2026-07-05, Johnny) | `analyze()` output invariant | **Launch angle can never be < 0** — the ball leaves the ground. A negative fit is noise on a near-zero launch or club-blend contamination, never reality. analyze() now clamps to 0, penalizes `geometry_confidence` proportionally to the violation (−2° barely dents it, −10° gates hard), and preserves the raw value as `launch_angle_raw_deg` for replay tuning. Enforced by the simulator on every scenario/seed, plus a new worst-case `bump_and_run` scenario (20 mph at 6° — flat AND slow, no club/ball separation in any axis) where the raw fit goes −3.6…−9.5° on all 6 seeds and the clamp+penalty must hold. Scenario assertions refactored into explicit classes (full/chip/floor); the floor class asserts the invariant, ballpark speed, and that confidence reads LOW — the pipeline knowing it's blended is the deliverable. |

Pressed and verified-good (no defect): every simulator flag combination
(spin: defaults/full-flags/--missing-fundamental/--sweep; geometry:
default/--verbose/--sweep), spin_decoder --selftest + wav + --bench +
wrong-sample-rate error message, gain.py's all subcommands failing
gracefully off-Linux + argparse rc=2 with none, session.from_args,
validate.py on csv AND jsonl including row-count-mismatch warning and
missing-column skip, archive→load_capture→analyze round trip,
BallTracker/FreqTracker at n=1/2, decode on zeros (both modes), cold
AudioRing window decodes to not-ok, fuser jsonl logging on the audio=None
path, infer_spin edge clipping, GSPro unconnected send raising
ConnectionError (⊂ OSError — the monitor's handler covers it), GSPro
connect-refused raising OSError (run_iwr6843 continues without GSPro),
close-before-connect, run_iwr6843 --help / missing-ports exit /
unknown-club exit, shot_simulator all flags + bad-club exit, upstream Shot
constructed from both a full and a minimal fused dict with
smash_factor/club_speed_ms/estimated_carry_yards properties exercised,
get_session_stats at 0 and 2 shots, ofserver surface present, live_client
emit fields all present in the upstream patch, patch reverse-check clean
against the current upstream checkout, hardware.env written keys ==
read keys.

---

## Audit #2 — 2026-07-05 (all datasheets re-read, top-down)

Every document in `~/Desktop/datasheets/` re-read via pypdf extraction.
New findings D-1…D-9, plus status of carried-forward F-1…F-6.

### Findings summary (new this audit)

| ID | Sev | Stage | Channel | Finding |
|----|-----|-------|---------|---------|
| D-1 | **HIGH** | Physical input (USB) | Geometry | ttyACM/XDS110 port story is wrong for our topology — standalone ISK uses a **CP2105** bridge → `ttyUSB*` |
| D-2 | **MED → RESOLVED 2026-07-05** | Physical input (power) | Spin | Order K-MC1-RFB-00D (5V: power plan + 3.6dB clip headroom); Pin 1 /Enable has internal 10k pullup → hardwire to GND or the radar is silently off. Full harness reference: `kmc1-harness.md`. |
| D-3 | **MED → DOWNGRADED, guard landed 2026-07-05** | Physical input (signal) | Spin | Clipping is an FMCW/static-clutter phenomenon per the datasheet; in CW the 40Hz AC corner removes static returns. Link budget: ball has ~24dB headroom at 2m — only club-face specular glints (~ms at impact) can clip. `AudioRing` clip detector (plateau-run + ADC-FS tests, pre-normalization) tags `audio_clipped` and halves measured spin confidence. Bench rung 4 tunes the threshold. |
| D-4 | LOW | (documentation) | Spin | 47dB-vs-32dB mystery fully solved: both numbers are in the primary datasheet |
| D-5 | ✔ verified → **profile gap RESOLVED 2026-07-05** | Physical input (chirp) | Geometry | golf.cfg legal per chip datasheet; the surfaced 6.09 m ceiling is now addressed by `golf-outdoor.cfg` (10 m gate, same range res, ~43 driver fixes, auto-selected for outdoor sessions). |
| D-6 | **MED → CLOSED 2026-07-05** | Physical input (ADC) | Spin | DAC2 ADC Pro sheet obtained; gain.py verified (−12…+32dB, 96kHz, overlay, 2.1Vrms max in). Surfaced two new bring-up requirements, both fixed: ADC input mux must be `VINL1[SE]`/`VINR1[SE]` (wizard now sets it; wrong mux = silent capture) and PGA starts at 0dB (module clips internally below ADC full scale — negative gain protects nothing). |
| D-7 | ✔ verified | (bring-up docs) | Geometry | firmware-flashing.md SOP table matches SWRU546E §3.5.1 exactly |
| D-8 | LOW | Physical input (mount) | Spin | K-MC1 beam axes (12°H/25°V) assume a specific module rotation — confirm orientation at build |
| D-9 | ✔ verified | (bring-up docs) | Both | UniFlash flashes over the CFG/"Enhanced" COM port (= CP2105 iface 0); Pi 5 power plan viable |

### D-1 (HIGH) — Serial port class: CP2105 → ttyUSB, not XDS110 → ttyACM

SWRU546E §3.8 (Modular Mode, the xWR6843ISK REV C section): *"the power is
supplied through a single USB connector; the same connector J5 is also used
for data transfer through the CP2015 USB to UART emulator. When enumerated
correctly, the 2 UART ports are displayed..."* — "CP2015" is TI's typo for
the SiLabs **CP2105 dual UART** (the guide's own Figure 4-19 caption says
"CP2105 COM Ports"; a dual-port bridge matches "the 2 UART ports").

The **XDS110 exists only on the MMWAVEICBOOST carrier board** (§2.2.2
block diagram) — which we do not use. Therefore, running the ISK standalone
over its own USB (exactly our topology):

- **Linux/Pi**: driver is `cp210x` (in Raspberry Pi OS), enumerates as
  **`/dev/ttyUSB0`/`ttyUSB1`** — NOT `ttyACM*`.
- **Windows**: needs the **SiLabs CP210x VCP driver** — NOT TI's XDS110
  driver (that's only needed with the ICBOOST carrier).
- Port roles: CP2105 "Enhanced" = interface 0 = CFG/User UART (115200,
  our CLI port); "Standard" = interface 1 = Data port (921600). Confirmed
  independently by the UniFlash doc's port table (Enhanced = CFG port).

**This means commit 650ceb1 ("Fix ttyUSB->ttyACM") fixed it in the wrong
direction** — the original ttyUSB was right for modular mode. Wrongness
blast radius (all prose/comments, no logic): `run_iwr6843.py` docstring +
`--help` text + error text; `scripts/setup_wizard.sh` comments + error
hints (including a misleading "cdc_acm kernel regression" debug hint);
`openflight_iwr6843/README.md` examples; `docs/firmware-flashing.md`
"Windows XDS110 driver" section; `HANDOFF.md` bug list entry.

**Why nothing functionally breaks** (verified by reading the wizard):
the port auto-detect globs `ls /dev/ttyACM* /dev/ttyUSB*` (both), the udev
persistence rule matches on generic `ATTRS{serial}` + `bInterfaceNumber`
(works for any bridge), and the interface-number convention (0=CLI, 1=data)
happens to match the CP2105's Enhanced/Standard split. The damage is that
every human-facing instruction directs debugging at the wrong device class.

**Action**: sweep all five files' prose ttyACM→ttyUSB / XDS110→CP2105 /
cdc_acm→cp210x for modular mode, keeping a note that ttyACM/XDS110 applies
only if an ICBOOST carrier is ever used. → logged in TODO.md.

### D-2 (MED) — K-MC1 ordering variant + RSW pin wiring

K-MC1 Rev J ordering table: **K-MC1-RFB-00C = 3.3V version, K-MC1-RFB-00D
= 5V version** — distinct part numbers, distinct supply ranges (3.13–3.47V
vs 4.8–5.2V). The plan (TODO) is to power from the Pi's 5V GPIO header pin
→ **must order the -00D (5V) variant**. Also confirmed: Icc = 90–100 mA
enabled (validates the power-bank trickle-mode concern in TODO), and
**Pin 1 (RSW) must be wired to VIL** — at VIH the module drops into its
7–10 mA Rapid-Sleep-Wakeup mode and the radar is effectively off. That's a
harness wiring requirement, not a software setting. VCO pin: leave open
(CW operation, fTX stays within 24.050–24.250 GHz per Note 3) — matches
how the code models it.

### D-3 (MED) — In-module clipping on the AC outputs (bench flag)

The datasheet, on the AC outputs: *"these outputs may saturate and clip
because of too high input signals. In these cases you may use the x_DC
outputs."* The clipping happens **inside the K-MC1's own 32dB IF amp** —
before our signal chain. The HiFiBerry PGA (which we planned to start near
−12dB "to be safe against clipping") protects the *ADC*, but **cannot
undo module-internal clipping**. At 2m from a driver-struck ball (large
RCS, close range) this is a real possibility with no datasheet answer.
**Bench check to add to rung 4**: inspect the raw captured waveform for
flat-topping at realistic ball distances. If the AC path clips in-module,
RFbeam's own documented remedy is the DC (0dB, unbuffered) outputs — which
is exactly the deferred "DC fallback" TODO item; this is the concrete
failure signature that would trigger it. (A clipped carrier also *smears
harmonics across the spin band*, so the symptom in decode() would be
spurious high-confidence-looking spin evidence — worth remembering when
eyeballing rung-4 Audacity captures.)

### D-4 (LOW) — The 47dB/32dB story, finally complete

The plain K-MC1 Rev J datasheet's own product-description text says the
module *"includes a RF low noise amplifier and two **47dB IF preamplifiers**
for both I and Q channels"* — while its spec table says **GIF_AC = 32 dB,
GIF_DC = 0 dB**. So "47 dB" was never a web-summary hallucination; it's in
the primary datasheet's marketing blurb, and it describes the internal
preamp, not the net gain at either output pin (the DC pin is 0 dB — tapped
before/around the amp; the AC pin nets 32 dB). Lesson refined: within one
datasheet, **the electrical-characteristics table outranks the product
blurb**. `gain.py`'s 32 dB stands, unchanged. Also reconfirmed here:
AC bandwidth 40 Hz–15 kHz, Uos_AC = Vcc/2 ± 0.5 V, IF noise 22 µV/√Hz
@ 500 Hz, I/Q balance ±2 dB — all consistent with existing code/comments.

### D-5 (✔) — golf.cfg is legal per the IWR6843 chip datasheet

Checked our chirp profile against the chip's hard limits:
- Ramp slope 197 MHz/µs ≤ **250 MHz/µs max** ✔
- ADC sampling 8 Msps ≤ **12.5 Msps max (complex 1x)** ✔
- Max beat frequency at gate top: 197e12 × 2×6.09m/c ≈ 8.0 MHz ≤ **10 MHz
  max IF** ✔ — but this check surfaced a real constraint:
  **the outdoor 15m range gate is physically unreachable under this
  profile.** The binding limit is the ADC sample rate: 8 Msps complex-1x →
  max unaliased beat 8 MHz → **R_max = 6.09 m** (this is *why* the 6m gate
  works — it IS the profile's hard edge, not a free choice). The chip's own
  ceilings would allow more (12.5 Msps / 10 MHz IF → ~7.6m at this slope),
  and beyond that only a slope reduction extends range. So the SessionConfig
  outdoor preset's 15m gate: the `_apply_session` cfarFovCfg rewrite to 15m
  is harmless (the chip just has no bins past ~6.1m), but **real outdoor
  detection stays ≤6.1m unless an outdoor profile variant (slower slope
  and/or faster sampling) is added**. Until then the outdoor preset's wider
  gate buys nothing physically. And it *does* matter: a 165mph ball crosses
  2m→6.1m in ~55ms (~27 frames at 500Hz) — the same track length as indoors,
  so the outdoor preset's stated rationale ("extend to harvest more
  trajectory fixes") is defeated by the profile ceiling. The extended 0.45s
  window still helps the SPIN channel (audio dwell doesn't care about the
  radar range gate), but the geometry side gains nothing until an outdoor
  profile variant exists (slower slope and/or 12.5 Msps sampling → ~7.6m,
  or a purpose-built long-range profile). Logged in TODO.md.
- RF sweep 60 → 63.74 GHz inside **60–64 GHz band** ✔

### D-6 (MED) — Wrong HiFiBerry datasheet in the folder

`Datasheet DAC2 Pro – HiFiBerry.pdf` is the **DAC2 Pro** — playback-only
(192kHz/24bit DAC, overlay `hifiberry-dacplus-pro`, no ADC anywhere in its
specs; the "ADC" strings in the extraction are just the site nav menu).
Our board is the **DAC2 ADC Pro** (overlay `hifiberry-dacplusadcpro`,
PCM1863 capture front-end). Still missing from the folder: the DAC2 ADC
Pro datasheet and/or the TI PCM1863 datasheet. Until then, the capture
side's PGA range (−12…+32dB), input impedance (20kΩ), and 96kHz capture
rate rest on the previous session's reading of the PCM1863 sheet — almost
certainly fine, but not re-verifiable from what's on disk. Also a warning
hiding in plain sight: the two products' overlay names differ by a few
characters (`dacplus-pro` vs `dacplusadcpro`) — the wizard has the right
one, but this is an easy copy-paste trap.

### D-7 (✔) — SOP/switch table verified

`firmware-flashing.md`'s S1 table matches SWRU546E §3.5.1 for the ISK
REV C exactly: S1.1=SOP2, S1.2=SOP1, S1.3=SOP0; flashing = SOP 101,
functional = SOP 001, only S1.1 changes; S1.5 OFF routes the user UART to
USB J5 (required for modular mode — and for the CP2105 in D-1 to be in the
path at all). The one wrong thing in that file is the driver section (D-1).

### D-8 (LOW) — K-MC1 mounting rotation

The spec table's beam labels ("Horizontal −3dB beamwidth E-Plane 12°,
Vertical H-Plane 25°") describe the module in one specific physical
rotation. Wide-vertical × narrow-horizontal is exactly right for a rising,
boresight-bound golf ball — but only if the module is rotated the way the
datasheet's antenna diagram assumes. **At build time**: check the K-MC1
mechanical drawing (Fig. 3) for which edge is "up," and pin that into
`mounting.md`. Getting this wrong swaps the axes: 12° vertical would clip
high wedge launches badly.

### D-9 (✔) — Flashing path and power, cross-confirmed

UniFlash doc: flashing uses the **CFG/"Enhanced" COM port** — the CP2105's
interface 0, same port our wizard designates CLI. No JTAG/ICBOOST needed
for our flashing path (the ICBOOST doc in the folder documents the carrier
alternative we're not taking). Pi 5 brief: 5V/5A USB-C PD supply, 2×USB3 +
2×USB2 — powering the K-MC1's 90–100 mA from the Pi's 5V header is well
within budget (given the 5A supply and the -00D variant per D-2).

### Carried forward from Audit #1 — all still open

| ID | Sev | Status | One-line reminder |
|----|-----|--------|-------------------|
| F-1 | **HIGH** | **FIXED 2026-07-05** | Frame timing now `frameNumber × framePeriodicity` (parsed from cfg), host clock kept only as absolute anchor for audio sync; archives round-trip frame numbers (old archives fall back gracefully). Synthetic proof of severity: USB-chunked host stamps turned a 69.6 mph ball into **181.5 mph**; frame-number path lands within 0.6 mph. |
| F-2 | **MED** | **FIXED 2026-07-05** | `geometry_confidence` now folds the expected radial velocity into ±v_max_ext (derived from the cfg: ±28.4 native / ±56.8 extended) before comparing; golf.cfg's false "±50 m/s software unwrap" comment replaced with the real numbers and rationale. Club-speed aliasing note superseded by F-7 (see below). |
| F-3 | **MED** | **FIXED 2026-07-05** | `_parse` length-guards every TLV body before `frombuffer` and sanity-caps num_obj/num_tlvs — corrupt frames now drop + resync instead of killing the thread (synthetically verified: lying tlv_len → None, no exception). |
| F-4 | LOW | **FIXED 2026-07-05** | `CARRIER_BAND` low edge 1216 → 1223 Hz (7.6 m/s at the corrected 24.125 GHz λ). |
| F-5 | LOW | **FIXED 2026-07-05** | `AudioRing.window()` clamps requests to ring depth with a loud message — shifted window degrades gracefully instead of silently wrapping. |
| F-6 | LOW | **FIXED 2026-07-05** | Fuser now records `spin_radial_speed_mps` + `radar_speed_agreement` (min/max ratio) on every shot — diagnostic only, no gating until real data locates the cosine losses. |
| F-7 | **MED** | **FIXED 2026-07-05** | Speed-band classification replaced with track-level classification. Design (each piece proven necessary by a synthetic failure): (1) frame-wise best-error-first track clustering (point-order greedy steals the ball's birth point); (2) ball = best *ballistic suffix* across tracks — range gain ≥1.2 m + lag-monotonic range + fitted \|accel\| ballistic (a swing arc pulls 450–2000 m/s², a ball pulls g; threshold scales with the polyfit covariance or ~15% of real drives false-reject); (3) z-minimum head trim in DE-TILTED world z (ball launches up, club arrives descending; sensor-frame z hides a chip's climb); (4) **directional gate (Johnny's)**: everything at-or-behind the birth range is not the ball — fit only rows ahead of birth; (5) club speed = fastest pre-birth row (**max clubhead radial occurs precisely at the ball's first detection** — arc bottom, fully radial), with ball-Doppler-match rows excluded as stolen detections; smash gate widened to 1.8. Verified: `geometry_capture_simulator.py` (swing-arc club + ballistic ball + FoV gate + folded Doppler + chunked host stamps), 4 scenarios × 6 seeds = 0 failures. Driver club reads 2.4% low, iron 0.1%, no phantom practice-swing shots, no missed shots. |

### Known measurement limitations (documented, bench rung 5 owns the numbers)

- **Chip-class launch angle reads ~10° low** (systematic, all seeds): club
  and ball separate at ~1 m/s, so their detections interleave within
  position noise for most of the window and the angle fit blends the two
  objects. Speed is unaffected (±1.3 mph across seeds). Scrub attempts
  removed as many ball rows as club rows and were reverted as overfitting
  to synthetic noise; a pure-ahead-of-birth fit helps but can't fully
  un-blend. If it ever matters: joint two-track Kalman with a shared birth
  constraint. The simulator asserts chip SPEED only, angles informational.
- **Driver-class launch scatter ±2°** from position noise: the ball crosses
  the 6 m profile ceiling in ~54 ms (~27 fixes). Tightening it means a
  longer observation window — i.e., the D-5 outdoor profile variant.

### Five-stage matrix after this audit

| Stage | Geometry (IWR6843) | Spin (K-MC1) |
|---|---|---|
| Physical input | ✔ chirp legal (D-5); ⚠ port docs wrong (D-1); ⚠ outdoor range IF-limited ~7.6m (D-5) | ⚠ variant/RSW purchase+wiring (D-2); ⚠ in-module clipping unknown (D-3); ⚠ rotation check (D-8); ❓ ADC sheet missing (D-6) |
| Trigger | OPEN F-1 (host-clock timing) | slaved to geometry; F-5 minor |
| Processing | OPEN F-2 (alias), F-3 (TLV crash) | ✔ decode chain sound; F-4 cosmetic |
| Output | ✔ units/fields verified | ✔; F-6 opportunity |
| Upstream | ✔ Shot mapping; upstream source itself still unaudited (needs symlink session) | ✔ GSPro mapping |

---

## Audit #1 — 2026-07-04 (code-only, retroactive record)

First comprehensive pass, before the datasheet folder existed. Six findings
F-1…F-6 (see carried-forward table above for one-liners; full analysis in
that session's conversation, summarized into the table when this log was
created). Verified-good at the time: TLV parse math vs TI's wire format,
tilt-corrected launch geometry, RTS smoothers, harmonic-sum spin search +
honest confidence, fusion provenance, GSPro field mapping, shared
monotonic clock across radar/audio.
