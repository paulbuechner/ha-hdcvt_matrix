# Firmware

Vendor firmware package for the HDP-MXC88A, as supplied by the seller
(bundle name `HDP-MX8K88H`, 2026-08-10).

> ## WARNING — verify your model before flashing
>
> This package is for the **HDP-MXC88A** only. Flashing firmware meant for a
> different model can permanently brick the matrix. This hardware is resold
> under several brands and bundle names — the zip itself is labeled
> `HDP-MX8K88H` while every file inside targets `HDP-MXC88A` — so the label
> on your unit or invoice is not proof. Trust only what the device itself
> reports, and flash nothing unless it says `HDP-MXC88A`:
>
> ```bash
> curl -s -X POST http://<matrix>/cgi-bin/instr \
>   -H 'Content-Type: application/json' -d '{"comhead":"get status"}'
> ```
>
> **If you are not certain, do not flash. Ask your seller to confirm the
> correct firmware for your exact unit.** Flashing is at your own risk; a
> failed or mismatched flash is not recoverable from the web UI.

Flashing also **factory-resets the user configuration**: routing, preset
names and stored presets are wiped (observed on the V1.00.16 → V1.00.19
upgrade). Note your routing before you start.

## Contents

| File | What it is |
| --- | --- |
| `IP_MODULE_RS02_firmware_HDP-MXC88A_10.01.17_V2.00.22_*.bin` | IP module and web UI V2.00.22 |
| `MCU_MAIN_HDP-MXC88A_V1.00.19.bin` | main MCU firmware V1.00.19 |
| `MCU_SUB_HDP-MXC88A_KEY_V1.00.08.bin` | front-panel key controller V1.00.08 |
| `HDMI2.1 Matrix Upgrade Guide.docx` | vendor's GTool walkthrough |
| `HDP-MXC88A Firmware Release Note.xlsx` | vendor release notes |

Upgrade per the vendor guide: GTool over IP with the "13 Byte" option
ticked. After flashing, verify with `get status` (or `r fw version!` on the
telnet CLI) and restore your routing by hand or from a saved preset.
