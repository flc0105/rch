# RCH Desktop Notifier

Standalone Python consumer for the RCH Notification Center. It keeps one authenticated SSE connection to the Server and projects each normalized RCH notification into the host operating system's desktop notification surface.

This first version targets **macOS 13.5**. Windows has a minimal PowerShell/WinRT toast backend but has not been validated on a real Windows host yet.

## Why this uses a dedicated SSE endpoint

The notifier consumes only:

```text
GET /api/notifications/stream
```

It does not subscribe to the Web UI's general `/api/stream` bus and does not need to know about `device_event`, background jobs, transfers, connection events, or other internal event types. RCH Server's existing `NotificationEventProjector` decides what becomes a notification.

The stream uses the notification id as the SSE `id`. After the first successfully delivered notification the client stores that id in `state.json`. On reconnect it sends `Last-Event-ID`, and the Server replays notifications written to SQLite after that cursor before returning to live delivery.

The very first connection intentionally receives **live notifications only**; it does not dump historical Notification Center records onto the desktop.

## Install on macOS 13.5

```bash
cd desktop_notifier
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py --init-config --config ./config.json
```

Edit `config.json`:

```json
{
  "server_url": "http://192.168.1.20:8085",
  "token": "YOUR_RCH_ADMIN_API_TOKEN",
  "sound": true,
  "backend": "auto",
  "reconnect_initial_seconds": 1,
  "reconnect_max_seconds": 30
}
```

For this first version the token is the existing RCH admin API token. The notifier only performs a GET against the notification stream, but the token itself still has the same authority as elsewhere in RCH; a dedicated read-only notifier credential can be added later.

Test local notification delivery before connecting to RCH:

```bash
python run.py --config ./config.json --test-notification
```

Then start the resident listener:

```bash
python run.py --config ./config.json
```

The process keeps a streaming HTTP connection open. It does **not** poll Notification Center. If the network connection is lost it reconnects with exponential backoff from 1 second up to the configured maximum.

## macOS backend behavior

`backend: "auto"` first attempts Apple's `UserNotifications.framework` through PyObjC. Apple scopes `UNUserNotificationCenter` authorization to an application identity, and bare Python installations differ in how well that works. If authorization or delivery fails, the first version automatically switches to the built-in macOS `osascript display notification` path so that the SSE-to-desktop pipeline remains usable before RCH Notifier is packaged as a real `.app` bundle.

You can force either path for testing:

```json
{"backend": "usernotifications"}
```

or:

```json
{"backend": "osascript"}
```

The later `.app`/menu-bar version should use its own bundle id and `UNUserNotificationCenter` as the canonical macOS backend.

## Environment overrides

Secrets do not have to live in JSON:

```bash
export RCH_NOTIFIER_SERVER_URL=http://192.168.1.20:8085
export RCH_NOTIFIER_TOKEN=...
export RCH_NOTIFIER_BACKEND=auto
python run.py --config ./config.json
```

## Cursor state

The client writes `state.json` beside the selected config file. Delete that file if you intentionally want to discard the reconnect cursor. A missing cursor starts from live events rather than replaying old history.

## Windows

The shared SSE/config/cursor code is cross-platform. The current Windows backend uses PowerShell and Windows Runtime Toast APIs as a first-pass implementation. It is intentionally not described as production-ready until tested on Windows.
