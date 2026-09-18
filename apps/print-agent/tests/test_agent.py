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


class LocalCupsTests(unittest.TestCase):
    """Очередь 3B-350B подключена к CUPS самого сервера по raw-сокету.

    `lpstat -v 3B-350B` → `socket://192.168.5.105:9100`: адрес принтера знает
    CUPS, поэтому агенту нужно только имя очереди. Порт 9100 — raw-порт
    принтера, а не порт CUPS, и в настройках MSB он не участвует.
    """

    def setUp(self):
        self.printer = {
            "mode": "cups_local",
            "name": "3B-350B",
            "media": "Custom.58x38mm",
        }

    def test_command_targets_local_queue(self):
        command = agent._local_cups_command(self.printer, "/tmp/label.pdf")
        self.assertEqual(
            command,
            ["lp", "-d", "3B-350B", "-o", "media=Custom.58x38mm", "/tmp/label.pdf"],
        )

    def test_no_host_or_port_in_command(self):
        """Локальная очередь не должна получать -h: CUPS и так локальный."""
        command = agent._local_cups_command(self.printer, "/tmp/label.pdf")
        self.assertNotIn("-h", command)
        self.assertFalse(any("9100" in part for part in command))

    def test_media_is_optional(self):
        command = agent._local_cups_command({**self.printer, "media": ""}, "/tmp/x.pdf")
        self.assertNotIn("-o", command)

    def test_missing_queue_name_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "имя локальной CUPS-очереди"):
            agent._local_cups_command({**self.printer, "name": ""}, "/tmp/x.pdf")

    def test_local_mode_bypasses_global_print_command(self):
        """Иначе этикетка уехала бы на A4: в проде MSB_PRINT_CMD='lp -d EPSON_L3250 {file}'."""
        with patch.object(agent, "print_via_local_cups") as local, patch.object(
            agent, "print_via_os"
        ) as via_os, patch.object(agent, "PRINT_CMD", "lp -d EPSON_L3250 {file}"):
            mode = agent.print_pdf(b"PDF", self.printer)
        self.assertEqual(mode, "cups_local")
        local.assert_called_once_with(b"PDF", self.printer)
        via_os.assert_not_called()


class TwoLocalQueuesTests(unittest.TestCase):
    """Бланки A4 и этикетки — две разные очереди одного CUPS сервера MSB.

    `office_printer_a4` печатает бланки, `3B-350B` — этикетки 58×38. Документ
    не должен попасть не в ту очередь: у бланка нет media-опции (размер задаёт
    драйвер A4-принтера), у этикетки — обязательна.
    """

    A4 = {"mode": "cups_local", "name": "office_printer_a4"}
    LABEL = {"mode": "cups_local", "name": "3B-350B", "media": "Custom.58x38mm"}

    def test_blank_goes_to_a4_queue_without_media(self):
        command = agent._local_cups_command(self.A4, "/tmp/blank.pdf")
        self.assertEqual(command, ["lp", "-d", "office_printer_a4", "/tmp/blank.pdf"])

    def test_queues_are_not_interchangeable(self):
        blank = agent._local_cups_command(self.A4, "/tmp/x.pdf")
        label = agent._local_cups_command(self.LABEL, "/tmp/x.pdf")
        self.assertNotEqual(blank[2], label[2])
        self.assertIn("office_printer_a4", blank)
        self.assertIn("3B-350B", label)
        self.assertNotIn("3B-350B", blank)

    def test_a4_local_mode_bypasses_global_print_command(self):
        """Бланк в локальную очередь, а не через MSB_PRINT_CMD старого Epson."""
        with patch.object(agent, "print_via_local_cups") as local, patch.object(
            agent, "print_via_os"
        ) as via_os, patch.object(agent, "PRINT_CMD", "lp -d EPSON_L3250 {file}"):
            mode = agent.print_pdf(b"PDF", self.A4)
        self.assertEqual(mode, "cups_local")
        local.assert_called_once_with(b"PDF", self.A4)
        via_os.assert_not_called()

    def test_missing_queue_name_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "имя локальной CUPS-очереди"):
            agent._local_cups_command({"mode": "cups_local", "name": ""}, "/tmp/x.pdf")


if __name__ == "__main__":
    unittest.main()
