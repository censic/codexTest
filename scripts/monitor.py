#!/usr/bin/env python3
"""Fault-tolerant entry point for the BOS-MCI holiday flight monitor."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "scripts" / "monitor_core.py"

spec = importlib.util.spec_from_file_location("monitor_core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = core
spec.loader.exec_module(core)

_original_get_json = core.get_json
_original_base_params = core.base_params
_original_render_report = core.render_report
_suppressed_errors: list[str] = []


def base_params(config: dict[str, Any], profile: Any) -> dict[str, Any]:
    """Build a current documented SerpApi request."""
    params = dict(_original_base_params(config, profile))
    params.pop("bags", None)
    params.pop("no_cache", None)
    return params


def get_json(endpoint: str, params: dict[str, Any], api_key: str, retries: int = 2) -> dict[str, Any]:
    """Keep one failed date search from aborting the entire matrix."""
    clean_params = dict(params)
    clean_params.pop("bags", None)
    clean_params.pop("no_cache", None)
    try:
        return _original_get_json(endpoint, clean_params, api_key, retries=retries)
    except core.MonitorError as exc:
        if endpoint == core.ACCOUNT_ENDPOINT:
            raise
        message = core.sanitize_error(str(exc), api_key)
        transient = any(term in message.lower() for term in ("timeout", "timed out", "proxy", "internal"))
        if transient:
            time.sleep(4)
            try:
                return _original_get_json(endpoint, clean_params, api_key, retries=0)
            except core.MonitorError as retry_exc:
                message = core.sanitize_error(str(retry_exc), api_key)
        _suppressed_errors.append(message)
        return {
            "best_flights": [],
            "other_flights": [],
            "booking_options": [],
            "search_metadata": {"status": "Error", "created_at": core.utc_now()},
        }


def render_report(payload: dict[str, Any]) -> str:
    report = _original_render_report(payload)
    if not _suppressed_errors:
        return report
    unique = list(dict.fromkeys(_suppressed_errors))
    warning_lines = [
        "",
        "## Search warnings",
        "",
        f"{len(_suppressed_errors)} SerpApi request(s) failed during this run. The table contains only successfully returned date windows.",
        "",
    ]
    warning_lines.extend(f"- {message}" for message in unique[:12])
    parts = report.splitlines()
    insert_at = min(7, len(parts))
    return "\n".join(parts[:insert_at] + warning_lines + parts[insert_at:])


# Patch the preserved core module. Including the window in the key prevents
# morning and after-work searches from overwriting one another.
core.base_params = base_params
core.get_json = get_json
core.render_report = render_report
core.SearchProfile.date_pair_key = property(
    lambda self: f"{self.holiday}:{self.outbound_date}:{self.return_date}:{self.window}"
)

# Re-export the public helpers used by the unit tests.
MonitorError = core.MonitorError
SearchProfile = core.SearchProfile
load_json = core.load_json
build_profiles = core.build_profiles
as_price = core.as_price
booking_price = core.booking_price
choose_with_nonstop_preference = core.choose_with_nonstop_preference


def write_failure_report(message: str) -> None:
    checked_at = core.utc_now()
    safe_message = message.replace(os.environ.get("SERPAPI_API_KEY", ""), "***")
    core.LATEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checked_at": checked_at,
        "status": "failed",
        "route": {"origin": "BOS", "destination": "MCI"},
        "account": {},
        "itineraries": [],
        "errors": [safe_message],
    }
    core.LATEST_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with core.HISTORY_PATH.open("a", encoding="utf-8") as history:
        history.write(json.dumps(payload) + "\n")
    core.REPORT_PATH.write_text(
        "# BOS–MCI Holiday Flight Monitor\n\n"
        f"**Last checked:** {checked_at}  \n"
        "**Run status:** failed\n\n"
        f"The live scan could not complete: {safe_message}\n",
        encoding="utf-8",
    )


def run() -> None:
    core.run()


if __name__ == "__main__":
    try:
        run()
    except core.MonitorError as exc:
        write_failure_report(core.sanitize_error(str(exc), os.environ.get("SERPAPI_API_KEY", "")))
    except Exception as exc:
        write_failure_report(f"Unexpected {type(exc).__name__}: {exc}")
