import unittest
from karna import fee_per_share, buy_cost, devig, edge


class T(unittest.TestCase):
    def test_fee_matches_polymarket_table(self):
        # docs: 100 andelar sport @ 0.50 -> 1.25 USDC, @ 0.30 -> 1.05, @ 0.70 -> 1.05
        self.assertAlmostEqual(100 * fee_per_share(0.50), 1.25)
        self.assertAlmostEqual(100 * fee_per_share(0.30), 1.05)
        self.assertAlmostEqual(100 * fee_per_share(0.70), 1.05)

    def test_buy_cost_walks_book(self):
        r = buy_cost([(0.60, 5.63), (0.61, 274.04)], 50, rate=0.0)
        self.assertTrue(r["filled"])
        self.assertAlmostEqual(r["spent"], 50)
        self.assertTrue(0.60 < r["avg_price"] < 0.61)

    def test_buy_cost_thin_book(self):
        r = buy_cost([(0.40, 10)], 100, rate=0.0)
        self.assertFalse(r["filled"])
        self.assertAlmostEqual(r["spent"], 4.0)

    def test_buy_cost_includes_fee(self):
        r = buy_cost([(0.50, 1000)], 100)
        self.assertAlmostEqual(r["avg_price"], 0.5125)

    def test_devig(self):
        a, b = devig(1.90, 1.90)
        self.assertAlmostEqual(a, 0.5)
        a, b = devig(1.50, 2.60)
        self.assertAlmostEqual(a + b, 1.0)
        self.assertAlmostEqual(a, (1 / 1.5) / (1 / 1.5 + 1 / 2.6))
        with self.assertRaises(ValueError):
            devig(1.0, 2.0)

    def test_edge(self):
        self.assertAlmostEqual(edge(0.60, 0.55), 0.05)
        # 2 % risk för 50-50 drar ner värdet på en favorit
        self.assertAlmostEqual(edge(0.60, 0.55, p_void=0.02), 0.98 * 0.60 + 0.01 - 0.55)
        self.assertLess(edge(0.50, 0.52), 0)


if __name__ == "__main__":
    unittest.main()
