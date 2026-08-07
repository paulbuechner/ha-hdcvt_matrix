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
`ha-hdcvt` conda env. Docker Desktop does not autostart; launch it and the
daemon is up in ~10s.

Full green means: `ruff check` + `ruff format --check` + `mypy` + `pytest` +
`hassfest`. Run all five before saying something works.

## Deploying to the live matrix

The test instance is at `\\homeassistant\config`, mounted on `Z:`.

```bash
rm -rf /z/custom_components/hdcvt_matrix
cp -r custom_components/hdcvt_matrix /z/custom_components/hdcvt_matrix
find /z/custom_components/hdcvt_matrix -name __pycache__ -type d -exec rm -rf {} +
```

A **new platform** needs an HA restart; edits to an existing one need only a
reload of the config entry.

## The device protocol

Reverse-engineered from the web UI. All of it is `POST /cgi-bin/instr` with a
JSON body keyed by `comhead`. Four traps, each of which has already cost time:

- **Unknown commands return plain text** (`not wait comhead [...]`), not JSON.
  Parse defensively.
- **The API is sessionless.** `login` validates credentials and returns
  `result: 1`/`0` but issues no token; every other command answers
  unauthenticated. Credentials are checked once at setup.
- **Array fields carry a trailing "all ports" aggregate.** On an 8x8 they have
  nine entries. Only `allinputname`/`alloutputname` are sized to the real port
  count, so use those to trim.
- **The web UI's command map lies in at least one place.** It calls the scaler
  command `video scaler`; the firmware only answers to `set video scaler`.
  Probe before trusting a comhead you have not seen work.

Ports are one-based in every payload. `0` usually means "all ports".

## Probing the real device

Read commands are safe and unauthenticated:

```bash
curl -s -X POST http://192.168.10.60/cgi-bin/instr \
  -H 'Content-Type: application/json' -d '{"comhead":"get video status"}'
```

**Outputs 1-3 have live displays attached. Do not send writes to them.**
Outputs 4-8 have no sink; output 8 is the scratch port used for probing. Send
a port its current value to test whether a comhead exists without changing
anything.

Never send `set factory` or `reboot`.

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
