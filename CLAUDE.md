# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A KDE Plasma 6 widget (plasmoid) for Fedora KDE that displays Cursor API usage counters on the desktop or panel. There is no build step and no test suite — it is a QML applet plus a standalone Python helper.

## Architecture

The widget is deliberately split so QML never does network or auth work:

- **`contents/scripts/usage_helper.py`** — does all fetching, auth, and parsing. Reads a JSON config, fetches each source, and prints **one JSON object** to stdout. It always exits 0 and always prints JSON (even on error, via the `UsageError` -> payload path in `main`), so the widget can render setup/auth errors instead of crashing.
- **`contents/ui/main.qml`** — `PlasmoidItem` that runs the helper via a `Plasma5Support.DataSource` (`engine: "executable"`), parses the JSON payload in `parsePayload`, and renders compact + full representations. A `Timer` re-runs the helper every `pollIntervalSeconds`.

Data contract between the two halves (payload shape): `{ ok, updatedAt, updatedAtLocal, items[], error, debug }`. Each item has `{ name, used, limit, remaining, percent, unit, valueText, status, group, detail? }`. `status` is one of `ok` / `warning` / `critical` / `unknown` and drives the bar/percent color in QML. `group` is the provider label (e.g. "Cursor", "Claude Code"); QML's `groupsModel()` buckets items by it into titled sections, and `compactSummary()` shows one worst-case percent chip per group in the panel. If you change the payload shape in the helper, update `parsePayload`, `usageText`, `percentFor`, `statusColor`, `groupsModel`, and `compactSummary` in `main.qml` to match.

### Helper internals

- **Sources** (`fetch_source` dispatch on `source.type`): `static` (demo values inline in config), `json_url` (generic JSON fetch), `command` (run a local command that prints JSON), `cursor` (built-in Cursor dashboard adapter), and `claude` (built-in Claude Code subscription adapter). `json_url`/`command`/`static` go through `extract_usage`; `cursor` and `claude` each return a 2-item list.
- **Claude adapter** (`claude_usage_items`): reads the Claude Code CLI's OAuth token from `~/.claude/.credentials.json` (`claudeAiOauth.accessToken`), GETs `https://api.anthropic.com/api/oauth/usage` with `Authorization: Bearer` + `anthropic-beta: oauth-2025-04-20`, and emits "5h Limit" (`five_hour.utilization`/`resets_at`) and "Weekly" (`seven_day.utilization`/`resets_at`). The token is short-lived, so `claude_access_token` auto-refreshes via `refresh_claude_token` (POST to `CLAUDE_TOKEN_URL` with the stored `refreshToken` and the public Claude Code `client_id`) when `expiresAt` is within ~1 min, writing the rotated token back to the credentials file atomically (mode 600, same JSON shape the CLI uses). If the usage response or `planUsage`-equivalent field names change server-side, this is where it breaks.
- **Field extraction** uses dot/bracket paths (`get_path` + `tokenize_path`): `used_path`, `limit_path`, `remaining_path`, `percent_path`, `text_path`, optional `root_path`. Derived values: `used = limit - remaining` when used is absent; percent computed from used/limit when absent; percents in 0–1 are auto-scaled to 0–100 (`normalize_percent`).
- **Cursor adapter** is the tricky part. It does NOT use simple header auth. `cursor_dashboard_json` builds a `CookieJar` opener, first hits `/api/auth/bootstrap-cursor-web-target` to establish the web session, then POSTs to `dashboard/get-current-period-usage` and `dashboard/get-plan-info`. It reads the `planUsage` object and emits two items: "Auto + Composer" (`autoPercentUsed`/`autoSpend`/`autoLimit`) and "API" (`apiPercentUsed`/`apiSpend`/`apiLimit`). If Cursor changes these endpoints or the `planUsage` field names, this is where it breaks.
- **Auth types** for `json_url` sources are handled in `apply_auth`: `bearer_env`, `bearer_file`, `header_env`, `header_file`, `cookie_env`, `cookie_file`, `cursor_local`. `cursor_local` (`find_cursor_local_token`) reads the Cursor desktop app's token from `state.vscdb` (SQLite) / `storage.json` under `~/.config/Cursor/User/globalStorage`.

## Config and secrets

Runtime config lives at `~/.config/ai-usage-monitor/config.json` (seeded from `examples/config.json` by `install.sh`). The Cursor session cookie (`WorkosCursorSessionToken`) goes in `~/.config/ai-usage-monitor/cursor-cookie`, mode 600. `examples/` holds reference configs; `config.static.json` uses the `static` source type for offline testing.

## Common commands

Install / upgrade the plasmoid (uses `kpackagetool6`):

```bash
./install.sh
```

Run the helper directly — this is the primary way to test changes without reloading the widget:

```bash
python3 contents/scripts/usage_helper.py --config ~/.config/ai-usage-monitor/config.json
python3 contents/scripts/usage_helper.py --config examples/config.static.json   # no network/auth needed
python3 contents/scripts/usage_helper.py --check-cursor-auth                     # reports if a local Cursor token is visible
```

Run the widget standalone (no panel needed):

```bash
plasmawindowed com.local.ai.usage.monitor
```

After editing QML, re-run `./install.sh` to upgrade the installed package; the standalone window or panel reads the installed copy, not the working tree.

## Constraints to respect

- The helper targets the Python 3 standard library only (`urllib`, `sqlite3`, `http.cookiejar`, etc.) — no third-party deps, since it runs in whatever Python the user's system provides. Keep it that way.
- Keep network/auth logic in the Python helper, not in QML.
- The applet id is `com.local.ai.usage.monitor` (in `metadata.json`); the config schema lives in `contents/config/main.xml` (`configPath`, `pollIntervalSeconds` min 15, `showDebugDetails`).
