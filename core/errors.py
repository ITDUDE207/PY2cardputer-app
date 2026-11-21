"""Exception hierarchy for Py2Cardputer.

Every error surfaced to the UI is one of these types so the GUI can render a
useful message without leaking credentials or tracebacks.
"""

from __future__ import annotations

from typing import Any


class Py2CardputerError(Exception):
    """Base class for all application errors."""


class ConfigError(Py2CardputerError):
    """Raised when configuration is missing or invalid."""


class ValidationError(Py2CardputerError):
    """Raised when user-supplied input (a source file, a name) is invalid."""


class JobCancelled(Py2CardputerError):
    """Raised when the user cancels a running conversion."""


class GitError(Py2CardputerError):
    """Raised when a git command fails."""

    def __init__(self, message: str, *, command: str | None = None, stderr: str = "") -> None:
        super().__init__(message)
        self.command = command
        self.stderr = stderr


class GitAuthError(GitError):
    """Raised when local git credentials cannot access the workspace repository."""


class OpenHandsError(Py2CardputerError):
    """Base class for OpenHands Cloud API errors."""


class OpenHandsAuthError(OpenHandsError):
    """Raised for 401/403 responses from the OpenHands API."""


class OpenHandsAPIError(OpenHandsError):
    """Raised for non-successful OpenHands API responses."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class OpenHandsTimeoutError(OpenHandsError):
    """Raised when an OpenHands request or monitoring window times out."""


class ArduinoCLIError(Py2CardputerError):
    """Raised when Arduino CLI cannot be executed."""


class ArduinoCLINotFoundError(ArduinoCLIError):
    """Raised when the Arduino CLI executable is not available."""


class CompilationError(ArduinoCLIError):
    """Raised when compilation fails or produces no binary."""

    def __init__(self, message: str, *, result: Any = None) -> None:
        super().__init__(message)
        self.result = result


class PipelineError(Py2CardputerError):
    """Raised when a conversion pipeline step fails."""

    def __init__(self, step: str, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.step = step
        self.cause = cause
