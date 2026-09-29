"""Rich interactive terminal interface for Deep Web Agent."""

from __future__ import annotations

import argparse
import uuid
from typing import Any

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.text import Text

from deep_web_agent.turn import TurnUpdate, run_turn

_ACTIVITY_VIEW_LINES = 3


def _clean_terminal_text(value: str) -> str:
    """Remove control characters before displaying untrusted text in a terminal."""
    return "".join(char if char.isprintable() or char in "\n\t" else " " for char in value)


def _append_activity(console: Console, activity: list[str], entry: str) -> None:
    """Keep the complete activity in terminal scrollback and in the live view."""
    activity.append(entry)
    console.print(Text(entry), soft_wrap=True, highlight=False)


def _view(response: str, activity: list[str], status: str, finished: bool = False) -> Group:
    response_view = Markdown(response) if response else Text("Waiting for the model…", style="dim")
    activity_view = Text("\n".join(activity[-_ACTIVITY_VIEW_LINES:]) or "Preparing request…")
    status_style = "green" if status == "Complete" else "yellow"
    if status.startswith("Run failed"):
        status_style = "red"
    status_view = (
        Text(status, style=status_style)
        if finished
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
) -> int:
    response = ""
    activity: list[str] = []
    with Live(
        _view(response, activity, "Working"),
        console=console,
        refresh_per_second=10,
        transient=False,
    ) as live:
        def render(update: TurnUpdate) -> None:
            nonlocal response
            for entry in update.activity:
                _append_activity(console, activity, _clean_terminal_text(entry))
            if update.response is not None:
                response = _clean_terminal_text(update.response)
            live.update(_view(
                response, activity, _clean_terminal_text(update.status), update.finished
            ))

        return int(run_turn(
            agent, memory_setup, prompt, thread_id, render, verbose=verbose
        ))


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
        from deep_web_agent.agent import agent_session
        from deep_web_agent.settings import settings

        with agent_session() as session:
            return _chat(session.agent, session.memory, settings.model_id, args, console)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Cancelled.[/bold yellow]")
        return 130
    except Exception as error:
        console.print(
            f"[bold red]Could not run the agent[/bold red] ({type(error).__name__}). "
            "Check configuration, browser installation, and filesystem access."
        )
        return 1


def _chat(agent: Any, memory_setup: Any, model_id: str, args: argparse.Namespace, console: Console) -> int:
    console.print(
        Panel.fit(
            Text.assemble(
                ("Deep Web Agent", "bold cyan"),
                (f"\nModel: {model_id}", "dim"),
            ),
            border_style="cyan",
            box=box.ROUNDED,
        )
    )

    thread_id = str(uuid.uuid4())
    if args.once is not None:
        return _run_turn(agent, memory_setup, args.once, thread_id, console, args.verbose)

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
