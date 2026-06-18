#!/usr/bin/env python3
"""Fetch usage counters for the Cursor API Monitor plasmoid.

The helper intentionally keeps network/auth logic outside QML. It accepts a
small JSON config file and prints one JSON object to stdout.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import http.cookiejar
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = "~/.config/cursor-usage-monitor/config.json"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
CURSOR_API_BASE = "https://cursor.com/api"


class UsageError(Exception):
    """A user-facing configuration or fetch error."""


def now_payload() -> tuple[str, str]:
    now = dt.datetime.now(dt.timezone.utc).astimezone()
    return now.isoformat(timespec="seconds"), now.strftime("%H:%M:%S")


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def read_text_file(path: str) -> str:
    expanded = expand_path(path)
    try:
        return expanded.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise UsageError(f"Secret file not found: {expanded}") from exc
    except OSError as exc:
        raise UsageError(f"Cannot read secret file {expanded}: {exc}") from exc


def substitute_env(value: str) -> str:
    pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

    def replace(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "")

    return pattern.sub(replace, value)


def load_config(path: str) -> dict[str, Any]:
    config_path = expand_path(path)
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise UsageError(
            f"Config not found: {config_path}. Run ./install.sh or copy examples/config.json there."
        ) from exc
    except json.JSONDecodeError as exc:
        raise UsageError(f"Invalid JSON in {config_path}: {exc}") from exc
    except OSError as exc:
        raise UsageError(f"Cannot read {config_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise UsageError("Config root must be a JSON object")
    return data


def tokenize_path(path: str) -> list[str]:
    normalized = str(path).replace("[", ".").replace("]", "")
    return [part for part in normalized.split(".") if part]


def get_path(data: Any, path: Any, default: Any = None) -> Any:
    if path in (None, ""):
        return default
    if isinstance(path, list):
        for candidate in path:
            value = get_path(data, candidate, default=None)
            if value is not None:
                return value
        return default

    current = data
    for token in tokenize_path(str(path)):
        if isinstance(current, dict):
            if token not in current:
                return default
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError):
                return default
        else:
            return default
    return current


def to_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        cleaned = cleaned.replace(",", "")
        cleaned = re.sub(r"[^0-9.+\-eE]", "", cleaned)
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def compact_number(value: float | None) -> int | float | None:
    if value is None:
        return None
    if abs(value - round(value)) < 0.001:
        return int(round(value))
    return round(value, 4)


def format_number(value: float | None) -> str:
    if value is None:
        return "--"
    if abs(value - round(value)) < 0.001:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def normalize_percent(value: float | None) -> float | None:
    if value is None:
        return None
    percent = value * 100 if 0 <= value <= 1 else value
    return max(0.0, min(100.0, percent))


def status_for(percent: float | None, source: dict[str, Any]) -> str:
    if percent is None:
        return "unknown"
    critical = to_number(source.get("critical_percent"))
    warning = to_number(source.get("warning_percent"))
    critical = 95.0 if critical is None else critical
    warning = 80.0 if warning is None else warning
    if percent >= critical:
        return "critical"
    if percent >= warning:
        return "warning"
    return "ok"


def value_text(used: float | None, limit: float | None, unit: str, fallback: Any = None) -> str:
    suffix = f" {unit}" if unit else ""
    if used is not None and limit is not None:
        return f"{format_number(used)} / {format_number(limit)}{suffix}"
    if used is not None:
        return f"{format_number(used)}{suffix}"
    if fallback is not None:
        return str(fallback)
    return "--"


def extract_usage(source: dict[str, Any], data: Any) -> dict[str, Any]:
    root_path = source.get("root_path")
    root = get_path(data, root_path, data) if root_path else data

    unit = str(source.get("unit", ""))
    name = str(source.get("name", "Usage"))
    used = to_number(source.get("used"))
    limit = to_number(source.get("limit"))
    remaining = to_number(source.get("remaining"))
    percent = normalize_percent(to_number(source.get("percent")))
    raw_text = source.get("text")

    used_from_path = to_number(get_path(root, source.get("used_path")))
    limit_from_path = to_number(get_path(root, source.get("limit_path")))
    remaining_from_path = to_number(get_path(root, source.get("remaining_path")))
    percent_from_path = normalize_percent(to_number(get_path(root, source.get("percent_path"))))
    text_from_path = get_path(root, source.get("text_path"))

    if used_from_path is not None:
        used = used_from_path
    if limit_from_path is not None:
        limit = limit_from_path
    if remaining_from_path is not None:
        remaining = remaining_from_path
    if percent_from_path is not None:
        percent = percent_from_path
    if text_from_path is not None:
        raw_text = text_from_path

    if used is None and limit is not None and remaining is not None:
        used = max(0.0, limit - remaining)
    if percent is None and used is not None and limit not in (None, 0):
        percent = normalize_percent(used / limit)

    return {
        "name": name,
        "used": compact_number(used),
        "limit": compact_number(limit),
        "remaining": compact_number(remaining),
        "percent": None if percent is None else round(percent, 2),
        "unit": unit,
        "valueText": value_text(used, limit, unit, raw_text),
        "status": status_for(percent, source),
    }


def decode_sqlite_value(value: Any) -> Any:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text.strip('"')


def find_in_json(data: Any, key_hints: tuple[str, ...]) -> str | None:
    if isinstance(data, dict):
        for key, value in data.items():
            lowered = str(key).lower()
            if any(hint in lowered for hint in key_hints) and isinstance(value, str) and value.strip():
                return value.strip()
            nested = find_in_json(value, key_hints)
            if nested:
                return nested
    elif isinstance(data, list):
        for value in data:
            nested = find_in_json(value, key_hints)
            if nested:
                return nested
    elif isinstance(data, str):
        text = data.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return find_in_json(json.loads(text), key_hints)
            except json.JSONDecodeError:
                return None
    return None


def cursor_storage_paths(filename: str) -> list[Path]:
    home = Path.home()
    candidates = [
        home / ".config" / "Cursor" / "User" / "globalStorage" / filename,
        home / ".config" / "cursor" / "User" / "globalStorage" / filename,
        home / ".var" / "app" / "com.cursor.Cursor" / "config" / "Cursor" / "User" / "globalStorage" / filename,
    ]
    return candidates


def find_cursor_local_token(kind: str = "access") -> str | None:
    key_hints = ("accesstoken", "access_token") if kind == "access" else ("refreshtoken", "refresh_token")

    for db_path in cursor_storage_paths("state.vscdb"):
        if not db_path.exists():
            continue
        try:
            connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1)
            try:
                rows = connection.execute("SELECT key, value FROM ItemTable").fetchall()
            finally:
                connection.close()
        except sqlite3.Error:
            continue

        for key, value in rows:
            decoded = decode_sqlite_value(value)
            lowered_key = str(key).lower()
            if any(hint in lowered_key.replace("/", "") for hint in key_hints):
                if isinstance(decoded, str) and decoded.strip():
                    return decoded.strip()
            nested = find_in_json(decoded, key_hints)
            if nested:
                return nested

    for json_path in cursor_storage_paths("storage.json"):
        if not json_path.exists():
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        token = find_in_json(data, key_hints)
        if token:
            return token

    return None


def apply_auth(headers: dict[str, str], auth: Any) -> None:
    if not auth:
        return
    if not isinstance(auth, dict):
        raise UsageError("auth must be an object")

    auth_type = str(auth.get("type", "")).lower()
    if not auth_type:
        return

    if auth_type == "bearer_env":
        env_name = str(auth.get("env", ""))
        token = os.environ.get(env_name, "").strip()
        if not token:
            raise UsageError(f"Environment variable {env_name} is empty")
        headers["Authorization"] = f"Bearer {token}"
        return

    if auth_type == "bearer_file":
        token = read_text_file(str(auth.get("path", "")))
        headers["Authorization"] = f"Bearer {token}"
        return

    if auth_type == "header_env":
        env_name = str(auth.get("env", ""))
        header_name = str(auth.get("header", "Authorization"))
        value = os.environ.get(env_name, "").strip()
        if not value:
            raise UsageError(f"Environment variable {env_name} is empty")
        headers[header_name] = value
        return

    if auth_type == "header_file":
        header_name = str(auth.get("header", "Authorization"))
        headers[header_name] = read_text_file(str(auth.get("path", "")))
        return

    if auth_type == "cookie_env":
        env_name = str(auth.get("env", ""))
        value = os.environ.get(env_name, "").strip()
        if not value:
            raise UsageError(f"Environment variable {env_name} is empty")
        cookie_name = auth.get("name")
        headers["Cookie"] = f"{cookie_name}={value}" if cookie_name else value
        return

    if auth_type == "cookie_file":
        value = read_text_file(str(auth.get("path", "")))
        cookie_name = auth.get("name")
        headers["Cookie"] = f"{cookie_name}={value}" if cookie_name else value
        return

    if auth_type == "cursor_local":
        token_kind = str(auth.get("token", "access"))
        token = find_cursor_local_token(token_kind)
        if not token:
            raise UsageError("Cannot find Cursor local auth token in ~/.config/Cursor")

        mode = str(auth.get("mode", "bearer")).lower()
        if mode == "bearer":
            headers["Authorization"] = f"Bearer {token}"
        elif mode == "cookie":
            cookie_name = str(auth.get("name", "WorkosCursorSessionToken"))
            headers["Cookie"] = f"{cookie_name}={token}"
        elif mode == "header":
            header_name = str(auth.get("header", "Authorization"))
            prefix = str(auth.get("prefix", ""))
            headers[header_name] = f"{prefix}{token}"
        else:
            raise UsageError(f"Unsupported cursor_local mode: {mode}")
        return

    raise UsageError(f"Unsupported auth type: {auth_type}")


def headers_from_source(source: dict[str, Any]) -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "cursor-api-monitor/0.1"}
    configured = source.get("headers", {})
    if configured:
        if not isinstance(configured, dict):
            raise UsageError("headers must be an object")
        for key, value in configured.items():
            headers[str(key)] = substitute_env(str(value))
    apply_auth(headers, source.get("auth"))
    return headers


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    body: Any = None,
    timeout: float = 10,
) -> Any:
    body_bytes = None
    if body is not None:
        if isinstance(body, (dict, list)):
            body_bytes = json.dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        else:
            body_bytes = str(body).encode("utf-8")

    request = urllib.request.Request(str(url), data=body_bytes, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise UsageError("Response is too large")
    except urllib.error.HTTPError as exc:
        raise UsageError(f"HTTP {exc.code} from {url}") from exc
    except urllib.error.URLError as exc:
        raise UsageError(f"Cannot reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise UsageError(f"Timeout fetching {url}") from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise UsageError(f"Response from {url} is not JSON: {exc}") from exc


def fetch_json_url(source: dict[str, Any]) -> dict[str, Any]:
    url = source.get("url")
    if not url:
        raise UsageError("json_url source requires url")

    method = str(source.get("method", "GET")).upper()
    timeout = to_number(source.get("timeout_seconds")) or 10
    body = source.get("body")
    headers = headers_from_source(source)
    return request_json(method, str(url), headers, body, timeout)


def run_command_source(source: dict[str, Any]) -> Any:
    command = source.get("command")
    if not command:
        raise UsageError("command source requires command")

    timeout = to_number(source.get("timeout_seconds")) or 10
    shell = bool(source.get("shell", False))
    if isinstance(command, list):
        argv: str | list[str] = [str(part) for part in command]
    else:
        argv = str(command) if shell else shlex.split(str(command))

    try:
        completed = subprocess.run(
            argv,
            check=False,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UsageError(f"Command failed: {exc}") from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise UsageError(f"Command exited {completed.returncode}: {detail}")

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise UsageError(f"Command output is not JSON: {exc}") from exc


def parse_datetime(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone()


def add_one_month(value: dt.datetime) -> dt.datetime:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def reset_detail(start_of_month: Any) -> str:
    start = parse_datetime(start_of_month)
    if not start:
        return ""
    reset_at = add_one_month(start)
    seconds = (reset_at - dt.datetime.now().astimezone()).total_seconds()
    days = max(0, int((seconds + 86399) // 86400))
    date_text = reset_at.date().isoformat()
    if days == 0:
        return f"resets today ({date_text})"
    if days == 1:
        return f"resets tomorrow ({date_text})"
    return f"resets in {days} days ({date_text})"


def cursor_cookie_header(value: str) -> str:
    text = value.strip()
    if not text:
        raise UsageError("Cursor session cookie is empty")
    if "=" in text or ";" in text:
        return text
    return f"WorkosCursorSessionToken={text}"


def cursor_headers(source: dict[str, Any]) -> dict[str, str]:
    headers = headers_from_source(source)
    headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Origin", "https://cursor.com")

    if "Cookie" not in headers and "Authorization" not in headers:
        env_name = source.get("cookie_env")
        cookie_value = os.environ.get(str(env_name), "").strip() if env_name else ""
        if not cookie_value:
            cookie_path = str(source.get("cookie_path", "~/.config/cursor-usage-monitor/cursor-cookie"))
            expanded_cookie_path = expand_path(cookie_path)
            try:
                cookie_value = read_text_file(cookie_path)
            except UsageError as exc:
                raise UsageError(
                    "Cursor session cookie not configured. Put the WorkosCursorSessionToken value in "
                    f"{expanded_cookie_path} or set auth/cookie_env in config.json."
                ) from exc
            if not cookie_value.strip():
                raise UsageError(
                    "Cursor session cookie file is empty. Paste the WorkosCursorSessionToken value into "
                    f"{expanded_cookie_path}."
                )
        headers["Cookie"] = cursor_cookie_header(cookie_value)
    elif "Cookie" in headers:
        headers["Cookie"] = cursor_cookie_header(headers["Cookie"])

    return headers


def cursor_cookie_value(source: dict[str, Any]) -> str:
    auth = source.get("auth")
    if isinstance(auth, dict):
        auth_type = str(auth.get("type", "")).lower()
        if auth_type == "cookie_env":
            env_name = str(auth.get("env", ""))
            value = os.environ.get(env_name, "").strip()
            if not value:
                raise UsageError(f"Environment variable {env_name} is empty")
            return value
        if auth_type == "cookie_file":
            return read_text_file(str(auth.get("path", "")))

    env_name = source.get("cookie_env")
    value = os.environ.get(str(env_name), "").strip() if env_name else ""
    if value:
        return value

    cookie_path = str(source.get("cookie_path", "~/.config/cursor-usage-monitor/cursor-cookie"))
    expanded_cookie_path = expand_path(cookie_path)
    try:
        value = read_text_file(cookie_path)
    except UsageError as exc:
        raise UsageError(
            "Cursor session cookie not configured. Put the WorkosCursorSessionToken value in "
            f"{expanded_cookie_path} or set auth/cookie_env in config.json."
        ) from exc
    if not value.strip():
        raise UsageError(
            "Cursor session cookie file is empty. Paste the WorkosCursorSessionToken value into "
            f"{expanded_cookie_path}."
        )
    return value


def cursor_request(source: dict[str, Any], method: str, endpoint: str, body: Any = None) -> Any:
    base_url = str(source.get("base_url", CURSOR_API_BASE)).rstrip("/")
    timeout = to_number(source.get("timeout_seconds")) or 10
    return request_json(method, f"{base_url}/{endpoint.lstrip('/')}", cursor_headers(source), body, timeout)


def cursor_dashboard_opener(source: dict[str, Any]) -> urllib.request.OpenerDirector:
    cookie_text = cursor_cookie_value(source)
    cookie_header = cursor_cookie_header(cookie_text)
    session_cookie = cookie_header
    if cookie_header.lower().startswith("workoscursorsessiontoken=") and ";" not in cookie_header:
        session_cookie = cookie_header.split("=", 1)[1]

    jar = http.cookiejar.CookieJar()
    jar.set_cookie(
        http.cookiejar.Cookie(
            version=0,
            name="WorkosCursorSessionToken",
            value=session_cookie,
            port=None,
            port_specified=False,
            domain="cursor.com",
            domain_specified=True,
            domain_initial_dot=False,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": None},
            rfc2109=False,
        )
    )
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def cursor_dashboard_json(source: dict[str, Any], endpoint: str, body: Any = None) -> Any:
    base_url = str(source.get("base_url", CURSOR_API_BASE)).rstrip("/")
    site_url = base_url.removesuffix("/api")
    timeout = to_number(source.get("timeout_seconds")) or 10
    opener = cursor_dashboard_opener(source)

    bootstrap_url = f"{site_url}/api/auth/bootstrap-cursor-web-target?redirectTo=%2Fdashboard%2Fusage"
    opener.open(
        urllib.request.Request(
            bootstrap_url,
            headers={"User-Agent": "cursor-api-monitor/0.1", "Accept": "text/html,application/xhtml+xml"},
        ),
        timeout=timeout,
    ).close()

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": site_url,
        "Referer": f"{site_url}/dashboard/usage",
        "User-Agent": "cursor-api-monitor/0.1",
    }
    body_bytes = json.dumps({} if body is None else body).encode("utf-8")
    url = f"{base_url}/{endpoint.lstrip('/')}"
    request = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise UsageError("Response is too large")
    except urllib.error.HTTPError as exc:
        raise UsageError(f"HTTP {exc.code} from {url}") from exc
    except urllib.error.URLError as exc:
        raise UsageError(f"Cannot reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise UsageError(f"Timeout fetching {url}") from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise UsageError(f"Response from {url} is not JSON: {exc}") from exc


def cursor_team_id(source: dict[str, Any], teams: Any) -> int | None:
    configured = source.get("team_id", source.get("teamId", "auto"))
    if configured not in (None, "", "auto"):
        try:
            return int(configured)
        except (TypeError, ValueError) as exc:
            raise UsageError(f"Invalid Cursor team_id: {configured}") from exc

    if isinstance(teams, dict):
        team_list = teams.get("teams", [])
        if isinstance(team_list, list) and team_list:
            first_id = get_path(team_list, "0.id")
            try:
                return int(first_id)
            except (TypeError, ValueError):
                return None
    return None


def find_team_member(spend_data: Any, user_id: Any) -> dict[str, Any] | None:
    members = get_path(spend_data, "teamMemberSpend", [])
    if not isinstance(members, list):
        return None
    for member in members:
        if isinstance(member, dict) and str(member.get("userId")) == str(user_id):
            return member
    return None


def parse_epoch_millis(value: Any) -> dt.datetime | None:
    number = to_number(value)
    if number is None or number <= 0:
        return None
    return dt.datetime.fromtimestamp(number / 1000, tz=dt.timezone.utc).astimezone()


def cycle_detail(usage_data: dict[str, Any], plan_info: dict[str, Any]) -> str:
    reset_at = parse_epoch_millis(usage_data.get("billingCycleEnd"))
    if reset_at is None:
        reset_at = parse_epoch_millis(get_path(plan_info, "planInfo.billingCycleEnd"))
    if reset_at is None:
        return ""

    seconds = (reset_at - dt.datetime.now().astimezone()).total_seconds()
    days = max(0, int((seconds + 86399) // 86400))
    date_text = reset_at.date().isoformat()
    if days == 0:
        return f"resets today ({date_text})"
    if days == 1:
        return f"resets tomorrow ({date_text})"
    return f"resets in {days} days ({date_text})"


def plan_amount_detail(plan_info: dict[str, Any], usage_data: dict[str, Any]) -> str:
    parts: list[str] = []
    plan_name = get_path(plan_info, "planInfo.planName")
    if plan_name:
        parts.append(str(plan_name))

    included_cents = to_number(get_path(plan_info, "planInfo.includedAmountCents"))
    if included_cents is None:
        included_cents = to_number(get_path(usage_data, "planUsage.limit"))
    if included_cents is not None and included_cents > 0:
        parts.append(f"included ${included_cents / 100:.2f}")

    reset = cycle_detail(usage_data, plan_info)
    if reset:
        parts.append(reset)
    return " · ".join(parts)


def percent_item(
    name: str,
    percent: float | None,
    detail: str,
    source: dict[str, Any],
    spend_cents: float | None = None,
    limit_cents: float | None = None,
) -> dict[str, Any]:
    normalized = normalize_percent(percent)
    used_dollars = spend_cents / 100 if spend_cents is not None else None
    limit_dollars = limit_cents / 100 if limit_cents is not None and limit_cents > 0 else None

    if used_dollars is not None and limit_dollars is not None:
        value = f"${used_dollars:.2f} / ${limit_dollars:.2f}"
        used = compact_number(used_dollars)
        limit = compact_number(limit_dollars)
        remaining = compact_number(max(0.0, limit_dollars - used_dollars))
        unit = "USD"
    else:
        value = "--" if normalized is None else f"{normalized:.1f}% used"
        used = None if normalized is None else compact_number(normalized)
        limit = 100
        remaining = None if normalized is None else compact_number(max(0.0, 100.0 - normalized))
        unit = "%"

    return {
        "name": name,
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "percent": None if normalized is None else round(normalized, 2),
        "unit": unit,
        "valueText": value,
        "status": status_for(normalized, source),
        "detail": detail,
    }


def cursor_usage_items(source: dict[str, Any]) -> list[dict[str, Any]]:
    body: dict[str, Any] = {}
    configured_team_id = source.get("team_id", source.get("teamId"))
    if configured_team_id not in (None, "", "auto"):
        try:
            body["teamId"] = int(configured_team_id)
        except (TypeError, ValueError) as exc:
            raise UsageError(f"Invalid Cursor team_id: {configured_team_id}") from exc

    usage_data = cursor_dashboard_json(source, "dashboard/get-current-period-usage", body)
    try:
        plan_info = cursor_dashboard_json(source, "dashboard/get-plan-info", {})
    except UsageError:
        plan_info = {}

    plan_usage = get_path(usage_data, "planUsage", {})
    if not isinstance(plan_usage, dict):
        raise UsageError("Cursor usage response did not include planUsage")

    detail = plan_amount_detail(plan_info, usage_data)
    total_percent = normalize_percent(to_number(plan_usage.get("totalPercentUsed")))
    display_message = usage_data.get("displayMessage")
    if display_message:
        detail = f"{display_message}" + (f" · {detail}" if detail else "")
    elif total_percent is not None:
        detail = f"Total {total_percent:.1f}% used" + (f" · {detail}" if detail else "")

    return [
        percent_item(
            str(source.get("auto_name", "Auto + Composer")),
            to_number(plan_usage.get("autoPercentUsed")),
            detail,
            source,
            to_number(plan_usage.get("autoSpend")),
            to_number(plan_usage.get("autoLimit")),
        ),
        percent_item(
            str(source.get("api_name", "API")),
            to_number(plan_usage.get("apiPercentUsed")),
            detail,
            source,
            to_number(plan_usage.get("apiSpend")),
            to_number(plan_usage.get("apiLimit")),
        ),
    ]


def fetch_source(source: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
    source_type = str(source.get("type", "json_url")).lower()
    if source_type == "static":
        return extract_usage(source, source)
    if source_type == "json_url":
        return extract_usage(source, fetch_json_url(source))
    if source_type == "command":
        return extract_usage(source, run_command_source(source))
    if source_type == "cursor":
        return cursor_usage_items(source)
    raise UsageError(f"Unsupported source type: {source_type}")


def build_payload(config_path: str) -> dict[str, Any]:
    updated_at, updated_at_local = now_payload()
    config = load_config(config_path)
    sources = config.get("sources", [])
    if not isinstance(sources, list):
        raise UsageError("sources must be an array")

    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"source {index + 1}: must be an object")
            continue
        try:
            fetched = fetch_source(source)
            if isinstance(fetched, list):
                items.extend(fetched)
            else:
                items.append(fetched)
        except UsageError as exc:
            name = source.get("name", f"source {index + 1}")
            errors.append(f"{name}: {exc}")
            items.append(
                {
                    "name": str(name),
                    "used": None,
                    "limit": None,
                    "remaining": None,
                    "percent": None,
                    "unit": str(source.get("unit", "")),
                    "valueText": "error",
                    "status": "critical",
                    "error": str(exc),
                }
            )

    return {
        "ok": not errors,
        "updatedAt": updated_at,
        "updatedAtLocal": updated_at_local,
        "items": items,
        "error": "; ".join(errors),
        "debug": "\n".join(errors),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Cursor usage counters")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Path to monitor config JSON")
    parser.add_argument("--check-cursor-auth", action="store_true", help="Report whether a local Cursor auth token is visible")
    args = parser.parse_args()

    if args.check_cursor_auth:
        updated_at, updated_at_local = now_payload()
        token = find_cursor_local_token("access")
        print(
            json.dumps(
                {
                    "ok": bool(token),
                    "updatedAt": updated_at,
                    "updatedAtLocal": updated_at_local,
                    "hasCursorAccessToken": bool(token),
                },
                ensure_ascii=True,
            )
        )
        return 0

    try:
        payload = build_payload(args.config)
    except UsageError as exc:
        updated_at, updated_at_local = now_payload()
        payload = {
            "ok": False,
            "updatedAt": updated_at,
            "updatedAtLocal": updated_at_local,
            "items": [],
            "error": str(exc),
            "debug": str(exc),
        }

    print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
