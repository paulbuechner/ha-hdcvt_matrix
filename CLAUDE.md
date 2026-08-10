# CLAUDE.md

## Home Assistant does not run on Windows

`homeassistant.runner` imports `fcntl`, so pytest dies at collection. Tests run
in Linux, always:

```bash
docker build -f Dockerfile.dev -t hdcvt-matrix-dev:latest .
docker run --rm -v "$PWD:/w" hdcvt-matrix-dev:latest pytest -q
docker run --rm -v "$PWD:/w" hdcvt-matrix-dev:latest mypy custom_components tests
docker run --rm -v "$PWD:/github/workspace" ghcr.io/home-assistant/hassfest
```

Ruff is the exception — it needs no HA import, so run it natively from the
`ha-hdcvt` conda env where that exists (the Windows machine). The macOS
machine has no such env; the dev image carries the pinned ruff, so run it in
Docker there. Docker Desktop does not autostart; launch it and the daemon is
up in ~10s.

Full green means: `ruff check` + `ruff format --check` + `mypy` + `pytest` +
`hassfest`. Run all five before saying something works.

## Deploying to the live matrix

The HA test instance's `config` share is mounted over SMB. The mount point
differs per dev machine, so the deploy commands below go through `$HA_CONFIG` —
set it once per shell, from Git Bash on Windows and any shell on macOS.

**Windows** — map the share to `Z:` (the `*` prompts for the password instead of
putting it in the command line):

```bash
net use Z: \\<ha-host>\config /user:<samba-user> *
export HA_CONFIG=/z
```

**macOS** — create the mount point once, then mount:

```bash
sudo mkdir -p /Volumes/homeassistant && sudo chown "$(id -un):$(id -gn)" /Volumes/homeassistant
mount_smbfs //<samba-user>@<ha-host>/config /Volumes/homeassistant
export HA_CONFIG=/Volumes/homeassistant
```

Two macOS traps: the mount point must be owned by the user or the mount fails
with `Operation not permitted`, and `mount_smbfs` ignores the keychain entry
Finder saves, so it needs an interactive terminal for the password prompt or it
fails with `Authentication error`.

Deploy:

```bash
rm -rf "$HA_CONFIG/custom_components/hdcvt_matrix"
cp -r custom_components/hdcvt_matrix "$HA_CONFIG/custom_components/hdcvt_matrix"
find "$HA_CONFIG/custom_components/hdcvt_matrix" -name __pycache__ -type d -exec rm -rf {} +
```

Then check it landed:

```bash
diff -r --brief custom_components/hdcvt_matrix "$HA_CONFIG/custom_components/hdcvt_matrix"
```

On macOS `.DS_Store` files turn up in that diff; `defaults write
com.apple.desktopservices DSDontWriteNetworkStores -bool true` (then re-login)
stops Finder writing them to network shares.

A **new platform** needs an HA restart; edits to an existing one need only a
reload of the config entry.

## The device protocol

Reverse-engineered from the web UI. All of it is `POST /cgi-bin/instr` with a
JSON body keyed by `comhead`. Four traps, each of which has already cost time:

- **Unknown commands fail in two shapes, neither of them JSON.** Plain text
  (`not wait comhead [...]`) — or, observed on fw V1.00.16 and V1.00.19, a
  body-less HTTP 200 that hangs until the client times out, stalling the
  single-threaded CGI for exactly that long. Parse defensively, probe with a
  short timeout, and space probes out.
- **The API is sessionless.** `login` validates credentials and returns
  `result: 1`/`0` but issues no token; every other command answers
  unauthenticated. Credentials are checked once at setup.
- **Array fields carry a trailing "all ports" aggregate.** On an 8x8 they have
  nine entries. Only `allinputname`/`alloutputname` are sized to the real port
  count, so use those to trim.
- **The web UI's command map lies in at least one place.** It calls the scaler
  command `video scaler`; the firmware only answers to `set video scaler`.
  Probe before trusting a comhead you have not seen work.

Besides `instr` the firmware serves `GET /cgi-bin/getinfo` (plain-text module
info: firmware string, IP, MAC) and `GET /cgi-bin/query` (a GET-shaped comhead
read the UI uses). `/cgi-bin/upload` flashes firmware — never touch it.
Flashing factory-resets user config: the V1.00.16→V1.00.19 upgrade wiped
routing and preset names.

The IP module also exposes the MCU's text CLI on telnet port 23, unauthenticated
(TCP 8000 carries the same thing in the vendor GTool's 13-byte binary framing —
`use_proto_size` in `getinfo`; left unmapped). Dialect: `s …!`/`r …!` with `!`
as terminator; `help!` self-documents all 86 commands, `status!` dumps the full
device state in one call, and errors come back as bare `E00` (usually a missing
`!`). Ports accept `0` = all. The CLI is a superset of the JSON API — extras
include the full per-input CEC pad (`s cec in x play/pause/stop/rew/ff/previous/
next/menu/back/up/down/left/right/enter/mute/vol±/on/off!`), `s cec hdmi out y
active!`, per-output video mode (`s output y video mode x!`, x=1~5, current
reads "pass-through"), hdcp x=1~5, EDID z=1~39 with writable user slots
(`s user x edid …!`, x=1~3), per-port link reads (`r link in x!`/`r link out
y!`) and `s net reboot!`. Still zero fan/temperature commands. Trap: on this
channel the factory reset is the short, unprefixed `reset!` and reboot is
`reboot!` — never send either; `power z!` is likewise unprefixed.

Comheads the web UI knows but the integration does not use: `set tpg`,
`set output resolution`, `set hdr conversion`, `set user edid`, `set hdcp`,
`set network`, `set defaults network`, `set language`, `get cec status`,
`set cec index`, `logout`.

Ports are one-based in every payload. `0` usually means "all ports".

Standby, measured on the reference unit rather than assumed:

- Every status command keeps answering in full; only `power` flips to 0.
- Writes are accepted and take effect, so routing can be changed while off.
- `set poweronoff` back on returns a usable device in about two seconds,
  not the ten the web UI's wait dialog implies.

## Probing the real device

Read commands are safe and unauthenticated:

```bash
curl -s -X POST http://<matrix-host>/cgi-bin/instr \
  -H 'Content-Type: application/json' -d '{"comhead":"get video status"}'
```

**Outputs 1-3 have live displays attached. Do not send writes to them.**
Outputs 4-8 have no sink; output 8 is the scratch port used for probing. Send
a port its current value to test whether a comhead exists without changing
anything.

Never send `set factory` or `reboot`.

Fan control does not exist — checked 2026-08 against the reference unit on
fw V1.00.16 and re-checked on V1.00.19: no
fan/temperature comhead answers, the full web UI vocabulary has no thermal
strings, and no status payload carries a temperature field. The 5V fan
headers are unmanaged rail taps; quieting the unit is hardware work.

## Conventions

- Entity naming uses `_attr_translation_key` plus
  `_attr_translation_placeholders`, never hardcoded names. Every new entity
  needs an entry in `strings.json`, `translations/en.json` and
  `translations/de.json`.
- Writes go through `HdcvtMatrixCoordinator._async_write`, which wraps errors,
  applies an optimistic update and schedules a refresh. Do not call the client
  from an entity directly.
- `async_get_state` is the polling path and reads only what entities actually
  consume. Adding a command there is a real cost: the CGI backend is single
  threaded. Anything diagnostic-only belongs in `async_get_raw_snapshot`.
- Unrecognised firmware values read as `None`/unknown rather than being
  guessed at.
- Sonar findings that are wrong for this codebase carry `# NOSONAR` with the
  reason next to them; ruff equivalents are scoped in `pyproject.toml`.
