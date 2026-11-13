# Heater-Shaker USB protocol

115200 baud; ASCII commands terminated by LF. Requests are serialized with a
response awaited after each. Actuator commands are not automatically retried.

| Command | Purpose |
| --- | --- |
| `M115` | Firmware, model, serial |
| `M105` | Current temperature C and target T (or None) |
| `M123` | Current and target RPM |
| `M241` | Latch state |
| `M104 S37` | Set 37 °C heater target |
| `M106` | Heater off |
| `M3 S200` / `M3 S0` | Set speed / stop |
| `G28` | Home platform; causes motion |
| `M242` / `M243` | Open / close latch |

Errors can end in `OK`, so `ERR...` is checked first. The parser buffers partial
lines and rejects unexpected command acknowledgements. Bare `OK` is accepted;
queries still require their payload fields. Numeric fields must be finite.

Ordinary timeout is five seconds. Motor start, homing, and latch commands allow
40 seconds. Timeout logs record partial response bytes in hexadecimal. These
host timeouts are not hardware watchdogs.

Shutdown independently attempts `M106` and `M3 S0`, then verifies heater target
off and zero actual/target RPM. A successful write alone does not prove shutdown.
Firmware errors and lost communication can prevent confirmation. The CLI does
not expose arbitrary commands, firmware flashing, calibration writes, or PID tuning.

Source: [official command table](https://docs.opentrons.com/heater-shaker/g-codes/).
