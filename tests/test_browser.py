import threading
import unittest
from unittest.mock import Mock

from deep_web_agent.browser import BrowserSession
from deep_web_agent.tools import create_tools


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.page = Mock()
        self.page.is_closed.return_value = False
        self.page.url = "https://example.com/"
        self.page.title.return_value = "Example"
        self.context = Mock()
        self.context.new_page.return_value = self.page
        self.browser = Mock()
        self.browser.new_context.return_value = self.context
        self.playwright = Mock()
        self.playwright.chromium.launch.return_value = self.browser
        self.factory = Mock()
        self.factory.return_value.start.side_effect = self.start
        self.browser.close.side_effect = lambda: self.record("close")
        self.playwright.stop.side_effect = lambda: self.record("stop")
        self.session = BrowserSession(playwright_factory=self.factory)
        self.addCleanup(self.session.shutdown)

    def record(self, event):
        self.events.append((event, threading.get_ident()))

    def start(self):
        self.record("start")
        return self.playwright

    def test_actions_and_cleanup_use_one_owner_thread(self):
        self.session.run(lambda page: self.record("action"))
        self.session.run(lambda page: self.record("action"))
        self.session.shutdown()
        self.session.shutdown()
        self.assertEqual([name for name, _ in self.events], ["start", "action", "action", "close", "stop"])
        self.assertEqual(len({thread for _, thread in self.events}), 1)
        self.assertNotEqual(self.events[0][1], threading.get_ident())
        with self.assertRaises(RuntimeError):
            self.session.run(lambda page: None)

    def test_close_allows_reopening(self):
        self.session.run(lambda page: None)
        self.session.close()
        self.session.close()
        self.session.run(lambda page: None)
        self.assertEqual(self.factory.return_value.start.call_count, 2)

    def test_closed_page_releases_old_resources_before_restart(self):
        self.session.run(lambda page: None)
        self.page.is_closed.return_value = True
        self.session.run(lambda page: None)
        self.assertEqual([name for name, _ in self.events], ["start", "close", "stop", "start"])

    def test_partial_startup_failure_rolls_back(self):
        self.browser.new_context.side_effect = RuntimeError("context failed")
        with self.assertRaisesRegex(RuntimeError, "context failed"):
            self.session.run(lambda page: None)
        self.browser.close.assert_called_once()
        self.playwright.stop.assert_called_once()
        self.browser.new_context.side_effect = None
        self.session.run(lambda page: None)

    def test_launch_failure_stops_playwright(self):
        self.playwright.chromium.launch.side_effect = RuntimeError("launch failed")
        with self.assertRaisesRegex(RuntimeError, "launch failed"):
            self.session.run(lambda page: None)
        self.playwright.stop.assert_called_once()
        self.browser.close.assert_not_called()

    def test_close_failure_still_stops_playwright_and_shutdown_is_idempotent(self):
        self.session.run(lambda page: None)
        self.browser.close.side_effect = RuntimeError("close failed")
        with self.assertRaisesRegex(RuntimeError, "close failed"):
            self.session.shutdown()
        self.playwright.stop.assert_called_once()
        self.session.shutdown()

    def test_tools_share_session_and_close_can_reopen(self):
        tools = {tool.name: tool for tool in create_tools(self.session)}
        self.assertEqual(len(tools), 9)
        result = tools["browser_navigate"].invoke({"url": "https://example.com/"})
        self.assertIn("Title: Example", result)
        self.assertIn("session closed", tools["browser_close"].invoke({}))
        tools["browser_navigate"].invoke({"url": "https://example.com/"})
        self.assertEqual(self.factory.return_value.start.call_count, 2)


if __name__ == "__main__":
    unittest.main()
