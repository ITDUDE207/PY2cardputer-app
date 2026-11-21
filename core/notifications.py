"""Best-effort desktop notifications.

The GUI always shows an in-app banner. On Windows, Py2Cardputer also tries to
raise a native toast through PowerShell. No third-party dependency is required.
Native toasts are best-effort because unpackaged applications must have a
registered AppUserModelID; the in-app banner remains the reliable channel.
"""

from __future__ import annotations

import base64
import logging
import shutil
import subprocess
import sys
from typing import Callable
from xml.sax.saxutils import escape

from core.logger import redact

TOAST_APP_ID = "Py2Cardputer"
MAX_TOAST_TEXT = 1800


def _powershell_string(value: str) -> str:
    return str(value).replace("'", "''")


def build_windows_toast_script(title: str, message: str) -> str:
    """Return a PowerShell script that displays a two-line Windows toast."""
    safe_title = _powershell_string(escape(redact(title)[:MAX_TOAST_TEXT]))
    safe_message = _powershell_string(escape(redact(message)[:MAX_TOAST_TEXT]))
    return f"""\
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$text = $template.GetElementsByTagName('text')
$text.Item(0).AppendChild($template.CreateTextNode('{safe_title}')) | Out-Null
$text.Item(1).AppendChild($template.CreateTextNode('{safe_message}')) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{TOAST_APP_ID}').Show($toast)
"""


class Notifier:
    """Send best-effort native notifications without blocking the caller."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        native: bool = True,
        logger: logging.Logger | None = None,
        platform: str | None = None,
        which: Callable[[str], str | None] | None = None,
        popen: Callable[..., object] | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.native = bool(native)
        self.logger = logger or logging.getLogger("py2cardputer.notifications")
        self._platform = platform if platform is not None else sys.platform
        self._which = which or shutil.which
        self._popen = popen or subprocess.Popen

    def configure(self, *, enabled: bool, native: bool) -> None:
        self.enabled = bool(enabled)
        self.native = bool(native)

    def notify(self, title: str, message: str, level: str = "info") -> bool:
        """Attempt a native toast. Returns True when a process was launched."""
        if not self.enabled or not self.native:
            return False
        if not self._platform.lower().startswith("win"):
            self.logger.debug("Native notifications are only attempted on Windows")
            return False
        executable = self._which("powershell") or self._which("pwsh")
        if not executable:
            self.logger.debug("PowerShell was not found; skipping native notification")
            return False
        script = build_windows_toast_script(title, message)
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._popen(
                [
                    executable,
                    "-NoProfile",
                    "-NonInteractive",
                    "-WindowStyle",
                    "Hidden",
                    "-EncodedCommand",
                    encoded,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            return True
        except (OSError, ValueError) as exc:
            self.logger.debug("Native notification failed: %s", exc)
            return False
