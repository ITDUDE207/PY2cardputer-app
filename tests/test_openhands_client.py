from __future__ import annotations

import pytest
import requests

from ai.openhands_client import OpenHandsClient
from core.errors import (
    ConfigError,
    OpenHandsAPIError,
    OpenHandsAuthError,
    OpenHandsTimeoutError,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text or (str(payload) if payload is not None else "")
        self.headers = headers or {}
        self.content = b"{}" if payload is not None else b""

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class FakeSession:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_client(responses, **kwargs) -> tuple[OpenHandsClient, FakeSession]:
    session = FakeSession(responses)
    kwargs.setdefault("sleep", lambda _seconds: None)
    client = OpenHandsClient(
        "https://app.all-hands.dev",
        "test-api-key",
        session=session,
        **kwargs,
    )
    return client, session


def test_base_url_normalisation() -> None:
    assert OpenHandsClient("https://app.all-hands.dev/").base_url == "https://app.all-hands.dev"
    assert (
        OpenHandsClient("https://app.all-hands.dev/api/v1").base_url
        == "https://app.all-hands.dev"
    )
    with pytest.raises(ConfigError):
        OpenHandsClient("app.all-hands.dev")
    with pytest.raises(ConfigError):
        OpenHandsClient("")


def test_start_conversation_payload_and_result() -> None:
    client, session = make_client(
        [FakeResponse(200, {"id": "task-1", "status": "WORKING", "sandbox_id": None})]
    )
    result = client.start_conversation(
        repository="owner/repo",
        branch="py2cardputer/20261121-150000-app",
        prompt="Convert this app.",
        title="Py2Cardputer: App",
    )
    assert result.start_task_id == "task-1"
    assert result.status == "WORKING"
    assert result.app_conversation_id is None

    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://app.all-hands.dev/api/v1/app-conversations"
    payload = call["json"]
    assert payload["selected_repository"] == "owner/repo"
    assert payload["selected_branch"] == "py2cardputer/20261121-150000-app"
    assert payload["git_provider"] == "github"
    assert payload["title"] == "Py2Cardputer: App"
    assert payload["initial_message"]["content"][0]["type"] == "text"
    assert payload["initial_message"]["content"][0]["text"] == "Convert this app."
    assert call["headers"]["Authorization"] == "Bearer test-api-key"


def test_start_conversation_requires_fields() -> None:
    client, _ = make_client([])
    with pytest.raises(ConfigError):
        client.start_conversation(repository="bad", branch="b", prompt="p")
    with pytest.raises(ConfigError):
        client.start_conversation(repository="a/b", branch="", prompt="p")
    with pytest.raises(ConfigError):
        client.start_conversation(repository="a/b", branch="b", prompt="   ")


def test_start_conversation_requires_api_key() -> None:
    session = FakeSession([])
    client = OpenHandsClient("https://app.all-hands.dev", "", session=session)
    with pytest.raises(OpenHandsAuthError):
        client.start_conversation(repository="a/b", branch="b", prompt="p")


def test_auth_error() -> None:
    client, _ = make_client([FakeResponse(401, {"detail": "bad key"})])
    with pytest.raises(OpenHandsAuthError) as excinfo:
        client.search_conversations()
    assert "rejected" in str(excinfo.value).lower()


def test_validation_error_detail_is_reported() -> None:
    client, _ = make_client(
        [FakeResponse(422, {"detail": [{"msg": "selected_branch is invalid"}]})]
    )
    with pytest.raises(OpenHandsAPIError) as excinfo:
        client.start_conversation(repository="a/b", branch="b", prompt="p")
    assert excinfo.value.status_code == 422
    assert "selected_branch is invalid" in str(excinfo.value)


def test_get_retries_server_errors_then_succeeds() -> None:
    client, session = make_client(
        [FakeResponse(500, {"detail": "oops"}), FakeResponse(200, [{"id": "c1"}])],
        max_retries=1,
    )
    assert client.get_conversation("c1") == {"id": "c1"}
    assert len(session.calls) == 2


def test_get_retries_exhausted() -> None:
    client, session = make_client(
        [FakeResponse(503, {"detail": "busy"}), FakeResponse(503, {"detail": "busy"})],
        max_retries=1,
    )
    with pytest.raises(OpenHandsAPIError) as excinfo:
        client.get_conversation("c1")
    assert excinfo.value.status_code == 503
    assert len(session.calls) == 2


def test_post_is_not_retried() -> None:
    client, session = make_client(
        [FakeResponse(500, {"detail": "oops"}), FakeResponse(200, {"id": "task"})],
        max_retries=3,
    )
    with pytest.raises(OpenHandsAPIError):
        client.start_conversation(repository="a/b", branch="b", prompt="p")
    assert len(session.calls) == 1


def test_timeout_raises_typed_error() -> None:
    client, _ = make_client([requests.exceptions.Timeout()], max_retries=0)
    with pytest.raises(OpenHandsTimeoutError):
        client.get_conversation("c1")


def test_connection_error_is_retried() -> None:
    client, session = make_client(
        [requests.exceptions.ConnectionError("down"), FakeResponse(200, [])],
        max_retries=1,
    )
    assert client.search_conversations() == []
    assert len(session.calls) == 2


def test_get_start_task_skips_none_items() -> None:
    client, _ = make_client(
        [FakeResponse(200, [None, {"id": "task-1", "status": "READY"}])]
    )
    assert client.get_start_task("task-1")["status"] == "READY"


def test_get_start_task_returns_none_for_empty_list() -> None:
    client, _ = make_client([FakeResponse(200, [])])
    assert client.get_start_task("missing") is None


def test_search_conversations_items() -> None:
    client, _ = make_client(
        [FakeResponse(200, {"items": [{"id": "a"}, "junk"], "next_page_id": None})]
    )
    assert client.search_conversations() == [{"id": "a"}]


def test_check_connection_without_key() -> None:
    client = OpenHandsClient("https://app.all-hands.dev", "", session=FakeSession([]))
    ok, message = client.check_connection()
    assert ok is False
    assert "not configured" in message.lower()


def test_check_connection_success() -> None:
    client, _ = make_client([FakeResponse(200, {"items": []})])
    ok, message = client.check_connection()
    assert ok is True
    assert "connected" in message.lower()


def test_check_connection_failure() -> None:
    client, _ = make_client([FakeResponse(403, {"detail": "forbidden"})])
    ok, message = client.check_connection()
    assert ok is False


def test_conversation_url_prefers_explicit() -> None:
    client, _ = make_client([])
    assert client.conversation_url("c1") == "https://app.all-hands.dev/conversations/c1"
    assert client.conversation_url("c1", "https://custom/url") == "https://custom/url"


def test_invalid_json_response() -> None:
    class BadResponse(FakeResponse):
        def json(self):
            raise ValueError("bad")

    response = BadResponse(200, None)
    response.content = b"not-json"
    client, _ = make_client([response])
    with pytest.raises(OpenHandsAPIError):
        client.search_conversations()
