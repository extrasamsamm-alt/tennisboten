import json, os, tempfile, unittest
import odds

T0 = 1795000000.0  # fast "nu" i testerna


def fake_api(calls, start=T0 + 3 * 3600, o1=1.80, o2=2.10, swap=False):
    def fetch(path, params):
        calls.append(path)
        if path == "fixtures":
            p1, p2 = ("Medvedev, Daniil", "Zverev, Alexander") if swap else ("Zverev, Alexander", "Medvedev, Daniil")
            return [{"fixtureId": "id1", "participant1Name": p1, "participant2Name": p2,
                     "startTime": "2026-11-21T18:30:00Z" if start is None else start},
                    {"fixtureId": "id2", "participant1Name": "Sinner, Jannik", "participant2Name": "Alcaraz, Carlos",
                     "startTime": T0 + 3 * 3600}]
        return {"bookmakerOdds": {"pinnacle": {"markets": {"121": {"outcomes": {
            "121": {"players": {"0": {"price": o1}}}, "122": {"players": {"0": {"price": o2}}}}}}}}}
    return fetch


class Names(unittest.TestCase):
    def test_parse_time(self):
        self.assertEqual(odds.parse_time(1700000000), 1700000000)
        self.assertEqual(odds.parse_time(1700000000000), 1700000000)
        self.assertEqual(odds.parse_time("2023-11-14T22:13:20Z"), 1700000000)
        self.assertEqual(odds.parse_time("2023-11-14 22:13:20"), 1700000000)

    def test_same_player(self):
        self.assertTrue(odds.same_player("Alexander Zverev", "Zverev, Alexander"))
        self.assertTrue(odds.same_player("Félix Auger-Aliassime", "Felix Auger Aliassime"))
        self.assertTrue(odds.same_player("A. Zverev", "Alexander Zverev"))
        self.assertFalse(odds.same_player("Alexander Zverev", "Mischa Zverev"))
        self.assertFalse(odds.same_player("Daniil Medvedev", "Alexander Zverev"))


class Pin(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "cache.json")

    def make(self, calls, **kw):
        return odds.Pinnacle(key="k", path=self.path, now=lambda: T0, fetch=fake_api(calls, **kw), per_month=10, per_day=3)

    def test_fair_and_cache(self):
        calls = []
        p = self.make(calls)
        r, why = p.fair("Alexander Zverev", "Daniil Medvedev", T0 + 3 * 3600)
        self.assertIsNone(why)
        self.assertAlmostEqual(r["pA"] + r["pB"], 1)
        self.assertAlmostEqual(r["pA"], (1 / 1.8) / (1 / 1.8 + 1 / 2.1))
        # andra gången: inget nytt anrop (cache), och räknaren överlever en ny instans
        r2, _ = self.make(calls).fair("Alexander Zverev", "Daniil Medvedev", T0 + 3 * 3600)
        self.assertEqual(calls, ["fixtures", "odds"])
        self.assertAlmostEqual(r2["pA"], r["pA"])
        self.assertEqual(self.make(calls).left(), 1)

    def test_swapped_order(self):
        calls = []
        r, _ = self.make(calls, swap=True).fair("Alexander Zverev", "Daniil Medvedev", T0 + 3 * 3600)
        # spelare 1 hos OddsPapi är nu Medvedev med odds 1.80, så Zverev får 2.10
        self.assertEqual(r["oddsA"], 2.10)
        self.assertLess(r["pA"], 0.5)

    def test_budget_stops_calls(self):
        calls = []
        p = self.make(calls)
        p.per_day = 1
        p.fair("Alexander Zverev", "Daniil Medvedev", T0 + 3 * 3600)   # fixtures tar sista anropet
        r, why = p.fair("Alexander Zverev", "Daniil Medvedev", T0 + 3 * 3600)
        self.assertIsNone(r)
        self.assertIn("budget", why)
        self.assertEqual(calls, ["fixtures"])

    def test_wrong_time_not_matched(self):
        calls = []
        r, why = self.make(calls, start=T0 + 40 * 3600).fair("Alexander Zverev", "Daniil Medvedev", T0 + 3 * 3600)
        self.assertIsNone(r)
        self.assertIn("hittades inte", why)

    def test_no_key(self):
        r, why = odds.Pinnacle(key="", path=self.path).fair("A B", "C D", T0)
        self.assertIsNone(r)
        self.assertIn("ODDSPAPI_KEY", why)


if __name__ == "__main__":
    unittest.main()
