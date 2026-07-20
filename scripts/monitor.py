#!/usr/bin/env python3
"""Weekly BOS–MCI holiday flight monitor using SerpApi Google Flights."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "trips.json"
LATEST_PATH = ROOT / "data" / "latest.json"
HISTORY_PATH = ROOT / "data" / "history.jsonl"
REPORT_PATH = ROOT / "REPORT.md"
SERP_ENDPOINT = "https://serpapi.com/search.json"
ACCOUNT_ENDPOINT = "https://serpapi.com/account.json"
USER_AGENT = "censic-bos-mci-flight-monitor/1.0"


class MonitorError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchProfile:
    holiday: str
    holiday_name: str
    outbound_date: str
    return_date: str
    window: str
    times: str
    work_safe: bool

    @property
    def date_pair_key(self) -> str:
        return f"{self.holiday}:{self.outbound_date}:{self.return_date}"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize_error(message: str, secret: str) -> str:
    return message.replace(secret, "***") if secret else message


def get_json(endpoint: str, params: dict[str, Any], api_key: str, retries: int = 2) -> dict[str, Any]:
    clean_params = {key: value for key, value in params.items() if value is not None}
    clean_params["api_key"] = api_key
    url = f"{endpoint}?{urllib.parse.urlencode(clean_params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=150) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict) and payload.get("error"):
                raise MonitorError(str(payload["error"]))
            return payload
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt >= retries:
                raise MonitorError(sanitize_error(str(exc), api_key)) from exc
            time.sleep(2 ** attempt)
    raise MonitorError("Unreachable request state")


def account_status(api_key: str) -> dict[str, Any]:
    return get_json(ACCOUNT_ENDPOINT, {}, api_key)


def build_profiles(config: dict[str, Any]) -> list[SearchProfile]:
    profiles: list[SearchProfile] = []
    for holiday, details in config["holidays"].items():
        for outbound in details["outbounds"]:
            for return_date in details["returns"]:
                profiles.append(
                    SearchProfile(
                        holiday=holiday,
                        holiday_name=details["display_name"],
                        outbound_date=outbound["date"],
                        return_date=return_date,
                        window=outbound["window"],
                        times=outbound["times"],
                        work_safe=bool(outbound["work_safe"]),
                    )
                )
    return profiles


def base_params(config: dict[str, Any], profile: SearchProfile) -> dict[str, Any]:
    return {
        "engine": "google_flights",
        "departure_id": config["origin"],
        "arrival_id": config["destination"],
        "outbound_date": profile.outbound_date,
        "return_date": profile.return_date,
        "type": "1",
        "travel_class": "1",
        "adults": str(config["passengers"]),
        "bags": str(config["carry_on_bags"]),
        "currency": config["currency"],
        "hl": config["locale"],
        "gl": config["country"],
        "outbound_times": profile.times,
        "sort_by": "2",
        "stops": "0",
        "show_hidden": "true",
        "deep_search": "true",
        "no_cache": "true",
    }


def flight_groups(payload: dict[str, Any]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for key in ("best_flights", "other_flights"):
        value = payload.get(key, [])
        if isinstance(value, list):
            groups.extend(item for item in value if isinstance(item, dict))
    return groups


def as_price(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = "".join(ch for ch in value if ch.isdigit() or ch == ".")
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None
    return None


def parse_segments(group: dict[str, Any]) -> list[dict[str, Any]]:
    segments = group.get("flights", [])
    return segments if isinstance(segments, list) else []


def summarize_segments(segments: list[dict[str, Any]]) -> dict[str, Any]:
    if not segments:
        return {
            "departure_time": None,
            "arrival_time": None,
            "airlines": [],
            "flight_numbers": [],
            "stops": None,
            "duration_minutes": None,
        }
    first = segments[0]
    last = segments[-1]
    airlines = list(dict.fromkeys(str(segment.get("airline")) for segment in segments if segment.get("airline")))
    numbers = [str(segment.get("flight_number")) for segment in segments if segment.get("flight_number")]
    duration = sum(int(segment.get("duration", 0) or 0) for segment in segments)
    return {
        "departure_time": (first.get("departure_airport") or {}).get("time"),
        "arrival_time": (last.get("arrival_airport") or {}).get("time"),
        "airlines": airlines,
        "flight_numbers": numbers,
        "stops": max(0, len(segments) - 1),
        "duration_minutes": duration or None,
    }


def parse_outbound_candidates(payload: dict[str, Any], profile: SearchProfile) -> list[dict[str, Any]]:
    metadata = payload.get("search_metadata", {}) if isinstance(payload.get("search_metadata"), dict) else {}
    candidates: list[dict[str, Any]] = []
    for group in flight_groups(payload):
        price = as_price(group.get("price"))
        token = group.get("departure_token")
        segments = parse_segments(group)
        if price is None or not token or not segments:
            continue
        summary = summarize_segments(segments)
        candidates.append(
            {
                "holiday": profile.holiday,
                "holiday_name": profile.holiday_name,
                "outbound_date": profile.outbound_date,
                "return_date": profile.return_date,
                "outbound_window": profile.window,
                "work_safe": profile.work_safe,
                "google_flights_display_price": price,
                "outbound": summary,
                "departure_token": token,
                "search_created_at": metadata.get("created_at"),
                "google_flights_url": metadata.get("google_flights_url"),
                "search_profile": profile,
            }
        )
    return dedupe_candidates(candidates, outbound_only=True)


def dedupe_candidates(candidates: Iterable[dict[str, Any]], outbound_only: bool = False) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    output: list[dict[str, Any]] = []
    for candidate in candidates:
        outbound = candidate.get("outbound", {})
        returning = candidate.get("return", {})
        signature: tuple[Any, ...] = (
            candidate.get("outbound_date"),
            candidate.get("return_date"),
            tuple(outbound.get("flight_numbers", [])),
            outbound.get("departure_time"),
            candidate.get("google_flights_display_price"),
        )
        if not outbound_only:
            signature += (tuple(returning.get("flight_numbers", [])), returning.get("departure_time"))
        if signature not in seen:
            seen.add(signature)
            output.append(candidate)
    return output


def is_nonstop(candidate: dict[str, Any]) -> bool:
    outbound_stops = candidate.get("outbound", {}).get("stops")
    return_stops = candidate.get("return", {}).get("stops")
    if "return" not in candidate:
        return outbound_stops == 0
    return outbound_stops == 0 and return_stops == 0


def choose_with_nonstop_preference(candidates: list[dict[str, Any]], threshold: float) -> dict[str, Any] | None:
    priced = [candidate for candidate in candidates if as_price(candidate.get("google_flights_display_price")) is not None]
    if not priced:
        return None
    cheapest = min(priced, key=lambda item: float(item["google_flights_display_price"]))
    nonstop = [item for item in priced if is_nonstop(item)]
    if not nonstop:
        return cheapest
    cheapest_nonstop = min(nonstop, key=lambda item: float(item["google_flights_display_price"]))
    if float(cheapest_nonstop["google_flights_display_price"]) <= float(cheapest["google_flights_display_price"]) + threshold:
        return cheapest_nonstop
    return cheapest


def parse_return_candidates(payload: dict[str, Any], outbound: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = payload.get("search_metadata", {}) if isinstance(payload.get("search_metadata"), dict) else {}
    output: list[dict[str, Any]] = []
    for group in flight_groups(payload):
        price = as_price(group.get("price"))
        booking_token = group.get("booking_token")
        segments = parse_segments(group)
        if price is None or not segments:
            continue
        item = {key: value for key, value in outbound.items() if key not in {"departure_token", "search_profile"}}
        item.update(
            {
                "google_flights_display_price": price,
                "return": summarize_segments(segments),
                "booking_token": booking_token,
                "return_search_created_at": metadata.get("created_at"),
                "google_flights_url": metadata.get("google_flights_url") or outbound.get("google_flights_url"),
                "booking_verified": False,
                "verified_price": None,
                "book_with": None,
            }
        )
        output.append(item)
    return dedupe_candidates(output)


def booking_price(option: dict[str, Any]) -> tuple[float | None, str | None]:
    together = option.get("together")
    if isinstance(together, dict):
        price = as_price(together.get("price"))
        seller = together.get("book_with")
        if price is not None:
            return price, str(seller) if seller else None
    departing = option.get("departing")
    returning = option.get("returning")
    if isinstance(departing, dict) and isinstance(returning, dict):
        out_price = as_price(departing.get("price"))
        back_price = as_price(returning.get("price"))
        if out_price is not None and back_price is not None:
            sellers = [departing.get("book_with"), returning.get("book_with")]
            return out_price + back_price, " + ".join(str(seller) for seller in sellers if seller)
    return None, None


def verify_booking(candidate: dict[str, Any], api_key: str, config: dict[str, Any]) -> dict[str, Any]:
    token = candidate.get("booking_token")
    if not token:
        return candidate
    payload = get_json(
        SERP_ENDPOINT,
        {
            "engine": "google_flights",
            "booking_token": token,
            "currency": config["currency"],
            "hl": config["locale"],
            "gl": config["country"],
            "no_cache": "true",
        },
        api_key,
    )
    options = payload.get("booking_options", [])
    parsed = [booking_price(option) for option in options if isinstance(option, dict)]
    parsed = [(price, seller) for price, seller in parsed if price is not None]
    if parsed:
        price, seller = min(parsed, key=lambda pair: float(pair[0]))
        candidate["booking_verified"] = True
        candidate["verified_price"] = price
        candidate["book_with"] = seller
        metadata = payload.get("search_metadata", {}) if isinstance(payload.get("search_metadata"), dict) else {}
        candidate["booking_verified_at"] = metadata.get("created_at") or utc_now()
    return candidate


def effective_price(candidate: dict[str, Any]) -> float:
    verified = as_price(candidate.get("verified_price"))
    displayed = as_price(candidate.get("google_flights_display_price"))
    return float(verified if verified is not None else displayed if displayed is not None else 10**9)


def itinerary_signature(candidate: dict[str, Any]) -> str:
    outbound = candidate.get("outbound", {})
    returning = candidate.get("return", {})
    return "|".join(
        [
            str(candidate.get("outbound_date")),
            str(candidate.get("return_date")),
            ",".join(outbound.get("flight_numbers", [])),
            str(outbound.get("departure_time")),
            ",".join(returning.get("flight_numbers", [])),
            str(returning.get("departure_time")),
        ]
    )


def choose_verification_candidates(options: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    for holiday in ("thanksgiving", "christmas"):
        holiday_options = [item for item in options if item.get("holiday") == holiday and item.get("booking_token")]
        if not holiday_options:
            continue
        chosen.append(min(holiday_options, key=effective_price))
        work_safe = [item for item in holiday_options if item.get("work_safe")]
        if work_safe:
            chosen.append(min(work_safe, key=effective_price))
    unique: list[dict[str, Any]] = []
    signatures: set[str] = set()
    for item in sorted(chosen, key=effective_price):
        signature = itinerary_signature(item)
        if signature not in signatures:
            signatures.add(signature)
            unique.append(item)
    return unique[:limit]


def strip_tokens(candidate: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in candidate.items() if key not in {"booking_token", "departure_token", "search_profile"}}


def previous_prices() -> dict[str, float]:
    if not LATEST_PATH.exists():
        return {}
    try:
        previous = load_json(LATEST_PATH)
    except (OSError, json.JSONDecodeError):
        return {}
    output: dict[str, float] = {}
    for item in previous.get("itineraries", []):
        if isinstance(item, dict):
            output[itinerary_signature(item)] = effective_price(item)
    return output


def price_change(candidate: dict[str, Any], prior: dict[str, float]) -> float | None:
    old = prior.get(itinerary_signature(candidate))
    return round(effective_price(candidate) - old, 2) if old is not None else None


def format_money(value: Any) -> str:
    price = as_price(value)
    if price is None:
        return "—"
    return f"${price:,.0f}" if float(price).is_integer() else f"${price:,.2f}"


def format_stops(value: Any) -> str:
    if value == 0:
        return "Nonstop"
    if isinstance(value, int):
        return f"{value} stop" if value == 1 else f"{value} stops"
    return "Unknown"


def best_by(options: list[dict[str, Any]], predicate=lambda _: True) -> dict[str, Any] | None:
    matches = [item for item in options if predicate(item)]
    return min(matches, key=effective_price) if matches else None


def render_highlight(label: str, item: dict[str, Any] | None) -> str:
    if not item:
        return f"- **{label}:** No verified itinerary found."
    out = item["outbound"]
    back = item["return"]
    verification = "booking option verified" if item.get("booking_verified") else "Google Flights displayed fare"
    return (
        f"- **{label}:** {item['outbound_date']} → {item['return_date']}, "
        f"{format_money(effective_price(item))}, {format_stops(out.get('stops'))} outbound / "
        f"{format_stops(back.get('stops'))} return, {item['outbound_window']} ({verification})."
    )


def render_report(payload: dict[str, Any]) -> str:
    options = payload["itineraries"]
    lines = [
        "# BOS–MCI Holiday Flight Monitor",
        "",
        f"**Last checked:** {payload['checked_at']}  ",
        "**Source:** SerpApi Google Flights with `deep_search=true`; booking-option verification is explicitly labeled.  ",
        f"**Searches remaining when run began:** {payload['account']['searches_left']} of {payload['account']['monthly_limit']}",
        "",
        "> Prices can change after the timestamp above. A ‘booking verified’ price came from Google Flights booking options during this run. Other prices are exact fares displayed by Google Flights at their listed search timestamp, but were not independently re-priced at checkout.",
        "",
    ]
    for holiday, title in (("thanksgiving", "Thanksgiving 2026"), ("christmas", "Christmas / New Year 2026–2027")):
        holiday_options = [item for item in options if item.get("holiday") == holiday]
        lines.extend(
            [
                f"## {title}",
                "",
                render_highlight("Cheapest usable", best_by(holiday_options)),
                render_highlight("Best nonstop", best_by(holiday_options, is_nonstop)),
                render_highlight("Best after-work outbound", best_by(holiday_options, lambda item: bool(item.get("work_safe")))),
                "",
                "| Outbound | Window | Return | Outbound flight | Return flight | Stops | Price | Verification | Change |",
                "|---|---|---|---|---|---|---:|---|---:|",
            ]
        )
        for item in sorted(holiday_options, key=lambda row: (row["outbound_date"], row["return_date"], effective_price(row))):
            out = item["outbound"]
            back = item["return"]
            flights_out = ", ".join(out.get("flight_numbers", [])) or ", ".join(out.get("airlines", [])) or "—"
            flights_back = ", ".join(back.get("flight_numbers", [])) or ", ".join(back.get("airlines", [])) or "—"
            stops = f"{format_stops(out.get('stops'))} / {format_stops(back.get('stops'))}"
            verification = f"Verified: {item.get('book_with') or 'seller shown'}" if item.get("booking_verified") else "Displayed fare"
            change = item.get("price_change_usd")
            change_text = "New" if change is None else (f"+{format_money(change)}" if change > 0 else format_money(change))
            lines.append(
                f"| {item['outbound_date']} {out.get('departure_time') or ''} | {item['outbound_window']} | "
                f"{item['return_date']} {back.get('departure_time') or ''} | {flights_out} | {flights_back} | "
                f"{stops} | {format_money(effective_price(item))} | {verification} | {change_text} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Scope and limits",
            "",
            "- Airports are strictly BOS and MCI.",
            "- One adult, economy, one carry-on bag.",
            "- Connections are allowed in the search, but nonstop is preferred when it costs no more than $100 extra.",
            "- Thanksgiving outbound windows: November 24 morning / after work and November 25 morning; returns November 27–29.",
            "- Christmas outbound windows: December 21–23 morning / after work; returns January 2–3 only.",
            "- This monitor retrieves cash fares. It cannot access authenticated Chase Travel or airline award-account pricing.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    api_key = os.environ.get("SERPAPI_API_KEY", "").strip()
    if not api_key:
        raise MonitorError("SERPAPI_API_KEY is missing. Add it as a GitHub Actions repository secret.")

    config = load_json(CONFIG_PATH)
    profiles = build_profiles(config)
    account = account_status(api_key)
    searches_left = int(account.get("total_searches_left", account.get("plan_searches_left", 0)) or 0)
    monthly_limit = int(account.get("searches_per_month", 0) or 0)
    minimum = int(config.get("minimum_searches_required", 33))
    if searches_left < minimum:
        raise MonitorError(f"Only {searches_left} SerpApi searches remain; at least {minimum} are required for a complete run.")

    previous = previous_prices()
    outbound_by_pair: dict[str, list[dict[str, Any]]] = {}
    for index, profile in enumerate(profiles, start=1):
        print(f"Initial search {index}/{len(profiles)}: {profile.holiday} {profile.outbound_date} {profile.window} → {profile.return_date}")
        payload = get_json(SERP_ENDPOINT, base_params(config, profile), api_key)
        outbound_by_pair.setdefault(profile.date_pair_key, []).extend(parse_outbound_candidates(payload, profile))

    threshold = float(config["connection_savings_threshold_usd"])
    final_options: list[dict[str, Any]] = []
    date_pairs = sorted(outbound_by_pair.items())
    for index, (_, outbound_candidates) in enumerate(date_pairs, start=1):
        selected_outbound = choose_with_nonstop_preference(outbound_candidates, threshold)
        if not selected_outbound:
            continue
        profile = selected_outbound["search_profile"]
        params = base_params(config, profile)
        params["departure_token"] = selected_outbound["departure_token"]
        print(f"Return search {index}/{len(date_pairs)}: {profile.outbound_date} → {profile.return_date}")
        payload = get_json(SERP_ENDPOINT, params, api_key)
        returns = parse_return_candidates(payload, selected_outbound)
        selected_round_trip = choose_with_nonstop_preference(returns, threshold)
        if selected_round_trip:
            final_options.append(selected_round_trip)

    verification_candidates = choose_verification_candidates(final_options, int(config.get("booking_verifications_per_run", 4)))
    verify_signatures = {itinerary_signature(item) for item in verification_candidates}
    for item in final_options:
        if itinerary_signature(item) in verify_signatures:
            verify_booking(item, api_key, config)

    cleaned: list[dict[str, Any]] = []
    for item in final_options:
        item["price_change_usd"] = price_change(item, previous)
        cleaned.append(strip_tokens(item))

    result = {
        "checked_at": utc_now(),
        "route": {"origin": config["origin"], "destination": config["destination"]},
        "account": {
            "searches_left": searches_left,
            "monthly_limit": monthly_limit,
            "plan_name": account.get("plan_name"),
        },
        "itineraries": cleaned,
    }
    LATEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with HISTORY_PATH.open("a", encoding="utf-8") as history:
        history.write(json.dumps({"checked_at": result["checked_at"], "itineraries": cleaned}, ensure_ascii=False) + "\n")
    REPORT_PATH.write_text(render_report(result), encoding="utf-8")
    print(f"Wrote {len(cleaned)} preferred date-pair itineraries.")


if __name__ == "__main__":
    try:
        run()
    except MonitorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
