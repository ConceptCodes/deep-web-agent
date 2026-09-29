import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from deep_web_agent.agent import agent_session
from deep_web_agent.audit import AuditLogHandler
from deep_web_agent.cli import main
from deep_web_agent.turn import TurnOutcome, run_turn


class LocalModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class AgentTests(unittest.TestCase):
    def test_assembled_agent_streams_and_refreshes_real_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SimpleNamespace(openai_api_key=None, model_id="test", memory_dir=Path(directory))
            browser = Mock()
            with patch("deep_web_agent.agent.settings", settings), \
                 patch("deep_web_agent.agent.get_model", return_value=LocalModel(responses=[AIMessage(content="Done")])), \
                 patch("deep_web_agent.agent.BrowserSession", return_value=browser), \
                 patch("deep_web_agent.audit._ensure_audit_root", return_value=Path(directory)):
                audit = AuditLogHandler()
                with agent_session() as session:
                    (Path(directory) / "insights.md").write_text("Updated notes")
                    updates = []
                    result = run_turn(session.agent, session.memory, "Hello", "test", updates.append,
                                      audit_factory=lambda: audit)
                    self.assertEqual(result, TurnOutcome.COMPLETE)
                    self.assertEqual(updates[-1].status, "Complete")
                    state = session.agent.get_state({"configurable": {"thread_id": "test"}})
                    self.assertEqual(state.values["memory_contents"]["/memories/insights.md"], "Updated notes")
                    self.assertIn("Done", [u.response for u in updates])
                browser.shutdown.assert_called_once()

    def test_startup_failure_shuts_down_browser(self):
        browser = Mock()
        with patch("deep_web_agent.agent.get_model", side_effect=ValueError("missing key")), \
             patch("deep_web_agent.agent.BrowserSession", return_value=browser):
            with self.assertRaises(ValueError):
                with agent_session():
                    self.fail("Startup should have failed")
        browser.shutdown.assert_called_once()

    def test_cli_exit_and_exceptions_release_session(self):
        for outcome in (0, 1, 130, KeyboardInterrupt(), RuntimeError("private")):
            with self.subTest(outcome=outcome):
                browser = Mock()
                with patch("deep_web_agent.agent.BrowserSession", return_value=browser), \
                     patch("deep_web_agent.agent.get_model"), \
                     patch("deep_web_agent.agent.initialize_memory"), \
                     patch("deep_web_agent.agent.initialize_backend"), \
                     patch("deep_web_agent.agent.create_deep_agent"), \
                     patch("deep_web_agent.cli._parse_args", return_value=Namespace()), \
                     patch("deep_web_agent.cli.Console"), \
                     patch("deep_web_agent.cli._chat") as chat:
                    if isinstance(outcome, BaseException):
                        chat.side_effect = outcome
                    else:
                        chat.return_value = outcome
                    expected = 130 if isinstance(outcome, KeyboardInterrupt) else (
                        1 if isinstance(outcome, Exception) else outcome
                    )
                    self.assertEqual(main(), expected)
                browser.shutdown.assert_called_once()


if __name__ == "__main__":
    unittest.main()
