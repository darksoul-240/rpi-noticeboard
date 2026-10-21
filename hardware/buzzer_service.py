#!/usr/bin/env python3
"""Local HTTP service for the Smart Notice Board buzzer (GPIO18 / BCM 18)."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import threading
import time

try:
    import RPi.GPIO as GPIO
except ImportError as exc:
    raise SystemExit(
        "RPi.GPIO is not available to this Python interpreter. Install/enable the "
        "Raspberry Pi GPIO library before starting the buzzer service."
    ) from exc

HOST = "127.0.0.1"
PORT = 8765
BUZZER_GPIO = 18  # BCM numbering; physical pin 12
FREQUENCY_HZ = 2000
BEEP_SECONDS = 0.15
STATE_FILE = "/home/ibrahim/nb/hardware/processed_alerts.json"

state_lock = threading.Lock()
buzzer_lock = threading.Lock()


def load_processed_ids():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            return set(str(item) for item in data)
    except (OSError, json.JSONDecodeError):
        pass
    return set()


processed_ids = load_processed_ids()


def save_processed_ids():
    directory = os.path.dirname(STATE_FILE)
    os.makedirs(directory, exist_ok=True)
    temporary = STATE_FILE + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(sorted(processed_ids), handle)
    os.replace(temporary, STATE_FILE)


def beep_once():
    # Serialize PWM access so concurrent requests cannot overlap beeps.
    with buzzer_lock:
        pwm = GPIO.PWM(BUZZER_GPIO, FREQUENCY_HZ)
        try:
            pwm.start(50)
            time.sleep(BEEP_SECONDS)
        finally:
            pwm.stop()


class BuzzerHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/beep":
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            event_id = self.rfile.read(min(length, 4096)).decode("utf-8").strip()
        except (ValueError, UnicodeDecodeError):
            self.send_error(400, "Invalid event ID")
            return

        if not event_id:
            self.send_error(400, "Missing event ID")
            return

        with state_lock:
            if event_id in processed_ids:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"duplicate ignored")
                return
            # Persist before beeping to prevent repeated Firebase snapshots
            # or service restarts from replaying this event.
            processed_ids.add(event_id)
            try:
                save_processed_ids()
            except OSError as exc:
                processed_ids.discard(event_id)
                self.send_error(500, f"Could not persist event ID: {exc}")
                return

        try:
            beep_once()
        except Exception as exc:
            self.send_error(500, f"Buzzer failed: {exc}")
            return

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"beeped")

    def log_message(self, fmt, *args):
        print("[buzzer] " + (fmt % args))


def main():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BUZZER_GPIO, GPIO.OUT, initial=GPIO.LOW)
    try:
        server = HTTPServer((HOST, PORT), BuzzerHandler)
        print(f"Buzzer service listening on http://{HOST}:{PORT}")
        server.serve_forever()
    finally:
        GPIO.cleanup(BUZZER_GPIO)


if __name__ == "__main__":
    main()
