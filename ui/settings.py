"""Settings page: credentials, repository, toolchain and timing."""

from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from ui.theme import (
    COLORS,
    entry_options,
    font,
    primary_button_options,
    secondary_button_options,
    status_color,
)
from ui.widgets import SectionCard

FIELDS = [
    ("openhands_api_url", "API URL"),
    ("openhands_api_key", "API key"),
    ("openhands_llm_model", "LLM model (optional)"),
    ("github_repository", "GitHub repository"),
    ("arduino_cli_path", "Arduino CLI path"),
    ("arduino_fqbn", "Arduino FQBN"),
    ("build_dir", "Build directory"),
    ("poll_interval_seconds", "Polling interval (s)"),
    ("startup_timeout_seconds", "Startup timeout (s)"),
    ("execution_timeout_seconds", "Execution timeout (s)"),
]
SECRET_FIELDS = {"openhands_api_key"}
NUMERIC_FIELDS = {
    "poll_interval_seconds",
    "startup_timeout_seconds",
    "execution_timeout_seconds",
}


class SettingsPage(ctk.CTkFrame):
    def __init__(self, app, master) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.entries: dict[str, ctk.CTkEntry] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

        self._build_openhands_card()
        self._build_github_card()
        self._build_arduino_card()
        self._build_runtime_card()
        self._build_actions()
        self.reload()

    # ------------------------------------------------------------------ build
    def _build_openhands_card(self) -> None:
        card = SectionCard(
            self.scroll,
            "OpenHands Cloud",
            "The API key is stored only in .env (git-ignored) and is never written to "
            "config.json, logs, GitHub or a pull request.",
        )
        card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        body = card.body
        body.grid_columnconfigure(1, weight=1)
        self._field(body, 0, "API URL", "openhands_api_url", placeholder="https://app.all-hands.dev")
        self._field(body, 1, "API key", "openhands_api_key", show="*", placeholder="Leave blank to keep the stored key")
        self._field(body, 2, "LLM model", "openhands_llm_model", placeholder="Optional model override")
        self.key_state_label = ctk.CTkLabel(
            body,
            text="",
            font=font(11),
            text_color=COLORS["text_muted"],
            anchor="w",
            justify="left",
            wraplength=780,
        )
        self.key_state_label.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        key_actions = ctk.CTkFrame(body, fg_color="transparent")
        key_actions.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ctk.CTkButton(
            key_actions,
            text="Save API key",
            command=self._save_key,
            width=150,
            **primary_button_options(),
        ).pack(side="left")
        ctk.CTkButton(
            key_actions,
            text="Remove stored API key",
            command=self._clear_key,
            width=170,
            **secondary_button_options(),
        ).pack(side="left", padx=(8, 0))

    def _build_github_card(self) -> None:
        card = SectionCard(
            self.scroll,
            "GitHub workspace",
            "Uses your existing local git authentication (Git Credential Manager or gh auth).",
        )
        card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        body = card.body
        body.grid_columnconfigure(1, weight=1)
        self._field(body, 0, "Repository", "github_repository", placeholder="owner/repo")

    def _build_arduino_card(self) -> None:
        card = SectionCard(
            self.scroll,
            "Arduino toolchain",
            "FQBN is configurable because board identifiers differ between core versions.",
        )
        card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        body = card.body
        body.grid_columnconfigure(1, weight=1)
        self._field(body, 0, "Arduino CLI path", "arduino_cli_path", placeholder="arduino-cli")
        self._field(body, 1, "FQBN", "arduino_fqbn", placeholder="m5stack:esp32:m5stack_cardputer")

    def _build_runtime_card(self) -> None:
        card = SectionCard(self.scroll, "Files and timing", "Paths are relative to the application folder")
        card.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        body = card.body
        body.grid_columnconfigure(1, weight=1)
        self._field(body, 0, "Build directory", "build_dir", placeholder="builds")
        self._field(body, 1, "Polling interval", "poll_interval_seconds", placeholder="5")
        self._field(body, 2, "Startup timeout", "startup_timeout_seconds", placeholder="900")
        self._field(body, 3, "Execution timeout", "execution_timeout_seconds", placeholder="5400")
        self.notifications_var = ctk.BooleanVar(value=True)
        self.native_notifications_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            body,
            text="Show notifications when a build finishes",
            variable=self.notifications_var,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["text"],
            font=font(12),
            border_color=COLORS["border"],
            checkmark_color=COLORS["bg"],
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 2))
        ctk.CTkCheckBox(
            body,
            text="Try native Windows toast (best effort; in-app banner always appears)",
            variable=self.native_notifications_var,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["text_muted"],
            font=font(11),
            border_color=COLORS["border"],
            checkmark_color=COLORS["bg"],
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))

    def _build_actions(self) -> None:
        card = ctk.CTkFrame(self.scroll, fg_color="transparent")
        card.grid(row=4, column=0, sticky="ew")
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            card,
            text="Save settings",
            command=self.save,
            width=150,
            **primary_button_options(),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            card,
            text="Test OpenHands",
            command=self.test_openhands,
            **secondary_button_options(),
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))
        ctk.CTkButton(
            card,
            text="Check GitHub",
            command=self.test_github,
            **secondary_button_options(),
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ctk.CTkButton(
            card,
            text="Detect Arduino CLI",
            command=self.test_arduino,
            **secondary_button_options(),
        ).grid(row=0, column=3, sticky="w", padx=(8, 0))

        self.status_label = ctk.CTkLabel(
            card,
            text="",
            font=font(12),
            text_color=COLORS["text_muted"],
            anchor="w",
            justify="left",
            wraplength=900,
        )
        self.status_label.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        self.paths_label = ctk.CTkLabel(
            card,
            text="",
            font=font(10),
            text_color=COLORS["text_dim"],
            anchor="w",
            justify="left",
        )
        self.paths_label.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))

    def _field(
        self,
        body,
        row: int,
        label: str,
        key: str,
        *,
        show: str | None = None,
        placeholder: str = "",
    ) -> None:
        ctk.CTkLabel(
            body,
            text=label,
            font=font(11),
            text_color=COLORS["text_muted"],
            anchor="w",
            width=150,
        ).grid(row=row, column=0, sticky="w", pady=4)
        entry = ctk.CTkEntry(
            body,
            placeholder_text=placeholder,
            show=show,
            **entry_options(),
        )
        entry.grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=4)
        self.entries[key] = entry

    # ------------------------------------------------------------------ state
    def on_show(self) -> None:
        self.reload()

    def reload(self) -> None:
        config = self.app.config
        values = {
            "openhands_api_url": config.openhands_api_url,
            "openhands_api_key": "",
            "openhands_llm_model": config.openhands_llm_model,
            "github_repository": config.github_repository,
            "arduino_cli_path": config.arduino_cli_path,
            "arduino_fqbn": config.arduino_fqbn,
            "build_dir": config.build_dir,
            "poll_interval_seconds": _number(config.poll_interval_seconds),
            "startup_timeout_seconds": _number(config.startup_timeout_seconds),
            "execution_timeout_seconds": _number(config.execution_timeout_seconds),
        }
        self.notifications_var.set(bool(config.notifications_enabled))
        self.native_notifications_var.set(bool(config.native_notifications))
        for key, entry in self.entries.items():
            entry.delete(0, "end")
            value = values.get(key, "")
            if value:
                entry.insert(0, value)
        self.entries["openhands_api_key"].configure(
            placeholder_text=f"Stored: {config.masked_api_key()} — leave blank to keep"
        )
        self.key_state_label.configure(
            text=(
                "API key source: .env / environment. "
                f"Current value: {config.masked_api_key()}."
            )
        )
        self.paths_label.configure(
            text=(
                f"config.json: {config.root / 'config.json'}\n"
                f".env: {config.env_path}\n"
                f"builds: {config.build_path}"
            )
        )

    def _values(self) -> dict[str, object]:
        values: dict[str, object] = {
            key: entry.get().strip() for key, entry in self.entries.items()
        }
        values["notifications_enabled"] = bool(self.notifications_var.get())
        values["native_notifications"] = bool(self.native_notifications_var.get())
        return values

    # ---------------------------------------------------------------- actions
    def save(self, silent: bool = False) -> bool:
        values = self._values()
        for key in NUMERIC_FIELDS:
            try:
                float(values[key])
            except ValueError:
                self._set_status(f"{key} must be a number.", "error")
                if not silent:
                    messagebox.showerror("Invalid settings", f"{key} must be a number.")
                return False
        try:
            problems = self.app.save_settings(values)
        except Exception as exc:  # keep the UI alive on unexpected I/O errors
            problems = [str(exc)]
        if problems:
            self._set_status("; ".join(problems), "error")
            if not silent:
                messagebox.showerror("Invalid settings", "\n".join(problems))
            return False
        self.reload()
        self._set_status("Settings saved. Secrets go to .env, everything else to config.json.", "success")
        return True

    def _save_key(self) -> None:
        value = self.entries["openhands_api_key"].get().strip()
        if not value:
            self._set_status("Enter an API key first, or use Save settings to keep the stored key.", "error")
            return
        ok, message = self.app.save_api_key(value)
        if not ok:
            self._set_status(message, "error")
            return
        self.reload()
        self._set_status(message, "success")

    def _clear_key(self) -> None:
        if not messagebox.askyesno(
            "Remove API key",
            "Remove the stored OpenHands API key from .env?",
        ):
            return
        if not self.app.clear_api_key():
            return
        self.reload()
        self._set_status("Stored API key removed.", "warning")

    def test_openhands(self) -> None:
        if not self.save(silent=True):
            return
        self._set_status("Checking OpenHands…", "info")
        self.app.check_openhands(lambda result: self._report(result, "OpenHands"))

    def test_github(self) -> None:
        if not self.save(silent=True):
            return
        self._set_status("Checking GitHub authentication…", "info")
        self.app.check_github(lambda result: self._report(result, "GitHub"))

    def test_arduino(self) -> None:
        if not self.save(silent=True):
            return
        self._set_status("Looking for Arduino CLI…", "info")
        self.app.check_arduino(lambda result: self._report(result, "Arduino CLI"))

    def _report(self, result, source: str) -> None:
        if isinstance(result, Exception):
            self._set_status(f"{source}: {result}", "error")
            return
        if source == "OpenHands":
            ok, message = result
            self._set_status(message, "success" if ok else "error")
        elif source == "GitHub":
            self._set_status(result.message, "success" if result.ok else "error")
        else:
            if result.available:
                self._set_status(result.summary(), "success")
            else:
                self._set_status(result.error or "Arduino CLI not available.", "error")

    def _set_status(self, text: str, state: str = "info") -> None:
        self.status_label.configure(text=text, text_color=status_color(state))


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)
