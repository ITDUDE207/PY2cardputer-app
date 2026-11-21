"""Reusable CustomTkinter widgets."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from core.models import Job, StepStatus
from ui.theme import (
    COLORS,
    font,
    mono_font,
    secondary_button_options,
    status_color,
)

STEP_ICONS = {
    StepStatus.PENDING: "○",
    StepStatus.RUNNING: "◐",
    StepStatus.DONE: "✓",
    StepStatus.FAILED: "✕",
    StepStatus.SKIPPED: "–",
}


class StatusCard(ctk.CTkFrame):
    """A compact status tile used on the dashboard."""

    def __init__(self, master: ctk.CTkBaseClass, title: str, **kwargs) -> None:
        super().__init__(
            master,
            fg_color=COLORS["surface"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
            **kwargs,
        )
        self.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        header.grid_columnconfigure(1, weight=1)
        self.dot = ctk.CTkLabel(header, text="●", text_color=COLORS["text_dim"], font=font(14))
        self.dot.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text=title,
            text_color=COLORS["text_muted"],
            font=font(12, "bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="w", padx=(6, 0))

        self.value_label = ctk.CTkLabel(
            self,
            text="Checking…",
            text_color=COLORS["text"],
            font=font(16, "bold"),
            anchor="w",
            justify="left",
        )
        self.value_label.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 0))

        self.detail_label = ctk.CTkLabel(
            self,
            text="",
            text_color=COLORS["text_muted"],
            font=font(11),
            anchor="w",
            justify="left",
            wraplength=320,
        )
        self.detail_label.grid(row=2, column=0, sticky="ew", padx=16, pady=(4, 14))

    def set_status(self, state: str, value: str, detail: str = "") -> None:
        self.dot.configure(text_color=status_color(state))
        self.value_label.configure(text=value)
        self.detail_label.configure(text=detail)


class SectionCard(ctk.CTkFrame):
    """A bordered panel with an optional heading and subtitle."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        title: str | None = None,
        subtitle: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            fg_color=COLORS["surface"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
            **kwargs,
        )
        self.grid_columnconfigure(0, weight=1)
        self._row = 0
        if title:
            ctk.CTkLabel(
                self,
                text=title,
                font=font(14, "bold"),
                text_color=COLORS["text"],
                anchor="w",
            ).grid(row=self._row, column=0, sticky="ew", padx=16, pady=(14, 0))
            self._row += 1
        if subtitle:
            ctk.CTkLabel(
                self,
                text=subtitle,
                font=font(11),
                text_color=COLORS["text_muted"],
                anchor="w",
                justify="left",
            ).grid(row=self._row, column=0, sticky="ew", padx=16, pady=(2, 0))
            self._row += 1
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=self._row, column=0, sticky="nsew", padx=16, pady=(10, 14))
        self.body.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(self._row, weight=1)


class StepList(ctk.CTkFrame):
    """Vertical checklist that mirrors the pipeline steps."""

    def __init__(self, master: ctk.CTkBaseClass, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self._rows: dict[str, tuple[ctk.CTkLabel, ctk.CTkLabel]] = {}

    def set_steps(self, steps) -> None:
        for widget in self.winfo_children():
            widget.destroy()
        self._rows.clear()
        for index, step in enumerate(steps):
            icon = ctk.CTkLabel(
                self,
                text=STEP_ICONS.get(step.status, "○"),
                font=font(13, "bold"),
                text_color=self._icon_color(step.status),
                width=20,
            )
            icon.grid(row=index, column=0, sticky="w", pady=2)
            label = ctk.CTkLabel(
                self,
                text=step.label,
                font=font(12),
                text_color=COLORS["text"] if step.status is not StepStatus.PENDING else COLORS["text_muted"],
                anchor="w",
            )
            label.grid(row=index, column=1, sticky="ew", pady=2)
            self._rows[step.name] = (icon, label)

    def update_step(self, name: str, status: StepStatus, message: str = "") -> None:
        row = self._rows.get(name)
        if row is None:
            return
        icon, label = row
        icon.configure(text=STEP_ICONS.get(status, "○"), text_color=self._icon_color(status))
        label.configure(
            text_color=COLORS["text"] if status is not StepStatus.PENDING else COLORS["text_muted"]
        )
        if message:
            label.configure(text=label.cget("text").split("  ·  ")[0] + f"  ·  {message}")

    @staticmethod
    def _icon_color(status: StepStatus) -> str:
        return {
            StepStatus.RUNNING: COLORS["accent"],
            StepStatus.DONE: COLORS["success"],
            StepStatus.FAILED: COLORS["error"],
            StepStatus.SKIPPED: COLORS["text_dim"],
        }.get(status, COLORS["text_dim"])


class TerminalView(ctk.CTkFrame):
    """Read-only scrollback used for compiler and pipeline output."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        on_clear: Callable[[], None] | None = None,
        on_open_logs: Callable[[], None] | None = None,
        height: int = 220,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color=COLORS["surface"], corner_radius=12, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 0))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="COMPILER OUTPUT",
            font=font(11, "bold"),
            text_color=COLORS["text_muted"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        small = secondary_button_options()
        small.update({"width": 64, "height": 24})
        if on_clear:
            ctk.CTkButton(
                header,
                text="Clear",
                command=on_clear,
                **small,
            ).grid(row=0, column=1, padx=(0, 6))
        if on_open_logs:
            ctk.CTkButton(
                header,
                text="Logs",
                command=on_open_logs,
                **small,
            ).grid(row=0, column=2)

        self.textbox = ctk.CTkTextbox(
            self,
            height=height,
            fg_color=COLORS["terminal_bg"],
            text_color=COLORS["terminal_text"],
            font=mono_font(11),
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
            wrap="none",
        )
        self.textbox.grid(row=1, column=0, sticky="nsew", padx=14, pady=(8, 14))
        self.textbox.configure(state="disabled")

    def append(self, text: str) -> None:
        if not text:
            return
        self.textbox.configure(state="normal")
        self.textbox.insert("end", text.rstrip("\n") + "\n")
        self.textbox.see("end")
        self.textbox.configure(state="disabled")

    def clear(self) -> None:
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")

    def set_text(self, text: str) -> None:
        self.clear()
        self.append(text)


class LabeledValue(ctk.CTkFrame):
    """A small label/value pair with a copy button."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        label: str,
        value: str = "—",
        *,
        mono: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self,
            text=label,
            width=110,
            anchor="w",
            font=font(11),
            text_color=COLORS["text_muted"],
        ).grid(row=0, column=0, sticky="w")
        self.value_label = ctk.CTkLabel(
            self,
            text=value,
            anchor="w",
            justify="left",
            font=mono_font(11) if mono else font(12),
            text_color=COLORS["text"],
            wraplength=520,
        )
        self.value_label.grid(row=0, column=1, sticky="ew")
        copy_options = secondary_button_options()
        copy_options.update({"width": 52, "height": 22})
        self._copy_button = ctk.CTkButton(
            self,
            text="Copy",
            command=self._copy,
            **copy_options,
        )
        self._copy_button.grid(row=0, column=2, padx=(8, 0))

    def set_value(self, value: str) -> None:
        self.value_label.configure(text=value or "—")

    def get_value(self) -> str:
        return self.value_label.cget("text")

    def _copy(self) -> None:
        value = self.get_value()
        if not value or value == "—":
            return
        self.clipboard_clear()
        self.clipboard_append(value)
        self._copy_button.configure(text="Copied")
        self.after(1200, lambda: self._copy_button.configure(text="Copy"))


class JobRow(ctk.CTkFrame):
    """Selectable row in the build history list."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        job: Job,
        command: Callable[[Job], None],
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            fg_color=COLORS["surface_alt"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
            **kwargs,
        )
        self.job = job
        self.grid_columnconfigure(0, weight=1)
        self.bind("<Button-1>", lambda _event: command(job))
        title = ctk.CTkLabel(
            self,
            text=job.app_name,
            font=font(13, "bold"),
            anchor="w",
            text_color=COLORS["text"],
        )
        title.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
        title.bind("<Button-1>", lambda _event: command(job))
        detail = f"{job.created_at[:16].replace('T', ' ')}  ·  {job.status.value.replace('_', ' ')}"
        subtitle = ctk.CTkLabel(
            self,
            text=detail,
            font=font(10),
            anchor="w",
            text_color=status_color(job.status.value),
        )
        subtitle.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        subtitle.bind("<Button-1>", lambda _event: command(job))
