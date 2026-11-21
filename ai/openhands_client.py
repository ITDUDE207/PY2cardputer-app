"""OpenHands Cloud V1 API client.

Endpoints and payloads follow the official documentation:

* ``POST /api/v1/app-conversations``
* ``GET  /api/v1/app-conversations/start-tasks?ids=...``
* ``GET  /api/v1/app-conversations?ids=...``
* ``GET  /api/v1/app-conversations/search``

Reference: https://docs.openhands.dev/openhands/usage/cloud/cloud-api
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import requests

from core.errors import (
    ConfigError,
    OpenHandsAPIError,
    OpenHandsAuthError,
    OpenHandsTimeoutError,
)
from core.logger import redact, register_secret
from core.models import OpenHandsStartResult

START_TASKS_PATH = "/api/v1/app-conversations/start-tasks"
CONVERSATIONS_PATH = "/api/v1/app-conversations"
SEARCH_PATH = "/api/v1/app-conversations/search"

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ERROR_DETAIL = 600


class OpenHandsClient:
    """Small, explicit client for the OpenHands Cloud V1 app-conversation API."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        *,
        session: requests.Session | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff_seconds: float = 1.5,
        logger: logging.Logger | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = self._normalise_base_url(base_url)
        self.api_key = (api_key or "").strip()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.backoff_seconds = backoff_seconds
        self.logger = logger or logging.getLogger("py2cardputer.openhands")
        self._sleep = sleep
        register_secret(self.api_key)

    @staticmethod
    def _normalise_base_url(base_url: str) -> str:
        url = (base_url or "").strip().rstrip("/")
        if not url:
            raise ConfigError("OpenHands API URL is empty.")
        if not url.startswith(("http://", "https://")):
            raise ConfigError("OpenHands API URL must start with http:// or https://")
        if url.endswith("/api/v1"):
            url = url[: -len("/api/v1")]
        return url

    # ------------------------------------------------------------------ HTTP
    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Py2Cardputer/1.0",
        }

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> Any:
        if not self.api_key:
            raise OpenHandsAuthError(
                "OPENHANDS_API_KEY is not configured. Add it to .env or in Settings."
            )
        attempts = self.max_retries + 1 if retry else 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = self.session.request(
                    method,
                    self._url(path),
                    headers=self.headers,
                    params=params,
                    json=json_body,
                    timeout=self.timeout,
                )
            except requests.Timeout as exc:
                last_error = exc
                if attempt < attempts:
                    self._sleep(self._delay(attempt))
                    continue
                raise OpenHandsTimeoutError(
                    f"OpenHands API request timed out after {self.timeout:.0f}s."
                ) from exc
            except requests.RequestException as exc:
                last_error = exc
                if attempt < attempts:
                    self._sleep(self._delay(attempt))
                    continue
                raise OpenHandsAPIError(f"Could not reach OpenHands: {exc}") from exc

            status = response.status_code
            if 200 <= status < 300:
                return self._decode(response)
            if status in (401, 403):
                raise OpenHandsAuthError(
                    f"OpenHands rejected the API key (HTTP {status}). "
                    "Create a new key at https://app.all-hands.dev/settings/api-keys."
                )
            if status in RETRYABLE_STATUS_CODES and attempt < attempts:
                self._sleep(self._retry_after(response, attempt))
                continue
            raise OpenHandsAPIError(
                self._error_message(status, response),
                status_code=status,
                payload=self._safe_payload(response),
            )
        raise OpenHandsAPIError(f"OpenHands request failed: {last_error}")  # pragma: no cover

    def _delay(self, attempt: int) -> float:
        return self.backoff_seconds * (2 ** (attempt - 1))

    def _retry_after(self, response: requests.Response, attempt: int) -> float:
        header = response.headers.get("Retry-After") if response.headers else None
        if header:
            try:
                return min(max(float(header), 0.0), 60.0)
            except ValueError:
                pass
        return self._delay(attempt)

    @staticmethod
    def _decode(response: requests.Response) -> Any:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise OpenHandsAPIError(
                "OpenHands returned a response that is not valid JSON."
            ) from exc

    @staticmethod
    def _safe_payload(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    def _error_message(self, status: int, response: requests.Response) -> str:
        detail = ""
        payload = self._safe_payload(response)
        if isinstance(payload, dict):
            raw = payload.get("detail") or payload.get("message") or payload.get("error")
            if isinstance(raw, list):
                parts = []
                for item in raw:
                    if isinstance(item, dict):
                        parts.append(str(item.get("msg") or item))
                    else:
                        parts.append(str(item))
                detail = "; ".join(parts)
            elif raw is not None:
                detail = str(raw)
        if not detail:
            detail = (response.text or "").strip()
        detail = redact(detail)[:MAX_ERROR_DETAIL]
        suffix = f": {detail}" if detail else ""
        return f"OpenHands API error (HTTP {status}){suffix}"

    # -------------------------------------------------------------- endpoints
    def start_conversation(
        self,
        *,
        repository: str,
        branch: str,
        prompt: str,
        title: str | None = None,
        llm_model: str | None = None,
        git_provider: str = "github",
    ) -> OpenHandsStartResult:
        """Create a conversation bound to ``repository`` and ``branch``."""
        if not repository or "/" not in repository:
            raise ConfigError("A GitHub repository in 'owner/repo' form is required.")
        if not branch:
            raise ConfigError("A branch is required before starting a conversation.")
        if not prompt.strip():
            raise ConfigError("The conversion prompt must not be empty.")

        payload: dict[str, Any] = {
            "initial_message": {"content": [{"type": "text", "text": prompt}]},
            "selected_repository": repository,
            "selected_branch": branch,
            "git_provider": git_provider,
        }
        if title:
            payload["title"] = title
        if llm_model:
            payload["llm_model"] = llm_model

        # A retried POST could create a duplicate conversation, so POST is never retried.
        data = self._request("POST", CONVERSATIONS_PATH, json_body=payload, retry=False)
        if not isinstance(data, dict) or not data.get("id"):
            raise OpenHandsAPIError("OpenHands did not return a start task id.", payload=data)

        conversation_id = data.get("app_conversation_id")
        result = OpenHandsStartResult(
            start_task_id=str(data["id"]),
            status=str(data.get("status") or "WORKING"),
            app_conversation_id=str(conversation_id) if conversation_id else None,
            sandbox_id=data.get("sandbox_id"),
            conversation_url=(
                self.conversation_url(str(conversation_id)) if conversation_id else None
            ),
            raw=data,
        )
        self.logger.info("Started OpenHands start task %s", result.start_task_id)
        return result

    def get_start_task(self, task_id: str) -> dict[str, Any] | None:
        data = self._request(
            "GET", START_TASKS_PATH, params={"ids": task_id}, retry=True
        )
        return self._first_item(data)

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        data = self._request(
            "GET", CONVERSATIONS_PATH, params={"ids": conversation_id}, retry=True
        )
        return self._first_item(data)

    def search_conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        data = self._request("GET", SEARCH_PATH, params={"limit": limit}, retry=True)
        if isinstance(data, dict):
            items = data.get("items", [])
            return [item for item in items if isinstance(item, dict)]
        return []

    @staticmethod
    def _first_item(data: Any) -> dict[str, Any] | None:
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    return item
            return None
        if isinstance(data, dict):
            return data
        return None

    def conversation_url(self, conversation_id: str, explicit: str | None = None) -> str:
        if explicit:
            return explicit
        return f"{self.base_url}/conversations/{conversation_id}"

    # ------------------------------------------------------------ diagnostics
    def check_connection(self) -> tuple[bool, str]:
        """Return ``(ok, message)`` without raising for the dashboard."""
        if not self.api_key:
            return False, "OPENHANDS_API_KEY is not configured."
        try:
            self.search_conversations(limit=1)
        except OpenHandsAuthError as exc:
            return False, str(exc)
        except OpenHandsTimeoutError:
            return False, "OpenHands API timed out while checking the connection."
        except OpenHandsAPIError as exc:
            return False, str(exc)
        except ConfigError as exc:
            return False, str(exc)
        return True, f"Connected to OpenHands at {self.base_url}"
