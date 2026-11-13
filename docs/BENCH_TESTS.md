# Bench record — November 13, 2026

One Heater-Shaker GEN1 was tested from an Apple Silicon Mac using Python 3.9
and pyserial 3.5. The operator confirmed secured compatible empty or water-only
labware and base, suitability for 500 RPM, and attendance beside the power switch.

## Before updating firmware

An initial v1.0.4 heat-only 37 °C / 60-second attempt stopped answering after
about seven seconds, with last temperature 30.43 °C. Shutdown requests received
no complete replies and software shutdown was unconfirmed. The operator switched
off power. Neither overheating nor the cause of communication loss was established.

After restarting, read-only checks and 10-second heat/shake retests succeeded.
A later 120-second heat-only run peaked at 37.54 °C; its final 30 seconds ranged
36.89–37.16 °C, with verified shutdown. A subsequent 200 RPM run was deliberately
interrupted for the firmware update, and is not counted as a full 60-second pass.

## After updating to v1.1.5

Version and unchanged identity were checked after restart, followed by a
successful 10-second read-only monitor.

| Test | Interval | Active sensor readings | Shutdown |
| --- | --- | --- | --- |
| 200 RPM, heat off | 60 s | 186–210 RPM | Heater off, RPM 0/0 confirmed |
| 500 RPM, heat off | 60 s | 486–504 RPM | Heater off, RPM 0/0 confirmed |
| 37 °C + 200 RPM | 120 s | 186–210 RPM; 31.77–37.71 °C | Heater off, RPM 0/0 confirmed |

No firmware errors, timeouts, or run errors were logged in these three runs.
The latch stayed closed. The operator reported stable operation with no
splashing or unusual noise at 500 RPM. During the combined run's final 30 seconds,
temperature ranged **36.68–37.70 °C**. Final status was 37.40 °C, heater target off,
zero actual/target RPM, and latch closed.

Intervals start after setpoint acknowledgement, not after temperature settles.
These onboard readings are not calibrated liquid-temperature or external
tachometer measurements. Full-range, long-duration, unattended, Linux, homing,
and latch-actuation performance were not validated. Successful tests do not
prove the firmware caused or resolved the earlier communication failure.

## Evidence

- [Initial interruption](test-data/v1.0.4-heating-interruption.jsonl)
- [Heat-only on v1.0.4](test-data/v1.0.4-heat-37c-120s.jsonl)
- [200 RPM on v1.1.5](test-data/v1.1.5-shake-200rpm-60s.jsonl)
- [500 RPM on v1.1.5](test-data/v1.1.5-shake-500rpm-60s.jsonl)
- [Combined on v1.1.5](test-data/v1.1.5-heat-37c-shake-200rpm-120s.jsonl)

Serials were replaced with `BENCH-UNIT` / `BENCH-USB`, and the port with
`/dev/cu.usbmodemBENCH`. Measurements, timestamps, commands, and errors are
unchanged. Original logs and flash backups remain local to the lab.
