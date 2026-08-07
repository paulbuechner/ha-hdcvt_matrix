# HDCVT HDMI Matrix — Home Assistant integration

Local control for HDCVT web-controlled HDMI matrices (tested on **HDP-MXC88A**, 8×8, 18 Gbps). No cloud, no polling of anything but the device itself.

> Status: early. Discovery, authentication and preset recall work. Per-output routing lands next.

## Entities

| Entity | Platform | Notes |
| --- | --- | --- |
| Power | `switch` | On, or standby |
| *one per output* | `select` | Which input feeds that output, by the names set on the device |
| Preset | `select` | Recalls a stored routing preset |

Port counts come from the device, so a 4×4 gets four routing selects and an 8×8 gets eight.

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
