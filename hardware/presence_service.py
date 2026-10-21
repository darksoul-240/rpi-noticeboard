#!/usr/bin/env python3
"""
Presence service for the Smart Notice Board.

- Reads VL53L0X distance over I2C.
- Reads displaySettings/mode from Firebase RTDB's REST endpoint.
- Serves GET http://127.0.0.1:8766/status for display/index.html.
- This controls a black overlay in the webpage; it does not power off the LCD.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import board
import busio
import adafruit_vl53l0x

# -------------------- EASY SETTINGS --------------------
PRESENCE_DISTANCE_MM = 900
PRESENCE_QUALIFY_SECONDS = 1.0
DISPLAY_SLEEP_TIMEOUT_SECONDS = 30  # Change this value to adjust idle timeout.
SENSOR_POLL_INTERVAL_SECONDS = 0.1
FIREBASE_MODE_POLL_SECONDS = 2.0
STATUS_HOST = "127.0.0.1"
STATUS_PORT = 8766
# -------------------------------------------------------

FIREBASE_MODE_URL = (
    "https://noticeboard-c1ed5-default-rtdb.asia-southeast1.firebasedatabase.app/"
    "displaySettings/mode.json"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [presence] %(levelname)s: %(message)s",
)

state_lock = threading.Lock()
display_mode = "alwaysOn"
display_awake = True
candidate_since = None
last_presence_time = None
last_sensor_distance_mm = None
sensor_ok = False
stopping = False


def fetch_display_mode():
    """Read the admin-selected mode from RTDB using its REST API."""
    request = Request(
        FIREBASE_MODE_URL,
        headers={"Accept": "application/json", "User-Agent": "SmartNoticeBoardPresence/1.0"},
    )
    with urlopen(request, timeout=3) as response:
        value = json.loads(response.read().decode("utf-8"))
    return "presenceBased" if value == "presenceBased" else "alwaysOn"


def set_mode(new_mode):
    """Apply mode transitions. Entering presence mode starts black immediately."""
    global display_mode, display_awake, candidate_since, last_presence_time
    with state_lock:
        if new_mode == display_mode:
            return
        old_mode = display_mode
        display_mode = new_mode
        candidate_since = None
        last_presence_time = None
        if new_mode == "alwaysOn":
            display_awake = True
        else:
            # Deliberately start asleep even if someone is already nearby.
            display_awake = False
        logging.info("Mode changed %s -> %s; displayAwake=%s",
                     old_mode, new_mode, display_awake)


def mode_worker():
    global stopping
    while not stopping:
        try:
            set_mode(fetch_display_mode())
        except (URLError, HTTPError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            # Keep the last known mode during temporary Firebase/network failures.
            logging.warning("Could not read Firebase display mode: %s", exc)
        time.sleep(FIREBASE_MODE_POLL_SECONDS)


def sensor_worker(sensor):
    global candidate_since, last_presence_time, last_sensor_distance_mm, sensor_ok, display_awake
    while not stopping:
        now = time.monotonic()
        try:
            distance = int(sensor.range)
            # The VL53L0X library may return out-of-range values (e.g. 8190/8191).
            valid_presence = 0 < distance <= PRESENCE_DISTANCE_MM
            with state_lock:
                last_sensor_distance_mm = distance
                sensor_ok = True

                if display_mode == "alwaysOn":
                    display_awake = True
                    candidate_since = None
                elif valid_presence:
                    last_presence_time = now
                    if candidate_since is None:
                        candidate_since = now
                    elif (not display_awake and
                          now - candidate_since >= PRESENCE_QUALIFY_SECONDS):
                        display_awake = True
                        logging.info("Presence qualified at %d mm; waking webpage", distance)
                else:
                    candidate_since = None
                    if (display_awake and last_presence_time is not None and
                            now - last_presence_time >= DISPLAY_SLEEP_TIMEOUT_SECONDS):
                        display_awake = False
                        logging.info("No presence for %d seconds; blanking webpage",
                                     DISPLAY_SLEEP_TIMEOUT_SECONDS)
        except Exception as exc:
            with state_lock:
                sensor_ok = False
                candidate_since = None
            logging.warning("ToF sensor read failed: %s", exc)
        time.sleep(SENSOR_POLL_INTERVAL_SECONDS)


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/status":
            self.send_error(404)
            return
        with state_lock:
            payload = {
                "mode": display_mode,
                "displayAwake": bool(display_awake),
                "sensorOk": bool(sensor_ok),
                "distanceMm": last_sensor_distance_mm,
            }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        logging.info("HTTP " + fmt, *args)


def main():
    global stopping
    logging.info("Starting VL53L0X on I2C...")
    i2c = busio.I2C(board.SCL, board.SDA)
    sensor = adafruit_vl53l0x.VL53L0X(i2c)
    logging.info("VL53L0X initialized. Threshold=%d mm; qualify=%.1f s; timeout=%d s",
                 PRESENCE_DISTANCE_MM, PRESENCE_QUALIFY_SECONDS,
                 DISPLAY_SLEEP_TIMEOUT_SECONDS)

    # Start in Always On until the current Firebase mode has been read.
    threading.Thread(target=mode_worker, daemon=True, name="firebase-mode").start()
    threading.Thread(target=sensor_worker, args=(sensor,), daemon=True, name="tof-sensor").start()

    server = ThreadingHTTPServer((STATUS_HOST, STATUS_PORT), StatusHandler)
    logging.info("Status endpoint listening at http://%s:%d/status", STATUS_HOST, STATUS_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopping = True
        server.server_close()
        try:
            i2c.deinit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
