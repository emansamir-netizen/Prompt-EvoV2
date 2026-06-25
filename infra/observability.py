

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

try:
    from pythonjsonlogger import jsonlogger
    _HAS_JSON_LOGGER = True
except ImportError:
    _HAS_JSON_LOGGER = False

# ─────────────────────────────────────────────────────────────────────────────
# SESSION CONTEXT  (ContextVar — propagates through async + threads)
# ─────────────────────────────────────────────────────────────────────────────

_ctx_session_id:    ContextVar[str]   = ContextVar("session_id",    default="")
_ctx_node_name:     ContextVar[str]   = ContextVar("node_name",     default="")
_ctx_turn_count:    ContextVar[int]   = ContextVar("turn_count",    default=0)
_ctx_session_start: ContextVar[float] = ContextVar("session_start", default=0.0)
_ctx_target_model:  ContextVar[str]   = ContextVar("target_model",  default="")

# Thread-local fallback for background threads that can't use ContextVar
_thread_local = threading.local()


def set_session_context(
    session_id:   str   = "",
    node_name:    str   = "",
    turn_count:   int   = 0,
    target_model: str   = "",
) -> None:
    """Set the logging context for the current async task or thread.

    Call at the start of every audit session. All subsequent log calls
    in this context will automatically include these fields.
    """
    _ctx_session_id.set(session_id)
    _ctx_node_name.set(node_name)
    _ctx_turn_count.set(turn_count)
    _ctx_target_model.set(target_model)
    _ctx_session_start.set(time.monotonic())
    # Also set thread-local for background threads
    _thread_local.session_id    = session_id
    _thread_local.node_name     = node_name
    _thread_local.turn_count    = turn_count
    _thread_local.target_model  = target_model
    _thread_local.session_start = time.monotonic()


def set_node_context(node_name: str, turn_count: int = 0) -> None:
    """Update the current node and turn — call at the top of each node function."""
    _ctx_node_name.set(node_name)
    _ctx_turn_count.set(turn_count)
    _thread_local.node_name  = node_name
    _thread_local.turn_count = turn_count


def clear_session_context() -> None:
    """Reset all context vars (call at session end)."""
    _ctx_session_id.set("")
    _ctx_node_name.set("")
    _ctx_turn_count.set(0)
    _ctx_target_model.set("")
    _ctx_session_start.set(0.0)
    for attr in ("session_id", "node_name", "turn_count", "target_model", "session_start"):
        setattr(_thread_local, attr, None)


def _get_ctx(var: ContextVar, tl_attr: str, default: Any) -> Any:
    """Get value from ContextVar with thread-local fallback."""
    val = var.get()
    if val:
        return val
    return getattr(_thread_local, tl_attr, default) or default


# ─────────────────────────────────────────────────────────────────────────────
# JSON FORMATTER
# ─────────────────────────────────────────────────────────────────────────────

_HOSTNAME = socket.gethostname()
_SERVICE  = "promptevo"


class PromptEvoJsonFormatter(logging.Formatter):
    """Custom JSON log formatter.

    Works with or without ``python-json-logger``.  When the library is
    installed it delegates to ``jsonlogger.JsonFormatter`` for the base
    serialisation; otherwise it builds the JSON dict manually.

    Every record is enriched with:
      - session context (session_id, node_name, turn_count, target_model)
      - elapsed_ms (time since session start)
      - hostname, service, pid, thread_name
      - Any extra fields the caller passed in ``extra={}``
    """

    # Fields from LogRecord that are redundant or internal — strip them from output
    _STRIP_KEYS = {
        "args", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelno", "lineno", "module", "msecs", "msg", "pathname",
        "process", "processName", "relativeCreated", "stack_info",
        "taskName", "thread",
    }

    def format(self, record: logging.LogRecord) -> str:
        # ── Base fields ───────────────────────────────────────────────────
        start = _get_ctx(_ctx_session_start, "session_start", 0.0) or 0.0
        doc: dict[str, Any] = {
            "timestamp":   datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level":       record.levelname,
            "logger":      record.name,
            "message":     record.getMessage(),
            "service":     _SERVICE,
            "hostname":    _HOSTNAME,
            "pid":         os.getpid(),
            "thread_name": record.threadName,
        }

        # ── Session context ───────────────────────────────────────────────
        sid   = _get_ctx(_ctx_session_id,    "session_id",    "")
        node  = _get_ctx(_ctx_node_name,     "node_name",     "")
        turn  = _get_ctx(_ctx_turn_count,    "turn_count",    0)
        model = _get_ctx(_ctx_target_model,  "target_model",  "")

        if sid:   doc["session_id"]   = sid
        if node:  doc["node_name"]    = node
        if turn:  doc["turn_count"]   = turn
        if model: doc["target_model"] = model
        if start: doc["elapsed_ms"]   = round((time.monotonic() - start) * 1000, 2)

        # ── Exception info ────────────────────────────────────────────────
        if record.exc_info:
            doc["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            doc["stack_info"] = self.formatStack(record.stack_info)

        # ── Caller extras (the 'extra={...}' kwarg) ───────────────────────
        for key, val in record.__dict__.items():
            if key not in self._STRIP_KEYS and not key.startswith("_"):
                if key not in doc:
                    doc[key] = val

        return json.dumps(doc, default=str, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURE LOGGING
# ─────────────────────────────────────────────────────────────────────────────

_configured = False


def configure_logging(level: str | None = None) -> None:
    """Install the JSON formatter on the root logger.

    Safe to call multiple times — idempotent after the first call.

    Parameters
    ──────────
    level : str | None
        Log level string (e.g., "INFO", "WARNING"). If None, reads from
        ``LOG_LEVEL`` environment variable. Default: "WARNING".
    """
    global _configured
    if _configured:
        return
    _configured = True

    target_level_str = (level or os.getenv("LOG_LEVEL", "WARNING")).upper()
    target_level     = getattr(logging, target_level_str, logging.WARNING)

    formatter = PromptEvoJsonFormatter()
    handler   = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Remove any existing handlers to avoid duplicate output
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(target_level)

    # Silence very noisy third-party loggers regardless of our level
    _noisy_loggers = [
        "httpx", "httpcore", "openai", "anthropic",
        "langchain_core", "langgraph", "urllib3",
        "hpack", "h2", "uvicorn.access",
    ]
    for name in _noisy_loggers:
        logging.getLogger(name).setLevel(logging.ERROR)

    # Ensure all promptevo.* loggers propagate to root
    logging.getLogger("promptevo").setLevel(target_level)

    logging.getLogger("promptevo.observability").info(
        "Structured JSON logging configured",
        extra={"log_level": target_level_str, "json_logger": _HAS_JSON_LOGGER},
    )


# ─────────────────────────────────────────────────────────────────────────────
# NODE EXECUTION DECORATOR
# ─────────────────────────────────────────────────────────────────────────────

def logged_node(node_name: str):
    """Decorator that wraps a LangGraph node function with structured logging.

    Automatically emits ``node_enter`` and ``node_exit`` events with latency,
    and sets the node context so all log calls inside the node carry the
    correct node_name and turn_count.

    Usage::

        @logged_node("inquiry_swarm")
        def inquiry_swarm_node(state: AuditorState) -> dict:
            ...
    """
    def decorator(fn):
        import functools

        @functools.wraps(fn)
        def wrapper(state, *args, **kwargs):
            turn = state.get("turn_count", 0) if isinstance(state, dict) else 0
            sid  = state.get("session_id", "")  if isinstance(state, dict) else ""
            set_node_context(node_name, turn)

            _node_logger = logging.getLogger(f"promptevo.nodes.{node_name}")
            t_start = time.monotonic()

            _node_logger.debug(
                "node_enter",
                extra={
                    "event":     "node_enter",
                    "node":      node_name,
                    "turn":      turn,
                    "session":   sid,
                    "coop":      state.get("cooperation_score", 0) if isinstance(state, dict) else 0,
                    "depth":     state.get("current_depth", 0)     if isinstance(state, dict) else 0,
                },
            )

            try:
                result = fn(state, *args, **kwargs)
                latency_ms = (time.monotonic() - t_start) * 1000
                _node_logger.debug(
                    "node_exit",
                    extra={
                        "event":      "node_exit",
                        "node":       node_name,
                        "latency_ms": round(latency_ms, 2),
                        "keys_written": list(result.keys()) if isinstance(result, dict) else [],
                    },
                )
                return result
            except Exception as exc:
                latency_ms = (time.monotonic() - t_start) * 1000
                _node_logger.error(
                    "node_error",
                    extra={
                        "event":      "node_error",
                        "node":       node_name,
                        "latency_ms": round(latency_ms, 2),
                        "error":      str(exc),
                        "error_type": type(exc).__name__,
                    },
                    exc_info=True,
                )
                raise

        return wrapper
    return decorator


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH / READINESS PROBE DATA
# ─────────────────────────────────────────────────────────────────────────────

def get_observability_status() -> dict:
    """Return observability configuration for the /health endpoint."""
    return {
        "json_logging":        True,
        "json_logger_lib":     _HAS_JSON_LOGGER,
        "log_level":           os.getenv("LOG_LEVEL", "WARNING"),
        "context_propagation": "contextvars + thread_local",
        "turn_records_path":   _turn_records_path(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# STRUCTURED PER-TURN RECORDS
# ─────────────────────────────────────────────────────────────────────────────
# These records are the seal point for everything that happened in a turn:
# audit-trail provenance summary, scoring lifecycle snapshot, and the
# persistence decision computed by the learning-memory layer. They are
# emitted as JSONL (one line per turn) so audits can be replayed without
# reparsing free-form INFO logs.

_TURN_RECORD_LOGGER = logging.getLogger("promptevo.turn_records")
_turn_record_handler_attached = False
_turn_record_lock = threading.Lock()


def _turn_records_path() -> str:
    """Resolve the file path for the JSONL turn-record stream.

    Default: ``data/turn_records.jsonl`` next to the working directory.
    Override with the ``PROMPTEVO_TURN_RECORDS_PATH`` environment variable.
    """
    return os.getenv("PROMPTEVO_TURN_RECORDS_PATH", "data/turn_records.jsonl")


def _ensure_turn_record_handler() -> None:
    """Attach a dedicated FileHandler the first time a turn record is emitted."""
    global _turn_record_handler_attached
    if _turn_record_handler_attached:
        return
    with _turn_record_lock:
        if _turn_record_handler_attached:
            return
        try:
            path = _turn_records_path()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            handler = logging.FileHandler(path, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            _TURN_RECORD_LOGGER.addHandler(handler)
            _TURN_RECORD_LOGGER.propagate = False
            _TURN_RECORD_LOGGER.setLevel(logging.INFO)
            _turn_record_handler_attached = True
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("promptevo.observability").warning(
                "Could not attach turn-record file handler: %s", exc,
            )


def emit_turn_record(
    *,
    turn:                 int,
    audit_summary:        dict[str, Any] | None = None,
    scoring:              dict[str, Any] | None = None,
    persistence_decision: dict[str, Any] | None = None,
    extra:                dict[str, Any] | None = None,
) -> None:
    """Emit a single structured JSON record for the given turn.

    The record shape is::

        {
          "schema":       "promptevo.turn_record.v1",
          "timestamp":    "...",
          "session_id":   "...",
          "turn":         int,
          "target_model": "...",
          "audit":        {complete, stage_count, first_hash, dispatched_hash, hash_changed, transforms},
          "scoring":      {score, status, divergence_type, consensus_stable},
          "persistence":  {persisted, reason, …},
          "extra":        {...}
        }

    The function never raises — callers fire-and-forget.
    """
    _ensure_turn_record_handler()
    sid   = _get_ctx(_ctx_session_id,   "session_id",   "")
    model = _get_ctx(_ctx_target_model, "target_model", "")
    record: dict[str, Any] = {
        "schema":       "promptevo.turn_record.v1",
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "session_id":   sid,
        "turn":         int(turn),
        "target_model": model,
        "audit":        dict(audit_summary or {}),
        "scoring":      dict(scoring or {}),
        "persistence":  dict(persistence_decision or {}),
        "extra":        dict(extra or {}),
    }
    try:
        _TURN_RECORD_LOGGER.info(json.dumps(record, default=str, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("promptevo.observability").warning(
            "Failed to emit turn record: %s", exc,
        )


def seal_turn_record(state: Any) -> dict[str, Any]:
    """Build and emit the consolidated turn record for the turn in ``state``.

    Reads:
      * ``audit_trail``                  (core.audit_trail)
      * ``prometheus_score`` / status     (core.score_lifecycle)
      * ``scoring_consensus_stable``     (set by graph judge node)
      * ``memory_persistence_decision``  (set by experience_pool)

    Returns the record dict (also written to the JSONL stream).
    """
    if not isinstance(state, dict) and not (hasattr(state, "get") and hasattr(state, "__setitem__")):
        return {}

    try:
        turn = int(state.get("turn_count", 0) or 0)
    except (TypeError, ValueError):
        turn = 0

    try:
        from core.audit_trail import summarize_turn as _audit_summary
        audit = _audit_summary(state, turn)
    except Exception:  # noqa: BLE001
        audit = {}

    try:
        from core.score_lifecycle import get_scoring_snapshot
        snap = get_scoring_snapshot(state)
        scoring = {
            "score":           snap.score,
            "status":          snap.status,
            "divergence_type": snap.divergence_type,
            "consensus_stable": snap.consensus_stable,
        }
    except Exception:  # noqa: BLE001
        scoring = {}

    persistence = dict(state.get("memory_persistence_decision") or {})

    record: dict[str, Any] = {
        "schema":       "promptevo.turn_record.v1",
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "session_id":   state.get("session_id", "") or _get_ctx(_ctx_session_id, "session_id", ""),
        "turn":         turn,
        "target_model": state.get("target_model_id", "") or _get_ctx(_ctx_target_model, "target_model", ""),
        "audit":        audit,
        "scoring":      scoring,
        "persistence":  persistence,
    }
    emit_turn_record(
        turn=turn,
        audit_summary=audit,
        scoring=scoring,
        persistence_decision=persistence,
    )
    return record
