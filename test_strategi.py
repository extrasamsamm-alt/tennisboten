"""Tester för signalregler, spelarmappning, rättning av ofyllda bud och valideringen."""
import json, math, unittest
from unittest import mock
import bot
import validera


def side(name, is_a, chans, budpris, pin=None):
    s = {"spelare": name, "är_A": is_a, "chans": chans, "budpris": budpris, "edge": chans - budpris,
         "mitt": budpris + 0.01, "spread": 0.01, "djup_sälj": [], "maxpris": chans - 0.10}
    if pin is not None:
        s.update({"pin": pin, "edge_pin": pin - budpris, "maxpris_pin": pin - 0.03})
    return s


class Decide(unittest.TestCase):
    def test_pinnacle_signal_with_model_filter(self):
        a = {"pin": {"pA": 0.55}, "sides": [side("A", True, 0.56, 0.50, 0.55), side("B", False, 0.44, 0.48, 0.45)]}
        bot.decide(a)
        self.assertEqual(a["signal"], "A")
        self.assertNotIn("signal_modell", a)     # modellen ser bara 6 procentenheter

    def test_model_disagrees_blocks(self):
        a = {"pin": {"pA": 0.55}, "sides": [side("A", True, 0.45, 0.50, 0.55), side("B", False, 0.55, 0.48, 0.45)]}
        bot.decide(a)
        self.assertNotIn("signal", a)

    def test_old_model_strategy_kept(self):
        a = {"sides": [side("A", True, 0.70, 0.50), side("B", False, 0.30, 0.48)]}
        bot.decide(a)
        self.assertNotIn("signal", a)
        self.assertEqual(a["signal_modell"], "A")
        self.assertIn("Ingen Pinnacle", a["slutsats"])


class Mapping(unittest.TestCase):
    def test_outcome_index(self):
        self.assertEqual(bot.outcome_index(["Medvedev", "Zverev"], "Alexander Zverev", "Daniil Medvedev"), 1)
        self.assertEqual(bot.outcome_index(["Alexander Zverev", "Daniil Medvedev"], "Alexander Zverev", "Daniil Medvedev"), 0)
        self.assertIsNone(bot.outcome_index(["Zverev", "Zverev"], "Alexander Zverev", "Mischa Zverev"))
        self.assertIsNone(bot.outcome_index(["Sinner", "Alcaraz"], "Alexander Zverev", "Daniil Medvedev"))


class Settle(unittest.TestCase):
    def test_unfilled_gets_outcome(self):
        b = {"lagd": 100, "start": 200, "slug": "x", "conditionId": "c", "utfall_index": 1, "budpris": 0.40,
             "insats_fast": 100.0, "insats_kelly": 300.0, "status": "ej fylld", "fylld": False}
        ev = {"markets": [{"conditionId": "c", "closed": True, "outcomePrices": json.dumps(["0", "1"])}]}
        with mock.patch.object(bot.h, "get", return_value=ev), mock.patch.object(bot, "NOW", lambda: 1000):
            n = bot.settle([b])
        self.assertEqual(n, 1)
        self.assertEqual(b["status"], "ej fylld")
        self.assertEqual(b["utfall"], 1.0)
        self.assertAlmostEqual(b["resultat_om_fylld_fast"], 150.0)
        self.assertNotIn("resultat_fast", b)
        self.assertEqual(bot.kassa_nu([b], "fast", "modell"), bot.STRAT["kassa"])   # påverkar inte kassan

    def test_old_bets_are_model_strategy(self):
        self.assertEqual(bot.strat_of({}), "modell")


class Validate(unittest.TestCase):
    def test_score_and_market_beats_noise(self):
        import random
        random.seed(1)
        data, noisy = [], []
        for _ in range(3000):
            p = random.uniform(0.1, 0.9)
            y = 1 if random.random() < p else 0
            data.append({"pris": p, "y": y})
            noisy.append(min(max(p + random.gauss(0, 0.15), 0.02), 0.98))
        res = validera.evaluate(data, noisy)
        self.assertLess(res["polymarket"][0], res["modell"][0])
        self.assertEqual(min(res["blandning"], key=lambda t: t[1])[0], 0.0)
        self.assertTrue(any("SÄMRE" in l for l in validera.verdict(res)))

    def test_ll(self):
        self.assertAlmostEqual(validera.ll(0.5, 1), math.log(2))


if __name__ == "__main__":
    unittest.main()
