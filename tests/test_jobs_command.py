"""Tests for the ``/jobs`` command handler (src/untether/telegram/jobs.py)."""

from __future__ import annotations

import time

import anyio
import pytest

from tests.telegram_fakes import FakeTransport, make_cfg
from untether.context import RunContext
from untether.ids import RESERVED_CHAT_COMMANDS
from untether.runner_bridge import RunningTask
from untether.telegram import at_scheduler, jobs
from untether.telegram import loop as loop_module
from untether.telegram.commands.menu import build_bot_commands
from untether.telegram.jobs import handle_jobs_command
from untether.telegram.loop import TelegramCommandContext, _dispatch_builtin_command
from untether.telegram.types import TelegramIncomingMessage
from untether.transport import MessageRef

pytestmark = pytest.mark.anyio


def _msg(text: str = "/jobs", *, chat_id: int = 123) -> TelegramIncomingMessage:
    return TelegramIncomingMessage(
        transport="telegram",
        chat_id=chat_id,
        message_id=1,
        text=text,
        reply_to_message_id=None,
        reply_to_text=None,
        sender_id=1,
        thread_id=None,
        chat_type="supergroup",
    )


def _last_text(transport: FakeTransport) -> str:
    return transport.send_calls[-1]["message"].text


class _FakeScheduler:
    """Duck-typed stand-in for ThreadScheduler.queued_for_chat()."""

    def __init__(self, queued: dict[int, list[object]] | None = None) -> None:
        self._queued = queued or {}

    def queued_for_chat(self, chat_id: int) -> list[object]:
        return self._queued.get(chat_id, [])


async def _run(
    *,
    running_tasks,
    scheduler=None,
    msg=None,
    ambient_context=None,
):
    transport = FakeTransport()
    cfg = make_cfg(transport)
    msg = msg or _msg()
    await handle_jobs_command(
        cfg,
        msg,
        running_tasks=running_tasks,
        scheduler=scheduler or _FakeScheduler(),
        ambient_context=ambient_context,
    )
    return transport


@pytest.fixture(autouse=True)
def _clean_at_scheduler(monkeypatch: pytest.MonkeyPatch):
    # Isolate each test from module-level /at pending state and from any
    # accidental real filesystem/proc access via collect_proc_diag.
    monkeypatch.setattr(at_scheduler, "pending_for_chat", lambda _chat_id: [])


class TestEmptyChat:
    async def test_empty_chat_reply(self) -> None:
        transport = await _run(running_tasks={})
        assert _last_text(transport).startswith("😴 No active runs in this chat.")

    async def test_empty_reply_has_footer(self) -> None:
        transport = await _run(running_tasks={})
        assert "Reply /cancel to a run's progress message to stop it." in _last_text(
            transport
        )


class TestRunningTaskRendering:
    async def test_one_running_task_renders_engine_elapsed_pid_alive_trigger(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = time.monotonic()
        monkeypatch.setattr(jobs.time, "monotonic", lambda: now)

        class _Diag:
            alive = True

        monkeypatch.setattr(jobs, "collect_proc_diag", lambda _pid: _Diag())

        ref = MessageRef(channel_id=123, message_id=99)
        task = RunningTask(
            engine="claude",
            started_at=now - 300,  # 5 minutes ago
            pid=4242,
            context=RunContext(trigger_source="cron:daily-review"),
        )
        transport = await _run(running_tasks={ref: task})
        text = _last_text(transport)

        assert "claude" in text
        assert "5m" in text
        assert "4242" in text
        assert "alive" in text
        assert "cron:daily-review" in text
        # Footer is present for a non-empty reply.
        assert "/cancel" in text

    async def test_exited_task_renders_exited(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Diag:
            alive = False

        monkeypatch.setattr(jobs, "collect_proc_diag", lambda _pid: _Diag())

        ref = MessageRef(channel_id=123, message_id=99)
        task = RunningTask(engine="codex", started_at=0.0, pid=555)
        transport = await _run(running_tasks={ref: task})
        text = _last_text(transport)

        assert "exited" in text
        assert "codex" in text

    async def test_started_at_zero_skips_elapsed_segment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jobs, "collect_proc_diag", lambda _pid: None)

        ref = MessageRef(channel_id=123, message_id=99)
        task = RunningTask(engine="pi", started_at=0.0, pid=None)
        transport = await _run(running_tasks={ref: task})
        text = _last_text(transport)

        # No "Nm" elapsed token should appear anywhere in the line.
        assert "0m" not in text
        assert "1m" not in text

    async def test_no_trigger_source_omits_segment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jobs, "collect_proc_diag", lambda _pid: None)

        ref = MessageRef(channel_id=123, message_id=99)
        task = RunningTask(engine="gemini", started_at=0.0, pid=None, context=None)
        transport = await _run(running_tasks={ref: task})
        text = _last_text(transport)

        assert "gemini" in text
        assert "⏰" not in text  # clock icon reserved for trigger source segment


class TestChatFiltering:
    async def test_tasks_in_other_chats_are_excluded(self) -> None:
        ref_this_chat = MessageRef(channel_id=123, message_id=1)
        ref_other_chat = MessageRef(channel_id=999, message_id=2)
        this_task = RunningTask(engine="claude", started_at=0.0, pid=None)
        other_task = RunningTask(engine="amp", started_at=0.0, pid=None)

        transport = await _run(
            running_tasks={ref_this_chat: this_task, ref_other_chat: other_task},
            msg=_msg(chat_id=123),
        )
        text = _last_text(transport)

        assert "claude" in text
        assert "amp" not in text


class TestPidAndDiagNoneRenderQuestionMark:
    async def test_pid_none_renders_question_mark_no_crash(self) -> None:
        ref = MessageRef(channel_id=123, message_id=1)
        task = RunningTask(engine="opencode", started_at=0.0, pid=None)
        transport = await _run(running_tasks={ref: task})
        text = _last_text(transport)

        assert "?" in text
        assert "opencode" in text

    async def test_diag_none_renders_question_mark_no_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jobs, "collect_proc_diag", lambda _pid: None)

        ref = MessageRef(channel_id=123, message_id=1)
        task = RunningTask(engine="opencode", started_at=0.0, pid=777)
        transport = await _run(running_tasks={ref: task})
        text = _last_text(transport)

        assert "777" in text
        assert "(?)" in text


class TestQueuedAndPendingCounts:
    async def test_queued_count_rendered_when_positive(self) -> None:
        scheduler = _FakeScheduler(queued={123: [object(), object()]})
        transport = await _run(running_tasks={}, scheduler=scheduler)
        text = _last_text(transport)

        assert "2" in text
        assert "queued" in text

    async def test_queued_count_omitted_when_zero(self) -> None:
        # zero queued + zero pending + zero running => empty-state reply.
        transport = await _run(running_tasks={}, scheduler=_FakeScheduler())
        assert "queued" not in _last_text(transport)

    async def test_pending_at_count_rendered_when_positive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(at_scheduler, "pending_for_chat", lambda _cid: [1, 2, 3])
        transport = await _run(running_tasks={})
        text = _last_text(transport)

        assert "3" in text
        assert "pending" in text
        assert "/at" in text

    async def test_both_queued_and_pending_rendered_together(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(at_scheduler, "pending_for_chat", lambda _cid: [1])
        scheduler = _FakeScheduler(queued={123: [object()]})
        transport = await _run(running_tasks={}, scheduler=scheduler)
        text = _last_text(transport)

        assert "1 queued" in text
        assert "1 pending" in text
        assert "/cancel" in text  # footer present since reply is non-empty


class TestSortingByStartedAt:
    async def test_running_lines_sorted_by_started_at_ascending(self) -> None:
        base = 1_000_000.0
        ref_a = MessageRef(channel_id=123, message_id=1)
        ref_b = MessageRef(channel_id=123, message_id=2)
        ref_c = MessageRef(channel_id=123, message_id=3)
        # Deliberately inserted out of order.
        task_b = RunningTask(engine="second", started_at=base + 20, pid=None)
        task_a = RunningTask(engine="first", started_at=base + 10, pid=None)
        task_c = RunningTask(engine="third", started_at=base + 30, pid=None)

        transport = await _run(
            running_tasks={ref_b: task_b, ref_a: task_a, ref_c: task_c}
        )
        text = _last_text(transport)
        pos_first = text.index("first")
        pos_second = text.index("second")
        pos_third = text.index("third")
        assert pos_first < pos_second < pos_third


# ── wiring: loop.py dispatch, ids.py reserved list, static menu (Task 9) ────
# Mirrors TestPrintTimeoutRouting in tests/test_print_timeout_command.py: build
# a TelegramCommandContext, monkeypatch the handler that loop.py imported by
# name, and assert the dispatch branch schedules it with the right arguments.


class TestJobsDispatchRouting:
    async def test_dispatch_routes_jobs_to_handler(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict] = []

        async def _fake_handler(
            cfg_arg,
            msg_arg,
            *,
            running_tasks,
            scheduler,
            ambient_context,
        ) -> None:
            calls.append(
                {
                    "cfg": cfg_arg,
                    "msg": msg_arg,
                    "running_tasks": running_tasks,
                    "scheduler": scheduler,
                    "ambient_context": ambient_context,
                }
            )

        monkeypatch.setattr(loop_module, "handle_jobs_command", _fake_handler)

        transport = FakeTransport()
        cfg = make_cfg(transport)
        msg = _msg("/jobs")
        ambient_context = RunContext(project="foo")
        sentinel_running_tasks = {"sentinel": "running_tasks"}
        sentinel_scheduler = object()

        async def _reply(*_a: object, **_k: object) -> None:
            return None

        async with anyio.create_task_group() as tg:
            ctx = TelegramCommandContext(
                cfg=cfg,
                msg=msg,
                args_text="",
                ambient_context=ambient_context,
                topic_store=None,
                chat_prefs=None,
                resolved_scope="all",
                scope_chat_ids=frozenset({msg.chat_id}),
                reply=_reply,
                task_group=tg,
                running_tasks=sentinel_running_tasks,
                scheduler=sentinel_scheduler,
            )
            result = _dispatch_builtin_command(ctx=ctx, command_id="jobs")
            assert result is True

        assert len(calls) == 1
        call = calls[0]
        assert call["running_tasks"] is sentinel_running_tasks
        assert call["scheduler"] is sentinel_scheduler
        assert call["ambient_context"] is ambient_context


class TestJobsReservedId:
    async def test_jobs_in_reserved_chat_commands(self) -> None:
        assert "jobs" in RESERVED_CHAT_COMMANDS


class TestJobsMenu:
    async def test_jobs_appears_exactly_once_with_description(self) -> None:
        transport = FakeTransport()
        cfg = make_cfg(transport)
        commands = build_bot_commands(cfg.runtime)

        matches = [cmd for cmd in commands if cmd["command"] == "jobs"]
        assert len(matches) == 1
        assert matches[0]["description"] == "list active runs in this chat"
