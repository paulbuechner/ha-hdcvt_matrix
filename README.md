# HDCVT HDMI Matrix — Home Assistant integration

Local control for HDCVT web-controlled HDMI matrices (tested on **HDP-MXC88A**, 8×8, 18 Gbps). No cloud, no polling of anything but the device itself.

> Status: early. Discovery, authentication and preset recall work. Per-output routing lands next.

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
| Front panel lock | `switch` | Locks the physical buttons |
| Beeper | `switch` | Front panel beep |

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
| `preset clear` | `index` | not yet used |
| `preset name` | `index`, `name` | not yet used |
| `tx stream` | `out: [output, 0\|1]` | enable the output |
| `set output audio mute` | `mute: [output, 0\|1]` | |
| `tx hdcp` | `hdcp: [output, mode]` | 1=1.4, 2=2.2, 3=follow sink, 4=follow source, 5=off |
| `set video scaler` | `scaler: [output, mode]` | 0=bypass, 1=4K→1080p, 3=auto. **Not** `video scaler`, which the web UI's own command map claims and the firmware rejects |
| `set panel lock` | `lock: 0\|1` | scalar, not an array |
| `set beep` | `beep: 0\|1` | scalar, not an array |
| `set edid` | `edid: [input, id]` | 1-36 fixed profiles, 37-39 user slots, 40-47 copy from an output |
| `set arc` | `arc: [output, 0\|1]` | |
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
