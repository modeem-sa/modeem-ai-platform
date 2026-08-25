"""OpenAI-compatible provider boundary; no credentials leave this module."""

import json
import os
from collections.abc import Mapping
from typing import Any, Protocol

import httpx


class ProviderUnavailableError(Exception):
    """No server-side model provider is configured."""


class ProviderFailureError(Exception):
    """The configured provider was unreachable or returned unusable output."""


class ContentManagerProvider(Protocol):
    def generate(self, *, system_prompt: str, user_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return the structured response object from the model."""


class OpenAICompatibleProvider:
    """Minimal OpenAI Chat Completions client using server environment only."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    @classmethod
    def from_environment(cls) -> "OpenAICompatibleProvider":
        managed_base_url = os.getenv("AI_INTEGRATIONS_OPENAI_BASE_URL")
        managed_api_key = os.getenv("AI_INTEGRATIONS_OPENAI_API_KEY")
        standard_api_key = os.getenv("OPENAI_API_KEY")
        api_key = managed_api_key or standard_api_key
        if not api_key:
            raise ProviderUnavailableError()
        base_url = (
            managed_base_url
            if managed_api_key
            else os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        )
        if not base_url:
            raise ProviderUnavailableError()
        return cls(base_url, api_key, os.getenv("MODEEM_AI_MODEL", "gpt-5.6-terra"))

    def generate(self, *, system_prompt: str, user_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        body = {
            "model": self.model,
            "max_completion_tokens": 6000,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            # ModelResult performs the authoritative strict validation. JSON
            # mode avoids accepting prose while remaining compatible with both
            # the managed proxy and standard OpenAI-compatible servers.
            "response_format": {"type": "json_object"},
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            value = _parse_json_object(content)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderFailureError() from exc
        return value


def _parse_json_object(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str):
        raise TypeError("provider output was not JSON text")
    text = value.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    decoded = json.loads(text)
    if not isinstance(decoded, Mapping):
        raise TypeError("provider output was not an object")
    return decoded
