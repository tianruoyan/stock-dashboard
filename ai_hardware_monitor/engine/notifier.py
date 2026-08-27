from __future__ import annotations

import subprocess
from typing import Any


def _applescript_string(value: Any) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


class DesktopNotifier:
    """Send a local macOS notification; never sends data off device."""

    def send(self, *, title: str, message: str, sound: str = "default") -> dict[str, Any]:
        script = (
            f'display notification "{_applescript_string(message)}" '
            f'with title "{_applescript_string(title)}" '
            f'sound name "{_applescript_string(sound)}"'
        )
        completed = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return {
            "state": "sent" if completed.returncode == 0 else "failed",
            "channel": "macos_notification_center",
            "returncode": completed.returncode,
            "detail": completed.stderr.strip()[:160] if completed.returncode else "",
        }

