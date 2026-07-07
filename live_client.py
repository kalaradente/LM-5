"""
live_client.py — push a typed-in shot to a running OpenFlight server so it
renders in the real React UI.

Requires the server to be started in mock+ballistics mode, and requires the
"simulate_custom_shot" socket handler added to server.py (see
openflight_upstream/src/openflight/server.py, next to "simulate_shot"):

    cd openflight_upstream
    uv run python -m openflight.server --mock --ballistics
    # UI at http://localhost:8080 (or `cd ui && npm run dev` for hot reload)

Then run shot_simulator.py with --live in another terminal.
"""

from __future__ import annotations

try:
    import socketio
except ImportError:
    socketio = None


class LiveClient:
    def __init__(self, url: str):
        if socketio is None:
            raise SystemExit(
                "error: --live needs the python-socketio client.\n"
                "  pip install \"python-socketio[client]\"\n"
            )
        self.sio = socketio.Client()
        try:
            self.sio.connect(url)
        except Exception as exc:  # noqa: BLE001 - surface any connect failure plainly
            raise SystemExit(
                f"error: could not connect to OpenFlight server at {url}: {exc}\n"
                "Start it first with:\n"
                "  cd openflight_upstream && uv run python -m openflight.server "
                "--mock --ballistics\n"
            ) from exc
        print(f"[live] connected to {url}")

    def send(self, typed) -> None:
        from shot_simulator import spin_axis_deg

        self.sio.emit(
            "simulate_custom_shot",
            {
                "ball_speed_mph": typed.ball_speed_mph,
                "spin_rpm": typed.spin_rpm,
                "launch_angle_deg": typed.launch_angle_deg,
                "side_angle_deg": typed.side_angle_deg,
                "spin_axis_deg": spin_axis_deg(typed.spin_rpm, typed.side_spin_rpm),
                "club": typed.club.value,
            },
        )
        # emit() only queues the packet on the transport's write loop; if the
        # process exits immediately the shot is silently dropped (observed
        # 2026-07-07: "[live] shot sent" printed, server never received it).
        # Give the background writer a beat, then close the socket cleanly.
        self.sio.sleep(1.0)
        self.sio.disconnect()
        print("[live] shot sent to server")
