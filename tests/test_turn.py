import io
import unittest
from argparse import Namespace
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, ToolMessage
from rich.console import Console

from deep_web_agent.cli import _chat, _run_turn
from deep_web_agent.turn import TurnOutcome, run_turn


class ReplayAgent:
    def __init__(self, parts=(), error=None):
        self.parts = parts
        self.error = error
        self.closed = False
        self.update_state = Mock()

    def stream(self, inputs, **kwargs):
        self.config = kwargs["config"]
        try:
            yield from self.parts
            if self.error:
                raise self.error
        finally:
            self.closed = True


def part(message):
    return {"type": "updates", "data": {"model": {"messages": [message]}}}


class TurnTests(unittest.TestCase):
    def setUp(self):
        self.audit = Mock(path="audit.jsonl")
        self.memory = Mock()
        self.memory.load_contents.return_value = {"/memories/insights.md": "saved"}
        self.updates = []

    def run_turn(self, agent, **kwargs):
        return run_turn(agent, self.memory, "hello", "thread", self.updates.append,
                        audit_factory=lambda: self.audit, **kwargs)

    def test_success_refreshes_memory_before_completion(self):
        agent = ReplayAgent([part(AIMessage(content="answer"))])
        result = self.run_turn(agent)
        self.assertEqual(result, TurnOutcome.COMPLETE)
        self.assertTrue(agent.closed)
        self.assertEqual(agent.config["configurable"]["thread_id"], "thread")
        agent.update_state.assert_called_once_with(
            agent.config, {"memory_contents": {"/memories/insights.md": "saved"}}
        )
        self.assertEqual([u.response for u in self.updates if u.response], ["answer"])
        self.assertTrue(self.updates[-1].finished)
        self.assertEqual([c.args[0] for c in self.audit.log_event.call_args_list],
                         ["memory_refreshed", "turn_finished"])

    def test_stream_failure_and_cancellation_close_stream_and_skip_refresh(self):
        for error, outcome in [(RuntimeError("private"), TurnOutcome.FAILED),
                               (KeyboardInterrupt(), TurnOutcome.CANCELLED)]:
            with self.subTest(outcome=outcome):
                agent = ReplayAgent(error=error)
                self.assertEqual(self.run_turn(agent), outcome)
                self.assertTrue(agent.closed)
                agent.update_state.assert_not_called()
                self.assertNotIn("private", str(self.updates))
                self.assertTrue(self.updates[-1].finished)

    def test_audit_creation_failure_does_not_start_agent(self):
        agent = Mock()
        result = run_turn(agent, self.memory, "hello", "thread", self.updates.append,
                          audit_factory=Mock(side_effect=OSError("private")))
        self.assertEqual(result, TurnOutcome.FAILED)
        agent.stream.assert_not_called()
        self.assertEqual(self.updates[-1].status, "Run failed (OSError)")

    def test_audit_write_failure_still_reports_failure(self):
        self.audit.log_event.side_effect = OSError("disk full")
        self.assertEqual(self.run_turn(ReplayAgent()), TurnOutcome.FAILED)
        self.assertIn("Could not write the final audit event.", self.updates[-1].activity)

    def test_memory_failure_is_explicit_warning_after_completed_response(self):
        self.memory.load_contents.side_effect = OSError("private")
        agent = ReplayAgent([part(AIMessage(content="answer"))])
        self.assertEqual(self.run_turn(agent), TurnOutcome.COMPLETE)
        self.assertEqual(self.updates[-1].status, "Complete (memory refresh failed)")
        agent.update_state.assert_not_called()
        self.audit.log_event.assert_any_call("memory_refresh_failed", error_type="OSError")

    def test_tool_dedup_checklist_and_full_verbose_output(self):
        call = AIMessage(content="", tool_calls=[
            {"id": "one", "name": "browser_fill", "args": {"value": "private"}}
        ])
        result = "a tool result " * 100
        agent = ReplayAgent([
            part(call), part(call),
            {"type": "updates", "data": {"todos": {"todos": [
                {"status": "completed", "content": "Checked page"}
            ]}}},
            part(ToolMessage(content=result, name="browser_fill", tool_call_id="one")),
        ])
        self.assertEqual(self.run_turn(agent, verbose=True), TurnOutcome.COMPLETE)
        entries = [entry for update in self.updates for entry in update.activity]
        self.assertEqual(len([s for s in entries if s.startswith("→")]), 1)
        self.assertNotIn("private", str(entries))
        self.assertIn("  ✓ [completed] Checked page", entries)
        self.assertIn(f"← browser_fill:\n{result}", entries)

    def test_cli_preserves_scrollback_and_returns_failure(self):
        output = io.StringIO()
        def replay(*args, **kwargs):
            from deep_web_agent.turn import TurnUpdate
            for index in range(8):
                args[4](TurnUpdate(activity=(f"activity-{index}",)))
            args[4](TurnUpdate(status="Run failed", finished=True))
            return TurnOutcome.FAILED
        with patch("deep_web_agent.cli.run_turn", side_effect=replay):
            code = _run_turn(None, None, "hello", "thread", Console(file=output), False)
        self.assertEqual(code, 1)
        for index in range(8):
            self.assertIn(f"activity-{index}", output.getvalue())

    def test_once_propagates_failure_and_cancellation(self):
        for code in (0, 1, 130):
            with patch("deep_web_agent.cli._run_turn", return_value=code):
                result = _chat(None, None, "test", Namespace(once="hello", verbose=False),
                               Console(file=io.StringIO()))
            self.assertEqual(result, code)


if __name__ == "__main__":
    unittest.main()
