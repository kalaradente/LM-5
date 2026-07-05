"""
gain.py — read/set the HiFiBerry DAC2 ADC Pro's K-MC1 capture gain via ALSA,
using pyalsaaudio (https://larsimmisch.github.io/pyalsaaudio/).

Linux/ALSA only. This does not import on macOS (no libasound) — it's meant
to run on the Pi itself, not a dev machine.

REMINDER (unverified on real hardware): DEFAULT_CONTROL and DEFAULT_CARD
below are guesses, not confirmed against your actual board. Before this does
anything useful, run on the Pi:

    amixer -c <cardindex> controls

or

    python -m openflight_iwr6843.gain list --card <cardindex>

to find the real capture-gain control name (PCM186x-based HiFiBerry boards
commonly expose something like "ADC Capture Volume" or "PGA Gain", but
confirm rather than trust the default) and the real card index (see
`aplay -l` / `arecord -l`). Pass both explicitly with --card/--control until
you've hardcoded the confirmed values here.

Per the K-MC1 (RFbeam datasheet, Rev J 11/2022) and DAC2 ADC Pro datasheets
(HiFiBerry sheet re-verified 2026-07-05, closing audit D-6):
  - K-MC1 AC output: 32dB fixed IF amplifier gain, 100 ohm output impedance,
    40Hz-15kHz -3dB bandwidth (this is the output we wire — see session.py).
  - DAC2 ADC Pro: input gain -12dB to +32dB (sheet spec table; its own
    example uses "40db" for mics — spec table wins), max input 2.1Vrms,
    ADC SNR 110dB, 44.1-192kHz. 20kOhm input impedance per pin (PCM1863):
    20k : 100 ohm is ~200:1 -- loading loss negligible (~0.04dB).
  - Gain staging, refined by the max-input figure: the K-MC1's own output
    stage clips at roughly +/-2.5V peak (5V part), BELOW the ADC's 0dB
    full scale of 2.1Vrms (+/-3.0V peak) -- so at PGA <= 0dB the module
    always clips before the ADC, and negative PGA buys no protection at
    all, just 12dB of lost level. START AT 0dB; add positive gain only if
    bench captures show weak signals (110dB ADC SNR leaves plenty of
    margin either way). Real departing-ball amplitude remains a bench
    question.
  - ROUTING (wizard step 6 sets this): the ADC input mux must select the
    single-ended onboard input -- "ADC Left Input"=VINL1[SE], "ADC Right
    Input"=VINR1[SE] -- and "ADC Mic Bias" must be OFF (bias would inject
    DC into the K-MC1 outputs). On the DIFF setting our unbalanced wiring
    reads as silence and looks exactly like a dead radar.
"""

from __future__ import annotations

import argparse

try:
    import alsaaudio
except ImportError:
    alsaaudio = None

DEFAULT_CONTROL = "ADC"   # Per the DAC2 ADC Pro datasheet's own examples
                          # ("amixer sset ADC 40db"); confirm with `list` --
                          # the exact ALSA name can differ by kernel/driver
                          # version (older guesses here said "ADC Capture
                          # Volume", which appears in some pcm186x builds).
DEFAULT_CARD = -1                        # UNVERIFIED -- confirm with `aplay -l`


def _require_alsaaudio() -> None:
    if alsaaudio is None:
        raise SystemExit(
            "error: pyalsaaudio isn't installed, or this isn't Linux/ALSA.\n"
            "On the Pi: pip install pyalsaaudio\n"
        )


def list_controls(cardindex: int = DEFAULT_CARD) -> list[str]:
    _require_alsaaudio()
    return alsaaudio.mixers(cardindex=cardindex)


def get_gain_db(control: str = DEFAULT_CONTROL, cardindex: int = DEFAULT_CARD) -> list[int]:
    """Current capture gain in dB, per channel (left, right)."""
    _require_alsaaudio()
    m = alsaaudio.Mixer(control=control, cardindex=cardindex)
    return m.getvolume(alsaaudio.PCM_CAPTURE, alsaaudio.VOLUME_UNITS_DB)


def set_gain_db(
    db: int, control: str = DEFAULT_CONTROL, cardindex: int = DEFAULT_CARD
) -> None:
    """Set capture gain in dB on both channels -- keep L/R matched (see
    shot_fusion.py's I/Q complex-signal construction, which is sensitive to
    channel gain imbalance)."""
    _require_alsaaudio()
    m = alsaaudio.Mixer(control=control, cardindex=cardindex)
    m.setvolume(db, alsaaudio.PCM_CAPTURE, alsaaudio.VOLUME_UNITS_DB)


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--card", type=int, default=DEFAULT_CARD)
    p.add_argument("--control", default=DEFAULT_CONTROL)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list mixer control names for this card")
    sub.add_parser("get", help="print current capture gain in dB, per channel")
    set_p = sub.add_parser("set", help="set capture gain in dB on both channels")
    set_p.add_argument("db", type=float, help="target gain, dB (range: -12 to +32)")
    args = p.parse_args()

    if args.cmd == "list":
        for name in list_controls(args.card):
            print(name)
    elif args.cmd == "get":
        print(get_gain_db(args.control, args.card))
    elif args.cmd == "set":
        set_gain_db(args.db, args.control, args.card)
        print(f"set {args.control!r} to {args.db} dB -> {get_gain_db(args.control, args.card)}")


if __name__ == "__main__":
    main()
