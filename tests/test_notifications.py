from __future__ import annotations

import base64

from core.logger import clear_secrets, register_secret
from core.notifications import Notifier, build_windows_toast_script


def test_toast_script_escapes_xml_and_powershell_quotes() -> None:
    script = build_windows_toast_script("Build & <done> 'ok'", "line 1 & line 2")
    assert "Build &amp; &lt;done&gt; ''ok''" in script
    assert "line 1 &amp; line 2" in script
    assert "CreateToastNotifier('Py2Cardputer')" in script


def test_toast_script_redacts_registered_secret() -> None:
    register_secret("super-secret-value")
    try:
        script = build_windows_toast_script("Done", "token super-secret-value")
        assert "super-secret-value" not in script
        assert "***REDACTED***" in script
    finally:
        clear_secrets()


def test_notifier_disabled_does_not_launch_process() -> None:
    calls = []
    notifier = Notifier(
        enabled=False,
        platform="win32",
        which=lambda _name: "powershell",
        popen=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    assert notifier.notify("Title", "Message") is False
    assert calls == []


def test_notifier_non_windows_is_noop() -> None:
    calls = []
    notifier = Notifier(
        platform="linux",
        which=lambda _name: "powershell",
        popen=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    assert notifier.notify("Title", "Message") is False
    assert calls == []


def test_notifier_windows_uses_encoded_powershell_command() -> None:
    captured: dict = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    notifier = Notifier(
        platform="win32",
        which=lambda _name: "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
        popen=fake_popen,
    )
    assert notifier.notify("Build done", "Binary ready") is True
    args = captured["args"]
    assert "-EncodedCommand" in args
    encoded = args[args.index("-EncodedCommand") + 1]
    script = base64.b64decode(encoded).decode("utf-16-le")
    assert "Build done" in script
    assert "Binary ready" in script
    assert captured["kwargs"]["creationflags"] == 0


def test_notifier_without_powershell_returns_false() -> None:
    notifier = Notifier(platform="win32", which=lambda _name: None)
    assert notifier.notify("Title", "Message") is False


def test_notifier_can_be_reconfigured() -> None:
    notifier = Notifier(enabled=False, native=False, platform="win32")
    notifier.configure(enabled=True, native=True)
    assert notifier.enabled is True
    assert notifier.native is True
