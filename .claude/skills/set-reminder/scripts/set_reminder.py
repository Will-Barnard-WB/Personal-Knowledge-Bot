#!/usr/bin/env python3
"""Set a one-off Telegram reminder via cron.

Writes a self-contained Python script to reminders/ and adds a cron entry.
The cron script sends the Telegram message then removes itself from crontab.
"""
from __future__ import annotations

import argparse
import json
import re
import stat
import subprocess
import sys
import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
REMINDERS_DIR = REPO_ROOT / "reminders"

# Template for the self-deleting reminder script.
# Uses .format() — double braces {{ }} become literal { } in the output.
_SCRIPT_TEMPLATE = """\
#!/usr/bin/env python3
# PKB_REMINDER_{reminder_id}
import json, subprocess, sys, urllib.request
from pathlib import Path

GATEWAY_URL = {gateway_url_repr}
TELEGRAM_ID = {telegram_id_repr}
MESSAGE     = {message_repr}
REMINDER_ID = {reminder_id_repr}

try:
    data = json.dumps({{"to": TELEGRAM_ID, "message": MESSAGE}}).encode()
    req  = urllib.request.Request(
        GATEWAY_URL + "/send", data, {{"Content-Type": "application/json"}}
    )
    urllib.request.urlopen(req, timeout=10)
except Exception as exc:
    print(f"Reminder send failed: {{exc}}", file=sys.stderr)

# Self-remove from crontab
try:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode == 0:
        lines = [l for l in result.stdout.splitlines() if REMINDER_ID not in l]
        new_crontab = "\\n".join(lines) + "\\n"
        subprocess.run(["crontab", "-"], input=new_crontab, text=True)
except Exception as exc:
    print(f"Crontab cleanup failed: {{exc}}", file=sys.stderr)

# Delete this script file
Path(__file__).unlink(missing_ok=True)
"""


def _load_env() -> dict[str, str]:
    """Parse .env file — avoids importing python-dotenv in the cron script."""
    env_file = REPO_ROOT / ".env"
    env: dict[str, str] = {}
    if not env_file.exists():
        return env
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def _parse_when(when_str: str) -> datetime:
    """Parse ISO datetime or relative shorthand (+45m, +2h, +1d)."""
    when_str = when_str.strip()
    m = re.match(r"^\+(\d+)([mhd])$", when_str)
    if m:
        amount, unit = int(m.group(1)), m.group(2)
        now = datetime.now()
        if unit == "m":
            return now + timedelta(minutes=amount)
        if unit == "h":
            return now + timedelta(hours=amount)
        if unit == "d":
            return now + timedelta(days=amount)

    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(when_str, fmt)
        except ValueError:
            continue

    raise ValueError(f"Cannot parse time: {when_str!r}. Use ISO (2026-03-27T15:00) or relative (+45m, +2h, +1d)")


def _to_cron(dt: datetime) -> str:
    """Convert datetime to a cron expression: minute hour day month *"""
    return f"{dt.minute} {dt.hour} {dt.day} {dt.month} *"


def _make_id(text: str) -> str:
    raw = f"{time.time_ns()}:{text}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _write_reminder_script(
    reminder_id: str,
    message: str,
    gateway_url: str,
    telegram_id: str,
) -> Path:
    REMINDERS_DIR.mkdir(exist_ok=True)
    script_path = REMINDERS_DIR / f"reminder_{reminder_id}.py"
    content = _SCRIPT_TEMPLATE.format(
        reminder_id=reminder_id,
        gateway_url_repr=repr(gateway_url),
        telegram_id_repr=repr(telegram_id),
        message_repr=repr(f"\u23f0 Reminder: {message}"),
        reminder_id_repr=repr(reminder_id),
    )
    script_path.write_text(content)
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script_path


def _add_cron_entry(cron_expr: str, script_path: Path, reminder_id: str) -> None:
    entry = f"{cron_expr} {script_path} # PKB_REMINDER_{reminder_id}"
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""
    new_crontab = existing.rstrip("\n") + "\n" + entry + "\n"
    subprocess.run(["crontab", "-"], input=new_crontab, text=True, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--reminder-text", required=True)
    parser.add_argument("--when", required=True, help="ISO datetime or +Nm/+Nh/+Nd")
    args = parser.parse_args()

    env = _load_env()
    gateway_url = env.get("TELEGRAM_GATEWAY_URL", "http://localhost:3001")
    telegram_id = env.get("MY_TELEGRAM_ID", "").strip()

    if not telegram_id:
        print(json.dumps({"ok": False, "error": "MY_TELEGRAM_ID not set in .env"}))
        return 1

    try:
        fire_at = _parse_when(args.when)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    if fire_at <= datetime.now():
        print(json.dumps({"ok": False, "error": f"Reminder time {fire_at.isoformat()} is in the past"}))
        return 1

    reminder_id = _make_id(args.reminder_text)
    cron_expr = _to_cron(fire_at)
    script_path = _write_reminder_script(reminder_id, args.reminder_text, gateway_url, telegram_id)
    _add_cron_entry(cron_expr, script_path, reminder_id)

    print(json.dumps({
        "ok": True,
        "reminder_id": reminder_id,
        "reminder_text": args.reminder_text,
        "fire_at": fire_at.strftime("%-d %b %Y at %-I:%M%p").lower(),
        "cron": cron_expr,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
