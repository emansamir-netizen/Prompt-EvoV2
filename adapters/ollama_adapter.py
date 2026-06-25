"""
adapters/ollama_adapter.py
─────────────────────────────────────────────────────────────────────────────
Ollama Target Adapter — Local / Air-Gapped Model Support

Enables PromptEvo to audit locally-hosted open-weights models via the
Ollama HTTP API (http://localhost:11434 by default).  No API keys required.

Configuration (all knobs are plain env vars read in config.py / main.py and
passed explicitly to the constructor — this file has no hidden magic)::

    TARGET_PROVIDER=ollama
    TARGET_MODEL=llama3.2:1b
    OLLAMA_BASE_URL=http://localhost:11434

    # Timeouts ─ fine-grained (preferred)
    OLLAMA_CONNECT_TIMEOUT_SECONDS=10
    OLLAMA_READ_TIMEOUT_SECONDS=300
    OLLAMA_TIMEOUT_SECONDS=300       # aggregate fallback

    # Retries & budgets
    OLLAMA_MAX_RETRIES=2
    OLLAMA_MAX_PROMPT_CHARS=24000    # safety guard against pathological input
    OLLAMA_TRUNCATE_PROMPT=true      # truncate instead of failing
    OLLAMA_NUM_PREDICT=512           # cap response length
    OLLAMA_NUM_CTX=4096              # Ollama context window
    OLLAMA_KEEP_ALIVE=10m            # keep model resident between calls
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from adapters.base_adapter import (
    AdapterAuthError,
    AdapterContextLengthError,
    AdapterError,
    AdapterResponse,
    AdapterTimeoutError,
    BaseTargetAdapter,
)
from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# OLLAMA MESSAGE FORMATTER
# ─────────────────────────────────────────────────────────────────────────────

def _format_messages_for_ollama(messages: list[BaseMessage]) -> list[dict[str, str]]:
    """Convert LangChain ``BaseMessage`` objects to the Ollama chat format."""
    role_map = {
        "system":    "system",
        "human":     "user",
        "user":      "user",
        "ai":        "assistant",
        "assistant": "assistant",
    }
    formatted: list[dict[str, str]] = []
    for msg in messages:
        role = role_map.get(
            getattr(msg, "type", "") or getattr(msg, "role", "user"),
            "user",
        )
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if content.strip():
            formatted.append({"role": role, "content": content})
    return formatted


def _total_prompt_chars(messages: list[dict[str, str]]) -> int:
    return sum(len(m.get("content", "")) for m in messages)


def _prompt_preview(messages: list[dict[str, str]], limit: int = 200) -> str:
    """Return a compact single-line preview of the final user message."""
    for m in reversed(messages):
        if m.get("role") == "user" and m.get("content"):
            txt = m["content"].replace("\n", " ").strip()
            return (txt[:limit] + "…") if len(txt) > limit else txt
    if messages:
        txt = (messages[-1].get("content") or "").replace("\n", " ").strip()
        return (txt[:limit] + "…") if len(txt) > limit else txt
    return "<empty>"


# ─────────────────────────────────────────────────────────────────────────────
# OLLAMA TARGET ADAPTER
# ─────────────────────────────────────────────────────────────────────────────

class OllamaTargetAdapter(BaseTargetAdapter):
    """Target adapter that communicates with a local Ollama instance via HTTP.

    Splits connect vs read timeout so a warm Ollama that is merely *slow*
    to generate (CPU-bound local inference) doesn't look like a network
    failure. Logs prompt size + preview on every call for observability.
    """

    def __init__(
        self,
        model:              str   = "llama3",
        base_url:           str   = "http://localhost:11434",
        timeout:            float = 300.0,
        connect_timeout:    float = 10.0,
        read_timeout:       float | None = None,
        max_retries:        int   = 2,
        temperature:        float = 0.8,
        context_length:     int   | None = 8192,
        num_predict:        int   = 2048,
        keep_alive:         str   | None = "10m",
        max_prompt_chars:   int   = 24000,
        truncate_prompt:    bool  = True,
    ) -> None:
        super().__init__(timeout=timeout, max_retries=max_retries)
        self._model            = model
        self._base_url         = base_url.rstrip("/")
        self._temperature      = temperature
        self._context_length   = context_length
        # Ollama's server default for num_predict is 128 tokens, which silently
        # truncates anything longer than ~100 words. We force a generous floor
        # so the judge never sees a chopped response.
        self._num_predict      = max(512, int(num_predict))
        # Ollama's keep_alive accepts either a Go duration string ("10m", "1h")
        # or a bare integer of seconds, where a negative value (e.g. -1) means
        # "keep the model loaded forever". That sentinel ONLY works as a JSON
        # number — sent as the string "-1" Ollama's duration parser rejects it
        # with: time: missing unit in duration "-1". So coerce integer-like
        # values (including "-1") to an int and leave real duration strings be.
        self._keep_alive       = self._coerce_keep_alive(keep_alive)
        self._max_prompt_chars = max(1000, int(max_prompt_chars))
        self._truncate_prompt  = truncate_prompt
        self._connect_timeout  = float(connect_timeout)
        self._read_timeout     = float(read_timeout if read_timeout is not None else timeout)
        self._chat_url         = f"{self._base_url}/api/chat"
        self._tags_url         = f"{self._base_url}/api/tags"
        self._call_count       = 0

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _coerce_keep_alive(value: Any) -> Any:
        """Normalize keep_alive so the negative-int 'forever' sentinel works.

        Ollama parses a string keep_alive as a Go duration (needs a unit), but
        accepts a JSON integer as seconds (negative = keep loaded forever).
        A bare "-1" / "0" string is therefore invalid; coerce such integer-like
        strings to int. Real duration strings ("10m") and None pass through.
        """
        if value is None or isinstance(value, (int, float)):
            return value
        s = str(value).strip()
        try:
            return int(s)
        except ValueError:
            return s

    # ── Metadata ──────────────────────────────────────────────────────────

    def get_model_id(self) -> str:
        return f"ollama/{self._model}"

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "multimodal":       False,
            "streaming":        True,
            "system_prompt":    True,
            "function_calling": False,
            "json_mode":        False,
        }

    # ── Preflight ─────────────────────────────────────────────────────────

    def _check_ollama_available(self) -> None:
        """Verify server reachable AND the requested model is pulled.

        Fatal errors raise ``AdapterAuthError`` (non-retryable).  A missing
        model is fatal because retries won't help.
        """
        try:
            with httpx.Client(timeout=self._connect_timeout) as client:
                resp = client.get(self._tags_url)
        except httpx.ConnectError as exc:
            raise AdapterAuthError(
                f"Cannot connect to Ollama at {self._base_url}. "
                "Is 'ollama serve' running? Install: https://ollama.com"
            ) from exc
        except httpx.TimeoutException as exc:
            raise AdapterAuthError(
                f"Ollama at {self._base_url} did not answer /api/tags within "
                f"{self._connect_timeout:.1f}s — server may be hung."
            ) from exc

        if resp.status_code != 200:
            raise AdapterAuthError(
                f"Ollama server at {self._base_url} returned HTTP {resp.status_code}. "
                "Is 'ollama serve' running?"
            )

        try:
            tags = resp.json().get("models", [])
        except Exception:
            tags = []
        available_full  = [t.get("name", "") for t in tags]
        available_bases = [n.split(":")[0] for n in available_full]

        if not available_full:
            logger.warning(
                "[Ollama] No models reported by %s. Pull one first: ollama pull %s",
                self._tags_url, self._model,
            )
            return

        if self._model not in available_full and self._model.split(":")[0] not in available_bases:
            raise AdapterAuthError(
                f"Model '{self._model}' not pulled on {self._base_url}. "
                f"Available: {available_full[:8]}. Run: ollama pull {self._model}"
            )

    # ── Prompt guards ─────────────────────────────────────────────────────

    def _guard_prompt_size(
        self,
        formatted: list[dict[str, str]],
    ) -> tuple[list[dict[str, str]], int, bool]:
        """Enforce ``max_prompt_chars``.

        Returns (possibly-truncated messages, final char count, truncated?).
        """
        total = _total_prompt_chars(formatted)
        if total <= self._max_prompt_chars:
            return formatted, total, False

        logger.warning(
            "[Ollama] Prompt exceeds OLLAMA_MAX_PROMPT_CHARS (%d > %d).",
            total, self._max_prompt_chars,
        )
        if not self._truncate_prompt:
            raise AdapterContextLengthError(
                f"Prompt size {total} chars > OLLAMA_MAX_PROMPT_CHARS "
                f"{self._max_prompt_chars}. Set OLLAMA_TRUNCATE_PROMPT=true "
                "to auto-truncate."
            )

        # Truncate oldest non-system messages first, keep system + last message whole.
        system_msgs = [m for m in formatted if m["role"] == "system"]
        other_msgs  = [m for m in formatted if m["role"] != "system"]
        if not other_msgs:
            return formatted, total, False

        budget = self._max_prompt_chars - sum(len(m["content"]) for m in system_msgs)
        budget = max(500, budget)
        kept_tail: list[dict[str, str]] = []
        used = 0
        for m in reversed(other_msgs):
            c = m["content"]
            if used + len(c) <= budget:
                kept_tail.append(m)
                used += len(c)
            else:
                remaining = max(0, budget - used)
                if remaining >= 200:
                    kept_tail.append({"role": m["role"], "content": c[-remaining:]})
                    used += remaining
                break
        kept_tail.reverse()
        new_msgs = system_msgs + kept_tail
        new_total = _total_prompt_chars(new_msgs)
        logger.warning(
            "[Ollama] Prompt truncated %d → %d chars (kept %d/%d messages).",
            total, new_total, len(new_msgs), len(formatted),
        )
        return new_msgs, new_total, True

    # ── Main invocation ───────────────────────────────────────────────────

    def invoke_full(self, messages: list[BaseMessage]) -> AdapterResponse:
        if not messages:
            raise AdapterError("invoke_full called with empty message list.")

        self._call_count += 1

        # Preflight only on first call (cached result implicit — a failure raises fatally).
        if self._call_count == 1:
            self._check_ollama_available()

        formatted = _format_messages_for_ollama(messages)
        if not formatted:
            raise AdapterError("invoke_full: all messages empty after formatting.")

        formatted, prompt_chars, was_truncated = self._guard_prompt_size(formatted)
        est_tokens = max(1, prompt_chars // 4)
        preview    = _prompt_preview(formatted)

        logger.info(
            "[Ollama] → model=%s  msgs=%d  chars=%d  est_tokens=~%d  "
            "truncated=%s  style=chat  preview=%r",
            self._model, len(formatted), prompt_chars, est_tokens,
            was_truncated, preview,
        )

        options: dict[str, Any] = {"temperature": self._temperature}
        if self._context_length:
            options["num_ctx"] = int(self._context_length)
        # Always emit num_predict — Ollama defaults to 128 tokens if omitted,
        # which is the single biggest cause of "truncated target response".
        options["num_predict"] = int(self._num_predict)

        # ── Context-aware prompt budget ──────────────────────────────
        # If prompt tokens + num_predict > num_ctx, the model may hang or
        # produce garbage. Truncate the prompt so it fits.
        if self._context_length and est_tokens + self._num_predict > self._context_length:
            safe_prompt_tokens = max(256, self._context_length - self._num_predict - 64)
            safe_prompt_chars = safe_prompt_tokens * 4  # rough estimate
            if prompt_chars > safe_prompt_chars:
                logger.warning(
                    "[Ollama] CONTEXT BUDGET: prompt ~%d tokens + num_predict %d > num_ctx %d. "
                    "Truncating prompt to ~%d chars to fit.",
                    est_tokens, self._num_predict, self._context_length, safe_prompt_chars,
                )
                # Re-truncate with tighter budget
                old_max = self._max_prompt_chars
                self._max_prompt_chars = safe_prompt_chars
                formatted, prompt_chars, was_truncated = self._guard_prompt_size(formatted)
                self._max_prompt_chars = old_max
                est_tokens = max(1, prompt_chars // 4)


        message: dict[str, Any] = {
            "model":    self._model,
            "messages": formatted,
            "stream":   False,
            "options":  options,
        }
        if self._keep_alive:
            message["keep_alive"] = self._keep_alive

        timeout_cfg = httpx.Timeout(
            connect = self._connect_timeout,
            read    = self._read_timeout,
            write   = self._connect_timeout,
            pool    = self._connect_timeout,
        )

        last_error: Exception | None = None
        attempts = self.max_retries + 1

        for attempt in range(1, attempts + 1):
            t_start = time.monotonic()
            try:
                # Fresh client per attempt — avoids stale keep-alive sockets
                # on a sluggish Ollama that just unloaded the model.
                with httpx.Client(timeout=timeout_cfg) as client:
                    resp = client.post(self._chat_url, json=message)

                latency_ms = (time.monotonic() - t_start) * 1000

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except ValueError as exc:
                        raise AdapterError(
                            f"Ollama returned HTTP 200 with non-JSON body "
                            f"(first 200 chars): {resp.text[:200]!r}"
                        ) from exc

                    content = (
                        (data.get("message") or {}).get("content", "")
                        or data.get("response", "")
                        or ""
                    )
                    usage = int(data.get("prompt_eval_count", 0) or 0)
                    comp  = int(data.get("eval_count", 0) or 0)

                    if not content.strip():
                        last_error = AdapterError(
                            f"Ollama returned empty content. done_reason="
                            f"{data.get('done_reason')!r}  eval_count={comp}"
                        )
                        logger.warning(
                            "[Ollama] Empty content on attempt %d/%d — retrying. "
                            "done_reason=%s",
                            attempt, attempts, data.get("done_reason"),
                        )
                        # Patch 6: Short context retry logic on empty response
                        if len(formatted) > 1:
                            logger.info("[Ollama] Context-reset retry logic triggered: sending only the last message.")
                            formatted = [formatted[-1]]
                            message["messages"] = formatted
                    else:
                        logger.info(
                            "[Ollama] ✓ model=%s tokens=%d+%d latency=%.0fms "
                            "finish=%s",
                            self._model, usage, comp, latency_ms,
                            data.get("done_reason", "stop"),
                        )
                        return AdapterResponse(
                            content           = content,
                            model_id          = self.get_model_id(),
                            prompt_tokens     = usage or est_tokens,
                            completion_tokens = comp,
                            latency_ms        = latency_ms,
                            finish_reason     = data.get("done_reason", "stop"),
                            raw_response      = data,
                        )

                elif resp.status_code == 404:
                    raise AdapterAuthError(
                        f"Model '{self._model}' not found on Ollama server. "
                        f"Run: ollama pull {self._model}"
                    )
                elif resp.status_code == 400:
                    body = resp.text[:400]
                    if "context" in body.lower() or "token" in body.lower():
                        raise AdapterContextLengthError(
                            f"Ollama rejected prompt (context window). "
                            f"chars={prompt_chars} num_ctx={self._context_length}. "
                            f"Body: {body}"
                        )
                    raise AdapterError(f"Ollama HTTP 400: {body}")
                elif resp.status_code in (502, 503, 504):
                    last_error = AdapterError(
                        f"Ollama HTTP {resp.status_code} (transient): "
                        f"{resp.text[:200]}"
                    )
                    logger.warning(
                        "[Ollama] Attempt %d/%d: transient HTTP %d — will retry.",
                        attempt, attempts, resp.status_code,
                    )
                else:
                    last_error = AdapterError(
                        f"Ollama HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    logger.warning(
                        "[Ollama] Attempt %d/%d: HTTP %d — will retry.",
                        attempt, attempts, resp.status_code,
                    )

            except (AdapterAuthError, AdapterContextLengthError):
                raise   # non-retryable

            except httpx.ConnectTimeout as exc:
                last_error = AdapterTimeoutError(
                    f"Ollama connect timeout after {self._connect_timeout:.1f}s "
                    f"(server unreachable at {self._base_url})."
                )
                logger.warning(
                    "[Ollama] Attempt %d/%d: CONNECT timeout %.1fs — %s",
                    attempt, attempts, self._connect_timeout, exc,
                )

            except httpx.ReadTimeout as exc:
                last_error = AdapterTimeoutError(
                    f"Ollama read timeout after {self._read_timeout:.1f}s "
                    f"(model={self._model}, prompt_chars={prompt_chars}, "
                    f"num_predict={self._num_predict}). "
                    "Local generation is slow — raise OLLAMA_READ_TIMEOUT_SECONDS "
                    "or lower OLLAMA_NUM_PREDICT / OLLAMA_NUM_CTX."
                )
                logger.warning(
                    "[Ollama] Attempt %d/%d: READ timeout %.1fs — %s",
                    attempt, attempts, self._read_timeout, exc,
                )

            except httpx.TimeoutException as exc:
                last_error = AdapterTimeoutError(
                    f"Ollama request timed out "
                    f"(connect={self._connect_timeout}s read={self._read_timeout}s) "
                    f"— {exc!s}"
                )
                logger.warning(
                    "[Ollama] Attempt %d/%d: timeout — %s",
                    attempt, attempts, exc,
                )

            except httpx.ConnectError as exc:
                raise AdapterAuthError(
                    f"Cannot connect to Ollama at {self._base_url} "
                    "(connection refused). Is 'ollama serve' running?"
                ) from exc

            except httpx.HTTPError as exc:
                last_error = AdapterError(f"Ollama HTTP error: {exc!s}")
                logger.warning(
                    "[Ollama] Attempt %d/%d: http error — %s",
                    attempt, attempts, exc,
                )

            except Exception as exc:   # noqa: BLE001
                last_error = AdapterError(
                    f"Ollama unexpected {type(exc).__name__}: {exc!s}"
                )
                logger.warning(
                    "[Ollama] Attempt %d/%d: %s — %s",
                    attempt, attempts, type(exc).__name__, exc,
                )

            if attempt < attempts:
                backoff = min(2.0 ** (attempt - 1), 8.0)
                logger.info("[Ollama] Backing off %.1fs before retry.", backoff)
                time.sleep(backoff)

        raise last_error or AdapterError(
            f"Ollama: all {attempts} attempts exhausted for model {self._model}"
        )

    def __repr__(self) -> str:
        return (
            f"OllamaTargetAdapter("
            f"model={self._model!r}, "
            f"base_url={self._base_url!r}, "
            f"connect_timeout={self._connect_timeout}s, "
            f"read_timeout={self._read_timeout}s, "
            f"num_ctx={self._context_length}, "
            f"num_predict={self._num_predict})"
        )
