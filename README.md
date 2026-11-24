# Qixu MCP for Home Assistant

[中文说明](README.zh-CN.md)

Custom integration (domain `qixu_mcp`) that connects Home Assistant to the **Qixu voice service**. Home Assistant dials out over WebSocket and acts as an MCP server on that connection, exposing the entities and scripts you have exposed to Assist as tools. The Qixu service handles speech recognition and the language model, then calls those tools to control devices.

```text
Voice device → Qixu voice service (ASR + LLM)
                     ▲
                     │  ws:// or wss://, opened by Home Assistant
                     │
Home Assistant ──────┘  tools = Assist-exposed entities and scripts
  + qixu_mcp
```

## What it is and what it is not

This integration is a connector for one specific service, the Qixu voice platform.

- **Outbound only.** Home Assistant opens the connection. No inbound port, port forwarding, or public address is needed.
- **Not a general MCP endpoint.** It does not expose an HTTP/SSE MCP server for desktop clients such as Claude Desktop, and it is not an MCP client or a conversation agent inside Home Assistant.
- **Scoped to Assist.** Only entities and scripts you expose under *Settings → Voice assistants → Expose* are available, through Home Assistant's own LLM API. It does not add admin tools for editing configuration, automations, or users.
- **Per-site identity.** Each connection carries an access token (`Authorization: Bearer`) and a site ID (`X-Qixu-Home`), so one Qixu account can serve several homes or offices.
- **Confirmation for sensitive actions.** Tool calls that match configured keywords (locks, door opening, disarming, and similar) are held and only run after an explicit confirmation step (see below).
- **Real connection state.** A status entity reports `connecting`, `connected`, or `disconnected` based on the actual socket.

## Requirements

- Home Assistant 2026.7 or later
- A Qixu endpoint URL and access token, issued by the Qixu console

## Installation

### HACS

1. HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/prismatechcode/ha-mcp-for-qixu`, category **Integration**.
3. Install **栖序 MCP** and restart Home Assistant.

### Manual

Copy `custom_components/qixu_mcp/` to `/config/custom_components/qixu_mcp/` and restart Home Assistant.

## Configuration

Settings → Devices & services → Add integration → **栖序 MCP**.

| Field | Value |
|-------|-------|
| Qixu endpoint | `wss://<qixu-host>/mcp` (`ws://` for local testing only) |
| Access token | Issued by the Qixu console |
| Site ID | Any label for this site, e.g. `office` |
| Control API | Assist |
| Confirmation keywords | Comma-separated; defaults are Chinese terms for lock, unlock, open door, car out, disarm |

Then expose the devices and scripts you want under *Settings → Voice assistants → Expose*.

To check the connection, open *Developer tools → States* and search for `qixu_mcp.`. The state should be `connected`.

You can add the integration more than once to connect to different endpoints or site IDs.

## Confirmation for sensitive actions

If a tool name, script name, or argument contains one of the confirmation keywords, the integration does not run it. It returns:

```json
{"requires_confirmation": true, "confirm_id": "a1b2c3d4", "action": "打开门锁", "speech": "这是安防动作：打开门锁。请确认后再执行。"}
```

The Qixu service runs the action by calling the `QixuConfirmAction` tool with that `confirm_id`. Each ID is valid for 30 seconds and can be used once.

The integration guarantees that a held action never runs without this call. Verifying that the user actually spoke the confirmation is the Qixu service's responsibility.

## Privacy

- Only Assist-exposed entities and scripts are visible to the Qixu service.
- The access token is stored in the config entry and sent only to the configured endpoint.
- No data is sent anywhere other than the endpoint you configure.

## Development

`hub/` contains a minimal local stand-in for the Qixu service, used for testing without the production backend. It is not part of the integration and is not installed by HACS.

```powershell
python hub/qixu_hub.py --port 8791 --token <token>
```

| Endpoint | Purpose |
|----------|---------|
| `ws://<host>:8791/mcp` | Point the integration here |
| `GET /homes` | Connected sites |
| `GET /homes/{home}/tools` | Tools for a site |
| `POST /homes/{home}/call` | Call a tool directly |
| `POST /v1/voice` | Send a text command, e.g. `{"text": "打开办公室灯"}` |

HTTP calls need `Authorization: Bearer <token>`. The voice endpoint reads an LLM key from `hub/config.json` (see `hub/config.example.json`).

### Tests

```powershell
python -m venv .venv-test
.\.venv-test\Scripts\python -m pip install "mcp==1.26.0" "anyio==4.13.0" aiohttp
.\.venv-test\Scripts\python tests\test_hub_e2e.py
```

`tests/fake_ha.py` simulates a Home Assistant instance with the same MCP library version and the integration's real confirmation logic. It covers connection, authentication, tool listing, pass-through calls, and held actions. The config flow and Assist tool loading need a real Home Assistant instance.

## Releasing

Publish a GitHub release with a tag such as `v0.1.0`. The `release.yml` workflow sets the manifest version from the tag, builds `ha-mcp-for-qixu.zip`, and attaches it to the release.

## License

MIT
