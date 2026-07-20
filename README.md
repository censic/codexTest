# Free BOS–MCI Holiday Flight Monitor

This repository checks exact Google Flights fares through SerpApi once each Tuesday for Charlie's 2026 Thanksgiving and Christmas / New Year travel between Boston Logan (`BOS`) and Kansas City (`MCI`). It searches the full approved date matrix, evaluates nonstop versus connecting itineraries, verifies a small set of booking options, records price history, and commits a readable report.

## Search scope

### Thanksgiving 2026

- Outbound: November 24 morning, November 24 after 6 p.m., or November 25 morning
- Return: November 27, 28, or 29
- Must be home on Thanksgiving Day

### Christmas / New Year 2026–2027

- Outbound: December 21, 22, or 23, morning or after 6 p.m.
- Return: January 2 or 3 only
- Must be home on Christmas Day, December 29, and New Year's Day

The search assumes one adult, economy, one carry-on bag, and strictly `BOS ↔ MCI`. A nonstop itinerary is preferred when it costs no more than $100 above the cheapest connection.

## One-time secure setup

1. Regenerate the SerpApi key that was exposed in chat. Do not reuse it.
2. In this repository, open **Settings → Secrets and variables → Actions → New repository secret**.
3. Name the secret exactly `SERPAPI_API_KEY` and paste the newly regenerated key.
4. Open **Actions → Weekly holiday flight scan → Run workflow** for the first scan.

Never place the key in a committed file, issue, pull request, workflow input, or chat message.

## Files

- `REPORT.md`: latest human-readable results
- `data/latest.json`: structured latest results for ChatGPT or another client
- `data/history.jsonl`: append-only weekly observations
- `config/trips.json`: travel dates and preferences
- `scripts/monitor.py`: API queries, ranking, verification, and reporting
- `.github/workflows/weekly-flight-scan.yml`: free Tuesday GitHub Actions schedule

## Cost controls

A normal run uses about 37 SerpApi searches: 21 initial searches, up to 12 return lookups, and up to 4 booking-option checks. The script checks the free account's remaining quota before beginning and refuses to start unless enough searches remain for a complete run.

## Accuracy

The monitor uses SerpApi's Google Flights engine with `deep_search=true`, `show_hidden=true`, and `no_cache=true`. Every result is timestamped. Booking-option verification is labeled separately from a fare merely displayed in Google Flights. Airfares can still change between the scan and purchase.

## Manual testing

```bash
export SERPAPI_API_KEY="your-regenerated-key"
python -m unittest discover -s tests -v
python scripts/monitor.py
```
