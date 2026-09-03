"""Provider configuration, registry, and concrete translation adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Thread
from typing import Final, cast
from uuid import uuid4

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from openai.types.chat import ChatCompletion

from novel_translator.core import TranslatorGateway
from novel_translator.shared.errors import ValidationError


@dataclass(frozen=True, slots=True)
class OpenCodeGoConfig:
    """Typed settings for the OpenCode Go OpenAI-compatible endpoint."""

    base_url: str
    model: str
    api_key: str
    timeout_seconds: float = 90.0


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    """Canonical provider metadata and the adapter configured from it."""

    name: str
    model: str
    gateway: TranslatorGateway


class OpenAICompatibleGateway:
    """Synchronous adapter backed by the official OpenAI Python SDK."""

    def __init__(self, config: OpenCodeGoConfig, *, client: OpenAI | None = None) -> None:
        self._base_url = config.base_url.rstrip("/")
        self._model = config.model
        self._api_key = config.api_key
        self._timeout_seconds = config.timeout_seconds
        self._session_id = uuid4().hex
        self._client = client or OpenAI(
            api_key=config.api_key,
            base_url=self._base_url,
            timeout=config.timeout_seconds,
            max_retries=0,
        )

    def translate(self, prompt: str) -> str:
        """Request one chat completion while enforcing a total deadline."""
        result_queue: Queue[ChatCompletion | Exception] = Queue(maxsize=1)

        def request_completion() -> None:
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    extra_headers={"x-opencode-session": self._session_id},
                )
            except Exception as error:
                result_queue.put(error)
            else:
                result_queue.put(response)

        Thread(target=request_completion, daemon=True).start()
        try:
            result = result_queue.get(timeout=self._timeout_seconds)
        except Empty as error:
            raise httpx.ReadTimeout(
                f"Provider did not complete the request within {self._timeout_seconds} seconds."
            ) from error
        if isinstance(result, APITimeoutError):
            raise httpx.ReadTimeout(str(result), request=httpx.Request("POST", self._base_url)) from result
        if isinstance(result, APIConnectionError):
            raise httpx.ConnectError(str(result), request=httpx.Request("POST", self._base_url)) from result
        if isinstance(result, APIStatusError):
            raise ValidationError(self._provider_error(result)) from result
        if isinstance(result, Exception):
            raise result
        content = result.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("Provider returned an empty translation.")
        return content.strip()

    def _provider_error(self, error: APIStatusError) -> str:
        """Return a bounded provider error without exposing request secrets."""
        payload = error.body
        if isinstance(payload, dict):
            typed_payload = cast(dict[str, object], payload)
            nested_error = typed_payload.get("error")
            error_message = (
                cast(dict[str, object], nested_error).get("message") if isinstance(nested_error, dict) else None
            )
            message = typed_payload.get("message")
        else:
            error_message = None
            message = None
        if isinstance(error_message, str):
            detail = error_message
        elif isinstance(message, str):
            detail = message
        else:
            detail = "No error detail returned."
        if self._api_key:
            detail = detail.replace(self._api_key, "***")
        suffix = f" Request ID: {error.request_id}." if error.request_id else ""
        return f"Provider rejected request with HTTP {error.status_code}: {detail[:500]}.{suffix}"


GatewayFactory = Callable[[OpenCodeGoConfig], TranslatorGateway]
_PROVIDER_FACTORIES: Final[dict[str, GatewayFactory]] = {
    "opencode-go": OpenAICompatibleGateway,
}


def resolve_provider(provider: str, config: OpenCodeGoConfig) -> ProviderSelection:
    """Resolve a configured provider to its canonical metadata and adapter."""
    canonical_name = provider.strip().casefold()
    factory = _PROVIDER_FACTORIES.get(canonical_name)
    if factory is None:
        supported = ", ".join(sorted(_PROVIDER_FACTORIES))
        raise ValidationError(f"Unsupported provider '{provider}'. Supported providers: {supported}.")
    return ProviderSelection(canonical_name, config.model, factory(config))
