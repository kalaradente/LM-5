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

## Windows COM-port driver (SiLabs CP210x — corrected 2026-07-05, audit D-1)

The standalone ISK's USB runs through a **SiLabs CP2105 dual-UART bridge**
(SWRU546E §3.8 — the "CP2015" in TI's text is a typo; the guide's own
Figure 4-19 caption says CP2105). So Windows needs the **SiLabs CP210x VCP
driver** before the board's two COM ports (or Uniflash) will work — this is
the Windows-specific step; **the Pi needs no driver at all** (`cp210x`
ships built into Raspberry Pi OS, and the board enumerates as
`/dev/ttyUSB0`/`ttyUSB1`). The two ports are "Enhanced" (= CFG/User UART,
115200 — the one Uniflash flashes over) and "Standard" (= data, 921600).

_An earlier revision of this doc said "TI XDS110 driver / ttyACM" — that
applies only when the antenna board is mounted on an MMWAVEICBOOST carrier
(which has the XDS110 probe). We flash and run the ISK standalone._

**Not bundled in this repo, on purpose.** Driver packages come under their
vendors' click-through licenses, which typically restrict redistribution —
and installers can run tens to hundreds of MB, which doesn't belong in this
git history either way.

Instead, pin the exact provenance here once you've downloaded it, so you can
always get back to the *identical* file even if TI reorganizes their site
(a checksum is verifiable against a mirror or the Wayback Machine even when
the original link is dead):

- [ ] Download URL used: `________`
- [ ] Driver/package version: `________`
- [ ] Installer filename: `________`
- [ ] SHA256 checksum (`shasum -a 256 <file>` or `certutil -hashfile <file> SHA256`): `________`
- [ ] Date downloaded: `________`

## SOP switch settings (confirmed from TI docs — SWRU546E Table 3-3, xWR6843ISK/IWR6843ISK-ODS Rev C section, cross-checked against the chip datasheet SWRS219F Table 8-1)

The ISK's S1 switch (S1.1=SOP2, S1.2=SOP1, S1.3=SOP0 — S1.4/S1.5 are unrelated
muxing, leave as shown):

| | S1.1 (SOP2) | S1.2 (SOP1) | S1.3 (SOP0) | S1.4 | S1.5 |
|---|---|---|---|---|---|
| **Flashing** | ON | OFF | ON | ON | OFF |
| **Functional** | OFF | OFF | ON | ON | OFF |

Only **S1.1 changes** between the two modes. Chip-level meaning (Table 8-1):
`SOP[2:1:0] = 101` (flashing — bootloader waits for a UART flashing utility),
`= 001` (functional — bootloader loads the app from QSPI flash). There's also
a `= 011` **Debug Mode** (bootloader bypassed, R4F halted for emulator
connection) if you ever need it, though the flashing ladder below doesn't.

**SOP is sensed only at boot** — after flipping S1.1, press the reset switch
(S2) or power-cycle; flipping the switch alone does nothing until the board
re-boots.

Not yet confirmed from documentation (needs the physical board / TI Demo
Visualizer): which COM port number is the CLI vs. data port. The EVM guide
shows this in a screenshot (its Figure 3-20), not as text, so it has to be
read off the actual device manager / Demo Visualizer the first time — this
is exactly what bring-up rung 1 is for.

## Steps

1. Set the board's **SOP switches to flashing mode** (table above): S1.1=ON,
   S1.2=OFF, S1.3=ON, S1.4=ON, S1.5=OFF.
2. Press reset (S2) or power-cycle — SOP is boot-sensed only.
3. In Uniflash: pick the IWR6843 target, load the mmw demo `.bin`, flash.
4. Set **S1.1 back to OFF** (functional mode) — S1.2-S1.5 unchanged.
5. Reset or power-cycle again.
6. Confirm with the TI mmWave Demo Visualizer (bring-up rung 1): stock config
   + hand-wave should show a point cloud.

## TO CONFIRM (do not trust from memory — record here once verified)

SOP switch settings above are sourced from TI's own docs (see table), not a
guess — but SDK version and the actual COM port numbers are still specific
to your setup:

- [ ] SDK version flashed: `________`
- [ ] OOB demo binary path/filename: `________`
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

**This applies to the TLV wire format too, not just `golf.cfg`'s CLI
parameters.** `iwr6843_source.py`'s frame/TLV parser was checked against
TI's "Understanding the Out of Box Demo Data Output" doc: the magic word,
both TLV type IDs, and the Detected Points structure all match exactly.
One open question that doc itself doesn't resolve: it lists frame header
fields that sum to 40 bytes (8-byte magic word + 32-byte header) but
separately states the header is 44 bytes total -- an internal
inconsistency, most likely an SDK-version difference (a field added in a
later revision) rather than either number being simply wrong. **Bring-up
rung 2** (this parser against a live stream, positions must match the TI
Demo Visualizer) is exactly the check that catches this empirically: a
wrong header length shows up as garbage or missing points, not a subtle
numeric drift. If rung 2 fails, this is the first thing to check against
your specific flashed SDK version's demo source.
