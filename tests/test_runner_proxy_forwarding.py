"""Attribute forwarding through the executor's runner wrappers.

``_ResumeLineProxy`` / ``_PreludeRunner`` wrap the real runner on most
Telegram-submitted runs. ``runner_bridge.handle_message`` reads optional
runner capabilities (``streams_progress``, ``expected_silence_budget_s``,
``last_pid``) via ``getattr`` and writes watchdog knobs
(``_LIVENESS_TIMEOUT_SECONDS``, ``_stall_auto_kill``) behind ``hasattr``.
Both directions must reach the wrapped runner, otherwise envelope-only
engines (Antigravity) are misclassified as streaming engines and
auto-cancelled at ~11 min with ``no_pid_no_events``.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest

from untether.model import Action, ActionEvent, ResumeToken
from untether.runners.antigravity import AntigravityRunner
from untether.runners.codex import CodexRunner
from untether.runners.mock import MockRunner, Return, ScriptRunner
from untether.telegram.commands.executor import _PreludeRunner, _ResumeLineProxy


def _prelude_event(engine: str) -> ActionEvent:
    return ActionEvent(
        engine=engine,
        action=Action(id="prelude", kind="note", title="prelude", detail={}),
        phase="completed",
        ok=True,
    )


def _wrap_resume(inner: Any) -> Any:
    return _ResumeLineProxy(inner)


def _wrap_prelude(inner: Any) -> Any:
    return _PreludeRunner(inner, [])


def _wrap_nested(inner: Any) -> Any:
    return _PreludeRunner(_ResumeLineProxy(inner), [])


WRAPPERS: list[Callable[[Any], Any]] = [_wrap_resume, _wrap_prelude, _wrap_nested]
WRAPPER_IDS = ["resume_proxy", "prelude", "nested"]


@pytest.mark.parametrize("wrap", WRAPPERS, ids=WRAPPER_IDS)
def test_proxy_forwards_streams_progress(wrap: Callable[[Any], Any]) -> None:
    assert wrap(AntigravityRunner()).streams_progress is False
    codex = CodexRunner(codex_cmd="codex", extra_args=[])
    assert wrap(codex).streams_progress is True


@pytest.mark.parametrize("wrap", WRAPPERS, ids=WRAPPER_IDS)
def test_proxy_forwards_expected_silence_budget_s(wrap: Callable[[Any], Any]) -> None:
    inner = AntigravityRunner(print_timeout="45m")
    proxy = wrap(inner)
    budget_fn = proxy.expected_silence_budget_s
    assert callable(budget_fn)
    assert budget_fn() == inner.expected_silence_budget_s()
    assert budget_fn() == 45 * 60


@pytest.mark.parametrize("wrap", WRAPPERS, ids=WRAPPER_IDS)
def test_proxy_forwards_last_pid_live(wrap: Callable[[Any], Any]) -> None:
    inner = AntigravityRunner()
    proxy = wrap(inner)
    assert proxy.last_pid is None
    inner.last_pid = 4242
    assert proxy.last_pid == 4242
    inner.last_pid = 4343
    assert proxy.last_pid == 4343


@pytest.mark.parametrize("wrap", WRAPPERS, ids=WRAPPER_IDS)
def test_proxy_setattr_forwards_watchdog_knobs(wrap: Callable[[Any], Any]) -> None:
    """Regression: bridge does ``hasattr`` then assigns; must not raise."""
    inner = AntigravityRunner()
    proxy = wrap(inner)
    assert hasattr(proxy, "_LIVENESS_TIMEOUT_SECONDS")
    assert hasattr(proxy, "_stall_auto_kill")

    proxy._LIVENESS_TIMEOUT_SECONDS = 123.0
    proxy._stall_auto_kill = True

    assert inner._LIVENESS_TIMEOUT_SECONDS == 123.0
    assert inner._stall_auto_kill is True
    assert proxy._LIVENESS_TIMEOUT_SECONDS == 123.0
    # The class default is untouched (instance-level write on the inner runner).
    assert AntigravityRunner._LIVENESS_TIMEOUT_SECONDS == 600.0


@pytest.mark.parametrize(
    "make",
    [
        lambda r: _ResumeLineProxy(r),
        lambda r: _PreludeRunner(r, []),
    ],
    ids=["resume_proxy", "prelude"],
)
def test_proxy_own_fields_stay_local(make: Callable[[Any], Any]) -> None:
    old = AntigravityRunner()
    other = AntigravityRunner(print_timeout="2h")
    proxy = make(old)

    proxy.runner = other

    assert proxy.runner is other
    assert "runner" not in getattr(old, "__dict__", {})
    assert not hasattr(old, "runner")
    assert proxy.expected_silence_budget_s() == 7200


def test_prelude_own_prelude_events_field_stays_local() -> None:
    inner = AntigravityRunner()
    proxy = _PreludeRunner(inner, [])
    events = [_prelude_event("antigravity")]
    proxy.prelude_events = events
    assert proxy.prelude_events is events
    assert not hasattr(inner, "prelude_events")


@pytest.mark.anyio
async def test_proxy_explicit_overrides_win() -> None:
    inner = ScriptRunner([Return(answer="done")], engine="codex", resume_value="r1")
    token = ResumeToken(engine="codex", value="abc123")
    assert inner.format_resume(token) != ""

    resume_proxy = _ResumeLineProxy(inner)
    assert resume_proxy.format_resume(token) == ""
    assert resume_proxy.engine == "codex"

    prelude = _prelude_event("codex")
    prelude_runner = _PreludeRunner(inner, [prelude])
    assert prelude_runner.engine == "codex"
    assert prelude_runner.format_resume(token) == inner.format_resume(token)

    events = [evt async for evt in prelude_runner.run("hi", None)]
    assert events[0] is prelude
    assert len(events) > 1

    nested = _PreludeRunner(_ResumeLineProxy(inner), [prelude])
    assert nested.engine == "codex"
    assert nested.format_resume(token) == ""


def test_nested_prelude_over_resume_proxy_forwards() -> None:
    inner = AntigravityRunner(print_timeout="30m")
    nested = _PreludeRunner(_ResumeLineProxy(inner), [_prelude_event("antigravity")])
    assert nested.streams_progress is False
    assert nested.expected_silence_budget_s() == inner.expected_silence_budget_s()
    assert nested.last_pid is None
    inner.last_pid = 99
    assert nested.last_pid == 99

    nested._LIVENESS_TIMEOUT_SECONDS = 77.0
    assert inner._LIVENESS_TIMEOUT_SECONDS == 77.0
    # The intermediate proxy stays a pure pass-through (no stored copy).
    assert nested.runner._LIVENESS_TIMEOUT_SECONDS == 77.0


@pytest.mark.parametrize("wrap", WRAPPERS, ids=WRAPPER_IDS)
def test_proxy_missing_attr_semantics(wrap: Callable[[Any], Any]) -> None:
    p = wrap(MockRunner(engine="mock"))
    assert getattr(p, "streams_progress", True) is True
    assert getattr(p, "expected_silence_budget_s", None) is None
    assert getattr(p, "last_pid", None) is None
    assert hasattr(p, "nope") is False
    assert hasattr(p, "_LIVENESS_TIMEOUT_SECONDS") is False
    # #98: current_stream stays an explicit property returning None.
    assert p.current_stream is None


@pytest.mark.parametrize("cls", [_ResumeLineProxy, _PreludeRunner])
def test_proxy_uninitialised_and_copy_safe(cls: type) -> None:
    blank = cls.__new__(cls)
    with pytest.raises(AttributeError):
        _ = blank.streams_progress
    with pytest.raises(AttributeError):
        _ = blank.runner

    inner = AntigravityRunner()
    proxy = _ResumeLineProxy(inner) if cls is _ResumeLineProxy else cls(inner, [])
    clone = copy.copy(proxy)
    assert clone.runner is inner
    assert clone.streams_progress is False
