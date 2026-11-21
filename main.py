"""Py2Cardputer entry point.

Examples:
    python main.py                 # launch the desktop app
    python main.py --check         # environment diagnostics
    python main.py --cli --file app.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai.openhands_client import OpenHandsClient
from compiler.arduino_cli import ArduinoCLI
from core.config import Config
from core.errors import ConfigError, GitError, Py2CardputerError
from core.jobs import JobStore
from core.logger import build_logger
from core.models import JobStatus, ProgressEvent
from core.notifications import Notifier
from core.pipeline import ConversionPipeline
from github.repository import GitAuthResult, GitHubRepository

APP_VERSION = "1.0"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIG = 2
EXIT_CANCELLED = 130


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="py2cardputer",
        description="Convert UIFlow 2.0 MicroPython apps into Cardputer ADV Arduino firmware.",
    )
    parser.add_argument("--version", action="version", version=f"Py2Cardputer {APP_VERSION}")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run a conversion without the GUI (requires --file).",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="MicroPython .py file, project folder, or .zip archive to convert (CLI mode).",
    )
    parser.add_argument("--fqbn", help="Override the Arduino FQBN for this run.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Print configuration and connectivity diagnostics, then exit.",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="List recorded builds, then exit.",
    )
    return parser


def _masked_key(config: Config) -> str:
    return config.masked_api_key()


def run_check(config: Config) -> int:
    print(f"Py2Cardputer {APP_VERSION} diagnostics")
    print("=" * 46)
    print(f"Project root      : {config.root}")
    print(f"OpenHands API URL : {config.openhands_api_url}")
    print(f"OpenHands API key : {_masked_key(config)}")
    print(f"GitHub repository : {config.github_repository}")
    print(f"Arduino CLI path  : {config.arduino_cli_path}")
    print(f"Arduino FQBN      : {config.arduino_fqbn}")
    print(f"Build directory   : {config.build_path}")
    print(f"Log directory     : {config.log_path}")
    print(f"Workspace clone   : {config.workspace_path}")
    print()

    failures = 0
    problems = config.validate()
    if problems:
        failures += 1
        print("[FAIL] Configuration")
        for problem in problems:
            print(f"       - {problem}")
    else:
        print("[ OK ] Configuration is valid")

    try:
        client = OpenHandsClient(
            config.openhands_api_url,
            config.openhands_api_key,
            timeout=min(config.request_timeout_seconds, 30),
        )
        ok, message = client.check_connection()
    except ConfigError as exc:
        ok, message = False, str(exc)
    print(f"[{' OK ' if ok else 'FAIL'}] OpenHands: {message}")
    if not ok:
        failures += 1

    try:
        repository = GitHubRepository(config.github_repository, config.workspace_path)
        auth = repository.check_auth()
    except GitError as exc:
        auth = GitAuthResult(ok=False, message=str(exc))
    print(f"[{' OK ' if auth.ok else 'FAIL'}] GitHub: {auth.message}")
    if not auth.ok and auth.detail:
        print(f"       {auth.detail.splitlines()[0] if auth.detail else ''}")
    if not auth.ok:
        failures += 1

    arduino = ArduinoCLI(config.arduino_cli_path)
    info = arduino.detect()
    print(f"[{' OK ' if info.available else 'FAIL'}] {info.summary()}")
    if not info.available:
        failures += 1
    else:
        boards = arduino.list_boards("cardputer")
        if boards.matches:
            print("[ OK ] Matching boards:")
            for line in boards.matches[:5]:
                print(f"       {line}")
        else:
            print("[WARN] No board matching 'cardputer' was listed. Verify the FQBN:")
            print(f"       {config.arduino_fqbn}")
            print("       Install the M5Stack core, then run: arduino-cli board listall cardputer")

    print()
    print("Diagnostics finished with no failures." if not failures else f"{failures} check(s) failed.")
    return EXIT_OK if failures == 0 else EXIT_FAILED


def run_history(config: Config, logger) -> int:
    store = JobStore(config.build_path, logger, log_dir=config.log_path)
    jobs = store.list_jobs()
    if not jobs:
        print("No builds recorded yet.")
        return EXIT_OK
    for job in jobs:
        print(f"{job.created_at[:19].replace('T', ' ')}  {job.status.value:<16} {job.app_name}")
        print(f"  branch : {job.branch}")
        if job.binary_path:
            print(f"  binary : {job.binary_path}")
        if job.openhands_conversation_url:
            print(f"  chat   : {job.openhands_conversation_url}")
        print(f"  folder : {job.job_dir}")
    return EXIT_OK


def run_cli(config: Config, logger, args: argparse.Namespace) -> int:
    if not args.file:
        print("error: --cli requires --file PATH", file=sys.stderr)
        return EXIT_CONFIG
    if args.fqbn:
        config.arduino_fqbn = args.fqbn

    config.ensure_directories()
    store = JobStore(config.build_path, logger, log_dir=config.log_path)
    try:
        pipeline = ConversionPipeline(config, store, logger)
        job = pipeline.create_job(args.file)
    except Py2CardputerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Could not create the conversion job")
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    print(f"Job       : {job.job_id}")
    print(f"Source    : {job.source_path}")
    print(f"Input     : {job.source_kind} ({len(job.source_files) or 1} file(s))")
    print(f"Repository: {job.repository}")
    print(f"Branch    : {job.branch}")
    print(f"Build dir : {job.job_dir}")
    print()

    def on_progress(event: ProgressEvent) -> None:
        if event.level == "terminal":
            print(event.message)
        else:
            print(f"[{event.level:<7}] {event.step}: {event.message}")

    try:
        job = pipeline.run(job, on_progress=on_progress)
    except KeyboardInterrupt:
        pipeline.cancel()
        print("\nCancelled. The branch and any generated files were left in place.", file=sys.stderr)
        return EXIT_CANCELLED

    print()
    print("=" * 46)
    print(f"Status    : {job.status.value}")
    print(f"Branch    : {job.branch} (kept)")
    print(f"Build dir : {job.job_dir}")
    if job.openhands_conversation_url:
        print(f"OpenHands : {job.openhands_conversation_url}")
    if job.compile_log_path:
        print(f"Compile   : {job.compile_log_path}")
    if job.binary_path:
        print(f"Binary    : {job.binary_path}")
    if job.error:
        print(f"Error     : {job.error}")

    notifier = Notifier(
        enabled=config.notifications_enabled,
        native=config.native_notifications,
        logger=logger.getChild("notifications"),
    )
    if job.status is JobStatus.SUCCEEDED:
        notifier.notify(
            "Build succeeded",
            f"{job.app_name} compiled.\n{job.binary_path or ''}".strip(),
            "success",
        )
    elif job.status is JobStatus.WAITING_FOR_USER:
        notifier.notify(
            "OpenHands needs you",
            f"{job.app_name} is waiting for confirmation.",
            "warning",
        )
    elif job.status is JobStatus.CANCELLED:
        notifier.notify("Conversion cancelled", f"{job.app_name} was cancelled.", "warning")
    else:
        notifier.notify(
            "Build failed",
            f"{job.app_name}: {job.error or job.message or 'See the log.'}",
            "error",
        )

    if job.status is JobStatus.SUCCEEDED:
        return EXIT_OK
    if job.status is JobStatus.CANCELLED:
        return EXIT_CANCELLED
    return EXIT_FAILED


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    args = build_parser().parse_args(argv)

    try:
        config = Config.load()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    config.ensure_directories()
    logger = build_logger("py2cardputer", log_dir=config.log_path)

    if args.check:
        return run_check(config)
    if args.history:
        return run_history(config, logger)
    if args.cli or args.file:
        return run_cli(config, logger, args)

    try:
        from ui.app import run_gui
    except ImportError as exc:
        print(
            "The desktop interface could not be loaded. Install the dependencies with "
            "'pip install -r requirements.txt'.\n"
            f"Details: {exc}",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    return run_gui(config)


if __name__ == "__main__":
    raise SystemExit(main())
