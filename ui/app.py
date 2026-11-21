"""Main CustomTkinter window and application controller."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from ai.openhands_client import OpenHandsClient
from compiler.arduino_cli import ArduinoCLI
from core.config import Config, parse_bool
from core.errors import Py2CardputerError, ValidationError
from core.jobs import JobStore
from core.logger import build_logger, redact
from core.models import Job, JobStatus
from core.notifications import Notifier
from core.pipeline import ConversionPipeline
from github.repository import GitHubRepository
from ui.about import AboutPage
from ui.conversion import ConversionPage
from ui.dashboard import DashboardPage
from ui.history import HistoryPage
from ui.settings import SettingsPage
from ui.theme import COLORS, PAGE_TITLES, apply_appearance, font, status_color
from ui.widgets import NotificationBanner

NAV_ITEMS = [
    ("dashboard", "Dashboard"),
    ("conversion", "New Conversion"),
    ("history", "Build History"),
    ("settings", "Settings"),
    ("about", "About"),
]

APP_VERSION = "1.0"


class Py2CardputerApp(ctk.CTk):
    """Desktop shell. Long-running work always runs on a worker thread."""

    def __init__(self, config: Config) -> None:
        apply_appearance()
        super().__init__(fg_color=COLORS["bg"])
        self.config = config
        self.logger = build_logger("py2cardputer", log_dir=config.log_path)
        self.job_store = JobStore(config.build_path, self.logger, log_dir=config.log_path)
        self.notifier = Notifier(
            enabled=config.notifications_enabled,
            native=config.native_notifications,
            logger=self.logger.getChild("notifications"),
        )
        self.events: queue.Queue = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="py2cardputer")
        self.pipeline: ConversionPipeline | None = None
        self.current_job: Job | None = None
        self.busy = False

        self.title("Py2Cardputer")
        self.geometry("1280x840")
        self.minsize(1080, 720)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main()
        self.show_page("dashboard")
        self.bind("<Control-o>", lambda _event: self.conversion_page.choose_file())
        self.bind("<Control-r>", lambda _event: self.dashboard.refresh())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._drain_events)

    # ------------------------------------------------------------------ layout
    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, width=236, corner_radius=0, fg_color=COLORS["sidebar"])
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(26, 6))
        ctk.CTkLabel(
            brand,
            text="▣ Py2Cardputer",
            font=font(20, "bold"),
            text_color=COLORS["accent"],
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand,
            text="UIFlow → Cardputer ADV",
            font=font(11),
            text_color=COLORS["text_muted"],
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=12, pady=(18, 0))
        nav.grid_columnconfigure(0, weight=1)
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for index, (name, label) in enumerate(NAV_ITEMS):
            button = ctk.CTkButton(
                nav,
                text=f"  {label}",
                anchor="w",
                height=40,
                corner_radius=8,
                fg_color="transparent",
                hover_color=COLORS["surface_hover"],
                text_color=COLORS["text_muted"],
                font=font(13),
                command=lambda page=name: self.show_page(page),
            )
            button.grid(row=index, column=0, sticky="ew", pady=2)
            self.nav_buttons[name] = button

        footer = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 20))
        ctk.CTkLabel(
            footer,
            text="Branches, sources and binaries are\nnever deleted automatically.",
            font=font(10),
            text_color=COLORS["text_dim"],
            justify="left",
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            footer,
            text=f"Version {APP_VERSION}",
            font=font(10),
            text_color=COLORS["text_dim"],
            anchor="w",
        ).pack(anchor="w", pady=(10, 0))

    def _build_main(self) -> None:
        main = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        self.notification_banner = NotificationBanner(main)

        header = ctk.CTkFrame(main, fg_color="transparent", height=76)
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(20, 8))
        header.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(
            header,
            text="Dashboard",
            font=font(24, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        )
        self.title_label.grid(row=0, column=0, sticky="w")
        self.subtitle_label = ctk.CTkLabel(
            header,
            text="",
            font=font(12),
            text_color=COLORS["text_muted"],
            anchor="w",
        )
        self.subtitle_label.grid(row=1, column=0, sticky="w", pady=(2, 0))

        self.activity_label = ctk.CTkLabel(
            header,
            text="● Idle",
            font=font(12, "bold"),
            text_color=COLORS["success"],
        )
        self.activity_label.grid(row=0, column=1, rowspan=2, sticky="e")

        container = ctk.CTkFrame(main, fg_color="transparent")
        container.grid(row=1, column=0, sticky="nsew", padx=28, pady=(0, 20))
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        self.pages: dict[str, ctk.CTkFrame] = {
            "dashboard": DashboardPage(self, container),
            "conversion": ConversionPage(self, container),
            "history": HistoryPage(self, container),
            "settings": SettingsPage(self, container),
            "about": AboutPage(self, container),
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
        self.dashboard: DashboardPage = self.pages["dashboard"]  # type: ignore[assignment]
        self.conversion_page: ConversionPage = self.pages["conversion"]  # type: ignore[assignment]
        self.history: HistoryPage = self.pages["history"]  # type: ignore[assignment]
        self.settings_page: SettingsPage = self.pages["settings"]  # type: ignore[assignment]

    def show_page(self, name: str) -> None:
        page = self.pages.get(name)
        if page is None:
            return
        page.tkraise()
        title, subtitle = PAGE_TITLES.get(name, (name.title(), ""))
        self.title_label.configure(text=title)
        self.subtitle_label.configure(text=subtitle)
        for key, button in self.nav_buttons.items():
            active = key == name
            button.configure(
                fg_color=COLORS["surface_alt"] if active else "transparent",
                text_color=COLORS["accent"] if active else COLORS["text_muted"],
            )
        on_show = getattr(page, "on_show", None)
        if callable(on_show):
            on_show()

    def set_activity(self, text: str, state: str = "info") -> None:
        self.activity_label.configure(text=f"● {text}", text_color=status_color(state))

    # --------------------------------------------------------------- threading
    def submit(self, func, *, on_done=None, on_error=None) -> None:
        """Run ``func`` in a worker thread and deliver the result on the UI thread."""

        def worker() -> None:
            try:
                result = func()
            except Exception as exc:  # noqa: BLE001 - delivered to the UI
                self.events.put(("task_error", (on_error, exc)))
            else:
                self.events.put(("task_done", (on_done, result)))

        self.executor.submit(worker)

    def _drain_events(self) -> None:
        try:
            while True:
                try:
                    kind, payload = self.events.get_nowait()
                except queue.Empty:
                    break
                if kind == "progress":
                    self.conversion_page.on_progress(payload)
                elif kind == "job_finished":
                    self._handle_job_finished(payload)
                elif kind == "task_done":
                    callback, result = payload
                    if callback:
                        callback(result)
                elif kind == "task_error":
                    callback, error = payload
                    if callback:
                        callback(error)
                    else:
                        messagebox.showerror("Py2Cardputer", str(error))
                elif kind == "log":
                    self.conversion_page.append_terminal(str(payload))
        finally:
            self.after(120, self._drain_events)

    # -------------------------------------------------------------- conversion
    def start_conversion(self, source_path: Path | str) -> None:
        if self.busy:
            messagebox.showinfo("Py2Cardputer", "A conversion is already running.")
            return
        problems = self.config.validate()
        if problems:
            messagebox.showerror("Configuration problem", "\n".join(problems))
            self.show_page("settings")
            return
        if not self.config.openhands_api_key:
            messagebox.showerror(
                "OpenHands API key missing",
                "Add your OpenHands API key in Settings. It is stored in .env and never committed.",
            )
            self.show_page("settings")
            return

        cancel_event = threading.Event()
        try:
            pipeline = ConversionPipeline(
                self.config,
                self.job_store,
                self.logger,
                cancel_event=cancel_event,
            )
            job = pipeline.create_job(source_path)
        except (ValidationError, Py2CardputerError) as exc:
            messagebox.showerror("Cannot start conversion", str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.exception("Could not create conversion job")
            messagebox.showerror("Cannot start conversion", str(exc))
            return

        self.pipeline = pipeline
        self.current_job = job
        self.busy = True
        self.set_activity("Working", "info")
        self.conversion_page.on_job_started(job)
        self.show_page("conversion")
        threading.Thread(
            target=self._run_pipeline,
            args=(pipeline, job),
            name=f"py2cardputer-{job.job_id}",
            daemon=True,
        ).start()

    def _run_pipeline(self, pipeline: ConversionPipeline, job: Job) -> None:
        try:
            pipeline.run(job, on_progress=lambda event: self.events.put(("progress", event)))
        except Exception:  # pragma: no cover - pipeline.run already catches
            self.logger.exception("Pipeline crashed outside its error handler")
        finally:
            self.events.put(("job_finished", job))

    def cancel_conversion(self) -> None:
        if self.pipeline is not None and self.busy:
            self.pipeline.cancel()
            self.set_activity("Cancelling", "warning")
            self.conversion_page.set_status_text("Cancelling — waiting for the current step to stop…")

    def _handle_job_finished(self, job: Job) -> None:
        self.busy = False
        self.current_job = job
        self.pipeline = None
        self.conversion_page.on_job_finished(job)
        self.dashboard.refresh_last_build(job)
        self.history.refresh()
        if job.status is JobStatus.SUCCEEDED:
            self.set_activity("Build succeeded", "success")
            self.notify(
                "Build succeeded",
                f"{job.app_name} compiled successfully.\n{job.binary_path or 'Binary path unavailable'}",
                "success",
            )
        elif job.status is JobStatus.WAITING_FOR_USER:
            self.set_activity("Waiting for you", "warning")
            self.notify(
                "OpenHands needs you",
                f"{job.app_name} is waiting for confirmation. Open the conversation to continue.",
                "warning",
            )
        elif job.status is JobStatus.CANCELLED:
            self.set_activity("Cancelled", "warning")
            self.notify("Conversion cancelled", f"{job.app_name} was cancelled.", "warning")
        else:
            self.set_activity("Build failed", "error")
            self.notify(
                "Build failed",
                f"{job.app_name}: {job.error or job.message or 'See the job log for details.'}",
                "error",
            )

    def notify(self, title: str, message: str, level: str = "info") -> None:
        """Show the in-app banner and attempt a native Windows toast."""
        safe_title = redact(title)
        safe_message = redact(message)
        try:
            self.notification_banner.show(safe_title, safe_message, level)
        except Exception:  # a notification must never break a job
            self.logger.debug("Could not show in-app notification", exc_info=True)
        try:
            self.notifier.notify(safe_title, safe_message, level)
        except Exception:  # pragma: no cover - defensive
            self.logger.debug("Native notification failed", exc_info=True)

    # ------------------------------------------------------------- diagnostics
    def check_openhands(self, callback) -> None:
        def work():
            client = OpenHandsClient(
                self.config.openhands_api_url,
                self.config.openhands_api_key,
                timeout=min(self.config.request_timeout_seconds, 30),
                logger=self.logger.getChild("openhands"),
            )
            return client.check_connection()

        self.submit(work, on_done=callback, on_error=callback)

    def check_github(self, callback) -> None:
        def work():
            repository = GitHubRepository(
                self.config.github_repository,
                self.config.workspace_path,
                logger=self.logger.getChild("github"),
            )
            return repository.check_auth()

        self.submit(work, on_done=callback, on_error=callback)

    def check_arduino(self, callback) -> None:
        def work():
            return ArduinoCLI(
                self.config.arduino_cli_path,
                logger=self.logger.getChild("arduino"),
            ).detect()

        self.submit(work, on_done=callback, on_error=callback)

    # ---------------------------------------------------------------- settings
    def save_settings(self, values: dict) -> list[str]:
        """Apply and persist settings; returns a list of problems."""
        config = self.config
        previous = {
            "openhands_api_url": config.openhands_api_url,
            "github_repository": config.github_repository,
            "arduino_cli_path": config.arduino_cli_path,
            "arduino_fqbn": config.arduino_fqbn,
            "build_dir": config.build_dir,
            "openhands_llm_model": config.openhands_llm_model,
            "poll_interval_seconds": config.poll_interval_seconds,
            "startup_timeout_seconds": config.startup_timeout_seconds,
            "execution_timeout_seconds": config.execution_timeout_seconds,
            "notifications_enabled": config.notifications_enabled,
            "native_notifications": config.native_notifications,
        }
        config.openhands_api_url = values["openhands_api_url"].strip()
        config.github_repository = values["github_repository"].strip()
        config.arduino_cli_path = values["arduino_cli_path"].strip()
        config.arduino_fqbn = values["arduino_fqbn"].strip()
        config.build_dir = values["build_dir"].strip()
        config.openhands_llm_model = values["openhands_llm_model"].strip()
        config.notifications_enabled = parse_bool(
            values.get("notifications_enabled", config.notifications_enabled)
        )
        config.native_notifications = parse_bool(
            values.get("native_notifications", config.native_notifications)
        )
        try:
            config.poll_interval_seconds = float(values["poll_interval_seconds"])
            config.startup_timeout_seconds = float(values["startup_timeout_seconds"])
            config.execution_timeout_seconds = float(values["execution_timeout_seconds"])
        except ValueError:
            for key, value in previous.items():
                setattr(config, key, value)
            return ["Polling interval and timeouts must be numbers."]

        problems = config.validate()
        if problems:
            for key, value in previous.items():
                setattr(config, key, value)
            return problems

        try:
            config.save()
            api_key = values.get("openhands_api_key", "").strip()
            if api_key:
                config.save_api_key(api_key)
        except OSError as exc:
            return [f"Could not save settings: {exc}"]

        self.job_store = JobStore(config.build_path, self.logger, log_dir=config.log_path)
        self.notifier.configure(
            enabled=config.notifications_enabled,
            native=config.native_notifications,
        )
        return []

    def clear_api_key(self) -> bool:
        try:
            self.config.save_api_key("")
        except OSError as exc:
            messagebox.showerror("Py2Cardputer", f"Could not update .env: {exc}")
            return False
        self.logger.info("Stored OpenHands API key was removed from .env")
        return True

    # ------------------------------------------------------------------ system
    def open_path(self, path: Path | str | None) -> None:
        if not path:
            return
        target = Path(path)
        if not target.exists():
            messagebox.showwarning("Py2Cardputer", f"Path does not exist:\n{target}")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as exc:
            messagebox.showerror("Py2Cardputer", f"Could not open {target}: {exc}")

    def open_url(self, url: str | None) -> None:
        if not url:
            return
        webbrowser.open(url)

    def copy_text(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    def _on_close(self) -> None:
        if self.busy:
            if not messagebox.askyesno(
                "Conversion running",
                "A conversion is still running. Cancel it and close Py2Cardputer?",
            ):
                return
            if self.pipeline:
                self.pipeline.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def launch(config: Config) -> int:
    app = Py2CardputerApp(config)
    app.mainloop()
    return 0


def _missing_tk_message() -> str:
    return (
        "Tkinter is not available in this Python installation. "
        "Install the standard Windows Python build (python.org), which includes Tk."
    )


def run_gui(config: Config) -> int:
    try:
        return launch(config)
    except ImportError as exc:  # pragma: no cover - environment specific
        print(_missing_tk_message(), file=sys.stderr)
        print(f"Details: {exc}", file=sys.stderr)
        return 2
