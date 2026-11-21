import unittest
from bot import tour_check

DAY = 86400


def row(name, date, level="250", surface="Hard"):
    return {"tourney_name": name, "tourney_date": date, "tourney_level": level, "surface": surface, "best_of": "3"}


def ts(d):
    from tml import ts_of
    return ts_of(d)


class TourCheck(unittest.TestCase):
    def test_running_now(self):
        r, why = tour_check([row("Stockholm", "20261110")], "Stockholm", ts("20261112"), "20261114")
        self.assertIsNotNone(r)

    def test_moved_tournament_rejected(self):
        # Metz fanns på touren nov 2025 men inte 2026, och TML är uppdaterad förbi den tiden
        rows = [row("Metz", "20251102"), row("Paris Masters", "20261108", "M")]
        r, why = tour_check(rows, "Metz", ts("20261121"), "20261120")
        self.assertIsNone(r)
        self.assertIn("Challenger", why)

    def test_new_season_accepted_from_last_year(self):
        rows = [row("Brisbane", "20260104")]
        r, why = tour_check(rows, "Brisbane International", ts("20270104"), "20261120")
        self.assertIsNotNone(r)
        self.assertIn("förra årets", why)

    def test_unknown_is_challenger(self):
        r, why = tour_check([row("Stockholm", "20261110")], "Yokohama", ts("20261121"), "20261120")
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
