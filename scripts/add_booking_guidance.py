#!/usr/bin/env python3
"""Add a date-aware holiday booking reminder to REPORT.md."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "REPORT.md"
LATEST_PATH = ROOT / "data" / "latest.json"
START = "<!-- booking-guidance:start -->"
END = "<!-- booking-guidance:end -->"

GUIDANCE = {
    "Thanksgiving 2026": {
        "serious_start": date(2026, 9, 26),
        "target_start": date(2026, 10, 13),
        "target_end": date(2026, 10, 27),
        "latest": date(2026, 11, 1),
        "basis": "Google Flights' historical Thanksgiving low-price range is 24–59 days before departure, with the lowest average around 35 days before departure.",
    },
    "Christmas / New Year 2026–2027": {
        "serious_start": date(2026, 10, 9),
        "target_start": date(2026, 10, 20),
        "target_end": date(2026, 11, 10),
        "latest": date(2026, 11, 20),
        "basis": "Google Flights' historical Christmas low-price range is 32–73 days before departure, with the lowest average around 51 days before departure.",
    },
}


def report_date() -> date:
    try:
        payload = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
        checked = datetime.fromisoformat(str(payload["checked_at"]))
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        return checked.date()
    except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return datetime.now(timezone.utc).date()


def fmt(value: date) -> str:
    return value.strftime("%B %-d, %Y")


def status(today: date, item: dict[str, date | str]) -> str:
    serious = item["serious_start"]
    target_start = item["target_start"]
    target_end = item["target_end"]
    latest = item["latest"]
    assert isinstance(serious, date)
    assert isinstance(target_start, date)
    assert isinstance(target_end, date)
    assert isinstance(latest, date)

    if today < serious:
        days = (serious - today).days
        return f"Baseline monitoring. Start seriously considering fares on **{fmt(serious)}** ({days} days from this report)."
    if today < target_start:
        days = (target_start - today).days
        return f"The serious consideration window is open. The preferred booking window begins **{fmt(target_start)}** ({days} days from this report)."
    if today <= target_end:
        return "**Preferred booking window is open now.** Book when a strong flexible itinerary meets the route-specific price target."
    if today <= latest:
        days = (latest - today).days
        return f"The preferred window has passed, but the broader low-price range is still open. Strongly consider booking by **{fmt(latest)}** ({days} days remaining)."
    return "**Past the preferred booking window.** Prioritize securing an acceptable flexible itinerary instead of waiting for a small price decrease."


def build_section(today: date) -> str:
    lines = [
        START,
        "## When to seriously consider booking",
        "",
        "These dates are planning reminders based on Google's latest published U.S. holiday-flight history. Your actual BOS–MCI trend and schedule flexibility can justify booking sooner.",
        "",
    ]
    for title, item in GUIDANCE.items():
        lines.extend(
            [
                f"### {title}",
                "",
                f"- **Current status:** {status(today, item)}",
                f"- **Serious consideration window opens:** {fmt(item['serious_start'])}",
                f"- **Preferred booking window:** {fmt(item['target_start'])} through {fmt(item['target_end'])}",
                f"- **Do not casually wait beyond:** {fmt(item['latest'])}",
                f"- **Historical basis:** {item['basis']}",
                "",
            ]
        )
    lines.extend(
        [
            "Source: [Google's latest published holiday travel booking insights](https://blog.google/products-and-platforms/products/search/holiday-travel-trends-2025/).",
            END,
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    if not REPORT_PATH.exists():
        raise SystemExit("REPORT.md does not exist; run the flight monitor first.")
    report = REPORT_PATH.read_text(encoding="utf-8")
    if START in report and END in report:
        before, remainder = report.split(START, 1)
        _, after = remainder.split(END, 1)
        report = before.rstrip() + "\n\n" + after.lstrip()
    section = build_section(report_date())
    marker = "## Scope and limits"
    if marker in report:
        report = report.replace(marker, section + marker, 1)
    else:
        report = report.rstrip() + "\n\n" + section
    REPORT_PATH.write_text(report.rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
