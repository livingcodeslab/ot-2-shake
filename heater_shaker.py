#!/usr/bin/env python3
"""Direct USB control of Opentrons Heater-Shaker GEN1 (macOS/Linux).

No robot, firmware update, calibration changes, or background polling service.
Run --help. Commands other than ports/status/monitor/stop require --ready.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import signal
import sys
import time

import serial
from serial.tools import list_ports

VID, PID = 0x0483, 0x4853
BAUD = 115200
LOG_DIR = Path(__file__).resolve().parent / "logs"


class ModuleError(RuntimeError):
    pass


class Audit:
    def __init__(self):
        LOG_DIR.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        self.path = LOG_DIR / (stamp + ".jsonl")
        self.file = self.path.open("x", encoding="utf-8")

    def __call__(self, kind, value):
        if self.file is None:
            return
        try:
            self.file.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(),
                                        "kind": kind, "value": value}) + "\n")
            self.file.flush()
        except OSError as exc:
            # A full disk must never prevent sending the shutdown commands.
            failed_file, self.file = self.file, None
            try:
                failed_file.close()
            except OSError:
                pass
            try:
                print("WARNING: Logging disabled: " + str(exc), file=sys.stderr)
            except OSError:
                pass

    def close(self):
        if self.file is not None:
            self.file.close()


def select_port(ports, requested=None, usb_serial=None):
    candidates = [p for p in ports if (p.vid, p.pid) == (VID, PID)]
    if requested:
        candidates = [p for p in candidates if p.device == requested]
    if usb_serial:
        candidates = [p for p in candidates if p.serial_number == usb_serial]
    if len(candidates) != 1:
        raise ModuleError("Expected one Heater-Shaker USB device (0483:4853); found %d. "
                          "Run 'hs ports'; check power/data cable/accessory permission. "
                          "Use --port or --usb-serial to select among multiple units."
                          % len(candidates))
    return candidates[0]


class Link:
    def __init__(self, device, audit=lambda *args: None):
        self.device = device
        self.audit = audit
        self.pending = b""

    def command(self, command, timeout=5):
        if "\n" in command or "\r" in command:
            raise ValueError("Only one command per request")
        expected = command.split()[0]
        self.audit("send", command)
        self.device.write((command + "\n").encode("ascii"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pending += self.device.read_until(b"\n", size=4096)
            if len(self.pending) > 8192:
                raise ModuleError("Oversized serial response")
            while b"\n" in self.pending:
                raw, self.pending = self.pending.split(b"\n", 1)
                line = raw.decode("ascii", errors="strict").strip()
                if not line:
                    continue
                self.audit("receive", line)
                # Firmware errors may ALSO end in OK. Check errors first.
                if re.search(r"\berr\d+", line, re.I):
                    raise ModuleError(line)
                if line == "OK" or (line.startswith(expected + " ")
                                    and line.endswith(" OK")):
                    return line
                raise ModuleError("Unexpected response to %s: %s" % (command, line))
        self.audit("timeout", {"command": command,
                               "partial_response_hex": self.pending.hex()})
        raise ModuleError("Timed out waiting for %s; device state is uncertain" % command)


def number(line, field, allow_none=False):
    match = re.search(r"\b" + field + r":\s*(\S+)", line)
    if not match:
        raise ModuleError("Missing %s in %s" % (field, line))
    if allow_none and match.group(1).lower() == "none":
        return None
    try:
        value = float(match.group(1))
    except ValueError as exc:
        raise ModuleError("Invalid number in " + line) from exc
    if not math.isfinite(value):
        raise ModuleError("Non-finite number in " + line)
    return value


class HeaterShaker:
    def __init__(self, link):
        self.link = link

    def identify(self):
        reply = self.link.command("M115")
        if "Opentrons Heater-Shaker" not in reply or "SerialNo:" not in reply:
            raise ModuleError("Not a recognized Heater-Shaker: " + reply)
        return reply

    def status(self):
        temperature = self.link.command("M105")
        speed = self.link.command("M123")
        latch = self.link.command("M241")
        match = re.search(r"STATUS:\s*(\w+)", latch)
        if not match:
            raise ModuleError("Unrecognized latch response: " + latch)
        return {"temperature_c": number(temperature, "C"),
                "target_c": number(temperature, "T", True),
                "rpm": number(speed, "C"), "target_rpm": number(speed, "T", True),
                "latch": match.group(1)}

    def idle(self):
        state = self.status()
        if state["rpm"] != 0 or state["target_rpm"] not in (0, None) or state["target_c"] is not None:
            raise ModuleError("Module is already active; refusing to take over. Use stop deliberately.")
        return state

    def stop(self):
        errors = []
        # Independent attempts: a motor error must not prevent heater shutdown.
        for command in ("M106", "M3 S0"):
            try:
                self.link.command(command, timeout=5)
            except Exception as exc:
                errors.append(str(exc))
        try:
            deadline = time.monotonic() + 10
            while True:
                state = self.status()
                if (state["target_c"] is None and state["target_rpm"] in (0, None)
                        and state["rpm"] == 0):
                    break
                if time.monotonic() >= deadline:
                    raise ModuleError("Stop readback did not confirm heater off and zero RPM")
                time.sleep(0.25)
        except Exception as exc:
            errors.append(str(exc))
        if errors:
            raise ModuleError("STOP NOT FULLY CONFIRMED: " + "; ".join(errors)
                              + ". If needed, switch off module power. The plate may remain hot.")
        return state

    def latch(self, action):
        self.idle()
        # No implicit homing: opening an unhomed unit is rejected by firmware.
        self.link.command("M242" if action == "open" else "M243", timeout=40)
        desired = "IDLE_OPEN" if action == "open" else "IDLE_CLOSED"
        deadline = time.monotonic() + 15
        while True:
            state = self.status()
            if state["latch"] == desired:
                return state
            if time.monotonic() >= deadline:
                raise ModuleError("Latch did not reach " + desired)
            time.sleep(0.25)

    def timed_run(self, seconds, temperature=None, rpm=None, emit=print):
        validate_run(seconds, temperature, rpm)
        state = self.idle()
        if rpm is not None and state["latch"] != "IDLE_CLOSED":
            raise ModuleError("Close the labware latch before shaking")
        failure = None
        try:
            if temperature is not None:
                self.link.command("M104 S%g" % temperature)
            if rpm is not None:
                self.link.command("M3 S%d" % rpm, timeout=40)
            deadline = time.monotonic() + seconds
            while True:
                state = self.status()
                emit(state)
                if rpm is not None and state["latch"] != "IDLE_CLOSED":
                    raise ModuleError("Latch is no longer confirmed closed")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(1, remaining))
        except BaseException as exc:
            failure = exc
            getattr(self.link, "audit", lambda *args: None)("run_error", str(exc))
            if not isinstance(exc, KeyboardInterrupt):
                try:
                    print("CONTROL ERROR: %s. Switch off module power now; "
                          "shutdown is not yet confirmed. Attempting shutdown commands."
                          % exc, file=sys.stderr, flush=True)
                except OSError:
                    pass
            raise
        finally:
            with cleanup_signals():
                try:
                    stopped = self.stop()
                except Exception as stop_error:
                    if failure is not None:
                        raise ModuleError("Initial run failure: %s; %s"
                                          % (failure, stop_error)) from stop_error
                    raise
                emit(stopped)


def validate_run(seconds, temperature, rpm):
    if not math.isfinite(seconds) or not 0 < seconds <= 3600:
        raise ValueError("Duration must be >0 and <=3600 seconds")
    if temperature is None and rpm is None:
        raise ValueError("Supply --temperature, --rpm, or both")
    if temperature is not None and (not math.isfinite(temperature) or not 37 <= temperature <= 95):
        raise ValueError("Temperature must be 37–95 °C")
    if rpm is not None and (not isinstance(rpm, int) or not 200 <= rpm <= 3000):
        raise ValueError("Shaking must be an integer from 200–3000 RPM")


@contextmanager
def cleanup_signals():
    """Avoid a second Ctrl-C interrupting the best-effort shutdown."""
    old = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        for s in old:
            signal.signal(s, signal.SIG_IGN)
        yield
    finally:
        for s, handler in old.items():
            signal.signal(s, handler)


def show(state):
    target = "off" if state["target_c"] is None else "%g C" % state["target_c"]
    print("%s  %.2f C (target %s) | %g RPM (target %s) | %s" % (
        datetime.now().strftime("%H:%M:%S"), state["temperature_c"], target,
        state["rpm"], state["target_rpm"], state["latch"]), flush=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", help="Explicit port; must still have Heater-Shaker VID/PID")
    p.add_argument("--usb-serial", help="Select the USB serial shown by ports (not HSV serial)")
    commands = p.add_subparsers(dest="action", required=True)
    commands.add_parser("ports", help="List ports without opening any device")
    commands.add_parser("status", help="Read identification, temperature, speed, and latch")
    monitor = commands.add_parser("monitor", help="Read status once per second")
    monitor.add_argument("--seconds", type=float, default=30)
    commands.add_parser("stop", help="Heater off and zero RPM; no homing or unlatching")
    run = commands.add_parser("run", help="Timed heat/shake run; attempts shutdown on completion/error/Ctrl-C")
    run.add_argument("--temperature", type=float, help="37–95 C; omitted = no heating")
    run.add_argument("--rpm", type=int, help="200–3000 RPM; omitted = no shaking")
    run.add_argument("--seconds", type=float, required=True, help="Run duration after setpoint acknowledgements, not hold at target")
    run.add_argument("--ready", action="store_true", help="Confirm labware/adapter and mounting suitable; stay present")
    latch = commands.add_parser("latch", help="Move labware latch; keep fingers clear")
    latch.add_argument("position", choices=["open", "close"])
    latch.add_argument("--ready", action="store_true")
    home = commands.add_parser("home", help="Rotate to indexed position (causes motion), needed before unlatching")
    home.add_argument("--ready", action="store_true")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    audit = None
    try:
        if args.action == "run":
            validate_run(args.seconds, args.temperature, args.rpm)
        if args.action == "monitor" and (not math.isfinite(args.seconds) or not 0 < args.seconds <= 3600):
            raise ValueError("Monitoring duration must be >0 and <=3600 seconds")
        if args.action in ("run", "latch", "home") and not args.ready:
            raise ModuleError("Add --ready only after checking compatible secured labware, "
                              "clear latch, and suitable base mounting for any motion. Stay present.")
        ports = list(list_ports.comports())
        if args.action == "ports":
            for port in ports:
                print("%s | %s | %s" % (port.device, port.description, port.hwid))
            if not ports:
                print("No serial ports found")
            return 0
        port = select_port(ports, args.port, args.usb_serial)
        audit = Audit()
        audit("port", {"device": port.device, "usb_serial": port.serial_number})
        print("Log: " + str(audit.path), flush=True)
        with serial.Serial(port.device, BAUD, timeout=0.2, write_timeout=2, exclusive=True) as dev:
            module = HeaterShaker(Link(dev, audit))
            print(module.identify(), flush=True)
            if args.action == "status":
                show(module.status())
            elif args.action == "monitor":
                end = time.monotonic() + args.seconds
                while True:
                    show(module.status())
                    remaining = end - time.monotonic()
                    if remaining <= 0:
                        break
                    time.sleep(min(1, remaining))
            elif args.action == "stop":
                with cleanup_signals():
                    show(module.stop())
                print("Confirmed heater off and shaker stopped. Plate may remain hot.")
            elif args.action == "latch":
                show(module.latch(args.position))
            elif args.action == "home":
                state = module.idle()
                if state["latch"] != "IDLE_CLOSED":
                    raise ModuleError("Homing requires a closed latch")
                try:
                    module.link.command("G28", timeout=40)
                    state = module.status()
                    if state["rpm"] != 0 or state["target_rpm"] not in (0, None):
                        raise ModuleError("Homing acknowledged but zero speed not confirmed")
                    show(state)
                except BaseException:
                    with cleanup_signals():
                        module.stop()
                    raise
            elif args.action == "run":
                module.timed_run(args.seconds, args.temperature, args.rpm, show)
                print("Run complete; heater off and shaker stopped. Plate may remain hot.")
        return 0
    except KeyboardInterrupt:
        print("Interrupted. Check the shutdown readback/log; power off if stop is unconfirmed.", file=sys.stderr)
        return 130
    except (ModuleError, serial.SerialException, OSError, ValueError, UnicodeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        if audit:
            audit("error", str(exc))
        return 1
    finally:
        if audit:
            audit.close()


if __name__ == "__main__":
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    sys.exit(main())
