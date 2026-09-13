# pyrefly: ignore [missing-import]
"""Backend-only LLM client.

A tiny OpenAI-compatible /chat/completions client used to power the AI career
recommendations. The API key is read from the backend environment ONLY (never
from the frontend) and is never returned by any endpoint.

Only generic, well-supported parameters are sent so that any OpenAI-compatible
provider (OpenAI, Azure OpenAI, local servers, etc.) works. Responses are
expected to be JSON; a lenient JSON extractor handles markdown fencing some
models add.
"""
import json
import os
import re
from typing import Any, Dict, Optional

import httpx


class LLMError(Exception):
    """Raised when an LLM call cannot be completed."""


class LLMNotConfigured(LLMError):
    """Raised when no API key is configured for the LLM provider."""


# ---------------------------------------------------------------------------
# Configuration (always read fresh so tests can override per-call)
# ---------------------------------------------------------------------------

def llm_settings() -> Dict[str, str]:
    """Return the LLM provider settings from environment variables."""
    return {
        "api_key": os.getenv("LLM_API_KEY", ""),
        "base_url": os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
        "timeout": os.getenv("LLM_TIMEOUT", "60"),
    }


def _timeout_seconds(settings: Dict[str, str]) -> float:
    try:
        return float(settings["timeout"])
    except (TypeError, ValueError):
        return 60.0


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> Dict[str, Any]:
    """Parse JSON out of an LLM response, tolerating markdown fences and prose."""
    if not text or not text.strip():
        raise LLMError("LLM returned an empty response.")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # Last resort: capture everything between the first '{' and last '}'.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM returned invalid JSON: {exc}") from exc
    raise LLMError("LLM response did not contain a JSON object.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_text(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.7,
) -> str:
    """Call the configured LLM and return the raw text reply.

    Used for free-form (conversational) output such as the RAG chatbot. Shares
    the exact configuration, error handling and payload shape of
    ``generate_json`` but returns the model's raw ``content`` verbatim instead
    of JSON-extracting it.

    Raises LLMNotConfigured when LLM_API_KEY is missing, and LLMError for any
    network/HTTP problem. Callers are expected to catch these and fall back
    gracefully.
    """
    settings = llm_settings()
    if not settings["api_key"]:
        raise LLMNotConfigured(
            "LLM_API_KEY is not set. Add it to backend/.env. "
            "The key is only ever used server-side and must never be exposed "
            "to the frontend."
        )

    url = f"{settings['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings['api_key']}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": settings["model"],
        "temperature": temperature,
        "messages": [
            {
                "role": "system",
                "content": system or "You are a helpful assistant.",
            },
            {"role": "user", "content": prompt},
        ],
    }

    try:
        with httpx.Client(timeout=_timeout_seconds(settings)) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMError(
            f"LLM API returned HTTP {exc.response.status_code}: "
            f"{exc.response.text[:500]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"LLM API request failed: {exc}") from exc

    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LLMError("LLM response was missing choices[0].message.content.") from exc

    return content


def generate_json(prompt: str, system: Optional[str] = None) -> Dict[str, Any]:
    """Call the configured LLM and return a parsed JSON object.

    Raises LLMNotConfigured when LLM_API_KEY is missing, and LLMError for any
    network/HTTP/parse problem. Callers are expected to catch these and fall
    back gracefully.
    """
    settings = llm_settings()
    if not settings["api_key"]:
        raise LLMNotConfigured(
            "LLM_API_KEY is not set. Add it to backend/.env. "
            "The key is only ever used server-side and must never be exposed "
            "to the frontend."
        )

    url = f"{settings['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings['api_key']}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": settings["model"],
        "temperature": 0.7,
        "messages": [
            {
                "role": "system",
                "content": system or "You are a helpful assistant. Reply in JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
    }

    try:
        with httpx.Client(timeout=_timeout_seconds(settings)) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMError(
            f"LLM API returned HTTP {exc.response.status_code}: "
            f"{exc.response.text[:500]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"LLM API request failed: {exc}") from exc

    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LLMError("LLM response was missing choices[0].message.content.") from exc

    return _extract_json(content)