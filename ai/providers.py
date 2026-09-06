"""Concrete multimodal provider adapters."""
from __future__ import annotations

import base64
from typing import Any

from rehan_bot.ai.errors import ProviderError, ProviderErrorKind
from rehan_bot.ai.key_pool import RoundRobinKeyPool
from rehan_bot.ai.parsing import chat_completion_text, gemini_text, json_object, openai_output_text
from rehan_bot.ai.schemas import VisualSolution
from rehan_bot.ai.transport import JsonTransport
from rehan_bot.ai.vision import VisionImage


def _schema() -> dict[str, Any]:
    return VisualSolution.model_json_schema()


def _data_url(image: VisionImage) -> str:
    encoded = base64.b64encode(image.data).decode("ascii")
    return f"data:{image.mime_type};base64,{encoded}"


class OpenAIVisionProvider:
    def __init__(self, keys: RoundRobinKeyPool, model: str, timeout_seconds: float = 30.0) -> None:
        self._keys = keys
        self._model = model
        self._transport = JsonTransport(timeout_seconds)

    def propose(self, image: VisionImage, prompt: str) -> VisualSolution:
        payload = {
            "model": self._model,
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": _data_url(image), "detail": "low"},
            ]}],
            "text": {"format": {"type": "json_schema", "name": "recovery_proposal", "strict": True, "schema": _schema()}},
            "reasoning": {"effort": "low"},
        }
        return self._request("openai", "https://api.openai.com/v1/responses", payload)

    def _request(self, provider: str, url: str, payload: dict[str, Any]) -> VisualSolution:
        last_error: ProviderError | None = None
        for state in self._keys.round_keys():
            try:
                data = self._transport.post(provider, url, {"Authorization": f"Bearer {state.key}", "Content-Type": "application/json"}, payload)
                proposal = VisualSolution.model_validate(json_object(openai_output_text(data)))
                self._keys.success(state)
                return proposal
            except ProviderError as exc:
                last_error = exc
                self._keys.failure(state, exc.kind)
                # Credentials/rate limits rotate within this provider. A
                # timeout or service outage moves straight to the next tier,
                # keeping browser recovery responsive.
                if exc.kind in {ProviderErrorKind.INVALID_REQUEST, ProviderErrorKind.TIMEOUT, ProviderErrorKind.UNAVAILABLE}:
                    break
            except Exception as exc:
                last_error = ProviderError(ProviderErrorKind.UNKNOWN, str(exc), provider)
                self._keys.failure(state, last_error.kind)
        assert last_error is not None
        raise last_error


class GeminiVisionProvider:
    def __init__(self, keys: RoundRobinKeyPool, model: str, timeout_seconds: float = 30.0) -> None:
        self._keys = keys
        self._model = model
        self._transport = JsonTransport(timeout_seconds)

    def propose(self, image: VisionImage, prompt: str) -> VisualSolution:
        payload = {
            "contents": [{"role": "user", "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": image.mime_type, "data": base64.b64encode(image.data).decode("ascii")}},
            ]}],
            "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": _schema()},
        }
        return self._request(payload)

    def _request(self, payload: dict[str, Any]) -> VisualSolution:
        last_error: ProviderError | None = None
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent"
        for state in self._keys.round_keys():
            try:
                data = self._transport.post("gemini", url, {"x-goog-api-key": state.key, "Content-Type": "application/json"}, payload)
                proposal = VisualSolution.model_validate(json_object(gemini_text(data)))
                self._keys.success(state)
                return proposal
            except ProviderError as exc:
                last_error = exc
                self._keys.failure(state, exc.kind)
                if exc.kind in {ProviderErrorKind.INVALID_REQUEST, ProviderErrorKind.TIMEOUT, ProviderErrorKind.UNAVAILABLE}:
                    break
            except Exception as exc:
                last_error = ProviderError(ProviderErrorKind.UNKNOWN, str(exc), "gemini")
                self._keys.failure(state, last_error.kind)
        assert last_error is not None
        raise last_error


class OpenRouterVisionProvider:
    def __init__(self, keys: RoundRobinKeyPool, model: str, timeout_seconds: float = 30.0) -> None:
        self._keys = keys
        self._model = model
        self._transport = JsonTransport(timeout_seconds)

    def propose(self, image: VisionImage, prompt: str) -> VisualSolution:
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": _data_url(image)}},
            ]}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "recovery_proposal", "strict": True, "schema": _schema()}},
            "temperature": 0,
        }
        return self._request(payload)

    def _request(self, payload: dict[str, Any]) -> VisualSolution:
        last_error: ProviderError | None = None
        for state in self._keys.round_keys():
            try:
                data = self._transport.post("openrouter", "https://openrouter.ai/api/v1/chat/completions", {"Authorization": f"Bearer {state.key}", "Content-Type": "application/json"}, payload)
                proposal = VisualSolution.model_validate(json_object(chat_completion_text(data)))
                self._keys.success(state)
                return proposal
            except ProviderError as exc:
                last_error = exc
                self._keys.failure(state, exc.kind)
                if exc.kind in {ProviderErrorKind.INVALID_REQUEST, ProviderErrorKind.TIMEOUT, ProviderErrorKind.UNAVAILABLE}:
                    break
            except Exception as exc:
                last_error = ProviderError(ProviderErrorKind.UNKNOWN, str(exc), "openrouter")
                self._keys.failure(state, last_error.kind)
        assert last_error is not None
        raise last_error


class GroqVisionProvider:
    def __init__(self, keys: RoundRobinKeyPool, model: str, timeout_seconds: float = 30.0) -> None:
        self._keys = keys
        self._model = model
        self._transport = JsonTransport(timeout_seconds)

    def propose(self, image: VisionImage, prompt: str) -> VisualSolution:
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": _data_url(image)}},
            ]}],
            "response_format": {"type": "json_object"},
            "reasoning_format": "hidden",
            "temperature": 0.2,
            "max_completion_tokens": 1000,
        }
        return self._request(payload)

    def _request(self, payload: dict[str, Any]) -> VisualSolution:
        last_error: ProviderError | None = None
        for state in self._keys.round_keys():
            try:
                data = self._transport.post("groq", "https://api.groq.com/openai/v1/chat/completions", {"Authorization": f"Bearer {state.key}", "Content-Type": "application/json"}, payload)
                proposal = VisualSolution.model_validate(json_object(chat_completion_text(data)))
                self._keys.success(state)
                return proposal
            except ProviderError as exc:
                last_error = exc
                self._keys.failure(state, exc.kind)
                if exc.kind in {ProviderErrorKind.INVALID_REQUEST, ProviderErrorKind.TIMEOUT, ProviderErrorKind.UNAVAILABLE}:
                    break
            except Exception as exc:
                last_error = ProviderError(ProviderErrorKind.UNKNOWN, str(exc), "groq")
                self._keys.failure(state, last_error.kind)
        assert last_error is not None
        raise last_error


class DeepSeekVisionProvider(OpenRouterVisionProvider):
    """DeepSeek's OpenAI-compatible endpoint, used only after other tiers fail."""

    def _request(self, payload: dict[str, Any]) -> VisualSolution:
        last_error: ProviderError | None = None
        for state in self._keys.round_keys():
            try:
                data = self._transport.post(
                    "deepseek", "https://api.deepseek.com/chat/completions",
                    {"Authorization": f"Bearer {state.key}", "Content-Type": "application/json"}, payload,
                )
                solution = VisualSolution.model_validate(json_object(chat_completion_text(data)))
                self._keys.success(state)
                return solution
            except ProviderError as exc:
                last_error = exc
                self._keys.failure(state, exc.kind)
                if exc.kind in {ProviderErrorKind.INVALID_REQUEST, ProviderErrorKind.TIMEOUT, ProviderErrorKind.UNAVAILABLE}:
                    break
            except Exception as exc:
                last_error = ProviderError(ProviderErrorKind.UNKNOWN, str(exc), "deepseek")
                self._keys.failure(state, last_error.kind)
        assert last_error is not None
        raise last_error
