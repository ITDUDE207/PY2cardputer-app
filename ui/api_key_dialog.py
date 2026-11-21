"""Modal dialog for saving the OpenHands API key to the local ``.env`` file."""

from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from ui.theme import (
    COLORS,
    entry_options,
    font,
    primary_button_options,
    secondary_button_options,
)
from ui.widgets import SectionCard

KEY_PAGE_URL = "https://app.all-hands.dev/settings/api-keys"


class ApiKeyDialog(ctk.CTkToplevel):
    """Ask for an API key without exposing it in the main window.

    The key is written only to the git-ignored ``.env`` file. It is never sent
    to GitHub, added to a pull request, or written to ``config.json``/logs.
    """

    def __init__(
        self,
        app,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(app)
        self.app = app
        self.on_saved = on_saved
        self.title("Save OpenHands API key")
        self.geometry("640x390")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["bg"])
        self.transient(app)
        self.grab_set()
        self.grid_columnconfigure(0, weight=1)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        card = SectionCard(
            self,
            "OpenHands API key",
            "Stored only on this PC in .env (git-ignored). It is never committed to "
            "GitHub or included in a pull request.",
        )
        card.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 12))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        self.entry = ctk.CTkEntry(
            body,
            placeholder_text="Paste your OpenHands API key",
            show="*",
            **entry_options(),
        )
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda _event: self._save())

        controls = ctk.CTkFrame(body, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        controls.grid_columnconfigure(1, weight=1)
        self.show_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            controls,
            text="Show key",
            variable=self.show_var,
            command=self._toggle_visibility,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["text_muted"],
            font=font(11),
            border_color=COLORS["border"],
            checkmark_color=COLORS["bg"],
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            controls,
            text="Open key page",
            command=self._open_key_page,
            **secondary_button_options(),
        ).grid(row=0, column=2, sticky="e")

        self.status_label = ctk.CTkLabel(
            body,
            text="",
            font=font(11),
            text_color=COLORS["text_muted"],
            anchor="w",
            justify="left",
            wraplength=560,
        )
        self.status_label.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=1, column=0, sticky="e", padx=20, pady=(0, 20))
        ctk.CTkButton(
            buttons,
            text="Save API key",
            command=self._save,
            width=150,
            **primary_button_options(),
        ).pack(side="left")
        ctk.CTkButton(
            buttons,
            text="Cancel",
            command=self.destroy,
            **secondary_button_options(),
        ).pack(side="left", padx=(8, 0))

        self.bind("<Escape>", lambda _event: self.destroy())
        self.after(50, self._center)
        self.after(80, self.entry.focus_set)

    def _toggle_visibility(self) -> None:
        self.entry.configure(show="" if self.show_var.get() else "*")

    def _open_key_page(self) -> None:
        self.app.open_url(KEY_PAGE_URL)

    def _save(self) -> None:
        value = self.entry.get().strip()
        if not value:
            self._set_status("Enter an OpenHands API key first.", "error")
            return
        ok, message = self.app.save_api_key(value)
        if not ok:
            self._set_status(message, "error")
            return
        self.entry.delete(0, "end")
        self._set_status(message, "success")
        if self.on_saved:
            self.on_saved()
        self.after(650, self.destroy)

    def _set_status(self, message: str, level: str) -> None:
        self.status_label.configure(
            text=message,
            text_color=COLORS[level] if level in COLORS else COLORS["text_muted"],
        )

    def _center(self) -> None:
        try:
            self.update_idletasks()
            width = max(self.winfo_width(), 640)
            height = max(self.winfo_height(), 390)
            x = self.app.winfo_rootx() + max(0, (self.app.winfo_width() - width) // 2)
            y = self.app.winfo_rooty() + max(0, (self.app.winfo_height() - height) // 2)
            self.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:  # pragma: no cover - window-manager specific
            pass
