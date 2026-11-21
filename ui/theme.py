"""Dark developer-tool palette and small styling helpers."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

COLORS = {
    "bg": "#0B0D0E",
    "sidebar": "#101315",
    "surface": "#14181A",
    "surface_alt": "#1A1F22",
    "surface_hover": "#22282C",
    "border": "#2A3135",
    "text": "#E7EAEC",
    "text_muted": "#8A949B",
    "text_dim": "#5F6A71",
    "accent": "#FFE165",
    "accent_hover": "#F2D34F",
    "accent_text": "#111315",
    "success": "#3DDC97",
    "warning": "#F5A623",
    "error": "#FF6B6B",
    "info": "#4CC2FF",
    "terminal_bg": "#080A0B",
    "terminal_text": "#C9D1D9",
}

UI_FONT = "Segoe UI"
MONO_FONT = "Cascadia Mono"

STATUS_COLORS = {
    "ok": COLORS["success"],
    "success": COLORS["success"],
    "succeeded": COLORS["success"],
    "running": COLORS["info"],
    "pending": COLORS["text_dim"],
    "waiting_for_user": COLORS["warning"],
    "warning": COLORS["warning"],
    "error": COLORS["error"],
    "failed": COLORS["error"],
    "cancelled": COLORS["warning"],
    "info": COLORS["info"],
    "unknown": COLORS["text_dim"],
}

PAGE_TITLES = {
    "dashboard": ("Dashboard", "System status and your most recent conversion"),
    "conversion": ("New Conversion", "Convert a UIFlow MicroPython app into Cardputer firmware"),
    "history": ("Build History", "Every conversion, source file, log and binary is kept"),
    "settings": ("Settings", "Credentials, repository and toolchain configuration"),
    "about": ("About", "How Py2Cardputer works and what it will not do"),
}


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=UI_FONT, size=size, weight=weight)


def mono_font(size: int = 12, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=MONO_FONT, size=size, weight=weight)


def status_color(state: str) -> str:
    return STATUS_COLORS.get((state or "unknown").lower(), COLORS["text_dim"])


def primary_button_options() -> dict[str, Any]:
    return {
        "fg_color": COLORS["accent"],
        "hover_color": COLORS["accent_hover"],
        "text_color": COLORS["accent_text"],
        "corner_radius": 8,
        "font": font(13, "bold"),
        "height": 38,
    }


def secondary_button_options() -> dict[str, Any]:
    return {
        "fg_color": COLORS["surface_alt"],
        "hover_color": COLORS["surface_hover"],
        "text_color": COLORS["text"],
        "border_width": 1,
        "border_color": COLORS["border"],
        "corner_radius": 8,
        "font": font(13),
        "height": 34,
    }


def entry_options() -> dict[str, Any]:
    return {
        "fg_color": COLORS["surface_alt"],
        "border_color": COLORS["border"],
        "text_color": COLORS["text"],
        "placeholder_text_color": COLORS["text_dim"],
        "corner_radius": 8,
        "height": 34,
        "font": font(13),
    }


def apply_appearance() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
