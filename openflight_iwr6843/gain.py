"""
gain.py — read/set the HiFiBerry DAC+ADC Pro's K-MC1 capture gain via ALSA,
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

Per the K-MC1/HiFiBerry DAC+ADC Pro datasheets: the Pro's capture PGA covers
-12dB to +32dB in 0.5dB steps; the K-MC1 already applies a fixed 47dB IF
preamp per channel ahead of that. Start low (near -12dB) for close-range
bench tests (drill rig) to avoid clipping; a real departing ball at ~1.5m
is a much weaker return and will likely need more gain.
"""

from __future__ import annotations

import argparse

try:
    import alsaaudio
except ImportError:
    alsaaudio = None

DEFAULT_CONTROL = "ADC Capture Volume"   # UNVERIFIED -- confirm with `list`
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
