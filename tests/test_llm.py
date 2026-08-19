"""
LLM layer tests: transient retry (non-streaming + streaming), policy rules,
and default model resolution (env -> user config -> builtin).
"""
from types import SimpleNamespace

import pytest

from jobhunt import llm


class TransientError(RuntimeError):
    status_code = 503


class AuthError(RuntimeError):
    status_code = 401


def _no_sleep(_s):
    pass


def test_retry_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", _no_sleep)
    calls = {"n": 0}

    @llm.retry(max_retries=3)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("down")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_retry_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", _no_sleep)
    calls = {"n": 0}

    @llm.retry(max_retries=2)
    def always_down():
        calls["n"] += 1
        raise TransientError("down")

    with pytest.raises(TransientError):
        always_down()
    assert calls["n"] == 3  # initial + 2 retries


def test_retry_does_not_retry_auth_errors(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", _no_sleep)
    calls = {"n": 0}

    @llm.retry(max_retries=3)
    def bad_key():
        calls["n"] += 1
        raise AuthError("bad key")

    with pytest.raises(AuthError):
        bad_key()
    assert calls["n"] == 1


def test_retry_does_not_retry_plain_valueerror(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", _no_sleep)
    calls = {"n": 0}

    @llm.retry(max_retries=3)
    def bad_args():
        calls["n"] += 1
        raise ValueError("bad")

    with pytest.raises(ValueError):
        bad_args()
    assert calls["n"] == 1


def test_is_transient_error_status_and_exception(monkeypatch):
    assert llm.is_transient_error(503, None)
    assert llm.is_transient_error(429, None)
    assert llm.is_transient_error(None, TimeoutError("t"))
    assert llm.is_transient_error(None, ConnectionError("c"))
    assert not llm.is_transient_error(401, None)
    assert not llm.is_transient_error(400, None)


class FakeCompletions:
    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def create(self, *args, **kwargs):
        self.calls += 1
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item()


def _complete_response(text):
    return lambda: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


def test_complete_retries_transient_and_returns(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", _no_sleep)
    completions = FakeCompletions([TransientError("down"), _complete_response("hi")])
    monkeypatch.setattr(
        llm, "_build_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    assert llm.complete([{"role": "user", "content": "x"}]) == "hi"
    assert completions.calls == 2


def _stream_response(chunks, fail_after=None):
    """Build a fake streaming response generator firing chunks (or raising)."""

    def gen():
        for i, c in enumerate(chunks):
            if fail_after is not None and i >= fail_after:
                raise TransientError("mid-stream drop")
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=c))]
            )

    return gen


def test_stream_restarts_after_mid_stream_drop(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", _no_sleep)
    completions = FakeCompletions(
        [
            _stream_response(["a", "b"], fail_after=1),
            _stream_response(["c", "d"]),
        ]
    )
    monkeypatch.setattr(
        llm, "_build_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    out = "".join(llm.stream([{"role": "user", "content": "x"}]))
    # "a" was already delivered before the mid-stream drop; the retry then
    # delivers the full successful attempt ("cd").
    assert out.endswith("cd")
    assert completions.calls == 2


def test_stream_gives_up_after_repeated_errors(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", _no_sleep)
    completions = FakeCompletions(
        [
            _stream_response(["a"], fail_after=0),
            _stream_response(["b"], fail_after=0),
            _stream_response(["c"], fail_after=0),
            _stream_response(["d"], fail_after=0),
        ]
    )
    monkeypatch.setattr(
        llm, "_build_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    with pytest.raises(TransientError):
        for _ in llm.stream([{"role": "user", "content": "x"}]):
            pass


def test_default_model_env_override(monkeypatch):
    monkeypatch.setenv("JOBHUNT_CHAT_MODEL", "custom-chat")
    assert llm.get_default_model("chat") == "custom-chat"
    monkeypatch.delenv("JOBHUNT_CHAT_MODEL")


def test_default_model_falls_back_to_builtin(monkeypatch):
    monkeypatch.delenv("JOBHUNT_CHAT_MODEL", raising=False)
    monkeypatch.delenv("JOBHUNT_EMBEDDING_MODEL", raising=False)
    from jobhunt.config.user_config import get_default_user_config
    monkeypatch.setattr("jobhunt.config.user_config.get_user_config", get_default_user_config)
    assert llm.get_default_model("chat") == llm.DEFAULT_CHAT_MODEL
    assert llm.get_default_model("embedding") == llm.DEFAULT_EMBEDDING_MODEL