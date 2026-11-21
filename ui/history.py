"""Build history: every job, its files, logs and conversation link."""

from __future__ import annotations

from pathlib import Path

import customtkinter as ctk

from core.models import Job
from ui.theme import COLORS, font, secondary_button_options, status_color
from ui.widgets import JobRow, LabeledValue, SectionCard, StepList


class HistoryPage(ctk.CTkFrame):
    def __init__(self, app, master) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.selected_job_id: str | None = None
        self.selected_job: Job | None = None

        self.grid_columnconfigure(0, weight=2)
        self.grid_columnconfigure(1, weight=3)
        self.grid_rowconfigure(0, weight=1)

        list_card = SectionCard(self, "Conversions", "Newest first · select a build to inspect it")
        list_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        list_card.body.grid_rowconfigure(0, weight=1)
        list_card.body.grid_columnconfigure(0, weight=1)
        self.list_frame = ctk.CTkScrollableFrame(list_card.body, fg_color="transparent")
        self.list_frame.grid(row=0, column=0, sticky="nsew")
        self.list_frame.grid_columnconfigure(0, weight=1)
        list_actions = ctk.CTkFrame(list_card.body, fg_color="transparent")
        list_actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkButton(
            list_actions,
            text="Refresh",
            command=self.refresh,
            width=90,
            **secondary_button_options(),
        ).pack(side="left")
        ctk.CTkButton(
            list_actions,
            text="Open builds folder",
            command=lambda: self.app.open_path(self.app.config.build_path),
            **secondary_button_options(),
        ).pack(side="left", padx=8)
        self.count_label = ctk.CTkLabel(
            list_actions,
            text="",
            font=font(11),
            text_color=COLORS["text_muted"],
        )
        self.count_label.pack(side="right")

        detail_card = SectionCard(self, "Build details")
        detail_card.grid(row=0, column=1, sticky="nsew")
        detail_card.body.grid_rowconfigure(0, weight=1)
        detail_card.body.grid_columnconfigure(0, weight=1)
        self.detail_frame = ctk.CTkScrollableFrame(detail_card.body, fg_color="transparent")
        self.detail_frame.grid(row=0, column=0, sticky="nsew")
        self.detail_frame.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------------ state
    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        for widget in self.list_frame.winfo_children():
            widget.destroy()
        jobs = self.app.job_store.list_jobs()
        self.count_label.configure(text=f"{len(jobs)} build(s)")
        if not jobs:
            ctk.CTkLabel(
                self.list_frame,
                text="No builds yet.\nStart a conversion from the Dashboard.",
                font=font(12),
                text_color=COLORS["text_muted"],
                justify="left",
                anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=4, pady=8)
            self._clear_details()
            return

        for index, job in enumerate(jobs):
            row = JobRow(self.list_frame, job, self.select)
            row.grid(row=index, column=0, sticky="ew", pady=3)

        target = next((job for job in jobs if job.job_id == self.selected_job_id), jobs[0])
        self.select(target)

    def select(self, job: Job) -> None:
        self.selected_job = job
        self.selected_job_id = job.job_id
        for widget in self.detail_frame.winfo_children():
            widget.destroy()
        self.detail_frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self.detail_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text=job.app_name,
            font=font(20, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text=job.status.value.replace("_", " ").upper(),
            font=font(11, "bold"),
            text_color=status_color(job.status.value),
            anchor="e",
        ).grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(
            header,
            text=f"Job {job.job_id}",
            font=font(10),
            text_color=COLORS["text_dim"],
            anchor="w",
        ).grid(row=1, column=0, sticky="w")

        row = 1
        fields = [
            ("Created", job.created_at[:19].replace("T", " ")),
            ("Duration", f"{job.duration_seconds:.1f} seconds"),
            ("Source file", job.source_filename),
            ("Source path", job.source_path),
            ("SHA-256", job.source_sha256),
            ("Repository", job.repository),
            ("Branch", job.branch),
            ("Source commit", job.commit_sha or "—"),
            ("Firmware commit", job.firmware_commit_sha or "—"),
            ("OpenHands task", job.openhands_start_task_id or "—"),
            ("Conversation", job.openhands_conversation_url or job.openhands_conversation_id or "—"),
            ("Agent status", job.openhands_execution_status or "—"),
            ("Sandbox", job.openhands_sandbox_status or "—"),
            ("Sketch", job.sketch_dir or "—"),
            ("Binary", job.binary_path or "—"),
            ("Compile log", job.compile_log_path or "—"),
            ("Job log", job.log_path or "—"),
        ]
        for label, value in fields:
            widget = LabeledValue(self.detail_frame, label, value, mono=label in {"SHA-256", "Branch"})
            widget.grid(row=row, column=0, sticky="ew", pady=2)
            row += 1
        if job.error:
            ctk.CTkLabel(
                self.detail_frame,
                text=f"Error: {job.error}",
                font=font(12),
                text_color=COLORS["error"],
                justify="left",
                anchor="w",
                wraplength=640,
            ).grid(row=row, column=0, sticky="ew", pady=(6, 0))
            row += 1
        if job.warnings:
            ctk.CTkLabel(
                self.detail_frame,
                text="Warnings:\n" + "\n".join(f"• {warning}" for warning in job.warnings),
                font=font(11),
                text_color=COLORS["warning"],
                justify="left",
                anchor="w",
                wraplength=640,
            ).grid(row=row, column=0, sticky="ew", pady=(6, 0))
            row += 1

        actions = ctk.CTkFrame(self.detail_frame, fg_color="transparent")
        actions.grid(row=row, column=0, sticky="w", pady=(12, 8))
        buttons = [
            ("Open build folder", lambda: self.app.open_path(job.job_dir), True),
            ("Open binary folder", lambda: self._open_binary(job), bool(job.binary_path)),
            ("Open compile log", lambda: self.app.open_path(job.compile_log_path), bool(job.compile_log_path)),
            ("Open job log", lambda: self.app.open_path(job.log_path), bool(job.log_path)),
            (
                "Open conversation",
                lambda: self.app.open_url(job.openhands_conversation_url),
                bool(job.openhands_conversation_url),
            ),
            ("Copy branch", lambda: self._copy(job.branch), True),
        ]
        for index, (text, command, enabled) in enumerate(buttons):
            ctk.CTkButton(
                actions,
                text=text,
                command=command,
                state="normal" if enabled else "disabled",
                **secondary_button_options(),
            ).grid(row=index // 3, column=index % 3, padx=(0, 8), pady=3, sticky="w")
        row += 1

        if job.steps:
            ctk.CTkLabel(
                self.detail_frame,
                text="PIPELINE",
                font=font(10, "bold"),
                text_color=COLORS["text_muted"],
                anchor="w",
            ).grid(row=row, column=0, sticky="w", pady=(10, 4))
            row += 1
            steps = StepList(self.detail_frame)
            steps.grid(row=row, column=0, sticky="ew")
            steps.set_steps(job.steps)

    # --------------------------------------------------------------- actions
    def _open_binary(self, job: Job) -> None:
        if job.binary_path:
            self.app.open_path(Path(job.binary_path).parent)

    def _copy(self, text: str) -> None:
        self.app.copy_text(text)

    def _clear_details(self) -> None:
        for widget in self.detail_frame.winfo_children():
            widget.destroy()
        ctk.CTkLabel(
            self.detail_frame,
            text="Select a build to see its details.",
            font=font(12),
            text_color=COLORS["text_muted"],
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=8)
