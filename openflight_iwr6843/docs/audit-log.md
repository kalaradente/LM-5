# Pipeline audit log

Running log of top-down system audits. One entry per audit, newest first.
Each audit walks **five stages per radar channel** (the "air/spark/fuel"
framework): **physical input → trigger mechanism → processing → output →
upstream**. Findings get IDs (`F-n` for the 2026-07-04 code audit, `D-n`
for datasheet-driven findings, `V-n` for the 2026-07-05/06 Visualizer/SDK
User Guide chip-config audit) and carry forward between entries until
closed — an audit isn't just what's newly broken, it's the standing state
of everything found so far.

Primary sources live at `~/Desktop/datasheets/` — see
`datasheets-manifest.md` in this folder.

---

## Audit #7 — 2026-07-06 (speed-training / mode-switch surface, hostile-dirt audit)

Johnny's brief: "full audit and sanity check with dirt" on the previous
day's feature commit (de3572f: speed-training mode, live 3-way mode
switching, reorderable UI grid). Method: fresh-eyes code reading of the
whole shipped diff (LM-2 side + `patches/session_mode.patch`), then
adversarial execution at every stage — hostile-sim captures the feature
was never tested against (balls in speed mode, slow practice swings),
the run() loop driven end-to-end over fake serial ports with synthesized
TLV byte streams and mid-stream switch requests, and a live SocketIO
re-press of the whole control surface including the S-2 posture.
Findings `M-n`; **all closed same-day**.

| ID | Sev | Finding | Resolution |
|----|-----|---------|------------|
| M-1 | **HIGH — FIXED** | **A real ball hit in speed-training mode published as a fake swing.** Speed training is ball-less by definition, but users forget which mode they're in — and a ball is faster than the club that struck it, so the ball won `analyze_swing()`'s peak search: a 120 mph 7-iron ball published as a **116.4 mph "swing"** (+31 over the real 85 mph club — exactly the session-max corruption overspeed training can't tolerate), and one hostile chip seed unfolded an 18 mph ball to an **84.7 mph swing**. A rep with a ball in it isn't a training swing at all (different mechanics), and salvaging the club number instead proved unreliable (impact merge eats the pre-birth rows precisely then; salvaged reads scattered to 37 mph) — so the fix REJECTS the capture outright: `_pick_ball_track` (F-7's own ballistic-suffix judge) runs first, and any ball-bearing capture is ignored with a loud console line telling the user to switch modes. It archives like every trigger. Proven over the full hostile matrix (4 ball scenarios × 20 seeds = 80 captures): **0 leaks**, bare-swing envelope unchanged. Now a standing simulator assertion (run + sweep). |
| M-1b | **MED — FIXED** | **Fragmented-ball leftovers could still fake a fast swing.** When a chip ball fragments below `_pick_ball_track`'s floor (the known 1-in-20 V-7 chip case), its junk rows unfold to the fold shoulder and mutually "support" an 84.7 mph swing on a track whose real motion is chip-slow. Gross-rate sanity added after peak selection: the winning track's actual range motion (±20 ms window) must be ≥0.45× the claimed peak — at arc bottom the head's motion is fully radial, so a real peak always is. Rejection only on POSITIVE evidence (window evaluable and rate far under claim), so sparse burst-gap seeds aren't false-rejected. |
| M-2 | **MED — FIXED (real-phone confirmation still pending)** | **Hold-to-drag would lose to page scroll on real touchscreens.** Browsers latch `touch-action` at GESTURE START; the grid only flipped its `touch-action: none` class after the 280 ms hold fired, so the first finger movement would hand the gesture to the scroller and fire `pointercancel` — desktop pointer simulation can't reproduce this. Fix: a native non-passive `touchmove` listener on the grid that `preventDefault()`s only while a drag is active (no scroll has begun during a stationary hold, so first-move prevention keeps the gesture). React attaches touch handlers passively, hence the manual `addEventListener`. Code-level fix; one minute on an actual phone remains the confirmation. |
| M-3 | **HIGH — FIXED (play-mode finding surfaced by the swing work)** | **Slow practice swings published phantom SHOTS through `analyze()`.** V-7's "0/20 phantoms" was measured at 105 mph practice swings only, and its suffix fences (0.04 s span, 0.5 fill, covariance-scaled accel/anti-gravity) were implicitly sized there. A slower swing lingers longer at arc bottom — where its range-rate is genuinely ball-flat — and the hostile sim published an 80 mph swing as a **67.3 mph shot (launch 0.0°, conf 0.58)** and a 70 mph swing as **63.0 mph at conf 0.87**. Two fixes, each ablation-diagnosed against the offending suffixes: (1) **rate-consistency gate** in `_pick_ball_track` — a free ball's range-rate is near-constant (drag ~2%, LOS geometry partially cancels it) while a swing arc must accelerate into the bottom (~e^{8t}, measured +26%) or decay off it (~e^{-6t}, measured 31→21 m/s); least-squares slope of r(t) over the FIRST vs LAST THIRD (halves diluted the signal), reject when the larger side ≥12 m/s and >1.25× the smaller +2 m/s (thirds σ≈2-3 m/s; real drives sit ~8σ inside). Activation keys on the LARGER side because follow-throughs decay right through any absolute floor. (2) **fill floor 0.5 → 0.6**: the dirt model's own worst case (one max 8-frame burst gap in the shortest real suffix) leaves a real ball ≥0.65, while the one bottom-straddling sweep whose rate profile is genuinely flat measured EXACTLY 0.50 and rode the boundary. Proven: **wide scan 70–125 mph × 20 seeds = 140 bare swings through `analyze()`: 0 phantoms**; real-shot misses unchanged (1/20 chip fragmentation, bit-identical to HEAD — checked by running the committed code side-by-side); all scenario envelopes unchanged. `practice_swing_80` added as a standing scenario. |
| M-4 | **MED — FIXED** | **`_parse()` dropped legitimately-EMPTY frames, starving the mode-switch check.** The demo emits frames with `numDetectedObj=0` and no points TLV whenever the scene is quiet — normal output, not corruption — but `_parse` returned None for them, so `run()`'s per-frame pending-switch check could wait UNBOUNDED in an empty range (outdoor, strict CFAR) before applying a switch the user already requested; the pre-roll's aging clock starved too. Found when the execution test's quiet phases never advanced the loop. Fix: `num_obj == 0` frames now yield an empty `Frame` (trigger logic already handles zero-point frames — the simulator has always fed them); corrupt frames (claimed objects, unparseable TLV) still drop for resync. Execution-proven: an outdoor switch now applies on a completely empty scene. |
| M-5 | **LOW — FIXED** | `_pick_ball_track`'s docstring claimed it returns `(track_index, start_index)`; it actually returns `(range_gain, track_index, start_index)` — bit the audit itself (unpack crash). Docstring corrected. |
| M-6 | **LOW — FIXED** | Swings-only sessions rendered StatsView's play block as "All (0)" club tabs over zeroed ball aggregates. Play block now renders only when play shots exist; the swing summary stands alone. |

**Execution/wire coverage added by this audit** (beyond the findings):
the full mode-switch machinery ran end-to-end for the first time —
`run()` over fake serial ports fed synthesized TLV byte streams:
boot cfg stream, mid-stream switch to speed (applied between captures,
full re-stream with speed-session lines verified line-by-line), a
hostile swing capture publishing 105.8 mph (true 105) through
`on_geometry`, a coalesced rapid double-switch (outdoor request
overwritten by indoor before applying — single pending slot, last wins),
a driver capture then publishing 163.5 mph / 11.1° (true 165/13) through
`analyze()`, and a second run proving the outdoor chirp-file swap
(10 m gate, 3 ms frame period, v_max_ext 27.8 re-derived) applies on an
EMPTY scene. Live SocketIO re-press: **S-2 holds with the new ingress
present** (`simulate_shot`/`simulate_custom_shot` inert in hardware
posture), 12 rapid mode switches processed in order with correct final
broadcast, junk/malformed/absent payloads produce errors not crashes,
unsupported-monitor posture reports cleanly, and mixed sessions
(shots + swings) serialize `mode` tags on reconnect without fabricating
smash factors from ball_speed 0.

**Verified-good, no change needed:** `estimate_launch_angle` is safe at
ball_speed 0 (guards its divisions; the live wire test pushed a swing
through the full `on_shot_detected` path); `handle_get_session`
serializes via the patched `shot_to_dict` so reconnecting clients get
swing tags; the wizard's patch loop is nullglob-safe and idempotent
(reverse-check → apply → warn); both patches apply to pristine upstream
in either order and the patched tree builds (tsc + vite) and compiles;
fuser swing branch consults neither audio nor spin (E-9 trivially
preserved); GSPro never sees swings; `from_selector` whitelisting makes
the SocketIO ingress control-plane-only.

**Standing limits touched by this audit:** the fold-shoulder ambiguity
band (`speed_fold_ambiguous`, ±10 mph self-flagged) is unchanged — the
M-1b gross-rate gate rejects junk-supported shoulder peaks but cannot
resolve genuine in-band ambiguity (same physics as before). Real-phone
drag feel (M-2) and everything hardware-gated remain bench items.

### Same-day addendum: M-7 — placement wiggle + teed-ball auto-detection

Johnny's follow-up brief: users should be able to place the unit 5–7 ft
behind the ball with wiggle room — "can we autodetect balls and then
place filters around them?" First step was measuring what placement
actually breaks, which required teaching the simulator two things
reality already does: a parameterized sensor-to-ball distance (`tee_y`)
and a **teed-ball static** (a weak, flickery zero-Doppler return at the
tee that vanishes at impact — `teeball_p=0.45`, deliberately marginal
because real static-ball CFAR visibility against the mat is a rung-3
bench question). The honest baseline: accuracy already tolerates 5–7 ft
(driver/iron ≤1.3 mph mean error at every distance, 0 phantoms), BUT
the teed-ball static and placement interacted with the V-7/M-3 fences,
which were all implicitly sized at 2.0 m:

| ID | Sev | Finding | Resolution |
|----|-----|---------|------------|
| M-7a | **HIGH — FIXED** | **Driver misses at 6–7 ft placement (measured up to 3/20/seed-set)**: at 2.13 m a 165 mph ball has only ~3.9 m of gate left and impact merge eats its birth rows (worst measured: first visible flight row 0.82 m downrange), so real flights fell below the 40 ms span / 0.6 fill / 1.2 m gain floors that exist to kill phantoms. Also the **teed-ball static stitches onto the flight track** as a resting prefix (impact handoff in reverse), and one 7 ft bump-and-run fitted resting rows as flight — published launch **37.7° wrong**. |
| M-7b | **FIXED (the feature)** | **`_find_teed_balls()`**: compact, persistent, near-zero-Doppler clusters in the tee zone (0.9–3.2 m, ±25° az) that **VANISH before the capture ends** — the vanish is what separates a ball from bay clutter (walls persist) and is evidence nothing but a shot can arrange. Consumed two ways in `_pick_ball_track`: (1) suffixes may not START on a resting-ball row (kills the 37.7° class), and (2) a suffix born within 0.9 m of a lock inside [−30,+60] ms of its vanish is **anchored**: span/fill/gain floors relax (0.028 s / 0.45 / 0.9 m) because the vanish coincidence is independent evidence, while every kinematic gate (monotonic, accel, anti-gravity, rate-consistency) stays at full strength. NO LOCK = EXACTLY the old behavior — detection is best-effort by design and nothing downstream requires it. Each shot records `tee_range_m` (nearest lock), giving the user placement validation for free; measured dead-on (1.52/1.83/2.00/2.13) across the sweep. |
| M-7c | **FIXED** | Two swing-side placement defects: the M-1b gross-rate sanity rejected whole CAPTURES when the top candidate was a junk fold-branch pair (measured: an 85 mph claim on a track moving 3.3 m/s at 5 ft — a real rep thrown away); moved INSIDE candidate selection so inconsistent candidates lose their turn and the next supported peak gets judged. And a mis-arbitrated branch at 7 ft read +15.3 mph just past the ambiguity flag's band — the estimate-side band widened to 1.15·v_max_ext and `SWING_AMBIG_TOL` set to the measured 16. A gross-ratio flag was tried first and measured USELESS (accurate swings p5=0.76/median 0.84; the two bad reads at 0.76 and 0.92, inside the accurate distribution) — recorded here so nobody re-invents it. |

### M-8 — adversarial gauntlet against the lock machinery (same day)

Johnny's brief: "test it. throw real dirt at it and see if it passes."
It did not pass, twice, and the gauntlet earned its keep:

- **The vanish spoof worked (FOUND + CLOSED)**: a practice swing over a
  teed ball whose return dies at exactly club-passage (occlusion /
  marginal SNR — no shot) formed a legitimate lock, the club swept the
  tee inside the vanish window, and the anchored relaxation bought
  **5/160 club-arc phantoms, one at confidence 0.95**. Discriminator
  hunting: birth-downrange-of-lock measured DEAD (real births scatter
  −0.60..+0.50 m around the lock; phantoms inside that), middle-third
  rate shapes inconsistent — what separated the populations was
  **prefix motion**: every phantom carries its own downswing in the
  track's 30 ms prefix (30.8–37.9 m/s), while merge-delayed real
  flights birth out of silence or resting-ball rows (median 4.7 m/s).
  Fix: anchoring now requires a QUIET prefix (≤8 m/s or absent); real
  handoff suffixes with fast prefixes simply aren't anchored and face
  the full fences as always. Plus locks now require a dense vanish tail
  (≥2 detections in the last 60 ms) — a struck ball is full-RCS right
  up to departure, so a sparse flickery tail (the physical spoof) earns
  no lock. Re-run: **0/160 spoof phantoms**, and the standing sweep now
  runs one spoof check per seed.
- **Cranked dirt (falarm 2×, merge 0.85, body 1.0)**: one isolated
  95 ms follow-through phantom at conf 0.88 (1/144). Not a cliff —
  0 phantoms at 1×, 1.5×, and 3× falarm — a single unlucky assembly at
  exactly 2× design. Documented tail, not chased (V-7's overfitting
  lesson); the bay-side lever is `cfar_threshold_offset_db`.
- **Clean under the rest of the gauntlet**: persistent teed ball under a
  practice swing (no vanish → no lock → 0/40), junk persistent static
  inside the tee zone (1 miss/288, 0 phantoms/144), two-ball scenes
  (tee_range_m attributed to the HIT ball 20/20), out-of-band
  placements 4 ft/8 ft (0 misses, 0 phantoms, ≤2.5 mph).

### M-9 — automatic CFAR threshold ("the compressor", same day)

Johnny's brief: "can we apply an automatic cfar threshold? almost like
what a compressor would do on vocals — bring the lows up and the highs
down." Built exactly on that model, automating the V-6 escape hatch
(which was a manual knob) and giving the M-7 teed-ball lock more
sensitivity when the scene has headroom:

- **Sidechain**: idle-scene detection density (points/frame), measured
  ONLY while armed — capture windows and post-shot cooldowns are flushed,
  so shots are never compressed against (they're the vocals). M-4's
  empty-frame fix matters here: truly quiet scenes still tick the clock.
- **Curve**: corridor 1–8 pts/frame (BENCH-TUNABLE PLACEHOLDERS — real
  idle density is a rung-3 measurement). Flooded → thresholdScale up
  1.5 dB/step ("highs down"); starved → down 1.5 dB ("lows up"). Slow
  attack/release: 4 s windows, 10 s cooldown, clamp −6..+12 dB around
  the session baseline, no churn when pinned at a rail.
- **Limiter**: UART frame-skips (real link saturation, the V-6 fear)
  step +3 dB immediately, cooldown notwithstanding.
- **Actuation**: the mode-switch machinery's safe-point cfg re-stream
  (`_request_cfar_retune`); a queued mode switch outranks a retune, and
  a mode switch RESETS the auto term (new venue, new scene).
- **Honesty**: every adjustment prints with its reason; shot/swing
  records carry `cfar_auto_db` when nonzero so validation can group by
  detector state. `--no-auto-cfar` disables the whole loop.

Verified closed-loop against a RESPONSIVE fake chip (idle density a
function of the threshold actually written to the fake CLI port — the
loop must converge, not ratchet): flood 20 pts/frame → three +1.5 dB
steps → corridor → quiet; a real driver capture mid-session published
at 163.4 mph with the correct stamp; a skip burst fired the limiter
+3 dB through the cooldown; a mode switch reset to 0; a starved scene
descended to the −6 rail and stopped. Wire-level cfarCfg values tracked
every step. (The test's first run also re-proved the parser's resync
path: a malformed empty-frame in the FAKE's serializer desynced the
stream and the parser recovered exactly as designed, skip-counting all
the while — harness bug, product behaving.)

**Final measured envelopes across 5–7 ft (20 seeds × 4 placements),
post-M-8: real-shot misses 3/320 — all ONE seed** (driver seed 16, a
merge-eats-everything draw whose tangled birth has fast prefix rows, so
the M-8 prefix-quiet rule correctly refuses to relax fences for it;
same residual class as V-7's accepted 1-in-20 chip fragmentation — not
chased, per V-7's own overfitting lesson, and the trade against a
confidence-0.95 phantom hole is obviously right). **Phantoms 0/160,
swing failures 0/240** (~50% of 80–95 mph swings carry the
fold-ambiguous flag — their raws genuinely touch the shoulder; 105/120
unflagged), **M-1 leaks 0/20**. The sweep now cycles placements
(`TEE_SWEEP`), runs a vanish-spoof check per seed, and the teed-ball
static is on by default in every synthesized capture.

---

## Audit #6 — 2026-07-05/06 (chip-configuration audit vs the Demo Visualizer + SDK User Guide)

Johnny's brief: the Demo Visualizer screenshots (in
`~/Desktop/datasheets/mmwave visualizer user guide/`) are the entire
configurability surface of the 6843 — study them plus the Visualizer
User's Guide (SWRU529C) and the chip datasheet, and sanity-check every
golf.cfg choice. Mid-audit he added the missing primary source that
settled everything: the **mmWave SDK User Guide 3.6 LTS** (now in the
same folder). Every finding below is traced to one of those documents.

| ID | Sev | Finding | Resolution |
|----|-----|---------|------------|
| V-1 | **CRITICAL — FIXED** | **Both chirp profiles enabled the wrong antennas: no elevation.** `channelCfg 15 5 0` = TX bitmask 0x5, which the SDK UG's own ISK example defines as "the 2 azimuth antennas" (TX1+TX3); elevation needs **0x7** (TX2 is the vertically-offset antenna, per the SWRU546E array figures already on record). With no elevation TX the demo cannot estimate elevation — every point arrives z=0 and **launch angle, the flagship metric, is structurally dead**. The golf.cfg comment claimed "TX1+TX3 for azimuth+elevation" — plausible-looking, wrong, and matched against the Visualizer's DEFAULT dropdown (`4Rx,2Tx(15 deg)` — TI's generic default, which has zero elevation resolution; the guide: only configs "with non-zero Elevation resolution" produce 3-D output). Fixed: `channelCfg 15 7 0` + third `chirpCfg` (mask 2) in both cfgs. Would have surfaced at rung 3 as every-launch-angle≈0; caught on paper instead. |
| V-2 | **HIGH — FIXED, then CONFIRMED against a generated cfg** | **Seven mandatory CLI commands missing from both cfgs**: `bpmCfg` (mandatory for the xwr68xx demo — it uses the DSP Doppler DPU), `lvdsStreamCfg`, `CQRxSatMonitor`, `CQSigImgMonitor`, `analogMonitor`, `measureRangeBiasAndRxChanPhase`, `calibData`. The SDK UG marks each "mandatory"; the demo tracks config completeness and refuses sensorStart. The audit-#2 arg-count audit only checked commands that were PRESENT — completeness against the mandatory list was never checked. Fixed: stock disabled/no-op forms appended to both cfgs. **2026-07-06: Johnny exported the Visualizer's own generated default (`3.6 EDITABLE DEFAULT CONFIG.cfg`, now in `~/Desktop/datasheets/`) — all seven commands appear in it with exactly the values we adopted, argument for argument.** |
| V-3 | **HIGH — FIXED (cascade + two pre-existing bugs found)** | **3 TX shrinks v_max**: native = λ/(4·Ntx·Tc) → extended ±37.9 m/s indoor / ±27.8 outdoor (`extendedMaxVelocity` is exactly "up to (2*vmax)" per the UG — also validates `_parse_vmax_ext`'s hardcoded ×2; the parser derives Ntx from the cfg so it adapted automatically). Five consequences worked through `analyze()`, each proven by the upgraded simulator: (1) the Doppler-magnitude pre-filter became a trap — balls folding to ~0 m/s (**~160–178 mph indoor, ~115–133 mph outdoor**) were silently deleted; filter removed, static clutter now rides through clustering and dies by having no ballistic suffix (sim grew two static reflectors to prove it). (2) A driver clubhead (~49 m/s) folds to ~26.7 — club speed is now **unfolded against the club track's own per-row local range-rate** (positions don't fold; branches ≥13 m/s apart where distinguishable, convergent-and-harmless near v_max_ext). (3) `geometry_confidence`'s relative-error denominator (folded Doppler, ~2 m/s on the best drives) floored at 0.1·v_max_ext. (4) Chip-speed impact handoff started interleaving ball/club tracks once slow club tails survived (the old filter had been accidentally deleting them): fixed with a capped **Doppler tie-break in track assignment** (5 cm/(m/s), max 15 cm) plus a 3-row velocity baseline (2-point finite difference at 2.2 ms = ~40 m/s noise, which was splitting real ball tracks). (5) Two **pre-existing latent bugs** exposed and fixed: the z-kink trim's smoothing zero-padded edges (`convolve mode="same"`) so the phantom edge zero pinned argmin to row 0, silently disabling the trim; and the trim searched the GLOBAL z-minimum, which for a flat bump-and-run (apex inside the window) is the track END — it once trimmed to 4 tail rows of confident garbage. Now edge-padded and first-half-only. |
| V-3b | **HIGH — FIXED (the big one)** | **Gravity back-extrapolation sign bug in `analyze()`**: `vel += -9.81·(sin,cos)·dt_launch` applied gravity FORWARD for another dt_launch instead of undoing it — doubling the gravity drop between launch and mid-track readout. Error grows with track length: ~0.4° on a driver (invisible), **~2 m/s of vz on chip-length windows**. This was the dominant share of the documented "chip-class launch reads ~10° low" limitation (previously attributed to club/ball blend physics) and most of what E-8's clamp was actually clamping. Found by tracing a pure-truth-ball fit that still read 16.3 mph / 5.4° where straight-line displacement said 17.9 / 23.2. After the flip: **chip launch 21.6° vs 22.0 true; bump-and-run raw fits no longer go negative; every scenario's launch within 0.7°**. The E-8 clamp stays (real noise can still cross zero), but the sim's floor-class "confidence must read LOW" assertion was retired as wrong — replaced by "a flat shot must never be reported lofted" (launch < truth+8°). |
| V-4 | **MED — FIXED** | **The SDK UG caps active chirp time at 50% of the frame period** (demo asserts beyond it) and requires numLoops be a multiple of 4 on xwr68xx (DSP Doppler windowing). 48 chirps × 22 µs = 1.056 ms means the old 2 ms indoor period would run 52.8%: periods now **2.2 ms indoor (454.5 Hz, 48.0%)** and **3.0 ms outdoor (333 Hz, 48.0%)**. Driver fix budget: ~25 indoor / ~36 outdoor (was ~27/~43 under 2 TX). Chip datasheet cross-check: device lifetime (100k POH) is specified at 50% RF duty — same ceiling from the silicon side. Incidentally: golf-outdoor.cfg's old comment claiming "70% indoor duty" was arithmetic rot (it was 35%). |
| V-5 | **LOW — chirp order CLOSED 2026-07-06; one bring-up check remains** | (1) **Chirp order — CONFIRMED, no longer a rung-1 question**: Johnny exported the Visualizer's own generated 3-TX cfg (`3TX CONFIG.cfg` in `~/Desktop/datasheets/`): `channelCfg 15 7 0`, chirps in exactly our order (masks 1, 4, 2 = TX1, TX3, TX2), `frameCfg 0 2 16 ...`. One divergence found and adopted: TI keeps `bpmCfg -1 0 0 1` (disable range spans only the two AZIMUTH chirps — BPM's TXA±TXB pattern never involves TX2), where we had generalized to `0 2`; both cfgs now match TI verbatim. The same file re-confirms the 25-value compRangeBias line under 3 TX and that the stock default's differences from golf.cfg are all ones we hold deliberately. (2) **z-axis sign/orientation** — at rung 2, raise a hand above boresight and confirm z goes positive with the board in its final mounting orientation. (3) The "indoor clutter dead band" originally documented here as a known limit was PROMOTED to finding V-6 and FIXED — see below. |
| V-6 | **HIGH — FIXED (Johnny's question: "how accurate are we in that zero bin?")** | **Indoor clutterRemoval was deleting real shots at two prime speed bands — turned OFF in both sessions.** The chip's static-clutter subtraction erases Doppler bin 0 BEFORE detection, and TDM folding parks real balls there at every multiple of 2·v_max_ext: **~83–87 mph** (mid-iron/wedge balls, and driver CLUBHEADS at arc bottom) and **~167–172 mph** (good drives). The earlier "10–25 ms of lost early fixes" estimate was WRONG in the optimistic direction: a dragged-ball simulation (k=ρC_dA/2m ≈ 4.8e-3 /m, chip-model: hard drop inside bin 0, 50% flicker one bin out) showed drag bleeds only ~1.2 m/s of radial speed across the whole 6 m gate while LOS-alignment geometry partially cancels it — so **drives launched 170–174 mph were missed outright on 8/8 seeds** (never a shot), and 165–169/175–180 lost half their fixes. With clutterRemoval off the same sweep measures every speed 150–180: 0 misses, ~21 fixes, ≤3 mph error, launch flat at 12.9–13.0. Bay statics are the pipeline's job now — already proven: the geometry simulator plants two static reflectors and the classifier rejects them as non-ballistic loiterers on every scenario/seed (V-3 groundwork). Escape hatch if a real bay floods the UART at rung 3: raise the indoor CFAR threshold via `cfar_threshold_offset_db` — never re-enable clutter removal. Changed: `session.clutter_removal` → False both environments, `golf.cfg` clutterRemoval line, comments in `_apply_session`. |

| V-7 | **HIGH — FIXED (Johnny's brief: "can you really be stress testing? throw clutter in")** | **The simulator was too polite, and honest dirt broke the pipeline in five distinct ways.** The observation model was rebuilt hostile-by-default (`observe()` in the simulator): anisotropic spherical noise (elevation 1.7°·range — the single-TX2-row axis; azimuth 0.7°; range bin-quantized + 2.5 cm), Doppler native-fold + 2.37 m/s bin quantization + occasionally WRONG ×2-extension hypothesis (the UG's own caveat, raised to 40% while club and ball share a range bin), two static reflectors, a swaying golfer with downswing surge, 12%/frame CFAR false alarms, club/ball detection MERGE near impact, and a 4–8-frame UART burst gap. First run: driver +12.9±30.8 mph (a 267 mph "shot" at confidence 0.83), iron +6.4±18.6, and **2/20 phantom shots on practice swings** (the clubhead's own arc-bottom sweep, 97 mph at confidence 0.94). Root causes and fixes, each ablation-diagnosed: (1) **false-alarm chains** — random pairs bridged multi-frame gaps under the 90 m/s immature gate and outbid the real ball on range gain; fixed by per-axis noise-normalized association (`_meas_sigma`), a 3.5-frame association cap for velocity-less tracks, killing tracks whose prediction exits the range gate, the Doppler tie-break counting toward ADMISSION (not just rank), a 105 m/s implied-rate ceiling, a 40 ms minimum span (fastest real ball needs 42 ms to cross the gate), and a ≥50% detection fill ratio (a real ball is detected nearly every frame; the phantom's tail was 7 rows in 40 expected). (2) **The short-window accel-test blindness** — quadratic-coefficient variance grows as 1/T⁴, so the covariance-scaled ballistic threshold went toothless exactly on short suffixes; fenced by the span floor + moving the z-kink head trim INSIDE the suffix picker (descent-conditioned >6 cm, first-half-only — the same first-half lesson analyze()'s trim already carried). (3) **BallTracker's velocity seed** — first-3-rows seeding let one junk birth row poison the prediction, the 5σ gate then rejected the REAL rows (a 7-iron read 176 mph / 59° off n_fixes 5-of-29); median-of-endpoints seed now, FreqTracker's E-9 lesson applied to 3-D. (4) **Flat-slow blend** — a bump-and-run's club approach prepends seamlessly and its z-kink drowns in elevation noise (5 cm climb vs 6–9 cm noise): one seed published a 40° "flop" at chip speed; fixed by a Doppler-STEP birth trim (ball = smash × club Doppler, a ~1.5× step, clean where nothing folds; 90th-percentile guard so one wrong-hypothesis row can't disarm it; fold regimes provably untouched — their prefixes are Doppler-high and the z-trim owns them). (5) **Isotropic Kalman R** over-trusted elevation exactly where it's worst; per-measurement anisotropic R now (range-scaled z/x variances, floors keep old close-range behavior). (6) **The club-speed unfold's candidate spacing was conceptually wrong** (Johnny caught the symptom in the result table): candidates stepped by 2·v_max_ext, which only models FOLDING — but the demo's ×2 velocity extension can also pick the WRONG hypothesis (the UG's same-range-bin caveat), shifting labels by odd multiples of 2·v_max_native. The true speed of a wrong-hypothesis club row was not in the candidate set at all, so a row labeled 9.5 m/s at true ~46 unfolded to 66.2 and published a 148 mph "clubhead" at a plausible smash factor. Candidates now step at v_max_ext (= 2·v_max_native), covering both error modes; two defense layers added behind it (67 m/s physical club ceiling; a motion-based stolen-row filter — a pre-birth row whose local range-rate matches the ball suffix's own rate IS the ball regardless of its Doppler label, and the Doppler stolen-filter tolerance gained a 1.5-bin quantization floor). Driver club worst error 38.2 → 9.5 mph. **Final 20-seed hostile envelopes: driver −0.4±1.0 mph / launch ±1.0° (worst 2.1°), club −0.3 worst 9.5; iron ±1.4 / ±2.4° (worst 5.4°), club 20/20 read; chip ±0.7 mph; bump ±0.5 mph / ±3.0°; phantoms 0/20; one residual chip miss (1/20, track fragmentation at the separability floor).** Simulator assertions now encode these measured envelopes, with body_p/merge_p/falarm_p ablation knobs for future regression-hunting. |

**Residual honest limits after V-7** (quantified, not estimated; bench rung 5
owns the underlying σ_el):
- **Launch-angle scatter is elevation-noise-limited**: full-swing tolerance
  6° at the placeholder σ_el=1.7° (the fine-elevation ablation collapses it
  to ±0.5°, so the estimator isn't the bottleneck — the antenna is).
  Real-board σ_el decides the real number; the RX phase calibration
  (compRangeBias measured string) is the lever.
- **Chip-class launch reads −3.6±3.8° (worst 13.6°)** under full dirt —
  the F-7 separability floor, now measured instead of estimated (the old
  "~10° low" claim was retracted in V-3b; this is what actually remains).
- **Chip-class shots can fragment under maximum dirt**: 1-in-20 missed
  chip in the hostile sim. Speed and spin still carry the short game.
- **Club speed under dirt**: ~25% of driver seeds read None (merge/flicker
  eats the pre-birth rows) and survivors scatter ±10 mph; honest per the
  quantized-Doppler + unfold pipeline. GSPro ClubData is optional anyway.
- **Retracted this audit**: the README's "driver-spin dwell
  (sub-revolution observation)" concern — stale math from an early 50 ms
  design; the 0.15 s window sees ~6.5 revolutions at 2600 rpm.

**Also verified-good against the same primary sources** (no change needed):
`guiMonitor -1 1 0 0 0 0 1` = point cloud + side info + stats (exactly what
the parser reads); `adcCfg 2 1` (16-bit, complex 1x — "only complex modes
supported"); `lowPower 0 0` (low-power ADC mode unsupported on xwr6xxx);
aoaFovCfg/cfarFovCfg arg orders; cfarCfg dB threshold semantics
(re-confirmed in this UG copy, now on disk); the Visualizer's tuning
surface (CFAR dB sliders, peak grouping, FoV gates, clutter removal) maps
1:1 onto commands golf.cfg already sets deliberately; frameCfg float
periodicity is legal. The radar-cube memory check passes with 12 virtual
antennas (≤~196 KB vs 768 KB L3 for both profiles).

**Measurement-limits ledger, updated:** the "chip launch ~10° low" entry
from audit #3 is **retracted** (it was V-3b, a code bug, not physics).
Driver-class launch scatter ±2° from position noise stands, now at ~25
fixes indoor (the outdoor profile's ~36 remains the lever). Elevation
angle noise per point is expected to be the weakest axis on real hardware
(single λ/2 elevation baseline; the measured `compRangeBiasAndRxChanPhase`
string at bring-up matters directly for it) — bench rung 5 owns the number.

---

## Audit #5 — 2026-07-05 (real-stimuli audit; supersedes failed #4)

The escalation beyond #3's button-pressing: feed the organism synthesized
REAL-WORLD STIMULI and verify what comes out the other end. 13 stimulus
scenarios in three parts, run against fake serial ports, a painted audio
ring, live TCP sockets, and the actual SocketIO wire.

| ID | Sev | Stimulus | Result |
|----|-----|----------|--------|
| S-1 | **HIGH — FIXED** | UART stream goes silent mid-capture (sensor unplug) | `frames()` busy-spun FOREVER on empty reads — `run()` wedged inside its capture loop at 100% CPU, shot lost, nothing logged. So severe it hung even the happy-path harness (stream ending right after a shot). Fixed: idle-read guard (~40 empty reads ≈ 2 s at the 50 ms port timeout, vs a 2–2.5 ms frame cadence) ends the generator with a loud message; `run()` finishes the capture with what it has and returns to its caller (the monitor thread exits cleanly, restartable). Re-pressed: dying stream → clean return in <1 s. |
| S-2 | ✔ security property | `simulate_custom_shot` at both server postures | The original C3 press FAILED — and the failure was the correct diagnosis path: the handler is guarded by `isinstance(monitor, MockLaunchMonitor)` by design ("only works in mock mode" per its own docstring), so my assertion was wrong, not the code. Full posture matrix now pressed live: **hardware posture → injection is a NO-OP** (a web client cannot inject fake shots into a real session — a guard breach here would have been the real bug); **mock posture → typed values round-trip the live wire** (`simulate_custom_shot` → MockLaunchMonitor → on_shot_detected → 'shot' event received with ball 150.0 / spin 3000 / RK4 carry 260 — the exact path Johnny's fake-shot sessions used, now under audit evidence rather than field memory). |

**Part A — geometry channel fed real bytes (6/6).** Synthesized the TI TLV
wire format (40-byte header, detected-points + side-info TLVs, 32-byte
padding), serialized a full driver swing, and pushed it through the REAL
`frames()`/`run()` path as a chunked UART stream (1–4096-byte reads) with
3 KB of leading garbage, one frame whose header lies about totalPacketLen,
and one dropped frame. Result: trigger fired, capture archived, analyze
recovered 165 mph/13° within tolerance, the frame-skip warning printed, the
corrupt frame resynced, the garbage flood (200 KB, no magic) trimmed the
buffer and recovered the next frame. `configure()` pressed against fake
CLI serials for BOTH cfgs: session rewrites verified ON THE WIRE
(sensorStop first, sensorStart last, outdoor gate/clutter/CFAR lines
correct). `stop()` puts sensorStop on the wire and closes both ports. A
mid-stream `SerialException` (simulated unplug) is contained by the
monitor wrapper.

**Part B — spin channel with a painted ring (4/4).** AudioRing's buffer
painted with a realistic K-MC1 timeline (club tone ramping in 60 ms
pre-impact, ball carrier + 2600 rpm spin AM after) and the fuser left to do
its OWN clock math: measured spin 2620/2600, confidence 1.0,
radar_speed_agreement 1.0, audio archived, jsonl written. In-module-clipped
variant: flagged AND demoted to inferred (the D-3 guard chain working
end-to-end). Dead K-MC1 (noise only): graceful inferred fallback. Ring
thread-safety: 4 concurrent capture callbacks vs 150 window slices, no
corruption. Harness lesson recorded: the first B1 run FAILED because the
synthetic K-MC1 was painted at 102% of ADC full scale — the clip detector
correctly flagged it; real-stimulus tests must respect the documented gain
staging (ball ~24 dB below FS), and the "failure" doubled as a live
demonstration of the guard chain.

**Part C — live upstream transports (3/3).** GSPro client against a real
local TCP server: payload schema field-exact (Speed/VLA/HLA/TotalSpin/
SpinAxis), ShotNumber increments, ClubData present only when club speed
exists, heartbeats arrive, 200 reply parsed. `monitor._on_fused` full
chain: GSPro wire + Shot construction + UI callback in one pass. And the
finale: `ofserver.socketio.run()` started for real, a python-socketio
client connected, `on_shot_detected()` fired from the hardware ingress —
**the 'shot' event arrived on the wire with our field values**. The last
unpressed transport in the system is now pressed.

Carried forward: none new open. The audit trail now covers reading (F),
datasheets (D), execution (E), and stimuli (S).

## Audit #4 — 2026-07-05 (real-stimuli audit) — **FAILED: interrupted**

Aborted mid-recon by a session interruption; no findings, no fixes, no
buttons pressed. Recon that survived (carried into Audit #5): the upstream
server emits shots on the `"shot"` SocketIO event (`server.py:2168`),
`python-socketio` client is available in the venv, and
`serial.SerialException` subclasses `OSError`. Designated FAILED per
Johnny; superseded in full by Audit #5.

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
