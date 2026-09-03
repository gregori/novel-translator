"""Provider registry and OpenAI-compatible adapter tests."""

import json
from threading import Event
from uuid import UUID

import httpx
import httpx2
import pytest
from openai import DefaultHttpxClient, OpenAI

from novel_translator.providers import (
    OpenAICompatibleGateway,
    OpenCodeGoConfig,
    resolve_provider,
)
from novel_translator.shared.errors import ValidationError


def sdk_client(transport: httpx2.BaseTransport) -> OpenAI:
    """Build an SDK client whose requests stay inside the test process."""
    return OpenAI(
        api_key="secret",
        base_url="https://example.test/v1",
        max_retries=0,
        http_client=DefaultHttpxClient(transport=transport),
    )


def completion_response() -> httpx2.Response:
    """Return the smallest valid chat-completion response."""
    return httpx2.Response(
        200,
        json={
            "id": "completion-1",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "translated"},
                }
            ],
        },
    )


def test_opencode_go_resolves_to_supported_adapter() -> None:
    """The v1 provider name explicitly selects its configured adapter."""
    selection = resolve_provider(
        "opencode-go",
        OpenCodeGoConfig("https://example.test/v1", "test-model", "secret"),
    )

    assert selection.name == "opencode-go"
    assert selection.model == "test-model"
    assert isinstance(selection.gateway, OpenAICompatibleGateway)


def test_unknown_provider_is_rejected() -> None:
    """An unsupported provider fails with the available choice."""
    config = OpenCodeGoConfig("https://example.test/v1", "test-model", "secret")

    with pytest.raises(ValidationError, match="Unsupported provider 'unknown'.*opencode-go"):
        resolve_provider("unknown", config)


def test_opencode_go_sends_chat_completion_contract() -> None:
    """The adapter sends the OpenCode Go compatible path, auth, model, and messages."""
    captured: dict[str, object] = {}

    def handle_request(request: httpx2.Request) -> httpx2.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["payload"] = json.loads(request.read())
        return completion_response()

    config = OpenCodeGoConfig("https://example.test/v1", "test-model", "secret")
    gateway = OpenAICompatibleGateway(
        config,
        client=sdk_client(httpx2.MockTransport(handle_request)),
    )

    assert gateway.translate("translate this") == "translated"
    assert captured == {
        "url": "https://example.test/v1/chat/completions",
        "authorization": "Bearer secret",
        "payload": {
            "messages": [{"role": "user", "content": "translate this"}],
            "model": "test-model",
        },
    }


def test_opencode_go_reuses_session_header() -> None:
    """All requests made by one gateway share a valid session identifier."""
    session_ids: list[str] = []

    def handle_request(request: httpx2.Request) -> httpx2.Response:
        session_ids.append(request.headers["x-opencode-session"])
        return completion_response()

    gateway = OpenAICompatibleGateway(
        OpenCodeGoConfig("https://example.test/v1", "test-model", "secret"),
        client=sdk_client(httpx2.MockTransport(handle_request)),
    )

    assert gateway.translate("first segment") == "translated"
    assert gateway.translate("second segment") == "translated"
    assert len(set(session_ids)) == 1
    assert UUID(hex=session_ids[0]).hex == session_ids[0]


def test_gateway_enforces_a_total_request_deadline() -> None:
    """A provider that keeps sending data cannot block the CLI indefinitely."""
    release_request = Event()

    def delayed_response(_: httpx2.Request) -> httpx2.Response:
        release_request.wait()
        return completion_response()

    config = OpenCodeGoConfig("https://example.test/v1", "test-model", "secret", timeout_seconds=0.01)
    gateway = OpenAICompatibleGateway(
        config,
        client=sdk_client(httpx2.MockTransport(delayed_response)),
    )

    try:
        with pytest.raises(httpx.ReadTimeout, match="did not complete"):
            gateway.translate("prompt")
    finally:
        release_request.set()


def test_gateway_reports_safe_provider_error_details() -> None:
    """Provider status errors retain a useful, bounded diagnostic message."""

    def forbidden_response(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            401,
            json={"error": {"message": "Invalid API key"}},
            headers={"x-request-id": "request-123"},
        )

    config = OpenCodeGoConfig("https://example.test/v1", "test-model", "secret")
    gateway = OpenAICompatibleGateway(
        config,
        client=sdk_client(httpx2.MockTransport(forbidden_response)),
    )

    with pytest.raises(
        ValidationError,
        match="HTTP 401: Invalid API key. Request ID: request-123",
    ):
        gateway.translate("prompt")


def test_gateway_redacts_configured_key_from_provider_error() -> None:
    """A provider response cannot echo the configured API key to the user."""

    def leaked_key_response(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"error": {"message": "Rejected secret-value"}})

    config = OpenCodeGoConfig("https://example.test/v1", "test-model", "secret-value")
    gateway = OpenAICompatibleGateway(
        config,
        client=sdk_client(httpx2.MockTransport(leaked_key_response)),
    )

    with pytest.raises(ValidationError) as raised:
        gateway.translate("prompt")

    assert "secret-value" not in str(raised.value)
    assert "***" in str(raised.value)
