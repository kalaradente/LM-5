"""
gspro_adapter.py — send shots to GSPro via its Open Connect API (v1).

GSPro listens on a TCP port (default 921) on the Windows PC running the sim.
Each shot is one JSON object. This adapter maps our fused Shot dict onto the
GSPro schema and manages the socket + heartbeat.

Usage:
    gspro = GSProClient(host="192.168.1.50")   # the GSPro PC's LAN address
    gspro.connect()
    fuser = ShotFuser(publish=gspro.send_shot, audio=ring)

Field mapping (ours -> GSPro BallData):
    ball_speed_mph      -> Speed   (mph)
    launch_angle_deg    -> VLA     (vertical launch angle)
    side_angle_deg      -> HLA     (horizontal launch angle; + = right)
    spin_rpm            -> TotalSpin
    spin_axis_hint_deg  -> SpinAxis (+ = fade/right tilt)
    club_speed_mph      -> ClubData.Speed (optional)
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Optional

GSPRO_PORT = 921
API_VERSION = "1"
DEVICE_ID = "OpenFlight-IWR6843"


class GSProClient:
    def __init__(self, host: str, port: int = GSPRO_PORT,
                 units: str = "Yards", heartbeat_s: float = 5.0):
        self.host, self.port = host, port
        self.units = units
        self.heartbeat_s = heartbeat_s
        self.sock: Optional[socket.socket] = None
        self.shot_number = 0
        self._hb_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

    # ---- connection -----------------------------------------------------

    def connect(self, timeout: float = 5.0) -> None:
        self.sock = socket.create_connection((self.host, self.port),
                                             timeout=timeout)
        self.sock.settimeout(2.0)
        self._running = True
        self._hb_thread = threading.Thread(target=self._heartbeat_loop,
                                           daemon=True)
        self._hb_thread.start()

    def close(self) -> None:
        self._running = False
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    # ---- messages -------------------------------------------------------

    def _base(self, ball: bool, club: bool, ready: bool = True,
              heartbeat: bool = False) -> dict:
        return {
            "DeviceID": DEVICE_ID,
            "Units": self.units,
            "ShotNumber": self.shot_number,
            "APIversion": API_VERSION,
            "ShotDataOptions": {
                "ContainsBallData": ball,
                "ContainsClubData": club,
                "LaunchMonitorIsReady": ready,
                "LaunchMonitorBallDetected": ball,
                "IsHeartBeat": heartbeat,
            },
        }

    def send_shot(self, shot: dict) -> Optional[dict]:
        """Map a fused Shot dict to GSPro JSON and transmit.
        Returns GSPro's response dict (code 200/201 = accepted)."""
        required = ("ball_speed_mph", "launch_angle_deg", "side_angle_deg")
        if any(shot.get(k) is None for k in required):
            return None                       # not a sendable shot

        self.shot_number += 1
        msg = self._base(ball=True, club=shot.get("club_speed_mph") is not None)
        msg["BallData"] = {
            "Speed": float(shot["ball_speed_mph"]),
            "VLA": float(shot["launch_angle_deg"]),
            "HLA": float(shot["side_angle_deg"]),
            "TotalSpin": float(shot.get("spin_rpm") or 0.0),
            "SpinAxis": float(shot.get("spin_axis_hint_deg") or 0.0),
        }
        if shot.get("club_speed_mph") is not None:
            msg["ClubData"] = {"Speed": float(shot["club_speed_mph"])}
        return self._send(msg)

    def _heartbeat_loop(self) -> None:
        while self._running:
            time.sleep(self.heartbeat_s)
            try:
                hb = self._base(ball=False, club=False, heartbeat=True)
                self._send(hb, expect_reply=False)
            except OSError:
                pass                          # transient; next beat retries

    def _send(self, msg: dict, expect_reply: bool = True) -> Optional[dict]:
        if self.sock is None:
            raise ConnectionError("not connected to GSPro")
        payload = json.dumps(msg).encode()
        with self._lock:
            self.sock.sendall(payload)
            if not expect_reply:
                return None
            try:
                raw = self.sock.recv(4096)
            except socket.timeout:
                return None
            if not raw:
                return None
        try:
            return json.loads(raw.decode())
        except json.JSONDecodeError:
            return None
