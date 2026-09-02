"""Unit tests for per-job routing to a remote CUPS queue."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


AGENT_PATH = Path(__file__).resolve().parents[1] / "agent.py"
SPEC = importlib.util.spec_from_file_location("msb_print_agent", AGENT_PATH)
assert SPEC and SPEC.loader
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


class RemoteCupsTests(unittest.TestCase):
    def setUp(self):
        self.printer = {
            "mode": "cups_remote",
            "ip": "192.168.5.238",
            "port": 631,
            "name": "3B-350B",
            "media": "Custom.58x38mm",
        }

    def test_command_targets_remote_queue_and_media(self):
        command = agent._remote_cups_command(self.printer, "/tmp/label.pdf")
        self.assertEqual(
            command,
            [
                "lp",
                "-h",
                "192.168.5.238:631",
                "-d",
                "3B-350B",
                "-o",
                "media=Custom.58x38mm",
                "/tmp/label.pdf",
            ],
        )

    def test_media_is_optional(self):
        command = agent._remote_cups_command(
            {**self.printer, "media": ""}, "/tmp/label.pdf"
        )
        self.assertNotIn("-o", command)

    def test_remote_mode_bypasses_global_print_command(self):
        with patch.object(agent, "print_via_remote_cups") as remote, patch.object(
            agent, "print_via_os"
        ) as local:
            mode = agent.print_pdf(b"PDF", self.printer)
        self.assertEqual(mode, "cups_remote")
        remote.assert_called_once_with(b"PDF", self.printer)
        local.assert_not_called()

    def test_missing_host_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "IP компьютера"):
            agent._remote_cups_command({**self.printer, "ip": ""}, "/tmp/x.pdf")


if __name__ == "__main__":
    unittest.main()
