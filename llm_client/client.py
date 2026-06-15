"""Chat client for OpenAI-compatible and Anthropic Messages endpoints.

Single-purpose: send a (system, user) prompt, get back text or parsed JSON.
No retries, no caching, no batching — those live in higher layers if needed.

Configuration is read from environment variables when constructor args are
omitted:

    OPENAI_API_KEY        / ANTHROPIC_AUTH_TOKEN
    OPENAI_BASE_URL       / ANTHROPIC_BASE_URL
    OPENAI_MODEL          / ANTHROPIC_MODEL
    OPENAI_API_TYPE       / ANTHROPIC_API_TYPE      ("openai" | "anthropic")
    ANTHROPIC_VERSION                                (default: "2023-06-01")

The API type is auto-detected from the base URL if not explicitly set
(``.../v1/messages`` → ``anthropic``, otherwise ``openai``).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


class ChatClient:
    """Send chat requests to an OpenAI-compatible or Anthropic endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_type: str | None = None,
        timeout_sec: int = 120,
    ) -> None:
        self.api_key = (
            api_key
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or ""
        )
        self.base_url = (
            base_url
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("ANTHROPIC_BASE_URL")
            or ""
        ).rstrip("/")
        self.model = (
            model
            or os.environ.get("OPENAI_MODEL")
            or os.environ.get("ANTHROPIC_MODEL")
            or ""
        )
        self.api_type = (api_type or self._detect_api_type()).lower()
        if self.api_type not in {"openai", "anthropic"}:
            raise ValueError(
                f"api_type must be 'openai' or 'anthropic', got {self.api_type!r}"
            )
        self.timeout_sec = timeout_sec
        self.last_usage_tokens: int = 0
        # Bypass any HTTP(S) proxy that might mangle the request.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # ------------------------------------------------------------------ API

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 2400,
        temperature: float = 0.0,
    ) -> str:
        """Send a chat request and return the assistant's text content."""

        self._require_configured()
        if self.api_type == "anthropic":
            return self._anthropic(system=system, user=user, max_tokens=max_tokens, temperature=temperature)
        return self._openai(system=system, user=user, max_tokens=max_tokens, temperature=temperature)

    def chat_json(
        self,
        system: str,
        user: str,
        max_tokens: int = 2400,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Send a chat request and return the parsed JSON object."""

        content = self.chat(system=system, user=user, max_tokens=max_tokens, temperature=temperature)
        parsed = self._parse_json(content)
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Expected JSON object, got {type(parsed).__name__}: {content[:500]}"
            )
        return parsed

    # ----------------------------------------------------------- Transport

    def _openai(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        thinking_type = os.environ.get("OPENAI_THINKING_TYPE")
        if thinking_type:
            payload["thinking"] = {"type": thinking_type}

        body = self._post(
            url=self._openai_chat_url(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
        )
        usage = body.get("usage") or {}
        self.last_usage_tokens = int(usage.get("total_tokens", 0) or 0)
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Unexpected OpenAI response shape: {str(body)[:500]}") from exc

    def _anthropic(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        body = self._post(
            url=self._anthropic_messages_url(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "x-api-key": self.api_key,
                "anthropic-version": os.environ.get("ANTHROPIC_VERSION", "2023-06-01"),
                "Content-Type": "application/json",
            },
            payload=payload,
        )
        usage = body.get("usage") or {}
        if usage:
            self.last_usage_tokens = int(usage.get("input_tokens", 0) or 0) + int(
                usage.get("output_tokens", 0) or 0
            )
        return self._anthropic_text(body)

    def _post(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=self.timeout_sec) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000] if exc.fp else ""
            raise RuntimeError(
                f"LLM HTTP {exc.code} from {url}: {exc.reason}. Body: {detail}"
            ) from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            raise RuntimeError(f"LLM request to {url} failed: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM response was not JSON: {raw[:500]}") from exc

    # --------------------------------------------------------- URL helpers

    def _openai_chat_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _anthropic_messages_url(self) -> str:
        if self.base_url.endswith("/v1/messages") or self.base_url.endswith("/messages"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"

    def _detect_api_type(self) -> str:
        explicit = (
            os.environ.get("OPENAI_API_TYPE")
            or os.environ.get("ANTHROPIC_API_TYPE")
            or os.environ.get("LLM_API_TYPE")
            or ""
        ).lower()
        if explicit in {"openai", "openai-compatible", "chat-completions"}:
            return "openai"
        if explicit in {"anthropic", "messages"}:
            return "anthropic"
        if self.base_url.endswith("/v1/messages") or self.base_url.endswith("/messages"):
            return "anthropic"
        return "openai"

    # ----------------------------------------------------------- Parsing

    @staticmethod
    def _anthropic_text(body: dict[str, Any]) -> str:
        content = body.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if isinstance(text, str):
                        parts.append(text)
            if parts:
                return "\n".join(parts)
        raise ValueError(f"Anthropic response missing text content: {str(body)[:500]}")

    @staticmethod
    def _parse_json(content: str) -> Any:
        """Extract a JSON value from raw LLM output.

        Accepts:
        - Raw JSON
        - Fenced code blocks (``` or ```json)
        - JSON embedded in prose (takes the largest balanced {...} or [...] span)
        """

        text = content.strip()
        # 1) Direct parse.
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2) Fenced block.
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            try:
                return json.loads(fenced.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 3) Largest balanced object or array.
        candidate = _extract_largest_balanced(text, "{", "}") or _extract_largest_balanced(text, "[", "]")
        if candidate is not None:
            return json.loads(candidate)

        raise ValueError(f"No JSON found in LLM response: {text[:500]}")

    # ----------------------------------------------------------- Internals

    def _require_configured(self) -> None:
        if not self.available:
            raise RuntimeError(
                "ChatClient is not configured. Set api_key/base_url/model "
                "via constructor args or environment variables "
                "(OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL)."
            )


def _extract_largest_balanced(text: str, open_char: str, close_char: str) -> str | None:
    """Return the longest substring of ``text`` that is a balanced
    ``open_char...close_char`` pair, or ``None`` if no such pair exists.

    Ignores braces that appear inside string literals (basic JSON-style
    handling: respects ``"..."`` with backslash escapes).
    """

    start = text.find(open_char)
    if start == -1:
        return None
    best: str | None = None
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == open_char:
                depth += 1
            elif ch == close_char:
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    if best is None or len(candidate) > len(best):
                        best = candidate
                    break
        start = text.find(open_char, start + 1)
    return best
