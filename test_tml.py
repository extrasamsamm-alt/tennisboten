import unittest
from tml import norm, short, match, index


def f(w, l, t, **kw):
    base = {"winner": w, "loser": l, "t": t}
    base.update(kw)
    return base


DAY = 86400


class T(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(norm("Félix Auger-Aliassime"), "felix auger aliassime")
        self.assertEqual(norm("  Vito Dell'Elba "), "vito dellelba")
        self.assertEqual(short("Carlos Alcaraz"), "alcaraz c")

    def test_exact_any_order(self):
        idx = index([f("Carlos Alcaraz", "Frances Tiafoe", 1000 * DAY)])
        m, kind = match("Frances Tiafoe", "Carlos Alcaraz", 1003 * DAY, idx)
        self.assertEqual(kind, "exakt")
        self.assertEqual(m["winner"], "Carlos Alcaraz")

    def test_short_name_fallback(self):
        idx = index([f("Felix Auger Aliassime", "Lorenzo Musetti", 1000 * DAY)])
        m, kind = match("Félix Auger-Aliassime", "Lorenzo Musetti", 1001 * DAY, idx)
        self.assertEqual(kind, "exakt")
        idx = index([f("Alex de Minaur", "Jannik Sinner", 1000 * DAY)])
        m, kind = match("A. De Minaur", "J. Sinner", 1001 * DAY, idx)  # samma efternamn + initial
        self.assertEqual(kind, "kortnamn")

    def test_outside_window(self):
        idx = index([f("Carlos Alcaraz", "Frances Tiafoe", 1000 * DAY)])
        m, why = match("Carlos Alcaraz", "Frances Tiafoe", 1100 * DAY, idx)
        self.assertIsNone(m)
        self.assertEqual(why, "saknas i TML")

    def test_ambiguous_is_flagged_not_guessed(self):
        idx = index([f("Carlos Alcaraz", "Jannik Sinner", 1000 * DAY),
                     f("Jannik Sinner", "Carlos Alcaraz", 1005 * DAY)])
        m, why = match("Carlos Alcaraz", "Jannik Sinner", 1006 * DAY, idx)
        self.assertIsNone(m)
        self.assertIn("osäker", why)

    def test_different_player_same_surname_not_matched(self):
        idx = index([f("Alexander Zverev", "Mischa Zverev", 1000 * DAY)])
        m, why = match("Alexander Zverev", "Daniil Medvedev", 1001 * DAY, idx)
        self.assertIsNone(m)


class T2(unittest.TestCase):
    def test_qualification_never_matched(self):
        idx = index([f("Francisco Comesana", "David Goffin", 1000 * DAY, tourney="Basel")])
        m, why = match("Francisco Comesana", "David Goffin", 999 * DAY, idx,
                       tourney="Swiss Indoors Basel, Qualification")
        self.assertIsNone(m)
        self.assertIn("kval", why)

    def test_tournament_name_breaks_tie(self):
        idx = index([f("Learner Tien", "Daniil Medvedev", 1000 * DAY, tourney="Beijing"),
                     f("Learner Tien", "Daniil Medvedev", 1007 * DAY, tourney="Shanghai Masters")])
        m, kind = match("Learner Tien", "Daniil Medvedev", 1010 * DAY, idx, tourney="Shanghai Rolex Masters")
        self.assertEqual(m["tourney"], "Shanghai Masters")


if __name__ == "__main__":
    unittest.main()
