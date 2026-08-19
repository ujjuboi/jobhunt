"""
LLM access layer for JobHunt.

Wraps the OpenAI-compatible oMLX endpoint (/v1) with:
  - a default model resolver (env -> user config -> builtin default)
  - a retry policy for transient failures (connect/timeout/429/5xx)
  - sensible timeouts on the underlying HTTP connections
  - shared logging helpers

Everything in this module is usable offline (no network at import time); the
client is only created lazily inside the call helpers.
"""
import asyncio
import logging
import os
import random
import time
from functools import wraps
from typing import Dict, Any, Iterator, List, Optional

logger = logging.getLogger("jobhunt.llm")

# Import these here to make sure they exist for type checking
try:
    from openai import APIConnectionError, APITimeoutError
except ImportError:
    pass
try:
    import httpx
except ImportError:
    pass

DEFAULT_CHAT_MODEL = "Qwen3-30B-A3B-6bit"
DEFAULT_EMBEDDING_MODEL = "bge-m3-mlx-fp16"
DEFAULT_TIMEOUT_SECONDS = 60.0

# Transient conditions worth retrying with backoff.
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
# This list will be expanded with proper exception types during runtime
TRANSIENT_EXCEPTION_TYPES = (ConnectionError, TimeoutError, OSError)


def get_default_model(kind: str = "chat") -> str:
    """Resolve the model for a kind ('chat' | 'embedding').

    Precedence: JOBHUNT_*_MODEL env var -> user config -> builtin default.
    """
    env_var = f"JOBHUNT_{kind.upper()}_MODEL"
    env_val = os.environ.get(env_var)
    if env_val:
        return env_val
    try:
        from .config.user_config import get_user_config
        config = get_user_config()
        models = getattr(config, "model", None)
        if models is not None:
            val = getattr(models, kind, None)
            if val:
                return val
    except Exception:
        logger.debug("Could not read user config for model resolution", exc_info=True)
    if kind == "embedding":
        return DEFAULT_EMBEDDING_MODEL
    return DEFAULT_CHAT_MODEL


def is_transient_error(status_code: Optional[int], exc: Optional[BaseException]) -> bool:
    """Return True if the error looks transient (retryable)."""
    if status_code in TRANSIENT_STATUS_CODES:
        return True
    if exc is not None:
        # Check if exc is a transient exception type
        if isinstance(exc, TRANSIENT_EXCEPTION_TYPES):
            return True
        # Handle string representations of exception types for dynamic exception checking
        exc_type_name = type(exc).__name__
        exc_module = type(exc).__module__
        full_type_name = f"{exc_module}.{exc_type_name}" if exc_module != "__main__" else exc_type_name
        if full_type_name in ("openai.APIConnectionError", "openai.APITimeoutError", 
                              "httpx.ConnectError", "httpx.TimeoutException"):
            return True
    return False


def retry(max_retries: int = 3, base_delay: float = 0.5, jitter: float = 0.1):
    """Decorator: retry a callable on transient errors with exponential backoff.

    Non-transient errors (auth failures, 4xx, malformed payloads) are re-raised
    on the first attempt. Transient errors are retried up to ``max_retries``.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    status = getattr(e, "status_code", None)
                    if status is None:
                        status = getattr(e, "status", None)
                    if attempts >= max_retries or not is_transient_error(status, e):
                        raise
                    attempts += 1
                    delay = base_delay * (2 ** (attempts - 1)) + random.uniform(0, jitter)
                    logger.warning(
                        "Retrying %s after transient error (%s), attempt %d/%d in %.2fs",
                        func.__name__, e, attempts, max_retries, delay,
                    )
                    time.sleep(delay)

        def wrapper_async(coro):
            @wraps(coro)
            async def async_wrapper(*args, **kwargs):
                attempts = 0
                while True:
                    try:
                        return await coro(*args, **kwargs)
                    except Exception as e:
                        status = getattr(e, "status_code", None)
                        if status is None:
                            status = getattr(e, "status", None)
                        if attempts >= max_retries or not is_transient_error(status, e):
                            raise
                        attempts += 1
                        delay = base_delay * (2 ** (attempts - 1)) + random.uniform(0, jitter)
                        logger.warning(
                            "Retrying %s after transient error (%s), attempt %d/%d in %.2fs",
                            coro.__name__, e, attempts, max_retries, delay,
                        )
                        await asyncio.sleep(delay)
            return async_wrapper

        if asyncio.iscoroutinefunction(func):
            return wrapper_async(func)
        return wrapper
    return decorator


def _build_client():
    """Create the OpenAI client, with timeouts, from the current oMLX settings."""
    from openai import OpenAI
    from .config import get_omlx_settings

    settings = get_omlx_settings()
    return OpenAI(
        base_url=settings.base_url,
        api_key=settings.api_key,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        max_retries=2,
    )


@retry(max_retries=3)
def complete(messages: List[Dict[str, str]], model: Optional[str] = None, **kwargs: Any) -> str:
    """Run a chat completion and return the plain-text reply.

    ``model`` defaults to the resolved chat model. Any OpenAI kwargs
    (temperature, response_format, ...) are forwarded.
    """
    client = _build_client()
    response = client.chat.completions.create(
        model=model or get_default_model("chat"),
        messages=messages,
        **kwargs,
    )
    return response.choices[0].message.content or ""


def stream(messages: List[Dict[str, str]], model: Optional[str] = None, **kwargs: Any) -> Iterator[str]:
    """Stream a chat completion, yielding text deltas as they arrive.

    Transient errors (connection drop, 5xx, 429) restart the stream; the caller
    sees an uninterrupted sequence of deltas. Non-transient errors propagate.
    """
    attempts = 0
    # Keep track of what's already been yielded to avoid duplication on restart
    seen_content = ""
    while True:
        try:
            client = _build_client()
            response = client.chat.completions.create(
                model=model or get_default_model("chat"),
                messages=messages,
                stream=True,
                **kwargs,
            )
            for chunk in response:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        # Only yield content that hasn't been seen yet
                        content_to_yield = delta.content
                        if content_to_yield.startswith(seen_content):
                            content_to_yield = content_to_yield[len(seen_content):]
                        if content_to_yield:
                            seen_content += content_to_yield
                            yield content_to_yield
            return
        except Exception as e:
            status = getattr(e, "status_code", None)
            if status is None:
                status = getattr(e, "status", None)
            if attempts >= 3 or not is_transient_error(status, e):
                raise
            attempts += 1
            delay = 0.5 * (2 ** (attempts - 1)) + random.uniform(0, 0.1)
            logger.warning("Restarting stream after transient error (%s), attempt %d/3 in %.2fs",
                            e, attempts, delay)
            time.sleep(delay)