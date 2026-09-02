"""Provider strategies for AI-assisted tax-rate research."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .guidance_diagnostics import log_http_failure, log_sdk_failure, print_request, print_response
from .models import ReportError
from .settings import gemini_api_key, gemini_model, openai_api_key, openai_model, openrouter_api_key, openrouter_model

PROVIDER_OPTIONS = (
    ("openai", "ChatGPT / OpenAI API"),
    ("gemini", "Google Gemini API"),
    ("openrouter", "OpenRouter API"),
)


def provider_label(provider_id: str) -> str:
    """Return the user-facing name for an AI provider."""
    return dict(PROVIDER_OPTIONS).get(provider_id, "AI")


class TaxGuidanceProvider(ABC):
    """Contract for a provider that can return tax-rate research."""

    provider_id: str
    config_key: str

    @property
    def label(self) -> str:
        return provider_label(self.provider_id)

    @abstractmethod
    def request(self, prompt: str) -> str:
        """Return source-backed guidance for a provider-neutral prompt."""


class HttpJsonTaxGuidanceProvider(TaxGuidanceProvider):
    """Shared transport and error handling for JSON-over-HTTP providers."""

    def _post_json(self, endpoint: str, request_body: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
        request = Request(endpoint, data=json.dumps(request_body).encode(), headers=headers)
        print_request(self.label, endpoint, request_body, headers)
        try:
            with urlopen(request, timeout=30) as response:
                body = json.loads(response.read())
                if not isinstance(body, dict):
                    raise ReportError(f"{self.label} returned an unexpected response.")
                print_response(self.label, body)
                return body
        except HTTPError as exc:
            log_http_failure(self.label, f"HTTP {exc.code}", endpoint, request_body, headers)
            raise _http_error(self.label, self.config_key, exc.code) from exc
        except URLError as exc:
            log_http_failure(self.label, str(exc.reason), endpoint, request_body, headers)
            raise ReportError(f"{self.label} rate guidance is unavailable. Check your internet connection.") from exc


class OpenAITaxGuidanceProvider(HttpJsonTaxGuidanceProvider):
    """OpenAI Responses API implementation with built-in web search."""

    provider_id = "openai"
    config_key = "openai_api_key"

    def request(self, prompt: str) -> str:
        api_key = os.environ.get("OPENAI_API_KEY") or openai_api_key()
        if not api_key:
            raise ReportError("Add openai_api_key to config.local.json before requesting OpenAI rate guidance.")
        request_body = {
            "model": openai_model(),
            "input": prompt,
            "tools": [{"type": "web_search"}],
            "store": False,
            "text": {"verbosity": "low"},
        }
        body = self._post_json(
            "https://api.openai.com/v1/responses",
            request_body,
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        return str(body.get("output_text") or "OpenAI returned no tax-rate guidance.")


class GeminiTaxGuidanceProvider(TaxGuidanceProvider):
    """Google GenAI SDK implementation with Google Search grounding."""

    provider_id = "gemini"
    config_key = "gemini_api_key"

    def request(self, prompt: str) -> str:
        api_key = os.environ.get("GEMINI_API_KEY") or gemini_api_key()
        if not api_key:
            raise ReportError("Add gemini_api_key to config.local.json before requesting Gemini rate guidance.")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ReportError("Google GenAI SDK is not installed. Run setup.command, then restart the app.") from exc

        request_body = {
            "model": gemini_model(),
            "contents": prompt,
            "config": {"tools": [{"google_search": {}}]},
        }
        try:
            print_request(self.label, "google-genai SDK generate_content", request_body, {"x-goog-api-key": api_key})
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=request_body["model"],
                contents=request_body["contents"],
                config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
            )
            body = _sdk_response_json(response)
            print_response(self.label, body)
        except Exception as exc:
            log_sdk_failure(self.label, exc, request_body)
            raise ReportError("Google Gemini API rate guidance could not be requested. See the terminal for details.") from exc
        return parse_gemini_response(body)


class OpenRouterTaxGuidanceProvider(HttpJsonTaxGuidanceProvider):
    """OpenRouter chat-completions implementation with server-side web search."""

    provider_id = "openrouter"
    config_key = "openrouter_api_key"

    def request(self, prompt: str) -> str:
        api_key = os.environ.get("OPENROUTER_API_KEY") or openrouter_api_key()
        if not api_key:
            raise ReportError("Add openrouter_api_key to config.local.json before requesting OpenRouter rate guidance.")
        request_body = {
            "model": openrouter_model(),
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"type": "openrouter:web_search"}],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://127.0.0.1",
            "X-Title": "Capital Gain Estimate Tax Calculator",
        }
        return parse_openrouter_response(self._post_json("https://openrouter.ai/api/v1/chat/completions", request_body, headers))


def default_providers() -> tuple[TaxGuidanceProvider, ...]:
    """Build the default provider registry used by the application service."""
    return OpenAITaxGuidanceProvider(), GeminiTaxGuidanceProvider(), OpenRouterTaxGuidanceProvider()


def parse_gemini_response(body: dict[str, object]) -> str:
    """Extract the JSON text returned by Gemini."""
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        return "Gemini returned no tax-rate guidance."
    content = candidates[0].get("content")
    parts = content.get("parts", []) if isinstance(content, dict) else []
    text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
    return text or "Gemini returned no tax-rate guidance."


def parse_openrouter_response(body: dict[str, object]) -> str:
    """Extract the JSON text returned by OpenRouter."""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return "OpenRouter returned no tax-rate guidance."
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return "OpenRouter returned no tax-rate guidance."
    text = str(message.get("content") or "").strip()
    return text or "OpenRouter returned no tax-rate guidance."


def _http_error(label: str, config_key: str, status: int) -> ReportError:
    if status in (401, 403):
        return ReportError(f"{label} authentication failed. Check {config_key} in config.local.json and try again.")
    if status == 429:
        return ReportError(f"{label} rate guidance is temporarily unavailable because the API rate limit was reached. Try again later.")
    return ReportError(f"{label} tax-rate guidance could not be requested (HTTP {status}). Try again later.")


def _sdk_response_json(response: object) -> dict[str, object]:
    """Convert a Google GenAI SDK response to printable API-shaped JSON."""
    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        body = model_dump(by_alias=True, mode="json")
        return body if isinstance(body, dict) else {"response": body}
    return {"text": str(getattr(response, "text", ""))}
