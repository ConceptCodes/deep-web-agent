"""Rich interactive terminal interface for Deep Web Agent."""

from __future__ import annotations

import argparse
import json
import uuid
from collections.abc import Iterable
from typing import Any

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.text import Text

_ACTIVITY_VIEW_LINES = 3
_SENSITIVE_ARGUMENTS = {"value", "content", "text", "password", "token", "secret", "api_key"}


def _clean_terminal_text(value: str) -> str:
    """Remove control characters before displaying untrusted text in a terminal."""
    return "".join(char if char.isprintable() or char in "\n\t" else " " for char in value)


def _append_activity(console: Console, activity: list[str], entry: str) -> None:
    """Keep the complete activity in terminal scrollback and in the live view."""
    activity.append(entry)
    console.print(Text(entry), soft_wrap=True, highlight=False)


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _format_tool_args(args: Any) -> str:
    if not isinstance(args, dict) or not args:
        return ""
    safe_args = {
        key: "[redacted]" if key.lower() in _SENSITIVE_ARGUMENTS else value
        for key, value in args.items()
    }
    rendered = json.dumps(safe_args, ensure_ascii=False, default=str)
    return _clean_terminal_text(rendered)


def _messages_from_update(update: Any) -> Iterable[Any]:
    if not isinstance(update, dict):
        return ()
    messages = update.get("messages", ())
    if isinstance(messages, (list, tuple)):
        return messages
    return (messages,) if messages else ()


def _view(response: str, activity: list[str], status: str) -> Group:
    response_view = Markdown(response) if response else Text("Waiting for the model…", style="dim")
    activity_view = Text("\n".join(activity[-_ACTIVITY_VIEW_LINES:]) or "Preparing request…")
    status_view = (
        Text(status, style="green")
        if status == "Complete"
        else Spinner("dots", text=status, style="yellow")
    )
    return Group(
        Panel(Group(activity_view, status_view), title="Activity", border_style="yellow", box=box.ROUNDED),
        Panel(response_view, title="Assistant", border_style="cyan", box=box.ROUNDED),
    )


def _run_turn(
    agent: Any,
    memory_setup: Any,
    prompt: str,
    thread_id: str,
    console: Console,
    verbose: bool,
) -> None:
    from deep_web_agent.audit import create_audit_handler

    audit = create_audit_handler()
    response = ""
    activity: list[str] = []
    _append_activity(console, activity, f"Audit log: {audit.path}")
    _append_activity(console, activity, "Request sent")
    status = "Working"
    seen_calls: set[str] = set()
    config = {"configurable": {"thread_id": thread_id}, "callbacks": [audit]}

    try:
        with Live(
            _view(response, activity, status),
            console=console,
            refresh_per_second=10,
            transient=False,
        ) as live:
            stream = agent.stream(
                {"messages": [{"role": "user", "content": prompt}]},
                config=config,
                stream_mode=["updates"],
                version="v2",
            )

            for part in stream:
                part_type = part.get("type")
                if part_type == "updates":
                    for node_name, update in part["data"].items():
                        if isinstance(update, dict) and isinstance(update.get("todos"), list):
                            _append_activity(console, activity, "QA checklist updated")
                            for todo in update["todos"]:
                                if not isinstance(todo, dict):
                                    continue
                                state = str(todo.get("status", "pending"))
                                marker = {"completed": "✓", "in_progress": "→"}.get(state, "○")
                                task = _clean_terminal_text(str(todo.get("content", "")))
                                _append_activity(console, activity, f"  {marker} [{state}] {task}")

                        for message in _messages_from_update(update):
                            for call in getattr(message, "tool_calls", ()):
                                call_id = call.get("id") or f"{node_name}:{call.get('name')}:{len(seen_calls)}"
                                if call_id in seen_calls:
                                    continue
                                seen_calls.add(call_id)
                                name = _clean_terminal_text(str(call.get("name", "tool")))
                                args = _format_tool_args(call.get("args"))
                                _append_activity(console, activity, f"→ {name} {args}".rstrip())
                                status = f"Running {name}"

                            message_type = getattr(message, "type", None)
                            if message_type == "tool":
                                name = _clean_terminal_text(str(getattr(message, "name", "tool")))
                                result = _text_content(getattr(message, "content", ""))
                                if verbose and result:
                                    _append_activity(
                                        console,
                                        activity,
                                        f"← {name}:\n{_clean_terminal_text(result)}",
                                    )
                                else:
                                    _append_activity(
                                        console,
                                        activity,
                                        f"← {name} returned ({len(result)} characters)",
                                    )
                                status = "Working"

                            elif getattr(message, "type", None) == "ai":
                                answer = _text_content(getattr(message, "content", ""))
                                if answer:
                                    response = answer
                                    status = "Preparing response"

                    live.update(_view(response, activity, status))

            status = "Complete"
            _append_activity(console, activity, "Turn finished")
            audit.log_event("turn_finished")
            live.update(_view(response, activity, status))

        try:
            from deep_web_agent.memory import load_memory_sources

            agent.update_state(
                config,
                {"memory_contents": load_memory_sources(memory_setup)},
            )
            audit.log_event("memory_refreshed")
        except Exception as error:
            audit.log_event("memory_refresh_failed", error_type=type(error).__name__)
            console.print(
                "[yellow]Could not refresh saved memory for the next turn.[/yellow]"
            )

    except KeyboardInterrupt:
        _append_activity(console, activity, "Turn cancelled")
        audit.log_event("turn_cancelled")
        console.print("\n[bold yellow]Turn cancelled.[/bold yellow]")
    except Exception as error:
        error_name = _clean_terminal_text(type(error).__name__)
        _append_activity(console, activity, f"Run failed ({error_name})")
        audit.log_event("turn_failed", error_type=error_name)
        console.print(f"\n[bold red]Run failed[/bold red] ({error_name}). Check the model and network configuration.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chat with the browser-enabled Deep Web Agent.")
    parser.add_argument(
        "--once",
        metavar="PROMPT",
        help="run one prompt and exit instead of opening the interactive chat",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="show complete browser tool results in terminal activity output",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    console = Console()

    try:
        from deep_web_agent.agent import agent, memory_setup
        from deep_web_agent.settings import settings
    except Exception as error:
        console.print(
            f"[bold red]Could not start the agent[/bold red] ({_clean_terminal_text(type(error).__name__)}). "
            "Check your .env configuration."
        )
        return 1

    console.print(
        Panel.fit(
            Text.assemble(
                ("Deep Web Agent", "bold cyan"),
                (f"\nModel: {settings.model_id}", "dim"),
            ),
            border_style="cyan",
            box=box.ROUNDED,
        )
    )

    thread_id = str(uuid.uuid4())
    if args.once is not None:
        _run_turn(agent, memory_setup, args.once, thread_id, console, args.verbose)
        return 0

    console.print("Type [bold]/help[/bold] for commands; [bold]/quit[/bold] to exit.")
    while True:
        try:
            prompt = Prompt.ask("[bold green]You[/bold green]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            return 0

        if not prompt:
            continue
        if prompt in {"/quit", "/exit"}:
            console.print("[dim]Goodbye.[/dim]")
            return 0
        if prompt == "/help":
            console.print(
                "[bold]Commands[/bold]\n"
                "  /new   Start a fresh conversation thread\n"
                "  /help  Show this help\n"
                "  /quit  Exit the CLI"
            )
            continue
        if prompt == "/new":
            thread_id = str(uuid.uuid4())
            console.print("[dim]Started a fresh conversation thread.[/dim]")
            continue

        _run_turn(agent, memory_setup, prompt, thread_id, console, args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
