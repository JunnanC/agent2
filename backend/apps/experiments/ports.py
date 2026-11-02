from collections.abc import Callable
from typing import Any

from apps.accounts.models import User

TaskTerminalHandler = Callable[..., object]

_task_terminal_handlers: list[TaskTerminalHandler] = []


def register_task_terminal_handler(handler: TaskTerminalHandler) -> None:
    if handler not in _task_terminal_handlers:
        _task_terminal_handlers.append(handler)


def request_task_terminal(
    *,
    task_id: str,
    terminal_target: str,
    trigger: str,
    context: Any,
    actor: User | None = None,
) -> None:
    for handler in _task_terminal_handlers:
        handler(
            task_id=task_id,
            terminal_target=terminal_target,
            trigger=trigger,
            context=context,
            actor=actor,
        )


def clear_task_terminal_handlers() -> None:
    _task_terminal_handlers.clear()
