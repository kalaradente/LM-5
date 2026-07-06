#!/usr/bin/env python3
"""
run_iwr6843.py — run the real IWR6843 + K-MC1 hardware against the actual
OpenFlight server: same on_shot_detected() pipeline (RK4 ballistics carry
when --ballistics is set, session logging, WebSocket emit to the React UI)
that shot_simulator.py --live exercises with typed-in values, except fed by
real radar/audio hardware instead.

This does NOT call openflight.server.main() -- that function is ~500 lines
of camera/K-LD7/roboflow argument handling built around OPS243, none of
which applies to this rig. Instead this does the minimal equivalent setup
by hand: session logger init, the ballistics_enabled flag, and injecting an
IWR6843Monitor in place of RollingBufferMonitor/MockLaunchMonitor before
starting the same Flask-SocketIO app.

REMINDER: --cli-port/--geom-port/--audio-device below have no safe
defaults -- they depend on your actual USB enumeration order and ALSA
card, which you have not confirmed yet. Find them for real before
trusting any default:
    ls /dev/ttyUSB*                                  # geometry ports -- the
                                                       # standalone ISK's USB
                                                       # runs through a SiLabs
                                                       # CP2105 dual-UART
                                                       # bridge (SWRU546E
                                                       # 3.8), so it
                                                       # enumerates as
                                                       # ttyUSB* on Linux via
                                                       # cp210x (built into
                                                       # Raspberry Pi OS).
                                                       # Windows needs the
                                                       # SiLabs CP210x VCP
                                                       # driver. (ttyACM*/
                                                       # XDS110 applies ONLY
                                                       # if mounted on an
                                                       # MMWAVEICBOOST
                                                       # carrier -- we don't
                                                       # use one.)
    aplay -l / arecord -l                             # HiFiBerry card index
    python -m openflight_iwr6843.gain list --card N    # mixer control name
scripts/setup_wizard.sh automates this discovery and writes the confirmed
values to hardware.env, which this script reads if present.

Usage:
    python3 run_iwr6843.py --geom-port /dev/ttyUSB1 --cli-port /dev/ttyUSB0 \\
        --ballistics
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

REPO_ROOT = Path(__file__).resolve().parent
UPSTREAM_SRC = REPO_ROOT / "openflight_upstream" / "src"
HARDWARE_ENV = REPO_ROOT / "hardware.env"

sys.path.insert(0, str(REPO_ROOT))
if UPSTREAM_SRC.is_dir():
    sys.path.insert(0, str(UPSTREAM_SRC))
else:
    sys.exit(
        f"error: {UPSTREAM_SRC} not found.\n"
        "git clone https://github.com/jewbetcha/openflight.git openflight_upstream\n"
    )

from openflight_iwr6843.iwr6843_source import IWR6843Source  # noqa: E402
from openflight_iwr6843.shot_fusion import AudioRing, ShotFuser  # noqa: E402
from openflight_iwr6843.gspro_adapter import GSProClient  # noqa: E402
from openflight_iwr6843.session import (SessionConfig, SELECTORS,  # noqa: E402
                                        from_selector)

import openflight.server as ofserver  # noqa: E402
from openflight.launch_monitor import ClubType, Shot  # noqa: E402

log = logging.getLogger("run_iwr6843")


def _load_hardware_env() -> dict:
    """Optional key=value overrides written by scripts/setup_wizard.sh."""
    if not HARDWARE_ENV.exists():
        return {}
    out = {}
    for line in HARDWARE_ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _assert_adc_routing(env: dict) -> None:
    """Re-assert the HiFiBerry ADC input routing (and capture gain, if the
    wizard recorded one) from hardware.env at every startup.

    Why every startup: ALSA mixer state only survives a CLEAN shutdown
    (alsa-restore replays what alsactl last stored). A power-yanked Pi boots
    with driver defaults, and the PCM1863's default input mux is not our
    single-ended wiring -- capture then reads pure silence, which looks
    exactly like a dead K-MC1 (audit D-6). Best-effort by design: a warning,
    never a fatal error, because the operator may be mid-rewire."""
    card = env.get("HIFIBERRY_CARD")
    if not card:
        return
    import subprocess
    for control, value in (("ADC Mic Bias", "Mic Bias off"),
                           ("ADC Left Input", "VINL1[SE]"),
                           ("ADC Right Input", "VINR1[SE]")):
        try:
            subprocess.run(["amixer", "-c", card, "sset", control, value],
                           check=True, capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            log.warning("[audio] couldn't set %r on card %s -- check the ADC "
                        "routing by hand (amixer -c %s controls); wrong mux = "
                        "silent capture", control, card, card)
    gain_control, gain_db = env.get("GAIN_CONTROL"), env.get("GAIN_DB")
    if gain_control and gain_db:
        try:
            from openflight_iwr6843 import gain as gain_mod
            if gain_mod.alsaaudio is None:
                raise RuntimeError("pyalsaaudio unavailable")
            gain_mod.set_gain_db(float(gain_db), control=gain_control,
                                 cardindex=int(card))
            log.info("[audio] capture gain re-asserted: %s dB on %r",
                     gain_db, gain_control)
        except Exception as e:  # pylint: disable=broad-except
            log.warning("[audio] couldn't re-assert capture gain (%s) -- set "
                        "it by hand: python -m openflight_iwr6843.gain set %s "
                        "--card %s --control '%s'", e, gain_db, card,
                        gain_control)


def _fused_to_shot(fused: dict, club: ClubType) -> Shot:
    """Adapt shot_fusion's fused dict to openflight's Shot dataclass, tagged
    mode="hardware" (not "mock") so on_shot_detected runs the real carry
    path: resolve_launch()+simulate() when --ballistics is set, table
    fallback otherwise -- the same branch real OPS243 shots take.

    Speed-training swings take the same adapter with mode="speed-training":
    on_shot_detected still runs (mode != "mock"), but ball_speed 0 + no
    launch angle degrade its ball machinery to no-ops (carry ~0), and the
    mode tag is what the patched shot_to_dict forwards so the UI renders a
    club-speed-only swing card instead of a shot card."""
    if fused.get("swing"):
        return Shot(
            ball_speed_mph=0.0,
            timestamp=datetime.now(),
            club_speed_mph=fused.get("club_speed_mph"),
            club=club,
            mode="speed-training",
        )
    conf = fused.get("geometry_confidence")
    return Shot(
        ball_speed_mph=fused["ball_speed_mph"],
        timestamp=datetime.now(),
        club_speed_mph=fused.get("club_speed_mph"),
        club=club,
        launch_angle_vertical=fused.get("launch_angle_deg"),
        launch_angle_horizontal=fused.get("side_angle_deg"),
        launch_angle_confidence=conf,
        launch_angle_vertical_confidence=conf,
        launch_angle_horizontal_confidence=conf,
        launch_angle_vertical_source="iwr6843",
        launch_angle_horizontal_source="iwr6843",
        angle_source="iwr6843",
        spin_rpm=fused.get("spin_rpm"),
        spin_confidence=fused.get("spin_confidence"),
        spin_source=fused.get("spin_source"),
        spin_axis_deg=fused.get("spin_axis_hint_deg"),
        mode="hardware",
    )


class IWR6843Monitor:
    """Adapts IWR6843Source + ShotFuser to the `monitor` interface server.py
    expects (the same surface MockLaunchMonitor/RollingBufferMonitor
    implement), so the existing club-select/session/clear-session UI
    controls keep working against real hardware."""

    def __init__(self, cli_port: str, data_port: str, cfg_path: str,
                 audio_device=None, gspro: Optional[GSProClient] = None,
                 session: Optional[SessionConfig] = None):
        # Param names fixed in audit E-3: they used to read (geom_port,
        # data_port) while main() passed (cli_port, geom_port) -- the
        # positional wiring was correct but any keyword caller following
        # the names would have swapped the serial ports.
        self._shots: List[Shot] = []
        self._current_club = ClubType.DRIVER
        self._shot_callback: Optional[Callable[[Shot], None]] = None
        self.session = session or SessionConfig()
        self.audio = AudioRing(device=audio_device)
        self.fuser = ShotFuser(publish=self._on_fused, audio=self.audio,
                                session=self.session)
        self.source = IWR6843Source(cli_port, data_port, cfg_path,
                                     on_geometry=self.fuser.on_geometry,
                                     session=self.session)
        self._thread: Optional[threading.Thread] = None
        self.gspro = gspro

    def _on_fused(self, fused: dict) -> None:
        # GSPro gets the raw fused dict (its field names match shot_fusion's
        # output directly -- ball_speed_mph/launch_angle_deg/etc.) BEFORE
        # conversion to openflight's Shot dataclass below. Best-effort: a
        # GSPro send failure must never take down real shot processing.
        # Speed-training swings are NOT forwarded: GSPro's Open Connect API
        # models ball flight, and a 0-mph "ball" would render as a whiffed
        # shot in the sim rather than a swing rep.
        if self.gspro is not None and not fused.get("swing"):
            try:
                self.gspro.send_shot(fused)
            except OSError:
                log.warning("[gspro] send failed (disconnected?)", exc_info=True)

        shot = _fused_to_shot(fused, self._current_club)
        self._shots.append(shot)
        if self._shot_callback:
            self._shot_callback(shot)

    def connect(self) -> bool:
        return True  # IWR6843Source opens both serial ports in __init__

    def disconnect(self) -> None:
        self.stop()

    def get_radar_info(self) -> dict:
        return {"Version": "IWR6843ISK + K-MC1"}

    def start(self, shot_callback=None, live_callback=None,
              diagnostic_callback=None) -> None:  # pylint: disable=unused-argument
        self._shot_callback = shot_callback
        self.audio.start()
        self._thread = threading.Thread(target=self._run_source, daemon=True)
        self._thread.start()
        log.info("[iwr6843] monitor started")

    def _run_source(self) -> None:
        try:
            self.source.run()
        except Exception:  # pylint: disable=broad-except
            log.exception("[iwr6843] source loop crashed")

    def stop(self) -> None:
        self.source.stop()
        if self.gspro is not None:
            self.gspro.close()

    def get_shots(self) -> List[Shot]:
        return list(self._shots)

    def get_session_stats(self) -> dict:
        # Swings (mode="speed-training") are kept OUT of the ball-speed
        # aggregates -- their ball_speed is a structural 0.0, not a slow
        # shot, and one swing would crater min/avg. They get their own
        # club-speed aggregates instead (max is the number overspeed
        # protocols train against).
        shots = [s for s in self._shots if s.mode != "speed-training"]
        swings = [s for s in self._shots if s.mode == "speed-training"]
        import statistics
        stats = {"shot_count": 0, "avg_ball_speed": 0, "max_ball_speed": 0,
                 "min_ball_speed": 0, "avg_club_speed": None,
                 "avg_smash_factor": None, "avg_carry_est": 0}
        if shots:
            speeds = [s.ball_speed_mph for s in shots]
            club_speeds = [s.club_speed_mph for s in shots if s.club_speed_mph]
            smashes = [s.smash_factor for s in shots if s.smash_factor]
            stats.update(
                shot_count=len(shots),
                avg_ball_speed=statistics.mean(speeds),
                max_ball_speed=max(speeds),
                min_ball_speed=min(speeds),
                avg_club_speed=statistics.mean(club_speeds) if club_speeds else None,
                avg_smash_factor=statistics.mean(smashes) if smashes else None,
                avg_carry_est=statistics.mean(
                    [s.estimated_carry_yards for s in shots]),
            )
        if swings:
            swing_speeds = [s.club_speed_mph for s in swings if s.club_speed_mph]
            if swing_speeds:
                stats.update(
                    swing_count=len(swing_speeds),
                    max_swing_speed=max(swing_speeds),
                    avg_swing_speed=statistics.mean(swing_speeds),
                )
        return stats

    def clear_session(self) -> None:
        self._shots = []

    def set_club(self, club: ClubType) -> None:
        self._current_club = club

    # ---- live mode switching (web UI mode picker) --------------------------

    def set_session_mode(self, mode: str) -> dict:
        """Switch indoor/outdoor/speed at runtime. Called from the SocketIO
        thread by the patched server's set_session_mode handler; the radar
        switch itself is queued and applied by the acquisition thread at a
        safe point (between captures) -- nothing here blocks or races the
        stream. Ball type stays whatever the session started with.

        Mode -> chirp profile is fixed (indoor/speed -> golf.cfg, outdoor ->
        golf-outdoor.cfg): a custom --cfg override holds only until the
        first switch, since an override tuned for one gate/duty profile has
        no meaning in the others."""
        session = from_selector(mode, self.session.ball_type)  # raises on junk
        cfg_name = "golf-outdoor.cfg" if session.environment == "outdoor" \
            else "golf.cfg"
        cfg_path = str(REPO_ROOT / "openflight_iwr6843" / cfg_name)
        self.session = session
        self.fuser.set_session(session)
        self.source.request_session(session, cfg_path)
        log.info("[session] mode -> %s (%s)", mode, session.summary())
        return self.get_session_mode()

    def get_session_mode(self) -> dict:
        return {"mode": self.session.selector,
                "modes": list(SELECTORS),
                "summary": self.session.summary()}


def main() -> None:
    env = _load_hardware_env()
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--geom-port", default=env.get("GEOM_PORT"),
                         help="IWR6843 data port, e.g. /dev/ttyUSB1 (UNVERIFIED default)")
    parser.add_argument("--cli-port", default=env.get("CLI_PORT"),
                         help="IWR6843 CLI/config port, e.g. /dev/ttyUSB0")
    parser.add_argument("--cfg", default=None,
                         help="chirp profile; default picks golf.cfg (indoor) or "
                              "golf-outdoor.cfg (--outdoor) to match the session")
    parser.add_argument("--audio-device", default=env.get("AUDIO_DEVICE"),
                         help="sounddevice device name/index for the HiFiBerry capture")
    parser.add_argument("--club", default="driver")
    parser.add_argument("--outdoor", action="store_true",
                         help="outdoor session preset (wider range gate + capture "
                              "window, looser CFAR, no clutter removal). Default: indoor.")
    parser.add_argument("--ball", choices=["plain", "marked", "rct"], default="plain",
                         help="ball type; sets the measured-spin confidence floor")
    parser.add_argument("--speed-training", action="store_true",
                         help="start in speed-training mode: club-head speed ONLY "
                              "(swinging without a ball). Swings ride the same "
                              "server/UI stream as shots, rendered as club-speed "
                              "cards. All three modes (indoor/outdoor/speed) are "
                              "also live-switchable from the web UI's mode picker.")
    parser.add_argument("--ballistics", action="store_true",
                         help="use the RK4 drag+Magnus physics engine for carry")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--web-port", type=int, default=8080)
    parser.add_argument("--no-logging", action="store_true")
    parser.add_argument("--session-location", default="range")
    parser.add_argument("--gspro-host", default=None,
                         help="GSPro PC's LAN address; enables sending shots to GSPro "
                              "over its Open Connect API. Omit to skip GSPro entirely.")
    parser.add_argument("--gspro-port", type=int, default=921,
                         help="GSPro Open Connect port (default: 921)")
    args = parser.parse_args()

    if not args.cli_port or not args.geom_port:
        sys.exit(
            "error: --cli-port/--geom-port are required (no safe default).\n"
            "Run `ls /dev/ttyUSB*` on the Pi to find them, or run "
            "scripts/setup_wizard.sh first to discover and save them.\n"
        )

    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    if args.speed_training and args.outdoor:
        # Deliberately the same session (see session.Mode): speed training
        # always runs the indoor chirp profile, whatever the venue.
        log.info("[session] --outdoor is moot in speed-training mode "
                 "(the clubhead is ~2-3 m out either way)")
    session = from_selector("speed" if args.speed_training
                            else ("outdoor" if args.outdoor else "indoor"),
                            args.ball)
    log.info("[session] %s", session.summary())
    if args.cfg is None:
        # The outdoor session needs the outdoor chirp profile to actually
        # reach past 6 m (audit D-5): the session's range-gate rewrite can
        # only tighten what the chip emits, never extend it. Indoor and
        # speed-training both use the indoor profile (max frame rate on a
        # close, briefly-radial clubhead).
        name = "golf-outdoor.cfg" if session.environment == "outdoor" \
            else "golf.cfg"
        args.cfg = str(REPO_ROOT / "openflight_iwr6843" / name)
        log.info("[session] chirp profile: %s", name)

    # Validate ALL arguments before any side effects (audit E-7): the club
    # check used to sit after session-logger init, so a rejected run still
    # left session/radar-log files behind in ~/openflight_sessions/.
    try:
        club = ClubType(args.club)
    except ValueError:
        sys.exit(f"error: unknown club '{args.club}'")

    ofserver.ballistics_enabled = args.ballistics
    ofserver.mock_mode = False

    if args.no_logging:
        ofserver.init_session_logger(enabled=False)
    else:
        ofserver.init_session_logger(location=args.session_location, enabled=True)
        session_logger = ofserver.get_session_logger()
        if session_logger:
            session_logger.start_session(
                radar_port=f"{args.cli_port},{args.geom_port}",
                camera_enabled=False,
                config={"cfg": args.cfg, "audio_device": args.audio_device,
                        "ballistics": args.ballistics, **session.tags()},
                mode="iwr6843",
            )

    gspro = None
    if args.gspro_host:
        gspro = GSProClient(host=args.gspro_host, port=args.gspro_port)
        try:
            gspro.connect()
            log.info("[gspro] connected to %s:%s", args.gspro_host, args.gspro_port)
        except OSError as e:
            # Non-fatal: run the launch monitor even if GSPro isn't reachable
            # yet (e.g. sim not started up on the Windows PC). Shots just
            # won't forward until you fix the connection and restart.
            log.warning("[gspro] connect to %s:%s failed (%s) -- continuing "
                        "without GSPro", args.gspro_host, args.gspro_port, e)
            gspro = None

    # Re-assert the HiFiBerry ADC mux/gain before the audio ring opens the
    # device -- guards against post-power-cut ALSA defaults (audit D-6).
    _assert_adc_routing(env)

    # sounddevice treats a numeric STRING as a device-name substring, not
    # an index -- hardware.env's AUDIO_DEVICE=2 must become int 2 or it
    # would match any device with "2" in its name (audit E-5).
    audio_device = args.audio_device
    if isinstance(audio_device, str) and audio_device.isdigit():
        audio_device = int(audio_device)

    monitor = IWR6843Monitor(args.cli_port, args.geom_port, args.cfg,
                              audio_device=audio_device, gspro=gspro,
                              session=session)
    monitor.set_club(club)
    ofserver.monitor = monitor
    monitor.start(shot_callback=ofserver.on_shot_detected)

    print("=" * 50)
    print("  OpenFlight -- IWR6843 + K-MC1 hardware")
    print("=" * 50)
    print(f"Session: {session.summary()}")
    print(f"Ballistics: {'ENABLED' if args.ballistics else 'DISABLED (table fallback)'}")
    print(f"GSPro: {'connected -> ' + args.gspro_host if gspro else 'not configured'}")
    print(f"Server starting at http://{args.host}:{args.web_port}")

    try:
        ofserver.socketio.run(ofserver.app, host=args.host, port=args.web_port,
                               debug=False, allow_unsafe_werkzeug=True)
    finally:
        monitor.stop()


if __name__ == "__main__":
    main()
