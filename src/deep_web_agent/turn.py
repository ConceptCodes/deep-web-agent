"""Execute a turn and report its activity and outcome independently of Rich."""

from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass
from enum import IntEnum
import json
from typing import Any

from deep_web_agent.activity import sanitize_activity
from deep_web_agent.audit import create_audit_handler


class TurnOutcome(IntEnum):
    COMPLETE = 0
    FAILED = 1
    CANCELLED = 130


@dataclass(frozen=True)
class TurnUpdate:
    activity: tuple[str, ...] = ()
    response: str | None = None
    status: str = "Working"
    finished: bool = False


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(
        block["text"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") in {"text", "output_text"}
        and isinstance(block.get("text"), str)
    )


def _updates(part: dict, seen_calls: set[str], verbose: bool) -> Iterator[TurnUpdate]:
    if part.get("type") != "updates":
        return
    for node_name, update in part["data"].items():
        if not isinstance(update, dict):
            continue
        if isinstance(update.get("todos"), list):
            entries = ["QA checklist updated"]
            for todo in update["todos"]:
                if not isinstance(todo, dict):
                    continue
                state = str(todo.get("status", "pending"))
                marker = {"completed": "✓", "in_progress": "→"}.get(state, "○")
                entries.append(f"  {marker} [{state}] {todo.get('content', '')}")
            yield TurnUpdate(activity=tuple(entries))
        messages = update.get("messages", ())
        if not isinstance(messages, (list, tuple)):
            messages = (messages,) if messages else ()
        for message in messages:
            for call in getattr(message, "tool_calls", ()):
                call_id = call.get("id") or f"{node_name}:{call.get('name')}:{len(seen_calls)}"
                if call_id in seen_calls:
                    continue
                seen_calls.add(call_id)
                name = str(call.get("name", "tool"))
                args = call.get("args")
                rendered = json.dumps(sanitize_activity(args), ensure_ascii=False) if args else ""
                yield TurnUpdate(
                    activity=(f"→ {name} {rendered}".rstrip(),), status=f"Running {name}"
                )
            message_type = getattr(message, "type", None)
            if message_type == "tool":
                name = str(getattr(message, "name", "tool"))
                result = _text_content(getattr(message, "content", ""))
                entry = (
                    f"← {name}:\n{result}"
                    if verbose and result
                    else f"← {name} returned ({len(result)} characters)"
                )
                yield TurnUpdate(activity=(entry,))
            elif message_type == "ai":
                answer = _text_content(getattr(message, "content", ""))
                if answer:
                    yield TurnUpdate(response=answer, status="Preparing response")


def run_turn(
    agent: Any,
    memory: Any,
    prompt: str,
    thread_id: str,
    emit: Callable[[TurnUpdate], None],
    *,
    verbose: bool = False,
    audit_factory: Callable = create_audit_handler,
) -> TurnOutcome:
    """Own streaming, audit events, memory refresh, and a terminal turn outcome.

    A refresh failure is a warning after a completed response. Execution or audit
    failures fail the turn. Emitted text is plain data; renderers must escape it.
    """
    audit = None
    try:
        audit = audit_factory()
        config = {"configurable": {"thread_id": thread_id}, "callbacks": [audit]}
        emit(TurnUpdate(activity=(f"Audit log: {audit.path}", "Request sent")))
        seen_calls: set[str] = set()
        with closing(agent.stream(
            {"messages": [{"role": "user", "content": prompt}]},
            config=config,
            stream_mode=["updates"],
            version="v2",
        )) as stream:
            for part in stream:
                for update in _updates(part, seen_calls, verbose):
                    emit(update)

        refresh_failed = False
        try:
            agent.update_state(config, {"memory_contents": memory.load_contents()})
        except Exception as error:
            refresh_failed = True
            audit.log_event("memory_refresh_failed", error_type=type(error).__name__)
            emit(TurnUpdate(activity=("Could not refresh saved memory for the next turn.",)))
        else:
            audit.log_event("memory_refreshed")
        audit.log_event("turn_finished", memory_refreshed=not refresh_failed)
        emit(TurnUpdate(
            activity=("Turn finished",),
            status="Complete (memory refresh failed)" if refresh_failed else "Complete",
            finished=True,
        ))
        return TurnOutcome.COMPLETE
    except KeyboardInterrupt:
        outcome = TurnOutcome.CANCELLED
        event, status, fields = "turn_cancelled", "Turn cancelled", {}
    except Exception as error:
        outcome = TurnOutcome.FAILED
        event = "turn_failed"
        status = f"Run failed ({type(error).__name__})"
        fields = {"error_type": type(error).__name__}

    entries = [status]
    if audit is not None:
        try:
            audit.log_event(event, **fields)
        except Exception:
            entries.append("Could not write the final audit event.")
    emit(TurnUpdate(activity=tuple(entries), status=status, finished=True))
    return outcome
