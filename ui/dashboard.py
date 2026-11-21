"""Dashboard: connection status, last build and quick start."""

from __future__ import annotations

from pathlib import Path

import customtkinter as ctk

from compiler.arduino_cli import ArduinoCLIInfo
from core.models import Job
from github.repository import GitAuthResult
from ui.theme import COLORS, font, primary_button_options, secondary_button_options
from ui.widgets import SectionCard, StatusCard


class DashboardPage(ctk.CTkFrame):
    def __init__(self, app, master) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._last_job: Job | None = None
        self.grid_columnconfigure((0, 1, 2), weight=1, uniform="status")
        self.grid_rowconfigure(2, weight=1)

        self.openhands_card = StatusCard(self, "OPENHANDS CLOUD")
        self.openhands_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.github_card = StatusCard(self, "GITHUB WORKSPACE")
        self.github_card.grid(row=0, column=1, sticky="nsew", padx=8)
        self.arduino_card = StatusCard(self, "ARDUINO CLI")
        self.arduino_card.grid(row=0, column=2, sticky="nsew", padx=(8, 0))

        last = SectionCard(self, "Last build", "Source, logs and binaries are preserved for every job")
        last.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        last.body.grid_columnconfigure(0, weight=1)
        self.last_title = ctk.CTkLabel(
            last.body,
            text="No conversions yet",
            font=font(17, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        )
        self.last_title.grid(row=0, column=0, sticky="w")
        self.last_meta = ctk.CTkLabel(
            last.body,
            text="Upload a UIFlow .py file to create your first Cardputer build.",
            font=font(12),
            text_color=COLORS["text_muted"],
            anchor="w",
            justify="left",
            wraplength=900,
        )
        self.last_meta.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.last_binary = ctk.CTkLabel(
            last.body,
            text="",
            font=font(11),
            text_color=COLORS["success"],
            anchor="w",
            justify="left",
            wraplength=900,
        )
        self.last_binary.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        actions = ctk.CTkFrame(last.body, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.open_build_button = ctk.CTkButton(
            actions,
            text="Open build folder",
            command=self._open_build,
            **secondary_button_options(),
        )
        self.open_build_button.pack(side="left")
        self.open_log_button = ctk.CTkButton(
            actions,
            text="Open job log",
            command=self._open_log,
            **secondary_button_options(),
        )
        self.open_log_button.pack(side="left", padx=8)
        ctk.CTkButton(
            actions,
            text="View history",
            command=lambda: self.app.show_page("history"),
            **secondary_button_options(),
        ).pack(side="left")

        quick = SectionCard(self, "Start a conversion", "Python in, Arduino firmware out")
        quick.grid(row=2, column=0, columnspan=3, sticky="nsew", pady=(16, 0))
        quick.body.grid_columnconfigure(0, weight=1)
        steps = (
            "1.  Upload a UIFlow 2.0 MicroPython .py file.\n"
            "2.  Py2Cardputer pushes it to a dedicated GitHub branch and asks OpenHands to convert it.\n"
            "3.  The generated sketch is validated, compiled locally and the .bin path is shown here."
        )
        ctk.CTkLabel(
            quick.body,
            text=steps,
            font=font(12),
            text_color=COLORS["text_muted"],
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        buttons = ctk.CTkFrame(quick.body, fg_color="transparent")
        buttons.grid(row=1, column=0, sticky="w", pady=(14, 0))
        ctk.CTkButton(
            buttons,
            text="Upload File or ZIP",
            command=lambda: self.app.conversion_page.choose_file(),
            **primary_button_options(),
        ).pack(side="left")
        ctk.CTkButton(
            buttons,
            text="Select Folder",
            command=lambda: self.app.conversion_page.choose_folder(),
            **secondary_button_options(),
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            buttons,
            text="Refresh status",
            command=self.refresh,
            **secondary_button_options(),
        ).pack(side="left")
        ctk.CTkButton(
            buttons,
            text="Settings",
            command=lambda: self.app.show_page("settings"),
            **secondary_button_options(),
        ).pack(side="left")

    # ------------------------------------------------------------------ state
    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.openhands_card.set_status("unknown", "Checking…", self.app.config.openhands_api_url)
        self.github_card.set_status("unknown", "Checking…", self.app.config.github_repository)
        self.arduino_card.set_status("unknown", "Checking…", self.app.config.arduino_cli_path)
        self.app.check_openhands(self._apply_openhands)
        self.app.check_github(self._apply_github)
        self.app.check_arduino(self._apply_arduino)
        self.refresh_last_build()

    def _apply_openhands(self, result) -> None:
        if isinstance(result, Exception):
            self.openhands_card.set_status("error", "Unavailable", str(result))
            return
        ok, message = result
        if ok:
            self.openhands_card.set_status("ok", "Connected", message)
        else:
            self.openhands_card.set_status("error", "Not connected", message)

    def _apply_github(self, result) -> None:
        if isinstance(result, Exception):
            self.github_card.set_status("error", "Unavailable", str(result))
            return
        if not isinstance(result, GitAuthResult):
            self.github_card.set_status("error", "Unknown response", str(result))
            return
        if result.ok:
            self.github_card.set_status("ok", "Authenticated", result.message)
        else:
            self.github_card.set_status("error", "Authentication required", result.message)

    def _apply_arduino(self, result) -> None:
        if isinstance(result, Exception):
            self.arduino_card.set_status("error", "Unavailable", str(result))
            return
        if not isinstance(result, ArduinoCLIInfo):
            self.arduino_card.set_status("error", "Unknown response", str(result))
            return
        if result.available:
            self.arduino_card.set_status(
                "ok",
                f"v{result.version}",
                f"FQBN: {self.app.config.arduino_fqbn}",
            )
        else:
            self.arduino_card.set_status("error", "Not installed", result.error or "")

    def refresh_last_build(self, job: Job | None = None) -> None:
        if job is None:
            jobs = self.app.job_store.list_jobs()
            job = jobs[0] if jobs else None
        self._last_job = job
        if job is None:
            self.last_title.configure(text="No conversions yet")
            self.last_meta.configure(
                text="Upload a UIFlow .py file to create your first Cardputer build."
            )
            self.last_binary.configure(text="")
            self.open_build_button.configure(state="disabled")
            self.open_log_button.configure(state="disabled")
            return

        self.open_build_button.configure(state="normal")
        self.open_log_button.configure(state="normal" if job.log_path else "disabled")
        status = job.status.value.replace("_", " ").upper()
        self.last_title.configure(text=f"{job.app_name}  ·  {status}")
        meta = (
            f"{job.created_at[:16].replace('T', ' ')}  ·  {job.source_filename}  ·  "
            f"branch {job.branch}"
        )
        if job.error:
            meta += f"\n{job.error}"
        self.last_meta.configure(text=meta)
        if job.binary_path and Path(job.binary_path).exists():
            self.last_binary.configure(text=f"Binary: {job.binary_path}", text_color=COLORS["success"])
        elif job.message:
            self.last_binary.configure(text=job.message, text_color=COLORS["text_muted"])
        else:
            self.last_binary.configure(text="", text_color=COLORS["text_muted"])

    def _open_build(self) -> None:
        if self._last_job:
            self.app.open_path(self._last_job.job_dir)

    def _open_log(self) -> None:
        if self._last_job and self._last_job.log_path:
            self.app.open_path(self._last_job.log_path)
