"""OpenRouter LLM client — stdlib only, fails closed, privacy-safe logging.

Sends chat-completion requests to OpenRouter. The API key is read ONLY from the
OPENROUTER_API_KEY environment variable — never hardcoded, never persisted.

Privacy note: this transmits whatever text you pass to OpenRouter's servers, and
free models may log/train on prompts. Callers decide what (if anything) to send.

Logging here records model name, message/character counts, and latency only —
never the prompt or response text — so conversation content can't leak into logs.
"""

import json
import os
import time
import socket
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ENV_KEY = "OPENROUTER_API_KEY"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash:free"

# Sent so OpenRouter can attribute traffic; harmless, no PII.
_REFERER = "https://github.com/local/gemini-analyzer"
_TITLE = "GeminiAnalyzer"


@dataclass
class LLMResult:
    """Standardized result. Mirrors the dict-return convention used elsewhere."""
    success: bool
    text: str = ""
    error: Optional[str] = None
    model: str = ""
    latency_ms: int = 0
    raw: dict = field(default_factory=dict)


def get_api_key() -> Optional[str]:
    key = os.environ.get(ENV_KEY, "").strip()
    return key or None


def is_available() -> bool:
    """True if an API key is present. Lets the UI gray out cloud features."""
    return get_api_key() is not None


class LLMClient:
    """Thin OpenRouter chat client. One instance per app is fine."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        fallback_models: Optional[list[str]] = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout: int = 60,
    ) -> None:
        self.model = model
        self.fallback_models = list(fallback_models or [])
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    # ── public API ──────────────────────────────────────────────────

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResult:
        """Single-prompt convenience wrapper."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)

    def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResult:
        """Call OpenRouter. Tries primary model then fallbacks. Fails CLOSED.

        Returns LLMResult(success=False, error=...) on any failure — never raises,
        never silently returns a fake answer.
        """
        key = get_api_key()
        if not key:
            return LLMResult(
                success=False,
                error=f"No API key. Set the {ENV_KEY} environment variable to use cloud LLM features.",
            )

        if not messages:
            return LLMResult(success=False, error="No messages to send.")

        models_to_try = [model or self.model] + self.fallback_models
        # de-dupe while preserving order
        seen: set[str] = set()
        models_to_try = [m for m in models_to_try if m and not (m in seen or seen.add(m))]

        char_count = sum(len(m.get("content", "")) for m in messages)
        last_error = "unknown error"

        for candidate in models_to_try:
            result = self._post_once(
                key=key,
                model=candidate,
                messages=messages,
                temperature=self.temperature if temperature is None else temperature,
                max_tokens=self.max_tokens if max_tokens is None else max_tokens,
                char_count=char_count,
            )
            if result.success:
                return result
            last_error = result.error or last_error
            logger.warning(
                "LLM model %s failed (%d chars in): %s — trying next",
                candidate, char_count, last_error,
            )

        return LLMResult(success=False, error=last_error, model=models_to_try[0])

    # ── internals ───────────────────────────────────────────────────

    def _post_once(
        self,
        key: str,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        char_count: int,
    ) -> LLMResult:
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")

        req = urllib.request.Request(
            OPENROUTER_URL,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": _REFERER,
                "X-Title": _TITLE,
            },
        )

        start = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            latency_ms = int((time.time() - start) * 1000)
        except urllib.error.HTTPError as e:
            detail = self._read_http_error(e)
            return LLMResult(success=False, error=f"HTTP {e.code}: {detail}", model=model)
        except (TimeoutError, socket.timeout):
            return LLMResult(success=False, error=f"Timed out after {self.timeout}s", model=model)
        except urllib.error.URLError as e:
            return LLMResult(success=False, error=f"Network error: {e.reason}", model=model)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return LLMResult(success=False, error="Malformed JSON response from OpenRouter", model=model)

        text = self._extract_text(data)
        if text is None:
            api_err = data.get("error", {})
            msg = api_err.get("message") if isinstance(api_err, dict) else str(api_err)
            return LLMResult(success=False, error=msg or "No choices in response", model=model, raw=data)

        # PII-safe: log counts + latency only, never the text.
        logger.info(
            "LLM ok model=%s in_chars=%d out_chars=%d latency_ms=%d",
            model, char_count, len(text), latency_ms,
        )
        return LLMResult(success=True, text=text, model=model, latency_ms=latency_ms, raw=data)

    @staticmethod
    def _extract_text(data: dict) -> Optional[str]:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        msg = choices[0].get("message", {})
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        # Some providers return content as a list of parts.
        if isinstance(content, list):
            parts = [p.get("text", "") for p in content if isinstance(p, dict)]
            return "\n".join(parts).strip()
        return None

    @staticmethod
    def _read_http_error(e: urllib.error.HTTPError) -> str:
        try:
            body = e.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            err = data.get("error", {})
            if isinstance(err, dict):
                return err.get("message", body[:200])
            return str(err)[:200]
        except (json.JSONDecodeError, OSError, UnicodeError) as parse_err:
            logger.debug("Could not parse HTTP error body: %s", parse_err)
            return getattr(e, "reason", "request failed")
