# Smart Notice Board

A cloud-connected smart notice board that lets administrators publish notices remotely and displays them on a Raspberry Pi-powered screen. The system combines a web-based admin panel, Firebase Realtime Database, a kiosk display, proximity-based screen control, QR codes, and audible alerts.

## Overview

The project replaces manually updated paper notices with a digital notice board. Administrators manage notices through a web interface; notice data is stored in Firebase Realtime Database and read by the display running on the Raspberry Pi.

### Key features

- **Web-based notice management:** Create and manage notices from the admin interface.
- **Cloud-backed updates:** Firebase Realtime Database stores notice data and display settings.
- **Automatic notice validity and expiry:** The display checks notice timing and removes notices that are no longer valid.
- **Notice rotation:** Multiple eligible notices can rotate on the display.
- **Priority and audible alerts:** Notices can carry priority information, and notices configured for an audible alert can trigger the connected buzzer.
- **QR codes and public notice view:** The display can show a QR code that leads viewers to a public notice page.
- **Presence-based screen control:** A VL53L0X time-of-flight sensor detects nearby people. The screen can be configured to stay on or to turn black after inactivity and wake when someone approaches.
- **Offline persistence for an already-running display:** During a test with the Raspberry Pi kept powered and Wi-Fi disconnected, a previously loaded notice remained visible and expired at its configured time.
- **RTC-backed local timekeeping:** A DS3231 RTC is configured on the Raspberry Pi to support local timekeeping when network access is unavailable while the Pi remains powered.

## System architecture

```text
Administrator
     |
     v
Web Admin Interface
     |
     v
Firebase Realtime Database
     |
     v
Raspberry Pi kiosk browser <---- Local HTTP server
     |                                |
     +---- Notice display             +---- Serves display files
     +---- Notice rotation
     +---- Validity / expiry checks
     +---- QR code
     +---- Presence overlay <---- Local presence service <---- VL53L0X sensor
     +---- Alert request ------> Local buzzer service -------> Buzzer
     |
     v
Public notice page (opened by QR code)
```

The web admin interface and public notice page are deployed separately from the local Raspberry Pi display. The Raspberry Pi serves the display files locally and runs the kiosk browser.

## Hardware

| Component | Role |
|---|---|
| Raspberry Pi 3B+ | Runs the local display server, kiosk browser, and Python hardware services |
| Waveshare 7-inch HDMI LCD (1024 × 600) | Displays the notices and provides a touchscreen interface |
| VL53L0X time-of-flight distance sensor | Detects nearby people for presence-based screen control |
| DS3231 real-time clock module | Provides local clock support |
| Buzzer | Produces audible alerts for configured notices |
| Power supply and connecting leads | Power and connect the system components |

### Interfaces and pin notes

- The VL53L0X communicates with the Raspberry Pi over I²C.
- The DS3231 RTC is connected over I²C and configured using the `i2c-rtc,ds3231` device-tree overlay.
- The buzzer output uses **GPIO18**.
- The Waveshare display connects over HDMI; its touchscreen interface uses USB.

Refer to the physical build and wiring notes for exact power, ground, and signal connections.

## Software components

| Component | Purpose |
|---|---|
| `admin/index.html` | Web-based admin interface for managing notices and display settings |
| `display/index.html` | Main notice-board display interface |
| `display/start-noticeboard.sh` | Starts Chromium in kiosk mode on the Raspberry Pi |
| `hardware/presence_service.py` | Reads the VL53L0X sensor, evaluates presence, and exposes local status |
| `hardware/buzzer_service.py` | Runs the local buzzer-control endpoint |
| `public-notice/index.html` | Public-facing notice page opened from a QR code |
| `public-notice/vercel.json` | Deployment/routing configuration for the public notice page |

## Notice data

Notices are stored under the Firebase Realtime Database `notices` node. A notice record can include fields such as:

| Field | Meaning |
|---|---|
| `title` | Notice heading |
| `description` | Notice body/details |
| `date` | Notice date |
| `time` | Displayed notice time |
| `startTime` | Beginning of the notice's validity window |
| `endTime` | End of the notice's validity window |
| `priority` | Notice priority, for example `HIGH` |
| `venue` | Venue or location |
| `audibleAlert` | Whether the notice requests an audible alert |
| `createdAt` | Creation timestamp |
| `updatedAt` | Last-update timestamp |

The display reads the notice records and applies the validity window before showing eligible notices. Display settings are stored under `displaySettings`; the presence service reads `displaySettings/mode`.

Example structure (illustrative; actual records may contain additional fields):

```json
{
  "displaySettings": {
    "mode": "alwaysOn"
  },
  "notices": {
    "<notice-id>": {
      "title": "Firebase Test Notice",
      "description": "This notice was published through Firebase.",
      "date": "2026-10-22",
      "time": "12:30",
      "startTime": "2026-10-22T16:47",
      "endTime": "2026-10-22T16:50",
      "priority": "HIGH",
      "venue": "HOME",
      "audibleAlert": false,
      "createdAt": 1791087532055,
      "updatedAt": 1792667884494
    }
  }
}
```

The example values above illustrate the data shape and are not live configuration values.

## Presence-based screen control

The presence service uses the VL53L0X sensor over I²C and applies these configured values:

- **Presence distance threshold:** 900 mm
- **Qualification time:** 1 second
- **Display sleep timeout:** 30 seconds
- **Display mode setting:** Read from Firebase at `displaySettings/mode`
- **Local status endpoint:** `http://127.0.0.1:8766/status`

The service provides local status information including the selected mode, whether the display should be awake, sensor health, and the measured distance. The browser uses this status to control the black screen overlay. In Always On mode, the display remains awake; in presence-based mode, it sleeps after the configured inactivity timeout and wakes when presence is detected.

## Audible alerts

The buzzer is controlled by `hardware/buzzer_service.py`, which runs as a local service. The display sends an alert request to the local endpoint:

- `http://127.0.0.1:8765/beep`

The buzzer output is connected to GPIO18. The buzzer service is managed by systemd so it can start automatically and be restarted if it exits.

## Running on the Raspberry Pi

The local display server is managed by systemd using `noticeboard.service`. It serves the `display/` directory on port **8000**:

```text
http://localhost:8000/
```

The kiosk launcher starts Chromium in kiosk mode and opens the local display page. The display server and the hardware services are configured to run independently of an interactive SSH session.

To inspect the installed service state on the Pi:

```bash
systemctl status noticeboard.service
systemctl status noticeboard-buzzer.service
systemctl status noticeboard-presence.service
```

To inspect the installed unit definitions:

```bash
systemctl cat noticeboard.service
systemctl cat noticeboard-buzzer.service
systemctl cat noticeboard-presence.service
```

The presence service unit is installed on the Raspberry Pi. Its exact unit-file contents are specific to the device installation.

## Offline behaviour and testing

The system was tested with the Raspberry Pi still powered while Wi-Fi was physically disconnected:

1. The kiosk was launched from the Raspberry Pi's on-device shell.
2. A notice with an expiry time in the near future was published and displayed.
3. Wi-Fi was disconnected while the Pi remained powered.
4. The notice stayed visible while offline.
5. The notice disappeared at its configured expiry time.

The test demonstrated that an already-running kiosk with a previously loaded notice could retain and expire that notice without an active Wi-Fi connection. The Raspberry Pi's DS3231 RTC was also readable and aligned with the system clock during checks.

**Limitations of the test:** It did not establish that the display can cold-start without internet when its browser cache is empty, that all external resources work offline, or that time is retained after complete power loss. The project does not rely on battery backup through a complete power outage.

## Deployment

- **Firebase:** Realtime Database is used for notice records and display settings.
- **Admin interface:** Deployed as a web application.
- **Public notice page:** Deployed as a separate web page and opened through the notice QR code.
- **Raspberry Pi display:** Served locally on port 8000 and rendered in Chromium kiosk mode.

Keep Firebase configuration and database rules appropriate for your deployment. Do not commit private keys, passwords, service-account files, or other secrets.

## Repository layout

```text
.
├── admin/
│   └── index.html
├── display/
│   ├── index.html
│   └── start-noticeboard.sh
├── hardware/
│   ├── presence_service.py
│   └── buzzer_service.py
└── public-notice/
    ├── index.html
    └── vercel.json
```

This layout lists the main project files; additional configuration or support files may exist.

## Current implementation notes

- The display uses a browser-based interface rather than rendering directly from a microcontroller.
- Firebase Realtime Database is the cloud data store.
- The local HTTP server uses Python's built-in `http.server` module.
- The screen's presence behaviour and buzzer output are handled by separate Python services.
- The DS3231 RTC is configured on the Raspberry Pi using the `i2c-rtc,ds3231` overlay.
- The working offline test depends on the kiosk already being open and the notice having been loaded before Wi-Fi is disconnected.

## License

No license is specified here. Add a license file if you want to define how others may use, modify, and distribute this project.
