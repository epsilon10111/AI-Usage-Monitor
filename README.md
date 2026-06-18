# Cursor API Monitor

Plasma 6 widget for Fedora KDE Plasma. It displays two Cursor API usage counters on the desktop or panel.

The widget is split into two parts:

- `contents/ui/main.qml` renders the Plasma widget.
- `contents/scripts/cursor_usage_helper.py` fetches usage data from the configured sources and prints JSON for QML.

## Install

```bash
chmod +x install.sh contents/scripts/cursor_usage_helper.py
./install.sh
```

Then add it from Plasma: right click the desktop or panel, choose `Add Widgets`, then search for `Cursor API Monitor`.

The install script also creates an empty cookie file:

```text
~/.config/cursor-usage-monitor/cursor-cookie
```

For a standalone test window:

```bash
plasmawindowed com.local.cursor.api.monitor
```

## Configure Cursor

The install script creates:

```text
~/.config/cursor-usage-monitor/config.json
```

Default config:

```json
{
  "sources": [
    {
      "type": "cursor",
      "cookie_path": "~/.config/cursor-usage-monitor/cursor-cookie",
      "team_id": "auto",
      "warning_percent": 80,
      "critical_percent": 95
    }
  ]
}
```

This uses Cursor's dashboard APIs directly and shows two rows:

- `Auto + Composer`: percentage of the Auto and Composer usage pool used.
- `API`: percentage of the included API usage pool used.

The detail line also shows the dashboard summary, plan name, included amount, and reset date when Cursor returns them.

Get the required browser session cookie:

1. Open `https://cursor.com` in your browser and log in.
2. Open developer tools.
3. Open `Application` or `Storage`, then `Cookies`, then `https://cursor.com`.
4. Copy the value of `WorkosCursorSessionToken`.
5. Put only that value into `~/.config/cursor-usage-monitor/cursor-cookie`.
6. Keep permissions strict with `chmod 600 ~/.config/cursor-usage-monitor/cursor-cookie`.

`team_id` can be:

- `auto`, empty, or omitted: use your individual dashboard usage.
- a numeric team id: request usage for a specific Cursor team.

The widget calls these Cursor endpoints directly from your machine:

- `/api/auth/bootstrap-cursor-web-target`
- `/api/dashboard/get-current-period-usage`
- `/api/dashboard/get-plan-info`

Your cookie is only sent to `https://cursor.com/api` by the local helper.

## Custom APIs

If Cursor changes its dashboard APIs, or if you want to monitor a different API, replace the default source with `json_url` sources.

Example with JSON APIs:

```json
{
  "sources": [
    {
      "name": "Cursor API 1",
      "type": "json_url",
      "url": "https://example.invalid/api/cursor/usage-1",
      "method": "GET",
      "auth": {
        "type": "header_file",
        "header": "Cookie",
        "path": "~/.config/cursor-usage-monitor/cursor-cookie"
      },
      "used_path": "data.used",
      "limit_path": "data.limit",
      "unit": "requests"
    },
    {
      "name": "Cursor API 2",
      "type": "json_url",
      "url": "https://example.invalid/api/cursor/usage-2",
      "method": "GET",
      "auth": {
        "type": "bearer_file",
        "path": "~/.config/cursor-usage-monitor/cursor-token"
      },
      "used_path": "usage.current",
      "limit_path": "usage.limit",
      "unit": "USD"
    }
  ]
}
```

Supported source types:

- `static`: local demo values.
- `cursor`: built-in Cursor dashboard API adapter.
- `json_url`: fetch a JSON endpoint.
- `command`: run a local command that prints JSON.

Supported auth types for `json_url`:

- `bearer_env`: `Authorization: Bearer $ENV_NAME`.
- `bearer_file`: `Authorization: Bearer <file content>`.
- `header_env`: arbitrary header from an environment variable.
- `header_file`: arbitrary header from a file.
- `cookie_env`: `Cookie` header from an environment variable.
- `cookie_file`: `Cookie` header from a file.
- `cursor_local`: best-effort token lookup from `~/.config/Cursor/User/globalStorage`.

The `cursor_local` mode is useful only when an endpoint accepts the local Cursor auth token. Cursor dashboard usage endpoints currently require the browser session cookie.

## Field Paths

The helper extracts values with dot paths:

```json
{
  "used_path": "data.usage.used",
  "limit_path": "data.usage.limit",
  "remaining_path": "data.usage.remaining",
  "percent_path": "data.usage.percent",
  "text_path": "data.usage.label"
}
```

Array indexes are supported with either style:

```json
{
  "used_path": "items.0.used",
  "limit_path": "items[0].limit"
}
```

If `used_path` is missing but `remaining_path` and `limit_path` exist, the helper computes `used = limit - remaining`.

If `percent_path` is missing but `used` and `limit` exist, the helper computes the percentage.

## Helper Test

```bash
python3 contents/scripts/cursor_usage_helper.py --config ~/.config/cursor-usage-monitor/config.json
python3 contents/scripts/cursor_usage_helper.py --check-cursor-auth
python3 contents/scripts/cursor_usage_helper.py --config examples/config.static.json
```

The helper always prints JSON so Plasma can display setup or auth errors instead of crashing the widget.
