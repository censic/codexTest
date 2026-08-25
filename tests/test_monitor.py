import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "monitor.py"
spec = importlib.util.spec_from_file_location("monitor", MODULE_PATH)
monitor = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = monitor
spec.loader.exec_module(monitor)


class MonitorTests(unittest.TestCase):
    def test_as_price(self):
        self.assertEqual(monitor.as_price("$1,234.50"), 1234.50)
        self.assertEqual(monitor.as_price(499), 499.0)
        self.assertIsNone(monitor.as_price("n/a"))

    def test_nonstop_preference_within_threshold(self):
        connection = {
            "google_flights_display_price": 300,
            "outbound": {"stops": 1},
            "return": {"stops": 1},
        }
        nonstop = {
            "google_flights_display_price": 385,
            "outbound": {"stops": 0},
            "return": {"stops": 0},
        }
        self.assertIs(monitor.choose_with_nonstop_preference([connection, nonstop], 100), nonstop)

    def test_connection_selected_when_savings_exceed_threshold(self):
        connection = {
            "google_flights_display_price": 300,
            "outbound": {"stops": 1},
            "return": {"stops": 1},
        }
        nonstop = {
            "google_flights_display_price": 425,
            "outbound": {"stops": 0},
            "return": {"stops": 0},
        }
        self.assertIs(monitor.choose_with_nonstop_preference([connection, nonstop], 100), connection)

    def test_booking_price_together(self):
        price, seller = monitor.booking_price({"together": {"price": 512, "book_with": "Delta"}})
        self.assertEqual(price, 512.0)
        self.assertEqual(seller, "Delta")

    def test_thanksgiving_profile_count_and_dates(self):
        config = monitor.load_json(Path(__file__).resolve().parents[1] / "config" / "trips.json")
        profiles = monitor.build_profiles(config)
        self.assertEqual(len(profiles), 2)
        self.assertEqual({profile.outbound_date for profile in profiles}, {"2026-11-25"})
        self.assertEqual({profile.return_date for profile in profiles}, {"2026-11-28", "2026-11-29"})
        self.assertEqual({profile.times for profile in profiles}, {"0,23"})


if __name__ == "__main__":
    unittest.main()
