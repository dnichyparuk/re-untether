"""Command handler for ``/jobs`` — snapshot of active work in this chat.

``/jobs`` is read-only (no admin gate, matching ``/ping``) and reports three
independent sources of in-flight work for the calling chat:

- **running** — active :class:`~untether.runner_bridge.RunningTask` entries
  (``running_tasks``), filtered to this chat via
  ``ref.channel_id == msg.chat_id`` and rendered sorted by ``started_at``
  ascending. Each line shows the engine, elapsed minutes (when the task's
  clock has actually started), pid + liveness, and the triggering cron/webhook
  (when the run was trigger-initiated).
- **queued** — jobs waiting behind an in-flight session lock, counted via
  ``len(scheduler.queued_for_chat(chat_id))``.
- **pending /at** — one-shot delayed runs scheduled via ``/at``, counted via
  ``len(at_scheduler.pending_for_chat(chat_id))``.

Both counters reuse existing chat-scoped accessors rather than adding new
counting methods to :mod:`untether.scheduler` / :mod:`untether.telegram.at_scheduler`.
``at_scheduler`` holds module-level state (no per-chat instance to thread
through), so it is imported as a module, not a class dependency — mirrors how
:mod:`untether.telegram.commands.cancel` reads it.

The handler shape (``cfg, msg, *, ... -> None``) mirrors the sibling builtin
command modules such as :mod:`untether.telegram.print_timeout` rather than the
``CommandBackend``/``CommandResult`` shape used by ``/health`` — the reply
composition style (bold key values, one line per fact) is borrowed from
``/health``, but delivered through :func:`~untether.telegram.commands.reply.make_reply`
like ``/printtimeout``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ..context import RunContext
from ..runner_bridge import RunningTasks
from ..scheduler import ThreadScheduler
from ..utils.proc_diag import collect_proc_diag
from . import at_scheduler
from .commands.reply import make_reply
from .types import TelegramIncomingMessage

if TYPE_CHECKING:
    from .bridge import TelegramBridgeConfig

_EMPTY_REPLY = "😴 No active runs in this chat."
_FOOTER = "Reply /cancel to a run's progress message to stop it."


def _aliveness_marker(pid: int | None) -> str:
    """Render pid liveness: ``alive``/``exited``/``?`` (no pid or no diag)."""
    if pid is None:
        return "?"
    diag = collect_proc_diag(pid)
    if diag is None:
        return "?"
    return "alive" if diag.alive else "exited"


def _running_line(
    *,
    engine: str | None,
    started_at: float,
    pid: int | None,
    trigger_source: str | None,
    now: float,
) -> str:
    """Compose one running-task line: engine · elapsed · pid (alive) · trigger."""
    parts = [f"🏃 **{engine or '?'}**"]
    if started_at != 0.0:
        elapsed_min = max(0, int((now - started_at) // 60))
        parts.append(f"{elapsed_min}m")
    pid_str = str(pid) if pid is not None else "?"
    parts.append(f"pid {pid_str} ({_aliveness_marker(pid)})")
    if trigger_source:
        parts.append(f"⏰ {trigger_source}")
    return " · ".join(parts)


async def handle_jobs_command(
    cfg: TelegramBridgeConfig,
    msg: TelegramIncomingMessage,
    *,
    running_tasks: RunningTasks,
    scheduler: ThreadScheduler,
    ambient_context: RunContext | None,
) -> None:
    """Reply with a snapshot of running/queued/pending work in this chat.

    ``ambient_context`` is accepted for signature parity with every other
    builtin command handler (and the wire-up call site) but is not consumed —
    scoping here comes entirely from ``msg.chat_id`` matched against each
    source's own chat-scoped accessor.
    """
    reply = make_reply(cfg, msg)
    chat_id = msg.chat_id
    now = time.monotonic()

    matches = [
        (ref, task) for ref, task in running_tasks.items() if ref.channel_id == chat_id
    ]
    matches.sort(key=lambda pair: pair[1].started_at)

    running_lines = [
        _running_line(
            engine=task.engine,
            started_at=task.started_at,
            pid=task.pid,
            trigger_source=(
                task.context.trigger_source if task.context is not None else None
            ),
            now=now,
        )
        for _, task in matches
    ]

    queued_count = len(scheduler.queued_for_chat(chat_id))
    pending_count = len(at_scheduler.pending_for_chat(chat_id))

    if not running_lines and queued_count == 0 and pending_count == 0:
        await reply(text=f"{_EMPTY_REPLY}\n\n{_FOOTER}")
        return

    lines: list[str] = list(running_lines)
    if queued_count:
        lines.append(f"⏳ {queued_count} queued")
    if pending_count:
        suffix = "s" if pending_count != 1 else ""
        lines.append(f"⏰ {pending_count} pending /at run{suffix}")

    lines.append("")
    lines.append(_FOOTER)

    await reply(text="\n".join(lines))
