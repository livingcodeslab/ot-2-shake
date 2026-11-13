"""Offline regression tests: fake serial and command links, never opens hardware."""
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import heater_shaker as hs


IDLE = {"temperature_c": 21.5, "target_c": None, "rpm": 0,
        "target_rpm": 0, "latch": "IDLE_CLOSED"}


class FakeSerial:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.writes = []

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def read_until(self, *args, **kwargs):
        return self.chunks.pop(0) if self.chunks else b""


class FakeLink:
    def __init__(self, fail=None, response=None):
        self.commands = []
        self.audit_events = []
        self.fail = fail or {}
        self.response = response or {}

    def audit(self, kind, value):
        self.audit_events.append((kind, value))

    def command(self, cmd, timeout=5):
        self.commands.append(cmd)
        if cmd in self.fail:
            raise self.fail[cmd]
        return self.response.get(cmd, cmd.split()[0] + " OK")


def port(name, vid=hs.VID, pid=hs.PID, usb="abc"):
    return SimpleNamespace(device=name, vid=vid, pid=pid, serial_number=usb)


class SerialProtocolTests(unittest.TestCase):
    def test_error_with_ok_is_not_success(self):
        for response in (b"ERR126:plate lock not closed OK\n",
                         b"async ERR126:plate lock not closed OK\n"):
            with self.subTest(response=response):
                dev = FakeSerial([response])
                with self.assertRaisesRegex(hs.ModuleError, "ERR126"):
                    hs.Link(dev).command("M3 S200")

    def test_partial_read_and_crlf(self):
        dev = FakeSerial([b"\r\n", b"M105 C:21.", b"36 T:None O", b"K\r\n"])
        reply = hs.Link(dev).command("M105")
        self.assertEqual(reply, "M105 C:21.36 T:None OK")
        self.assertEqual(dev.writes, [b"M105\n"])

    def test_wrong_command_ack_rejected(self):
        with self.assertRaisesRegex(hs.ModuleError, "Unexpected response"):
            hs.Link(FakeSerial([b"M104 OK\n"])).command("M106")

    def test_plain_ok_accepted(self):
        self.assertEqual(hs.Link(FakeSerial([b"OK\n"])).command("M106"), "OK")

    def test_timeout_is_bounded_without_retry(self):
        dev = FakeSerial([])
        with patch.object(hs.time, "monotonic", side_effect=[0, 6]):
            with self.assertRaisesRegex(hs.ModuleError, "Timed out"):
                hs.Link(dev).command("M104 S37", timeout=5)
        self.assertEqual(dev.writes, [b"M104 S37\n"])

    def test_timeout_audits_command_and_all_partial_bytes(self):
        partial = b"M105 C:\x00\xff"
        dev = FakeSerial([partial[:7], partial[7:]])
        events = []
        link = hs.Link(dev, lambda kind, value: events.append((kind, value)))
        with patch.object(hs.time, "monotonic", side_effect=[0, 0, 1, 6]):
            with self.assertRaisesRegex(hs.ModuleError, "Timed out waiting for M105"):
                link.command("M105", timeout=5)
        self.assertEqual(events, [("send", "M105"), ("timeout", {
            "command": "M105", "partial_response_hex": partial.hex()})])
        self.assertEqual(dev.writes, [b"M105\n"])

    def test_multiline_command_rejected_before_write(self):
        dev = FakeSerial([])
        with self.assertRaises(ValueError):
            hs.Link(dev).command("M115\nM3 S200")
        self.assertEqual(dev.writes, [])


class SelectionAndValidationTests(unittest.TestCase):
    def test_explicit_port_does_not_override_wrong_vid(self):
        with self.assertRaises(hs.ModuleError):
            hs.select_port([port("wrong", vid=1)], requested="wrong")

    def test_multiple_units_require_selection(self):
        ports = [port("one", usb="1"), port("two", usb="2")]
        with self.assertRaises(hs.ModuleError):
            hs.select_port(ports)
        self.assertEqual(hs.select_port(ports, usb_serial="2").device, "two")

    def test_wrong_module_identity_rejected(self):
        link = FakeLink(response={"M115": "M115 FW:v1 HW:Opentrons Tempdeck SerialNo:TD1 OK"})
        with self.assertRaises(hs.ModuleError):
            hs.HeaterShaker(link).identify()
        self.assertEqual(link.commands, ["M115"])

    def test_numeric_bounds_and_nonfinite_values(self):
        invalid = [(0, 37, None), (-1, 37, None), (3601, 37, None),
                   (float("nan"), 37, None), (float("inf"), 37, None),
                   (1, float("nan"), None), (1, float("inf"), None),
                   (1, 36, None), (1, 96, None), (1, None, 199),
                   (1, None, 3001), (1, None, 200.5), (1, None, None)]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                hs.validate_run(*values)
        hs.validate_run(1, 37, 200)
        hs.validate_run(3600, 95, 3000)

    def test_missing_ready_never_scans_or_opens_hardware(self):
        with patch.object(hs.list_ports, "comports") as ports, patch.object(hs.serial, "Serial") as serial:
            with patch("sys.stderr", io.StringIO()):
                self.assertEqual(hs.main(["run", "--temperature", "37", "--seconds", "1"]), 1)
            ports.assert_not_called()
            serial.assert_not_called()


class RunSafetyTests(unittest.TestCase):
    def test_disk_full_logging_cannot_block_shutdown(self):
        for failed_method in ("write", "flush"):
            with self.subTest(failed_method=failed_method):
                file = Mock()
                getattr(file, failed_method).side_effect = OSError("No space left on device")
                audit = hs.Audit.__new__(hs.Audit)
                audit.file = file
                dev = FakeSerial([b"M106 OK\n", b"M3 OK\n",
                                  b"M105 C:21.36 T:None OK\n",
                                  b"M123 C:0 T:0 OK\n",
                                  b"M241 STATUS:IDLE_CLOSED OK\n"])
                module = hs.HeaterShaker(hs.Link(dev, audit))
                with patch("sys.stderr", io.StringIO()) as warning:
                    state = module.stop()
                self.assertIsNone(audit.file)
                self.assertIsNone(state["target_c"])
                self.assertEqual(state["rpm"], 0)
                self.assertEqual(dev.writes, [b"M106\n", b"M3 S0\n", b"M105\n", b"M123\n", b"M241\n"])
                self.assertIn("Logging disabled", warning.getvalue())
                file.close.assert_called_once()
                audit.close()

    def test_setpoint_failure_still_stops_both_functions(self):
        link = FakeLink(fail={"M104 S37": hs.ModuleError("bad setpoint ack")})
        module = hs.HeaterShaker(link)
        with patch.object(module, "status", return_value=IDLE.copy()):
            with self.assertRaisesRegex(hs.ModuleError, "bad setpoint ack"):
                module.timed_run(1, temperature=37, emit=lambda _: None)
        self.assertEqual(link.commands, ["M104 S37", "M106", "M3 S0"])

    def test_motor_start_failure_after_heating_still_stops_both(self):
        link = FakeLink(fail={"M3 S200": hs.ModuleError("motor fault")})
        module = hs.HeaterShaker(link)
        with patch.object(module, "status", return_value=IDLE.copy()):
            with self.assertRaisesRegex(hs.ModuleError, "motor fault"):
                module.timed_run(1, temperature=37, rpm=200, emit=lambda _: None)
        self.assertEqual(link.commands, ["M104 S37", "M3 S200", "M106", "M3 S0"])

    def test_status_failure_and_ctrl_c_after_start_cleanup(self):
        for failure in (hs.ModuleError("read failed"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                link = FakeLink()
                module = hs.HeaterShaker(link)
                with patch.object(module, "status", side_effect=[IDLE.copy(), failure, IDLE.copy()]):
                    with self.assertRaises(type(failure)):
                        module.timed_run(1, temperature=37, emit=lambda _: None)
                self.assertEqual(link.commands, ["M104 S37", "M106", "M3 S0"])

    def test_run_error_is_logged_and_power_warning_precedes_first_stop(self):
        for failure in (hs.ModuleError("serial connection lost"), RuntimeError("unexpected runtime failure")):
            with self.subTest(failure=type(failure).__name__):
                link = FakeLink()
                module = hs.HeaterShaker(link)
                snapshots = []
                original_command = link.command
                warning = io.StringIO()

                def record_stop(cmd, timeout=5):
                    if cmd == "M106":
                        snapshots.append((list(link.audit_events), warning.getvalue()))
                    return original_command(cmd, timeout=timeout)

                with patch.object(link, "command", side_effect=record_stop):
                    with patch.object(module, "status", side_effect=[IDLE.copy(), failure, IDLE.copy()]):
                        with patch("sys.stderr", warning):
                            with self.assertRaises(type(failure)) as raised:
                                module.timed_run(1, temperature=37, emit=lambda _: None)
                self.assertIs(raised.exception, failure)
                self.assertEqual(len(snapshots), 1)
                self.assertEqual(snapshots[0][0], [("run_error", str(failure))])
                self.assertIn("switch off module power", snapshots[0][1].lower())
                self.assertIn(str(failure), snapshots[0][1])
                self.assertEqual(link.commands, ["M104 S37", "M106", "M3 S0"])

    def test_original_run_error_survives_failed_shutdown(self):
        link = FakeLink(fail={"M104 S37": hs.ModuleError("initial setpoint timeout"),
                              "M106": hs.ModuleError("heater stop timeout"),
                              "M3 S0": hs.ModuleError("motor stop timeout")})
        module = hs.HeaterShaker(link)
        with patch.object(module, "status", return_value=IDLE.copy()):
            with patch("sys.stderr", io.StringIO()):
                with self.assertRaises(hs.ModuleError) as raised:
                    module.timed_run(1, temperature=37, emit=lambda _: None)
        for message in ("initial setpoint timeout", "STOP NOT FULLY CONFIRMED",
                        "heater stop timeout", "motor stop timeout"):
            self.assertIn(message, str(raised.exception))
        self.assertEqual(link.commands, ["M104 S37", "M106", "M3 S0"])
        self.assertEqual(link.audit_events, [("run_error", "initial setpoint timeout")])

    def test_ctrl_c_is_preserved_without_premature_power_alarm(self):
        link = FakeLink()
        module = hs.HeaterShaker(link)
        interruption = KeyboardInterrupt()
        with patch.object(module, "status", side_effect=[IDLE.copy(), interruption, IDLE.copy()]):
            with patch("sys.stderr", io.StringIO()) as warning:
                with self.assertRaises(KeyboardInterrupt) as raised:
                    module.timed_run(1, temperature=37, emit=lambda _: None)
        self.assertIs(raised.exception, interruption)
        self.assertNotIn("CONTROL ERROR", warning.getvalue())
        self.assertEqual(link.commands, ["M104 S37", "M106", "M3 S0"])

    def test_open_latch_blocks_motor_before_mutation(self):
        link = FakeLink()
        module = hs.HeaterShaker(link)
        with patch.object(module, "status", return_value=dict(IDLE, latch="IDLE_OPEN")):
            with self.assertRaisesRegex(hs.ModuleError, "latch"):
                module.timed_run(1, rpm=200, emit=lambda _: None)
        self.assertEqual(link.commands, [])

    def test_existing_activity_is_not_stopped_or_overwritten(self):
        for state in (dict(IDLE, target_c=37), dict(IDLE, rpm=200), dict(IDLE, target_rpm=200)):
            with self.subTest(state=state):
                link = FakeLink()
                module = hs.HeaterShaker(link)
                with patch.object(module, "status", return_value=state):
                    with self.assertRaisesRegex(hs.ModuleError, "already active"):
                        module.timed_run(1, temperature=37, emit=lambda _: None)
                self.assertEqual(link.commands, [])

    def test_stop_attempts_motor_even_if_heater_off_fails(self):
        link = FakeLink(fail={"M106": hs.ModuleError("heater off failed")})
        module = hs.HeaterShaker(link)
        with patch.object(module, "status", return_value=IDLE.copy()):
            with self.assertRaisesRegex(hs.ModuleError, "STOP NOT FULLY CONFIRMED"):
                module.stop()
        self.assertEqual(link.commands, ["M106", "M3 S0"])

    def test_stop_failure_never_reports_success(self):
        link = FakeLink(fail={"M3 S0": hs.ModuleError("motor error")})
        module = hs.HeaterShaker(link)
        with patch.object(module, "status", return_value=IDLE.copy()):
            with self.assertRaisesRegex(hs.ModuleError, "STOP NOT FULLY CONFIRMED"):
                module.stop()
        self.assertNotIn("G28", link.commands)

    def test_timed_completion_stops_without_home_or_unlatch(self):
        link = FakeLink()
        module = hs.HeaterShaker(link)
        with patch.object(module, "status", return_value=IDLE.copy()):
            with patch.object(hs.time, "monotonic", side_effect=[0, 2, 2]):
                module.timed_run(1, temperature=37, emit=lambda _: None)
        self.assertEqual(link.commands, ["M104 S37", "M106", "M3 S0"])

    def test_latch_change_during_shaking_triggers_shutdown(self):
        link = FakeLink()
        module = hs.HeaterShaker(link)
        with patch.object(module, "status", side_effect=[IDLE.copy(), dict(IDLE, latch="IDLE_UNKNOWN"), IDLE.copy()]):
            with self.assertRaisesRegex(hs.ModuleError, "no longer confirmed closed"):
                module.timed_run(1, rpm=200, emit=lambda _: None)
        self.assertEqual(link.commands, ["M3 S200", "M106", "M3 S0"])


if __name__ == "__main__":
    unittest.main()
