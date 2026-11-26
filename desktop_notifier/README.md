# RCH Desktop Notifier

Independent Python consumer for operating-system desktop notifications. It includes local notification backends, cursor state, headless operation and a macOS menu-bar mode.

**Connection status:** the RCH Server exposes a WebSocket notification subscription; this consumer currently uses HTTP SSE. Live delivery with the current Server requires a WebSocket-capable consumer. Local notification tests remain available. See [Desktop Notifier](../backend/docs/desktop_notifier.md) for configuration and platform behavior, and [WebSocket Events and Notifications](../backend/docs/websocket_notifications.md) for the Server protocol.

## Local installation and test (macOS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py --init-config --config ./config.json
python run.py --config ./config.json --test-notification
```

The configuration contains the Server URL, administrator API Token, backend choice, sound preference and retry intervals. Protect the Token and local configuration. `--test-notification` tests the local OS backend without connecting to the Server. Windows has a PowerShell/WinRT Toast backend awaiting real-host verification.
