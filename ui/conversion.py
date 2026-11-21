"""New Conversion page: file selection, live progress and build result."""

from __future__ import annotations

import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.models import Job, JobStatus, ProgressEvent, StepRecord, StepStatus
from core.pipeline import STEP_ORDER
from core.validation import SourceFile, validate_source_input
from ui.theme import (
    COLORS,
    entry_options,
    font,
    primary_button_options,
    secondary_button_options,
    status_color,
)
from ui.widgets import LabeledValue, SectionCard, StepList, TerminalView

LEVEL_PREFIX = {
    "success": "✓",
    "warning": "!",
    "error": "✕",
    "terminal": "·",
    "info": "›",
}


class ConversionPage(ctk.CTkFrame):
    def __init__(self, app, master) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.selected_path: Path | None = None
        self.selected_source: SourceFile | None = None
        self.job: Job | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

        self._build_source_card()
        self._build_target_card()
        self._build_actions()
        self._build_progress_card()
        self._build_openhands_card()
        self._build_github_card()
        self._build_terminal()
        self._build_result_card()
        self._reset_job_fields()

    # ------------------------------------------------------------------ build
    def _build_source_card(self) -> None:
        card = SectionCard(
            self.scroll,
            "Source application",
            "UIFlow 2.0 .py file, project folder or .zip archive. The original input is never modified.",
        )
        card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        self.file_name_label = ctk.CTkLabel(
            body,
            text="No file selected",
            font=font(16, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        )
        self.file_name_label.grid(row=0, column=0, sticky="w")

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.grid(row=0, column=1, sticky="e")
        self.upload_button = ctk.CTkButton(
            buttons,
            text="Upload File or ZIP",
            command=self.choose_file,
            **primary_button_options(),
        )
        self.upload_button.pack(side="left")
        self.folder_button = ctk.CTkButton(
            buttons,
            text="Select Folder",
            command=self.choose_folder,
            **secondary_button_options(),
        )
        self.folder_button.pack(side="left", padx=(8, 0))
        self.clear_button = ctk.CTkButton(
            buttons,
            text="Clear",
            command=self.clear_file,
            **secondary_button_options(),
        )
        self.clear_button.pack(side="left", padx=(8, 0))

        self.file_meta_label = ctk.CTkLabel(
            body,
            text="Supported: .py files, project folders and .zip archives using display, keyboard, sensors and Wi-Fi.",
            font=font(11),
            text_color=COLORS["text_muted"],
            anchor="w",
            justify="left",
            wraplength=900,
        )
        self.file_meta_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.file_warning_label = ctk.CTkLabel(
            body,
            text="",
            font=font(11),
            text_color=COLORS["warning"],
            anchor="w",
            justify="left",
            wraplength=900,
        )
        self.file_warning_label.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    def _build_target_card(self) -> None:
        card = SectionCard(self.scroll, "Target hardware", "The FQBN is passed to Arduino CLI")
        card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        body = card.body
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            body, text="Board profile", font=font(11), text_color=COLORS["text_muted"], anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        profiles = list(self.app.config.board_profiles.keys()) + ["Custom FQBN"]
        self.profile_combo = ctk.CTkComboBox(
            body,
            values=profiles,
            state="readonly",
            command=self._on_profile_change,
            fg_color=COLORS["surface_alt"],
            border_color=COLORS["border"],
            button_color=COLORS["surface_hover"],
            dropdown_fg_color=COLORS["surface_alt"],
            text_color=COLORS["text"],
            font=font(12),
            height=32,
        )
        self.profile_combo.grid(row=0, column=1, sticky="ew", padx=(0, 18))
        ctk.CTkLabel(
            body, text="FQBN", font=font(11), text_color=COLORS["text_muted"], anchor="w"
        ).grid(row=0, column=2, sticky="w", padx=(0, 8))
        self.fqbn_entry = ctk.CTkEntry(
            body, placeholder_text="m5stack:esp32:m5stack_cardputer", **entry_options()
        )
        self.fqbn_entry.grid(row=0, column=3, sticky="ew")
        self._select_profile_for_fqbn()

        self.repo_value = LabeledValue(body, "Repository", self.app.config.github_repository, mono=True)
        self.repo_value.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))

    def _build_actions(self) -> None:
        frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
        frame.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        frame.grid_columnconfigure(2, weight=1)
        self.start_button = ctk.CTkButton(
            frame,
            text="Start Conversion",
            command=self.start_conversion,
            width=180,
            **primary_button_options(),
        )
        self.start_button.grid(row=0, column=0, sticky="w")
        self.cancel_button = ctk.CTkButton(
            frame,
            text="Cancel",
            command=self.app.cancel_conversion,
            width=110,
            state="disabled",
            **secondary_button_options(),
        )
        self.cancel_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.status_text = ctk.CTkLabel(
            frame,
            text="Ready.",
            font=font(12),
            text_color=COLORS["text_muted"],
            anchor="w",
        )
        self.status_text.grid(row=0, column=2, sticky="ew", padx=(16, 0))

    def _build_progress_card(self) -> None:
        card = SectionCard(self.scroll, "Conversion progress", "Pipeline steps run in the background")
        card.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        body = card.body
        body.grid_columnconfigure(0, weight=1)
        self.progress_bar = ctk.CTkProgressBar(
            body,
            height=6,
            progress_color=COLORS["accent"],
            fg_color=COLORS["surface_alt"],
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew")
        self.progress_bar.set(0)
        self.step_list = StepList(body)
        self.step_list.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self._render_initial_steps()

    def _build_openhands_card(self) -> None:
        card = SectionCard(self.scroll, "OpenHands Cloud", "AI conversion runs remotely on your branch")
        card.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        body = card.body
        body.grid_columnconfigure(0, weight=1)
        self.start_task_value = LabeledValue(body, "Start task", "—", mono=True)
        self.start_task_value.grid(row=0, column=0, sticky="ew")
        self.conversation_value = LabeledValue(body, "Conversation", "—", mono=True)
        self.conversation_value.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.execution_value = LabeledValue(body, "Agent status", "—")
        self.execution_value.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.sandbox_value = LabeledValue(body, "Sandbox", "—")
        self.sandbox_value.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        self.conversation_button = ctk.CTkButton(
            body,
            text="Open conversation in browser",
            command=self.open_conversation,
            state="disabled",
            **secondary_button_options(),
        )
        self.conversation_button.grid(row=4, column=0, sticky="w", pady=(10, 0))

    def _build_github_card(self) -> None:
        card = SectionCard(self.scroll, "GitHub branch", "Kept permanently until you delete it")
        card.grid(row=5, column=0, sticky="ew", pady=(0, 12))
        body = card.body
        body.grid_columnconfigure(0, weight=1)
        self.branch_value = LabeledValue(body, "Branch", "—", mono=True)
        self.branch_value.grid(row=0, column=0, sticky="ew")
        self.commit_value = LabeledValue(body, "Commit", "—", mono=True)
        self.commit_value.grid(row=1, column=0, sticky="ew", pady=(4, 0))

    def _build_terminal(self) -> None:
        self.terminal = TerminalView(
            self.scroll,
            on_clear=lambda: self.terminal.clear(),
            on_open_logs=lambda: self.app.open_path(self.app.config.log_path),
            height=240,
        )
        self.terminal.grid(row=6, column=0, sticky="ew", pady=(0, 12))

    def _build_result_card(self) -> None:
        card = SectionCard(self.scroll, "Build result", "Local Arduino CLI compilation")
        card.grid(row=7, column=0, sticky="ew", pady=(0, 12))
        body = card.body
        body.grid_columnconfigure(0, weight=1)
        self.result_label = ctk.CTkLabel(
            body,
            text="No build yet.",
            font=font(14, "bold"),
            text_color=COLORS["text_muted"],
            anchor="w",
        )
        self.result_label.grid(row=0, column=0, sticky="ew")
        self.binary_value = LabeledValue(body, "Binary", "—", mono=True)
        self.binary_value.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.duration_value = LabeledValue(body, "Duration", "—")
        self.duration_value.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.open_binary_button = ctk.CTkButton(
            buttons,
            text="Open binary folder",
            command=self.open_binary_folder,
            state="disabled",
            **secondary_button_options(),
        )
        self.open_binary_button.pack(side="left")
        self.open_build_button = ctk.CTkButton(
            buttons,
            text="Open build folder",
            command=self.open_build_folder,
            state="disabled",
            **secondary_button_options(),
        )
        self.open_build_button.pack(side="left", padx=8)
        self.open_compile_button = ctk.CTkButton(
            buttons,
            text="Open compile log",
            command=self.open_compile_log,
            state="disabled",
            **secondary_button_options(),
        )
        self.open_compile_button.pack(side="left")

    # ------------------------------------------------------------------- file
    def choose_file(self) -> None:
        if self.app.busy:
            messagebox.showinfo("Py2Cardputer", "Wait for the running conversion to finish.")
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="Select a UIFlow file or ZIP",
            filetypes=[
                ("MicroPython source or ZIP", "*.py *.zip"),
                ("MicroPython source", "*.py"),
                ("ZIP archive", "*.zip"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.load_file(path)

    def choose_folder(self) -> None:
        if self.app.busy:
            messagebox.showinfo("Py2Cardputer", "Wait for the running conversion to finish.")
            return
        path = filedialog.askdirectory(
            parent=self,
            title="Select a UIFlow project folder",
            mustexist=True,
        )
        if path:
            self.load_file(path)

    def load_file(self, path: Path | str) -> None:
        try:
            source = validate_source_input(path)
        except Exception as exc:  # ValidationError or OSError
            messagebox.showerror("Invalid conversion input", str(exc))
            return
        self.selected_path = source.path
        self.selected_source = source
        self.file_name_label.configure(text=source.display_name, text_color=COLORS["text"])
        imports = ", ".join(source.inspection.imports) or "none detected"
        bundle_line = (
            "Single Python file"
            if source.kind == "file"
            else f"{source.kind.upper()} bundle · {source.file_count} file(s) · "
            f"{source.asset_count} asset(s)"
        )
        self.file_meta_label.configure(
            text=(
                f"{source.path}\n"
                f"{bundle_line}  ·  {source.size_bytes:,} bytes  ·  "
                f"{source.inspection.line_count} lines  ·  "
                f"SHA-256 {source.sha256[:16]}…  ·  sketch {source.app_name}\n"
                f"Primary: {source.primary_relative}\n"
                f"Imports: {imports}"
            )
        )
        warnings = list(source.inspection.warnings)
        if source.asset_count:
            warnings.append(
                f"{source.asset_count} asset file(s) will be uploaded under input/ and "
                "can be copied into the sketch data/ folder by OpenHands."
            )
        self.file_warning_label.configure(text="\n".join(warnings))
        self.set_status_text(f"Selected {source.display_name}. Ready to convert.")

    def clear_file(self) -> None:
        if self.app.busy:
            return
        self.selected_path = None
        self.selected_source = None
        self.file_name_label.configure(text="No file selected", text_color=COLORS["text"])
        self.file_meta_label.configure(
            text="Supported: .py files, project folders and .zip archives using display, keyboard, sensors and Wi-Fi."
        )
        self.file_warning_label.configure(text="")
        self.set_status_text("Ready.")

    # ------------------------------------------------------------------ board
    def _on_profile_change(self, choice: str) -> None:
        fqbn = self.app.config.board_profiles.get(choice)
        if fqbn:
            self.fqbn_entry.delete(0, "end")
            self.fqbn_entry.insert(0, fqbn)

    def _select_profile_for_fqbn(self) -> None:
        fqbn = self.app.config.arduino_fqbn
        selected = "Custom FQBN"
        for label, value in self.app.config.board_profiles.items():
            if value == fqbn:
                selected = label
                break
        self.profile_combo.set(selected)
        self.fqbn_entry.delete(0, "end")
        self.fqbn_entry.insert(0, fqbn)

    def on_show(self) -> None:
        self.repo_value.set_value(self.app.config.github_repository)
        if not self.fqbn_entry.get().strip():
            self._select_profile_for_fqbn()

    # --------------------------------------------------------------- starting
    def start_conversion(self) -> None:
        if self.app.busy:
            return
        if not self.selected_path:
            messagebox.showwarning(
                "No input selected",
                "Upload a UIFlow .py file or ZIP, or select a project folder first.",
            )
            return
        fqbn = self.fqbn_entry.get().strip()
        if not fqbn:
            messagebox.showwarning("Board not configured", "Enter an Arduino FQBN.")
            return
        self.app.config.arduino_fqbn = fqbn
        try:
            self.app.config.save()
        except OSError as exc:
            messagebox.showwarning("Settings not saved", f"Could not save config.json: {exc}")
        self.app.start_conversion(self.selected_path)

    def on_job_started(self, job: Job) -> None:
        self.job = job
        self.terminal.clear()
        self.terminal.append(
            f"Py2Cardputer job {job.job_id}\n"
            f"Source: {job.source_path}\nRepository: {job.repository}\n"
            f"Branch: {job.branch}\n"
        )
        self._render_initial_steps()
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.upload_button.configure(state="disabled")
        self.folder_button.configure(state="disabled")
        self.clear_button.configure(state="disabled")
        self.status_text.configure(text="Starting conversion…", text_color=COLORS["info"])
        self.branch_value.set_value(job.branch)
        self.repo_value.set_value(job.repository)
        self.start_task_value.set_value("—")
        self.conversation_value.set_value("—")
        self.execution_value.set_value("—")
        self.sandbox_value.set_value("—")
        self.commit_value.set_value("—")
        self.binary_value.set_value("—")
        self.duration_value.set_value("—")
        self.result_label.configure(text="Conversion running…", text_color=COLORS["info"])
        self.conversation_button.configure(state="disabled")
        self.open_binary_button.configure(state="disabled")
        self.open_build_button.configure(state="disabled")
        self.open_compile_button.configure(state="disabled")

    # -------------------------------------------------------------- progress
    def on_progress(self, event: ProgressEvent) -> None:
        prefix = LEVEL_PREFIX.get(event.level, "›")
        stamp = time.strftime("%H:%M:%S")
        self.terminal.append(f"[{stamp}] {prefix} {event.step}: {event.message}")
        if event.step in dict(STEP_ORDER) and event.level not in {"terminal"}:
            if event.level == "success":
                self.step_list.update_step(event.step, StepStatus.DONE)
            elif event.level == "error":
                self.step_list.update_step(event.step, StepStatus.FAILED)
            else:
                self.step_list.update_step(event.step, StepStatus.RUNNING)
        if event.level not in {"terminal", "info"}:
            self.status_text.configure(
                text=event.message[:160],
                text_color=status_color(event.level),
            )
        data = event.data or {}
        if data.get("conversation_url"):
            self.conversation_value.set_value(str(data["conversation_url"]))
            self.conversation_button.configure(state="normal")
        if data.get("start_status"):
            self.start_task_value.set_value(str(data["start_status"]))
        if data.get("execution_status"):
            self.execution_value.set_value(str(data["execution_status"]))
        if data.get("sandbox_status"):
            self.sandbox_value.set_value(str(data["sandbox_status"]))
        if event.step == "start_conversation" and event.level == "info":
            self._refresh_ids_from_job()

    def _refresh_ids_from_job(self) -> None:
        if not self.job:
            return
        if self.job.openhands_start_task_id:
            self.start_task_value.set_value(self.job.openhands_start_task_id)
        if self.job.openhands_conversation_id:
            self.conversation_value.set_value(self.job.openhands_conversation_id)
        if self.job.openhands_conversation_url:
            self.conversation_button.configure(state="normal")

    # ---------------------------------------------------------------- finish
    def on_job_finished(self, job: Job) -> None:
        self.job = job
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(1.0 if job.status is JobStatus.SUCCEEDED else 0.0)
        self.start_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.upload_button.configure(state="normal")
        self.folder_button.configure(state="normal")
        self.clear_button.configure(state="normal")
        self.step_list.set_steps(job.steps or [])
        self.branch_value.set_value(job.branch)
        self.repo_value.set_value(job.repository)
        self.start_task_value.set_value(job.openhands_start_task_id or "—")
        self.conversation_value.set_value(
            job.openhands_conversation_url or job.openhands_conversation_id or "—"
        )
        self.execution_value.set_value(job.openhands_execution_status or "—")
        self.sandbox_value.set_value(job.openhands_sandbox_status or "—")
        self.commit_value.set_value(job.firmware_commit_sha or job.commit_sha or "—")
        self.duration_value.set_value(f"{job.duration_seconds:.1f} seconds")
        self.open_build_button.configure(state="normal")
        if job.openhands_conversation_url:
            self.conversation_button.configure(state="normal")
        if job.compile_log_path:
            self.open_compile_button.configure(state="normal")

        if job.status is JobStatus.SUCCEEDED and job.binary_path:
            self.binary_value.set_value(job.binary_path)
            self.result_label.configure(
                text=f"Build succeeded · firmware ready ({job.app_name})",
                text_color=COLORS["success"],
            )
            self.open_binary_button.configure(state="normal")
            self.status_text.configure(
                text=f"Done. Binary: {job.binary_path}", text_color=COLORS["success"]
            )
        elif job.status is JobStatus.WAITING_FOR_USER:
            self.result_label.configure(
                text="Waiting for confirmation in OpenHands",
                text_color=COLORS["warning"],
            )
            self.status_text.configure(text=job.message, text_color=COLORS["warning"])
        elif job.status is JobStatus.CANCELLED:
            self.result_label.configure(text="Conversion cancelled", text_color=COLORS["warning"])
            self.status_text.configure(text=job.message, text_color=COLORS["warning"])
        else:
            self.result_label.configure(
                text=job.error or job.message or "Build failed",
                text_color=COLORS["error"],
            )
            self.status_text.configure(
                text=job.error or job.message or "Build failed", text_color=COLORS["error"]
            )

        self.terminal.append("")
        self.terminal.append(
            f"Result: {job.status.value} · duration {job.duration_seconds:.1f}s"
        )
        if job.binary_path:
            self.terminal.append(f"Binary: {job.binary_path}")
        if job.error:
            self.terminal.append(f"Error: {job.error}")
        for warning in job.warnings:
            self.terminal.append(f"Warning: {warning}")
        self.terminal.append(f"Branch (kept): {job.branch}")
        if job.openhands_conversation_url:
            self.terminal.append(f"Conversation: {job.openhands_conversation_url}")

    # --------------------------------------------------------------- actions
    def set_status_text(self, text: str) -> None:
        self.status_text.configure(text=text, text_color=COLORS["text_muted"])

    def open_conversation(self) -> None:
        if self.job and self.job.openhands_conversation_url:
            self.app.open_url(self.job.openhands_conversation_url)

    def open_binary_folder(self) -> None:
        if self.job and self.job.binary_path:
            self.app.open_path(Path(self.job.binary_path).parent)

    def open_build_folder(self) -> None:
        if self.job:
            self.app.open_path(self.job.job_dir)

    def open_compile_log(self) -> None:
        if self.job and self.job.compile_log_path:
            self.app.open_path(self.job.compile_log_path)

    # ---------------------------------------------------------------- helpers
    def _render_initial_steps(self) -> None:
        self.step_list.set_steps(
            [StepRecord(name=name, label=label) for name, label in STEP_ORDER]
        )

    def _reset_job_fields(self) -> None:
        self.start_task_value.set_value("—")
        self.conversation_value.set_value("—")
        self.execution_value.set_value("—")
        self.sandbox_value.set_value("—")
        self.branch_value.set_value("—")
        self.commit_value.set_value("—")
        self.binary_value.set_value("—")
        self.duration_value.set_value("—")
