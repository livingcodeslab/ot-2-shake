# ot-2-shake — Opentrons Heater-Shaker control over USB

Python driver and CLI for an **Opentrons Heater-Shaker Module GEN1** connected
directly to a Mac or Linux PC. No OT-2/Flex robot or Opentrons app is required.
This is a community controller, not an Opentrons-certified application.
Companion project: [ot-2-temp](https://github.com/livingcodeslab/ot-2-temp).

| Property | Value |
| --- | --- |
| USB name / ID | `Heater/Shaker FS` / `0483:4853` |
| Heating | 37–95 °C; no active cooling |
| Shaking | 200–3000 RPM, clockwise 2 mm orbit |
| Host | macOS tested; Linux implementation not yet bench-tested |
| Requirements | Python 3.9+, pyserial 3.5, external power, USB data cable |

## Quick start

```sh
git clone https://github.com/livingcodeslab/ot-2-shake.git
cd ot-2-shake
./setup.sh
./hs ports
./hs status
./hs monitor --seconds 30
```

Turn the module on and allow the USB accessory if macOS asks. Setup creates a
local `.venv` and installs the pinned dependency. The commands above only read
information; they do not start heating or motion.

## Commands

| Command | Behavior |
| --- | --- |
| `./hs ports` | List serial ports without opening them |
| `./hs status` | Read identity, temperature, targets, speed, latch |
| `./hs monitor --seconds 30` | Bounded status monitoring |
| `./hs run --temperature 37 --seconds 60 --ready` | Heat only, then shutdown |
| `./hs run --rpm 200 --seconds 10 --ready` | Shake only, then shutdown |
| `./hs run --temperature 37 --rpm 200 --seconds 120 --ready` | Heat and shake, then shutdown |
| `./hs stop` | Request heater off and zero RPM; verify shutdown |
| `./hs latch close --ready` | Close labware latch |
| `./hs home --ready` | Rotate platform to indexed position |
| `./hs latch open --ready` | Open latch; firmware may require homing first |

Global selectors precede the command:

```sh
./hs --usb-serial YOUR_USB_SERIAL status
./hs --port /dev/ttyACM0 status
```

The USB serial differs from the module's `HSV...` serial. Multiple matching
devices require explicit selection. Explicit ports must still match the USB ID;
the controller also checks firmware identity. See `./hs --help`.

## Attended operation

Use compatible labware in the correct, firmly installed thermal adapter. Secure
the base in a suitable mount before shaking or homing. Check the plate, lid,
fill volume, and temperature limits. A closed latch reading alone does not prove
proper seating. Start with empty or water-only labware. `--ready` acknowledges
these physical checks; it is not a safety sensor.

- Stay beside the power switch and keep the computer awake and USB connected.
  On macOS, `caffeinate -i ./hs run ...` can inhibit idle sleep during the run.
- Low-speed runs briefly kickstart at about **300 RPM**. Homing also causes
  motion. Keep fingers clear of moving parts and the latch.
- Runs are limited to one hour. The timer begins after setpoint acknowledgements,
  **not after the sample reaches its target temperature**. Readback measures the
  module sensor, not calibrated liquid temperature.
- Completion, errors, Ctrl-C, and SIGTERM trigger independent heater-off and
  motor-stop attempts followed by status verification. Control errors are
  reported before cleanup; original errors and shutdown failures are retained.
- Sleep, USB disconnection, power loss, SIGKILL, and device faults can prevent
  software shutdown. **Switch off module power if control is lost or shutdown
  is unconfirmed.** The plate may remain hot afterward.
- Only one program should own the port. Interrupt the active run with Ctrl-C;
  another `hs stop` process cannot take over its exclusively held port.
- New runs, latch changes, and homing refuse to take over an active module.
  `stop` is a deliberate exception. Stop never implicitly homes or opens the
  latch. Firmware interlocks remain enabled.

There is no hardware watchdog or unattended-operation guarantee in this script.

## Linux setup

Install Python with venv support, then run `./setup.sh`. Debian/Ubuntu may need
the administrator to install `python3-venv`. Recreate `.venv` on Linux instead
of copying the Mac environment. Auto-discovery avoids hard-coded port names.
If serial access is denied, inspect the owning group (commonly `dialout`), have
the administrator grant membership, then log out and back in. Do not run the
controller as root or grant world-write access. Linux hardware testing is pending.

## Tests and bench results

```sh
.venv/bin/python -m unittest discover -s tests -v
```

The **25 offline tests** use fake serial links and never open hardware. They
cover framing, partial replies, error acknowledgements, timeout diagnostics,
selection, bounds, interrupts, shutdown, disk-full logging, and preserved errors.

On November 13, 2026, firmware v1.1.5 completed 200 RPM for 60 seconds, 500 RPM
for 60 seconds, and 37 °C plus 200 RPM for 120 seconds, with no communication
errors and verified shutdown. An earlier v1.0.4 heating run lost communication
and required physical power-off. Its cause remains unproven.

See [bench results and limitations](docs/BENCH_TESTS.md), [wire protocol](docs/PROTOCOL.md),
and [firmware provenance](docs/FIRMWARE.md). Runtime JSONL logs go to ignored
`logs/`. Selected historical logs have device IDs and port paths anonymized;
their measurements and timestamps are unchanged. Device flash backups stay local.

## Layout

```text
heater_shaker.py       Driver, CLI, timed runs, shutdown, audit logging
hs                    CLI wrapper using the project virtual environment
setup.sh              Create environment and install pyserial
requirements.txt      Pinned dependency
tests/                Offline regression tests
docs/                 Protocol, firmware, bench record, example transcripts
```

## Official references

- [Specifications](https://docs.opentrons.com/heater-shaker/product-specs/)
- [Serial framing](https://docs.opentrons.com/heater-shaker/g-code-concepts/)
- [Commands](https://docs.opentrons.com/heater-shaker/g-codes/)
- [Installation](https://docs.opentrons.com/heater-shaker/pre-installation/)
- [Thermal adapters](https://docs.opentrons.com/heater-shaker/adapters/)
