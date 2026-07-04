# IWR6843ISK firmware flashing

One-time setup, done on the **Windows machine** with TI Uniflash — not the
Pi. The Pi cannot flash the board; it only talks to already-flashed firmware
at runtime (see "Flash vs. config" below — this is the important part).

## Flash vs. config (read this first)

There are two completely separate things, and confusing them causes most of
the "why isn't it working" pain:

| | **Flash** (firmware) | **Config** (`golf.cfg`) |
|---|---|---|
| What | The mmWave SDK demo *program* running on the chip | Chirp/frame *parameters* fed to that program |
| Where it lives | Board's onboard flash (persistent) | Sent over serial each run; gone on power-cycle |
| Who does it | You, once, via Uniflash on Windows | The Pi, automatically, every time `run_iwr6843.py` starts |
| How | SOP jumpers -> flash mode -> Uniflash | `IWR6843Source.configure()` writes `golf.cfg` lines to the CLI port |
| Changes when moved to the Pi? | **No.** Firmware persists. | Re-sent fresh on every startup. |

So: **once you flash the board on Windows, that firmware stays put.** Moving
the board to the Pi, power-cycling it, unplugging it — none of that touches
the firmware. The Pi just opens the CLI serial port and streams `golf.cfg`
into the firmware that's already there (`configure()` in
`iwr6843_source.py`), then reads the TLV point cloud back off the data port.

If you ever want to change the *firmware* (e.g. a different SDK version),
that's another Windows/Uniflash trip. If you just want to change *chirp
parameters*, edit `golf.cfg` — no flashing, the Pi picks it up next run.

## Why flash at all (vs. trusting what shipped)

The board ships with *some* demo firmware, but not necessarily the SDK
version `golf.cfg` and the TLV parser target. `golf.cfg`'s own header warns
that parameter formats differ between SDK versions. Flashing a known OOB
(Out-of-Box) demo version removes that variable: you develop `golf.cfg`
against the same version's reference config, and both the TI Demo Visualizer
(bring-up rung 1) and our parser talk to firmware you chose.

## What you need

- TI **Uniflash** (Windows)
- TI **mmWave SDK** for IWR6843 — install a specific version and record it below
- The OOB demo binary from that SDK (the IWR6843 `mmw_demo` image; confirm
  the exact filename in your installed SDK, it's under the SDK's
  `packages/ti/demo/xwr68xx/mmw/` build output)
- Micro-USB to the board; note the CLI (115200) and data (921600) COM ports

## Windows XDS110 driver

Windows needs TI's XDS110 driver installed before the board's CLI/data COM
ports (or Uniflash) will work — this is the Windows-specific step; **the Pi
needs no driver at all** (the same XDS110 debug probe is USB CDC-ACM class
on Linux, and `cdc_acm` ships built into Raspberry Pi OS).

**Not bundled in this repo, on purpose.** TI's driver packages (whether the
standalone XDS110 driver or the one bundled with Uniflash/Code Composer
Studio) come under TI's own click-through license, which typically restricts
redistribution — and the installer can run tens to hundreds of MB, which
doesn't belong in this git history either way.

Instead, pin the exact provenance here once you've downloaded it, so you can
always get back to the *identical* file even if TI reorganizes their site
(a checksum is verifiable against a mirror or the Wayback Machine even when
the original link is dead):

- [ ] Download URL used: `________`
- [ ] Driver/package version: `________`
- [ ] Installer filename: `________`
- [ ] SHA256 checksum (`shasum -a 256 <file>` or `certutil -hashfile <file> SHA256`): `________`
- [ ] Date downloaded: `________`

## Steps (outline — fill in the confirmed values as you go)

1. Set the board's **SOP jumpers to flashing mode** (see table below).
2. Power-cycle the board.
3. In Uniflash: pick the IWR6843 target, load the mmw demo `.bin`, flash.
4. Set the **SOP jumpers back to functional mode**.
5. Power-cycle again.
6. Confirm with the TI mmWave Demo Visualizer (bring-up rung 1): stock config
   + hand-wave should show a point cloud.

## TO CONFIRM (do not trust from memory — record here once verified)

These depend on your exact board revision and SDK version. Get them from the
**IWR6843ISK EVM User's Guide** and the board silkscreen, and write the
confirmed values in so this file becomes the record:

- [ ] SDK version flashed: `________`
- [ ] OOB demo binary path/filename: `________`
- [ ] SOP jumper positions — **flashing** mode: `SOP2=__ SOP1=__ SOP0=__`
- [ ] SOP jumper positions — **functional** mode: `SOP2=__ SOP1=__ SOP0=__`
- [ ] CLI COM port on Windows: `________`  data COM port: `________`
- [ ] After flashing, did the Demo Visualizer show a point cloud? `yes / no`

## After it's flashed

Nothing else to do on the firmware side. On the Pi:

```bash
./scripts/setup_wizard.sh      # discovers ports, gain, etc.
python3 run_iwr6843.py --ballistics
```

`run_iwr6843.py` -> `IWR6843Source.configure()` streams `golf.cfg` to the
board on startup. Diff `golf.cfg`'s argument formats against the reference
config from the **same SDK version you flashed** before the first real
capture — that version match is the entire reason for pinning the flash.
