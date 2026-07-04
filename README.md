# LM-2

DIY golf launch monitor: TI IWR6843ISK (geometry) + RFbeam K-MC1 (spin) on a
Raspberry Pi, targeting the [OpenFlight](https://github.com/jewbetcha/openflight)
server/physics/UI stack.

LM-2 merges two lines of work: the acquisition-layer signal processing
(spin decoder with `clean_iq` filtering, session AC/DC modes, GSPro adapter,
synthetic-capture self-tests) and the OpenFlight integration/tooling (live
physics simulator, hardware runner, one-command setup wizard, ALSA gain
control, firmware-flashing docs). See [LM-1](https://github.com/kalaradente/LM-1)
for the earlier integration-only snapshot.

## Layout

| Path | What |
|---|---|
| `openflight_iwr6843/` | Acquisition layer: TLV parser + Kalman trackers (`iwr6843_source.py`, `kalman.py`), spin decoder with pre-clean filtering (`spin_decoder.py`), geometry+spin fusion (`shot_fusion.py`), session presets incl. K-MC1 AC/DC output mode (`session.py`), GSPro Open Connect adapter (`gspro_adapter.py`), ALSA capture-gain control (`gain.py`), truth-data scoring (`validate.py`), chirp profile (`golf.cfg`). See its own README. |
| `shot_simulator.py` | **Flight-physics** sim: type in ball speed/spin/launch/side-spin → full RK4 drag+Magnus trajectory (carry, apex, curve). `--live` pushes it into a running OpenFlight server so it renders in the real UI. |
| `spin_capture_simulator.py` | **Spin-decoder** sim: synthesize a raw K-MC1 I/Q capture for a given shot and run the real `spin_decoder.decode()` on it — tests the signal path with no hardware. `--sweep` runs a speed×spin grid. |
| `run_iwr6843.py` | Run the **real** IWR6843 + K-MC1 hardware against the real OpenFlight server/UI (same `on_shot_detected()` pipeline the live simulator exercises). |
| `scripts/setup_wizard.sh` | One-command Pi bring-up: clones `openflight_upstream`, installs deps, discovers serial ports + HiFiBerry gain, writes `hardware.env`. |
| `live_client.py` | WebSocket helper for `shot_simulator.py --live`. |
| `TODO.md` | Running hardware/software roadmap. |

## Setup

**On the Pi, from a fresh clone — one command:**

```bash
git clone git@github.com:kalaradente/LM-2.git && cd LM-2
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
```

## Try it without hardware

```bash
# spin-decoder signal path (no upstream needed):
python3 spin_capture_simulator.py --speed 150 --spin 3000
python3 -m openflight_iwr6843.spin_decoder --selftest

# flight physics (needs openflight_upstream cloned):
python3 shot_simulator.py --ball-speed 165 --spin 2600 --launch-angle 13 --side-spin 900
```

## Bring-up

Follow the ladder in `openflight_iwr6843/README.md` — rung 0 is flashing the
IWR6843 firmware on Windows (`openflight_iwr6843/docs/firmware-flashing.md`);
the Pi never flashes the board, it only streams `golf.cfg` at runtime.

## Notes

- The `openflight_upstream/src/openflight/server.py` `simulate_custom_shot`
  patch (from LM-1) is required for `shot_simulator.py --live`. If you clone
  a fresh `openflight_upstream`, re-apply it, or copy the patched file from
  LM-1.
- No LICENSE yet. OpenFlight is AGPL-3.0; since this integrates with it,
  consider matching (see `TODO.md`).
