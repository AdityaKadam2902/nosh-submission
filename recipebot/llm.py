"""Gemini wrapper (ARCHITECTURE §10): disk cache, exponential backoff on 429/5xx, hard timeout, request counter, LLM-down handling.
The model comes from env GEMINI_MODEL. Tests inject `backend`; production uses GeminiBackend (google-genai, imported lazily)."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from pathlib import Path

from pydantic import BaseModel, ValidationError

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

LLM_DOWN_MESSAGE = "LLM unavailable, use /search /stats /match /sub"
RETRY_CODES = {429, 500, 502, 503, 504}


class LLMUnavailable(Exception):
    """Network/quota/auth/config failure after retries (caller falls back to code templates / slash commands)."""


class LLMBadOutput(LLMUnavailable):
    """Model replied but not with schema-valid JSON, even after one re-ask."""


class GeminiBackend:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._client = None

    def __call__(self, model: str, prompt: str, system: str | None, schema, timeout_s: float) -> str:
        if not self.api_key:
            raise LLMUnavailable("GEMINI_API_KEY is not set (.env)")
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise LLMUnavailable(f"google-genai not installed: {e}") from e
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key, http_options=types.HttpOptions(
                api_version=os.environ.get("GEMINI_API_VERSION", "v1beta"), timeout=int(timeout_s * 1000)))
        cfg = {"temperature": 0, "system_instruction": system}
        if schema is not None:
            cfg.update(response_mime_type="application/json", response_schema=schema)
        resp = self._client.models.generate_content(model=model, contents=prompt, config=types.GenerateContentConfig(**cfg))
        return resp.text or ""


def _status(exc: Exception):
    for attr in ("code", "status_code", "status"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    return None


class LLM:
    def __init__(self, model: str | None = None, backend=None, cache_dir: str | Path | None = ".cache/llm", timeout_s: float | None = None,
                 max_retries: int = 5, base_delay: float = 2.0, max_calls: int = 300, sleep=time.sleep, jitter: bool = True,
                 fallback_model: str | None = None, min_interval: float | None = None):
        self.model = model or os.environ.get("GEMINI_MODEL")
        self.fallback_model = (os.environ.get("GEMINI_FALLBACK_MODEL") or None) if fallback_model is None else (fallback_model or None)
        self.min_interval = float(os.environ.get("LLM_MIN_INTERVAL_S", 0)) if min_interval is None else min_interval
        timeout_s = float(os.environ.get("LLM_TIMEOUT_S", 60)) if timeout_s is None else timeout_s
        self._last_call_at = 0.0
        self.last_error: str | None = None
        self.fallbacks_used = 0
        self.backend = backend or GeminiBackend()
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout_s, self.max_retries, self.base_delay = timeout_s, max_retries, base_delay
        self.max_calls, self.sleep, self.jitter = max_calls, sleep, jitter
        self.calls = self.cache_hits = self.retries = self.failures = 0

    # ---- cache ----
    def _key(self, kind: str, prompt: str, system: str | None, schema) -> str:
        sch = json.dumps(schema.model_json_schema(), sort_keys=True) if schema is not None else ""
        return hashlib.sha256("\x1f".join([str(self.model), kind, system or "", prompt, sch]).encode()).hexdigest()

    def _cache_get(self, key: str):
        if self.cache_dir and (p := self.cache_dir / f"{key}.json").exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))["text"]
            except (OSError, ValueError, KeyError):
                return None
        return None

    def _cache_put(self, key: str, text: str) -> None:
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{key}.json").write_text(json.dumps({"model": self.model, "text": text}), encoding="utf-8")

    # ---- raw call with backoff ----
    def _call(self, prompt: str, system: str | None, schema) -> str:
        try:
            return self._call_with(self.model, prompt, system, schema)
        except LLMUnavailable as e:
            if getattr(e, "retryable", False) and self.fallback_model and self.fallback_model != self.model:
                self.fallbacks_used += 1
                return self._call_with(self.fallback_model, prompt, system, schema)
            raise

    def _call_with(self, model: str | None, prompt: str, system: str | None, schema) -> str:
        if not model:
            raise LLMUnavailable("GEMINI_MODEL is not set (.env)")
        last = None
        max_retries = 1 if (self.fallback_model and model == self.model) else self.max_retries
        for attempt in range(max_retries + 1):
            if self.calls >= self.max_calls:
                raise LLMUnavailable(f"request budget exceeded ({self.max_calls})")
            self.calls += 1
            if self.min_interval:
                wait = self.min_interval - (time.monotonic() - self._last_call_at)
                if wait > 0:
                    self.sleep(wait)
            self._last_call_at = time.monotonic()
            try:
                return self.backend(model, prompt, system, schema, self.timeout_s)
            except LLMUnavailable as e:
                self.failures += 1
                self.last_error = str(e)
                raise
            except Exception as e:  # noqa: BLE001 - classify below
                last, code = e, _status(e)
                retryable = code in RETRY_CODES or isinstance(e, (TimeoutError, ConnectionError)) or (code is None and "timed out" in str(e).lower())
                if not retryable or attempt == max_retries:
                    self.failures += 1
                    err = LLMUnavailable(f"{model}: {type(e).__name__}{f' ({code})' if code else ''}: {str(e)[:700]}")
                    err.retryable = retryable
                    self.last_error = str(err)
                    raise err from e
                self.retries += 1
                delay = min(self.base_delay * 2 ** attempt, 20.0)
                self.sleep(delay * (random.uniform(0.5, 1.0) if self.jitter else 1.0))
        raise LLMUnavailable(str(last))  # pragma: no cover

    # ---- public ----
    def generate_text(self, prompt: str, system: str | None = None, cache: bool = True) -> str:
        key = self._key("text", prompt, system, None)
        if cache and (hit := self._cache_get(key)) is not None:
            self.cache_hits += 1
            return hit
        text = self._call(prompt, system, None).strip()
        if cache:
            self._cache_put(key, text)
        return text

    def generate_json(self, prompt: str, schema: type[BaseModel], system: str | None = None, cache: bool = True) -> BaseModel:
        key = self._key("json", prompt, system, schema)
        if cache and (hit := self._cache_get(key)) is not None:
            try:
                out = schema.model_validate_json(hit)
                self.cache_hits += 1
                return out
            except ValidationError:
                pass
        text, err = self._call(prompt, system, schema), None
        for attempt in range(2):  # original + ONE re-ask
            try:
                out = schema.model_validate_json(_strip_fences(text))
                if cache:
                    self._cache_put(key, out.model_dump_json())
                return out
            except ValidationError as e:
                err = e
                if attempt == 0:
                    text = self._call(prompt + "\n\nYour previous reply was not valid JSON for the schema. Reply with ONLY the JSON object.", system, schema)
        raise LLMBadOutput(f"invalid JSON for {schema.__name__}: {str(err)[:200]}")


def _strip_fences(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    return m.group(1) if m else t
