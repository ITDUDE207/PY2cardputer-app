"""About page: behaviour, guarantees and documentation links."""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import COLORS, font, secondary_button_options
from ui.widgets import SectionCard

DOC_LINKS = [
    ("OpenHands Cloud API", "https://docs.openhands.dev/openhands/usage/cloud"),
    ("Arduino CLI", "https://arduino.github.io/arduino-cli/"),
    ("M5Stack Arduino docs", "https://docs.m5stack.com/en/arduino/arduino_board"),
    ("M5Launcher", "https://github.com/bmorcelli/M5Stick-Launcher"),
]


class AboutPage(ctk.CTkFrame):
    def __init__(self, app, master) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

        intro = SectionCard(self.scroll, "Py2Cardputer V1")
        intro.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ctk.CTkLabel(
            intro.body,
            text=(
                "Py2Cardputer converts M5Stack UIFlow 2.0 MicroPython applications into Arduino C++ "
                "firmware for the Cardputer ADV.\n\n"
                "The conversion is performed by OpenHands Cloud against a dedicated branch in your "
                "private GitHub workspace repository. Compilation runs locally with Arduino CLI, so "
                "the firmware is built with your own board cores and libraries."
            ),
            font=font(12),
            text_color=COLORS["text"],
            justify="left",
            anchor="w",
            wraplength=880,
        ).grid(row=0, column=0, sticky="ew")

        workflow = SectionCard(self.scroll, "Workflow")
        workflow.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        ctk.CTkLabel(
            workflow.body,
            text=(
                "1.  Validate the selected .py file, folder or ZIP (read-only, never executed).\n"
                "2.  Clone the workspace repository using local git authentication.\n"
                "3.  Create a unique branch such as py2cardputer/20261121-150000-myapp.\n"
                "4.  Commit the input bundle to input/ on that branch.\n"
                "5.  Start an OpenHands Cloud V1 conversation bound to the branch.\n"
                "6.  Poll the start task, then the conversation, until it finishes.\n"
                "7.  Fetch firmware/AppName/ from the branch.\n"
                "8.  Validate the sketch structure and compile it locally.\n"
                "9.  Keep the branch, source, logs and binary for later inspection.\n"
                "10. Show an in-app notification and attempt a native Windows toast."
            ),
            font=font(12),
            text_color=COLORS["text_muted"],
            justify="left",
            anchor="w",
            wraplength=880,
        ).grid(row=0, column=0, sticky="ew")

        guarantees = SectionCard(self.scroll, "Guarantees and limits")
        guarantees.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        ctk.CTkLabel(
            guarantees.body,
            text=(
                "•  Branches, files and repositories are never deleted or merged automatically.\n"
                "•  Conversion files are never pushed to main by Py2Cardputer.\n"
                "•  API keys are read from .env and redacted from logs and error messages.\n"
                "•  Python sources are parsed, not executed.\n"
                "•  A successful local compile does not prove the firmware runs on hardware; "
                "flash and test it yourself.\n"
                "•  Generated firmware quality depends on the OpenHands conversion report; read it "
                "before flashing."
            ),
            font=font(12),
            text_color=COLORS["text_muted"],
            justify="left",
            anchor="w",
            wraplength=880,
        ).grid(row=0, column=0, sticky="ew")

        links = SectionCard(self.scroll, "Documentation")
        links.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        for index, (label, url) in enumerate(DOC_LINKS):
            ctk.CTkButton(
                links.body,
                text=label,
                command=lambda target=url: self.app.open_url(target),
                anchor="w",
                **secondary_button_options(),
            ).grid(row=index, column=0, sticky="w", pady=2)
