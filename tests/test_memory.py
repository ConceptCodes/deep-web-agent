import tempfile
import unittest
from pathlib import Path

from deep_web_agent.backend import initialize_backend
from deep_web_agent.memory import initialize_memory


class MemoryTests(unittest.TestCase):
    def test_refresh_reads_same_files_as_agent_route(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = initialize_memory(root)
            guidance = (root / "AGENTS.md").read_text()
            (root / "insights.md").write_text("Fresh notes")
            contents = memory.load_contents()
            self.assertEqual(contents["/memories/insights.md"], "Fresh notes")
            self.assertEqual(contents["/memories/AGENTS.md"], guidance)
            backend = initialize_backend(memory)
            downloads = backend.backend.download_files(memory.files)
            self.assertEqual([r.content.decode() for r in downloads], list(contents.values()))
            initialize_memory(root)
            self.assertEqual((root / "insights.md").read_text(), "Fresh notes")
            self.assertEqual((root / "AGENTS.md").read_text(), guidance)
            self.assertEqual([(p.paths, p.mode) for p in backend.permissions], [
                (["/memories/insights.md"], "allow"),
                (["/memories/**"], "deny"),
                (["/skills/**"], "deny"),
            ])

    def test_missing_file_is_skipped_but_unreadable_file_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = initialize_memory(root)
            (root / "insights.md").unlink()
            self.assertNotIn("/memories/insights.md", memory.load_contents())
            (root / "insights.md").mkdir()
            with self.assertRaises(OSError):
                memory.load_contents()


if __name__ == "__main__":
    unittest.main()
