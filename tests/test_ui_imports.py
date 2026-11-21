"""Import-level checks for the GUI.

Tk cannot be rendered in headless CI, so this test stubs ``customtkinter`` and
``tkinter`` and verifies that every UI module imports cleanly and exposes the
expected entry points. Widget construction itself requires a real display and
is verified manually on Windows (see README).
"""

from __future__ import annotations

import sys
import types

import pytest


class _AnyCallable:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __call__(self, *args, **kwargs) -> "_AnyCallable":
        return _AnyCallable()

    def __getattr__(self, name: str) -> "_AnyCallable":
        return _AnyCallable()


class _DummyWidget:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __getattr__(self, name: str) -> _AnyCallable:
        return _AnyCallable()

    def __call__(self, *args, **kwargs) -> "_DummyWidget":
        return _DummyWidget()


class _WidgetModule(types.ModuleType):
    def __getattr__(self, name: str):
        return _DummyWidget


class _PlainModule(types.ModuleType):
    def __getattr__(self, name: str):
        return _AnyCallable()


@pytest.fixture()
def gui_stubs(monkeypatch):
    for name in [module for module in sys.modules if module == "ui" or module.startswith("ui.")]:
        sys.modules.pop(name, None)
    monkeypatch.setitem(sys.modules, "customtkinter", _WidgetModule("customtkinter"))
    tkinter_stub = _PlainModule("tkinter")
    monkeypatch.setitem(sys.modules, "tkinter", tkinter_stub)
    yield
    for name in [module for module in sys.modules if module == "ui" or module.startswith("ui.")]:
        sys.modules.pop(name, None)


def test_ui_modules_import(gui_stubs) -> None:
    import ui.about
    import ui.app
    import ui.conversion
    import ui.dashboard
    import ui.history
    import ui.settings
    import ui.theme
    import ui.widgets

    assert ui.app.APP_VERSION == "1.0"
    assert issubclass(ui.app.Py2CardputerApp, ui.app.ctk.CTk)
    assert callable(ui.app.Py2CardputerApp.start_conversion)
    assert callable(ui.app.Py2CardputerApp.cancel_conversion)
    assert callable(ui.app.Py2CardputerApp.check_openhands)
    assert callable(ui.app.Py2CardputerApp.save_settings)
    assert hasattr(ui.app.Py2CardputerApp, "clear_api_key")
    assert ui.theme.COLORS["bg"].startswith("#")
    assert set(ui.theme.PAGE_TITLES) == {"dashboard", "conversion", "history", "settings", "about"}


def test_navigation_covers_required_sections(gui_stubs) -> None:
    import ui.app

    names = [name for name, _label in ui.app.NAV_ITEMS]
    assert names == ["dashboard", "conversion", "history", "settings", "about"]


def test_pages_expose_expected_hooks(gui_stubs) -> None:
    import ui.conversion
    import ui.dashboard
    import ui.history
    import ui.settings

    assert callable(ui.dashboard.DashboardPage.refresh)
    assert callable(ui.conversion.ConversionPage.choose_file)
    assert callable(ui.conversion.ConversionPage.on_progress)
    assert callable(ui.conversion.ConversionPage.on_job_finished)
    assert callable(ui.history.HistoryPage.refresh)
    assert callable(ui.settings.SettingsPage.save)
