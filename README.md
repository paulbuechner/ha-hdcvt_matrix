# HDCVT HDMI Matrix — Home Assistant integration

Local control for HDCVT web-controlled HDMI matrices (tested on **HDP-MXC88A**, 8×8, 18 Gbps). No cloud, no polling of anything but the device itself.

Routing, presets, power, per-port video settings, de-embedded audio and CEC are all covered. The protocol was reverse-engineered from the device's own web interface; see [Protocol notes](#protocol-notes).

## Quick start

### Using HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=paulbuechner&repository=ha-hdcvt_matrix&category=integration)

1. Use the button above, or add `paulbuechner/ha-hdcvt_matrix` as a custom repository in HACS
2. Download the integration and restart Home Assistant

### Manual installation

1. Copy `custom_components/hdcvt_matrix` into your Home Assistant `config/custom_components/`
2. Restart Home Assistant

### Setup

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=hdcvt_matrix)

1. The matrix is usually found on its own — check *Settings → Devices & Services* for a discovered card
2. Otherwise use the button above, or *Add Integration* and search for **HDCVT HDMI Matrix**
3. Enter the matrix's IP address
4. Leave **Use the factory credentials** ticked unless you changed the web interface login

Ten entities appear straight away: power, one routing select per output, and preset recall. Everything else is [opt-in](#only-ten-entities-are-enabled-by-default).

## Entities

| Entity | Platform | Notes |
| --- | --- | --- |
| Power | `switch` | On, or standby |
| *one per output* | `select` | Which input feeds that output |
| Preset | `select` | Recalls a stored routing preset |
| Save *preset* | `button` | Overwrites a preset with the current routing |
| *output* HDCP | `select` | HDCP 1.4 / 2.2 / follow sink / follow source / off |
| *output* scaler | `select` | Bypass / 4K to 1080p / auto |
| *output* stream | `switch` | Enable or disable the HDMI output |
| *output* audio mute | `switch` | Mute the output's audio |
| *output* ARC | `switch` | Audio return channel |
| *input* EDID | `select` | One of 47 firmware profiles, plus user slots and copy-from-output |
| *input* signal | `binary_sensor` | A source is detected, diagnostic |
| *output* display | `binary_sensor` | A sink is detected, diagnostic |
| *output* display on / off | `button` | Powers the attached display over CEC |
| Audio mode | `select` | Bind to input / bind to output / audio matrix |
| *output* audio source | `select` | De-embedded audio routing, matrix mode only |
| *output* audio out | `switch` | Enables a de-embedded audio output |
| Front panel lock | `switch` | Locks the physical buttons |
| Beeper | `switch` | Front panel beep |
| Serial baud rate | `select` | RS-232 control port, 4800 to 115200 |
| Panel backlight timeout | `select` | Always on, through to 10 minutes |
| Reboot | `button` | Restarts the matrix |
| Clear *preset* | `button` | Empties a preset slot |
| *output* display volume up / down / mute | `button` | Over CEC |
| *input* / *output* / *preset* name | `text` | Renames it on the device |

Renaming a port renames its Home Assistant entities too, since every per-port entity takes its name from the device. Ports allow 32 characters, presets 49.

The de-embedded audio outputs are a second matrix with their own mode. In the two bind modes the audio follows a video port and routing sent to it is ignored, so those selects report unavailable outside **audio matrix** mode rather than silently doing nothing.

CEC is one-way here: the matrix sends the command but cannot report whether the display obeyed, or what state it is in. Hence buttons rather than a switch. They stay available even when no sink is detected, because a display in standby may drop hotplug detect — which would otherwise hide the button that wakes it.

Port counts come from the device, so a 4×4 gets four routing selects and an 8×8 gets eight.

### Only ten entities are enabled by default

An 8×8 exposes around ninety entities. Adding them all would bury the handful anyone routinely uses, so a fresh install enables only **power, the eight routing selects, and preset recall**. Everything else is registered but disabled — enable what you want under *Settings → Devices & Services → HDCVT HDMI Matrix → entities*, filtering by **Disabled**.

Home Assistant groups them on the device page the same way the matrix's own web UI does: routing under *Controls*, per-port and front-panel settings under *Configuration*, and signal detection under *Diagnostic*.

Everything except Power goes unavailable while the matrix is in standby. Power never does — including when the matrix answers a status read with nothing useful, which would otherwise leave no way to switch it back on.

The preset select reads `unknown` until you pick one. That is deliberate: the firmware reports preset *names* but never which one is active, and there is no command to read a preset's stored routing back, so any other value would be a guess. Routing an individual output after recalling a preset likewise leaves the select showing the preset you last chose.

## Install

**HACS** → Custom repositories → add this repo as an *Integration* → download → restart Home Assistant.

**Manual** — copy `custom_components/hdcvt_matrix` into your HA `config/custom_components/`, then restart.

## Configure

Matrices are auto-discovered via DHCP and appear under *Settings → Devices & Services*. To add one by hand: *Add Integration* → **HDCVT HDMI Matrix** → enter the IP.

Credentials are the ones for the matrix **web interface**, not your HA account. Leave them empty if the matrix has no login configured.

## Protocol notes

Reverse-engineered from the device web UI. Everything is `POST /cgi-bin/instr` with a JSON body keyed by `comhead`.

```bash
curl -s -X POST http://<matrix>/cgi-bin/instr \
  -H 'Content-Type: application/json' \
  -d '{"comhead":"get video status"}'
```

| Command | Payload | Notes |
| --- | --- | --- |
| `login` | `user`, `password` | `result: 1` ok, `result: 0` rejected |
| `get status` | — | model, MAC, firmware, hostname |
| `get video status` | — | `allsource`, port and preset names |
| `get output status` | — | `allconnect`, HDCP, scaler, mute |
| `get input status` | — | `inactive`, EDID |
| `get network` | — | DHCP, ports, hostname |
| `video switch` | `source: [output, input]` | both one-based |
| `set poweronoff` | `power: 0\|1` | |
| `preset set` | `index` | one-based, recalls a stored preset |
| `preset save` | `index` | stores the current routing |
| `preset clear` | `index` | |
| `preset name` | `index`, `name` | note the key order differs from the two below |
| `set input name` | `name`, `index` | |
| `set output name` | `name`, `index` | |
| `tx stream` | `out: [output, 0\|1]` | enable the output |
| `set output audio mute` | `mute: [output, 0\|1]` | |
| `tx hdcp` | `hdcp: [output, mode]` | 1=1.4, 2=2.2, 3=follow sink, 4=follow source, 5=off |
| `set video scaler` | `scaler: [output, mode]` | 0=bypass, 1=4K→1080p, 3=auto. **Not** `video scaler`, which the web UI's own command map claims and the firmware rejects |
| `set panel lock` | `lock: 0\|1` | scalar, not an array |
| `set beep` | `beep: 0\|1` | scalar, not an array |
| `set edid` | `edid: [input, id]` | 1-36 fixed profiles, 37-39 user slots, 40-47 copy from an output |
| `set arc` | `arc: [output, 0\|1]` | |
| `ext-audio switch` | `source: [output, input]` | de-embedded audio routing |
| `set ext-audio out` | `out: [output, 0\|1]` | |
| `set ext-audio mode` | `mode` | 0=bind to input, 1=bind to output, 2=audio matrix |
| `reboot` | `reboot: 1` | ~10s offline |
| `set lcd on time` | `lcd on time` | this is the `mode` field in `get system status` |
| `set baudrate` | `baudrate` | ids start at **1**: 1=4800 … 6=115200 |
| `set tpg` | — | named in the web UI's command map but never called, so its payload is unknown |
| `set factory` | `factory: 1` | not exposed |
| `cec command` | `object`, `port`, `index` | `object` 0=input 1=output; `port` is a **mask over all ports**, not a port number; outputs number power as 0=on 1=off, inputs as 1=on 2=off |
| `set cec index` | `inputindex`, `outputindex` | persists the UI's port selection; not needed, since `cec command` carries its own mask |

Two traps worth knowing:

- **Sessionless.** `login` validates credentials but issues no token, and every read answers unauthenticated. The integration verifies credentials at setup so a device-side password change surfaces as a reauth prompt, rather than pretending reads are protected.
- **Array fields carry a trailing aggregate.** On an 8×8, `allsource` and friends have 9 entries; the last is the "all ports" value the web UI uses for bulk controls. Only `allinputname` / `alloutputname` are sized to the real port count, so those size the matrix.

Unknown commands come back as plain text (`not wait comhead [...]`), not JSON.

## Development

> Home Assistant does not run on native Windows — `homeassistant.runner` imports `fcntl`, so pytest fails at collection no matter which Python you use. Run the tests in Linux.

```bash
docker run --rm -v "$PWD:/w" -w /w python:3.13 \
  bash -c "pip install -q -r requirements-dev.txt && pytest -q"
```

Linting works anywhere, since ruff needs no Home Assistant import:

```bash
ruff check . && ruff format --check .
```

Manifest, translation and config-flow validation, the same check CI runs:

```bash
docker run --rm -v "$PWD:/github/workspace" ghcr.io/home-assistant/hassfest
```

## License

MIT. Not affiliated with or endorsed by HDCVT.
