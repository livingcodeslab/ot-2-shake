# Firmware provenance

The bench unit was updated from v1.0.4 to **v1.1.5** with owner approval.
The [official tagged build recipe](https://github.com/Opentrons/buildroot/blob/v1.19.13/package/opentrons/opentrons-heater-shaker-firmware/opentrons-heater-shaker-firmware.mk)
pins v1.1.5. The [official image](https://opentrons-modules-builds.s3.us-east-2.amazonaws.com/heater-shaker/v1.1.5/heater-shaker@v1.1.5.bin)
is 177,856 bytes and matches the [manufacturer checksum](https://github.com/Opentrons/buildroot/blob/v1.19.13/package/opentrons/opentrons-heater-shaker-firmware/opentrons-heater-shaker-firmware.hash):

```text
e26ad3ce3bde898f0b23ea38f5b7af1148b3effbcf99c5234de8bae7f47eaff8
```

The local update used dfu-util 0.11, preserving startup and factory data. Only
unchanged application bytes from offset `0x8000` were written at `0x08008000`.
The application is 145,088 bytes with SHA-256:

```text
46eae0f3724d8df65ec3634ed9c6d26c8be2ccfc83cbdc2574c84d14c2740b52
```

A complete backup preceded writing. Full readback verified the exact application
bytes and unchanged startup, backup, factory data, and all bytes outside the
programmed pages before restart. Normal identification after power cycling
reported v1.1.5 and the same serial.

An initial USB descriptor failure blocked backup before any firmware write.
Reconnecting USB restored communication; exact device-identity filtering was
retained. No protection bypass, force, unprotect, option-byte write, or mass erase
was used.

This was a Mac USB adaptation of the official application-only layout, not a
published Opentrons Mac update wizard. This repo provides no automatic firmware
updater or device flash dumps. Consult current manufacturer guidance before
updating another unit. Successful updating does not establish the cause of the
earlier communication failure.

- [Official flash targets](https://github.com/Opentrons/opentrons-modules/blob/heater-shaker%40v1.1.5/stm32-modules/heater-shaker/README.md)
- [Memory layout](https://github.com/Opentrons/opentrons-modules/blob/heater-shaker%40v1.1.5/stm32-modules/common/STM32F303/STM32F303RETx_FLASH.ld)
- [Recovery design](https://github.com/Opentrons/opentrons-modules/blob/heater-shaker%40v1.1.5/stm32-modules/common/module-startup/README.md)
