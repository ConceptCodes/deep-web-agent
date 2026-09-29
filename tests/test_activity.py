"""Regression checks for privacy at both activity output paths."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from langchain_core.messages import ToolMessage

from deep_web_agent.activity import sanitize_activity
from deep_web_agent.audit import AuditLogHandler
from types import SimpleNamespace

from deep_web_agent.turn import run_turn


def _format_tool_args(arguments):
    message = SimpleNamespace(
        type="ai", content="", tool_calls=[{"id": "call", "name": "example", "args": arguments}]
    )
    part = {"type": "updates", "data": {"model": {"messages": [message]}}}
    agent = Mock()
    agent.stream.return_value = (item for item in [part])
    memory = Mock()
    memory.load_contents.return_value = {}
    updates = []
    run_turn(agent, memory, "test", "thread", updates.append,
             audit_factory=lambda: Mock(path="audit.jsonl"))
    return next(entry.removeprefix("→ example").strip()
                for update in updates for entry in update.activity
                if entry.startswith("→ example"))


class ActivityTests(unittest.TestCase):
    def test_terminal_and_audit_share_recursive_policy(self):
        arguments = {
            "url": "https://user:private@example.com/search?q=private#private",
            "options": [{"Authorization": "Bearer private", "password": "private"}],
            "question": "private",
            "selector": "input[name=email]",
            "count": 3,
        }
        original = deepcopy(arguments)
        expected = {
            "url": "https://example.com/search?[REDACTED]",
            "options": [{"Authorization": "[REDACTED]", "password": "[REDACTED]"}],
            "question": "[REDACTED]",
            "selector": "input[name=email]",
            "count": 3,
        }
        terminal = _format_tool_args(arguments)
        with tempfile.TemporaryDirectory() as directory:
            with patch("deep_web_agent.audit._ensure_audit_root", return_value=Path(directory)):
                audit = AuditLogHandler()
                audit.on_tool_start(
                    {"name": "browser_navigate"}, "unused", inputs=arguments, run_id=uuid4()
                )
                records = [json.loads(line) for line in audit.path.read_text().splitlines()]
        self.assertEqual(json.loads(terminal), expected)
        self.assertEqual(records[-1]["arguments"], expected)
        self.assertNotIn("private", terminal)
        self.assertNotIn("private", json.dumps(records))
        self.assertEqual(arguments, original)

    def test_audit_sanitizes_fields_without_tool_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("deep_web_agent.audit._ensure_audit_root", return_value=Path(directory)):
                audit = AuditLogHandler()
                audit.log_event("example", token="private", details={"cookie": "private"})
                record = json.loads(audit.path.read_text().splitlines()[-1])
        self.assertEqual(record["token"], "[REDACTED]")
        self.assertEqual(record["details"], {"cookie": "[REDACTED]"})

    def test_audit_recognizes_timeout_strings_and_tool_message_errors(self):
        timeout = "Browser action timed out. Check the URL or selector and try again."
        outputs = [timeout, ToolMessage(content=timeout, tool_call_id="one"),
                   ToolMessage(content="Failure details", status="error", tool_call_id="two")]
        with tempfile.TemporaryDirectory() as directory:
            with patch("deep_web_agent.audit._ensure_audit_root", return_value=Path(directory)):
                audit = AuditLogHandler()
                for output in outputs:
                    audit.on_tool_end(output, run_id=uuid4())
                records = [json.loads(line) for line in audit.path.read_text().splitlines()][1:]
        self.assertEqual([record["status"] for record in records], ["error"] * 3)
        self.assertEqual(records[1]["result_characters"], len(timeout))

    def test_urls_preserve_destination_and_remove_private_parts(self):
        cases = {
            "https://example.com/path?x=private#private": "https://example.com/path?[REDACTED]",
            "http://user:private@[::1]:8080/path#private": "http://[::1]:8080/path",
            "https://example.com:invalid/path": "[REDACTED URL]",
            "https://example.com/password=private": "https://example.com/password=[REDACTED]",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(sanitize_activity({"href": url}), {"href": expected})

    def test_strings_are_redacted_then_bounded(self):
        self.assertEqual(sanitize_activity("Bearer private"), "Bearer [REDACTED]")
        self.assertEqual(sanitize_activity("password=private"), "password=[REDACTED]")
        for value in ({"selector": "a" * 501}, {"url": "https://example.com/" + "a" * 501}):
            result = next(iter(sanitize_activity(value).values()))
            self.assertEqual(len(result), 500 + len("…[truncated]"))
            self.assertTrue(result.endswith("…[truncated]"))

    def test_unknown_objects_are_not_rendered(self):
        class PrivateObject:
            def __str__(self):
                raise AssertionError("Must not stringify unknown values")

        self.assertEqual(
            json.loads(_format_tool_args({"extra": PrivateObject()})),
            {"extra": "<PrivateObject>"},
        )

    def test_terminal_control_characters_remain_escaped(self):
        rendered = _format_tool_args({"selector": "\x1b[31mexample\n"})
        self.assertNotIn("\x1b", rendered)
        self.assertNotIn("\n", rendered)
        self.assertEqual(json.loads(rendered), {"selector": "\x1b[31mexample\n"})

    def test_empty_terminal_arguments_and_json_values(self):
        self.assertEqual(_format_tool_args(None), "")
        self.assertEqual(_format_tool_args({}), "")
        self.assertEqual(sanitize_activity((True, None, 1.5)), [True, None, 1.5])


if __name__ == "__main__":
    unittest.main()
