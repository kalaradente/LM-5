# LM-5

**LM** — a DIY golf launch monitor: TI IWR6843ISK (geometry) + RFbeam K-MC1
(spin) on a Raspberry Pi, targeting the
[OpenFlight](https://github.com/jewbetcha/openflight) server/physics/UI stack.

Naming: the project is **LM**; the `-x` suffix is the version. This repo is
the current version, **LM-5**. Earlier versions:
[LM-2](https://github.com/kalaradente/LM-2) (the development line this
version grew from — same tree, kept as the working mirror) and
[LM-1](https://github.com/kalaradente/LM-1) (the frozen integration-only
snapshot).

LM merges two lines of work: the acquisition-layer signal processing
(spin decoder with mains-hum cleanup, GSPro adapter, synthetic-capture
self-tests) and the OpenFlight integration/tooling (live physics simulator,
hardware runner, one-command setup wizard, ALSA gain control, firmware-flashing
docs).

## Layout

| Path | What |
|---|---|
| `openflight_iwr6843/` | Acquisition layer: TLV parser + Kalman trackers (`iwr6843_source.py`, `kalman.py`), spin decoder (`spin_decoder.py`), geometry+spin fusion (`shot_fusion.py`), session presets (`session.py`), GSPro Open Connect adapter (`gspro_adapter.py`), ALSA capture-gain control (`gain.py`), truth-data scoring (`validate.py`), chirp profile (`golf.cfg`). See its own README. |
| `shot_simulator.py` | **Flight-physics** sim: type in ball speed/spin/launch/side-spin → full RK4 drag+Magnus trajectory (carry, apex, curve). `--live` pushes it into a running OpenFlight server so it renders in the real UI. |
| `spin_capture_simulator.py` | **Spin-decoder** sim: synthesize a raw K-MC1 I/Q capture for a given shot and run the real `spin_decoder.decode()` on it — tests the signal path with no hardware. `--sweep` runs a speed×spin grid. |
| `geometry_capture_simulator.py` | **Geometry-channel** sim: synthesize IWR6843 captures (swing-arc club + ballistic ball) through a hostile observation model (elevation noise, Doppler folding + quantization, CFAR false alarms, swaying golfer, impact merge, UART burst gaps — all on by default) and run the real `analyze()` on them. `--sweep` asserts the measured accuracy envelopes across noise seeds; this is the pipeline's standing regression harness. |
| `shortgame_probe.py` | Short-game floor probe: how low can the trigger gate go, measured through the hostile sim (and on real hardware later with `--live`). |
| `run_iwr6843.py` | Run the **real** IWR6843 + K-MC1 hardware against the real OpenFlight server/UI (same `on_shot_detected()` pipeline the live simulator exercises). Optional `--gspro-host` also forwards each shot to GSPro. |
| `scripts/setup_wizard.sh` | One-command Pi bring-up: clones `openflight_upstream`, applies `patches/`, installs deps, **builds the web UI** (the bundle the server serves), discovers serial ports + HiFiBerry gain, writes `hardware.env`. |
| `patches/` | Our changes to OpenFlight upstream, applied by the wizard in glob order: `session_mode` (3-way mode picker + swing view), `simulate_custom_shot` (mock injection for `--live`), `ui_redesign` (the "Calibrated Instrument" web UI — signal-amber design system, IBM Plex, dark/light themes, per-club tour-average launch/spin ratings). The stock OpenFlight UI is what you get by simply not applying `ui_redesign.patch`. |
| `live_client.py` | WebSocket helper for `shot_simulator.py --live`. |
| `launch_monitor_parts_list.txt` | Hardware BOM + wiring summary. |
| `TODO.md` | Running hardware/software roadmap. |

## Setup

**On the Pi, from a fresh clone — one command:**

```bash
git clone https://github.com/kalaradente/LM-5.git && cd LM-5
./scripts/setup_wizard.sh
```

That clones `openflight_upstream` (not tracked here — it has its own git
history), creates `.venv`, installs `requirements.txt`, and walks through
hardware discovery. Safe to re-run.

**On a dev machine with no hardware** (just the simulators):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
git clone https://github.com/jewbetcha/openflight.git openflight_upstream   # only shot_simulator.py --live / run_iwr6843.py need this
# then check out the pinned commit the patches are verified against
# (UPSTREAM_COMMIT in scripts/setup_wizard.sh) before applying patches/ --
# upstream HEAD moves, and an unpinned tree once broke ui_redesign.patch
# (audit #9, T-3)
git -C openflight_upstream checkout "$(grep -m1 '^UPSTREAM_COMMIT=' scripts/setup_wizard.sh | cut -d'"' -f2)"
```

## Try it without hardware

```bash
# spin-decoder signal path (no upstream needed):
python3 spin_capture_simulator.py --speed 150 --spin 3000
python3 -m openflight_iwr6843.spin_decoder --selftest

# geometry channel through the full hostile observation model (no upstream needed):
python3 geometry_capture_simulator.py --sweep

# flight physics (needs openflight_upstream cloned):
python3 shot_simulator.py --ball-speed 165 --spin 2600 --launch-angle 13 --side-spin 900
```

## Bring-up

Follow the ladder in `openflight_iwr6843/README.md` — rung 0 is flashing the
IWR6843 firmware on Windows (`openflight_iwr6843/docs/firmware-flashing.md`);
the Pi never flashes the board, it only streams `golf.cfg` at runtime.

## Notes

- `shot_simulator.py --live` needs one small addition to upstream's
  `server.py` (a `simulate_custom_shot` WebSocket handler). It lives in
  `patches/simulate_custom_shot.patch` and the setup wizard applies it
  automatically after cloning `openflight_upstream`. It's purely additive —
  nothing in upstream's behavior changes. `run_iwr6843.py` (real hardware)
  and the offline sims don't need it.
- Licensed **AGPL-3.0-or-later**, matching OpenFlight (see `LICENSE`).
