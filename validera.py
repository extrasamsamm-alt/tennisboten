"""Slår statistikmodellen Polymarket-priset? Det enda test som avgör om modellen får styra bet.

Kör:  python3 hamta_historik.py atp     (en gång, hämtar Polymarkets avslutade ATP-matcher)
      python3 validera.py                (eller: python3 validera.py 180  = pris 180 min före start)

Så går det till:
  1. Modellen tränas BARA på TML-matcher före den första Polymarket-matchen,
     så den har aldrig sett de matcher den testas på.
  2. Varje Polymarket-match kopplas till TML (samma kopplingsregler som boten).
  3. För varje match jämförs modellens chans och Polymarket-priset X minuter före
     start med hur det faktiskt gick: log loss och Brier (lägre = bättre).
  4. Blandningstest: blir priset bättre av att blanda in lite modell? Gör det inte
     det har modellen ingen information som marknaden saknar.
  5. Edgetest: om man köpt varje gång modellen såg minst 10 procentenheter edge
     (till priset + 1 cent + avgift), hade man gått plus?

Utlåtandet längst ner säger rakt ut om modellen duger som edgekälla.
"""
import json, math, os, sys
from datetime import datetime, timezone
import numpy as np
from sklearn.linear_model import LogisticRegression
import tml
from modell_val import vec, rows
from backtest import price_at, HALF_SPREAD, FEE_RATE

EPS = 1e-4


def ll(p, y):
    p = min(max(p, EPS), 1 - EPS)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def score(ps, ys):
    """(log loss, Brier) för listor av sannolikheter och utfall 0/1."""
    n = len(ys)
    return sum(ll(p, y) for p, y in zip(ps, ys)) / n, sum((p - y) ** 2 for p, y in zip(ps, ys)) / n


def orient(f, name):
    """Är Polymarkets spelare `name` vinnaren i TML-matchen f? None om oklart."""
    import odds
    w, l = odds.same_player(name, f["winner"]), odds.same_player(name, f["loser"])
    return True if w and not l else False if l and not w else None


def x_for(f, first_is_winner):
    a, b = (f["w"], f["l"]) if first_is_winner else (f["l"], f["w"])
    g = {"h2h_a": f["h2h_w"] if first_is_winner else f["h2h_l"],
         "h2h_b": f["h2h_l"] if first_is_winner else f["h2h_w"], "best_of": f["best_of"]}
    return vec(a, b, g, True)


def collect(pm, feats, minutes):
    """Kopplar Polymarket-matcher till TML. Returnerar lista av dict med pris, x, y."""
    idx = tml.index(feats)
    out, skipped = [], {}
    for m in pm:
        p = price_at(m["pre"], m["start"] - minutes * 60)
        r = float(m["result"][0])
        if p is None or not (0.02 <= p <= 0.98) or r not in (0.0, 1.0):
            skipped["inget pris / 50-50"] = skipped.get("inget pris / 50-50", 0) + 1; continue
        title = (m.get("title") or "")
        tour, rest = title.split(": ", 1) if ": " in title else ("", title)
        n1, n2 = m["outcomes"]
        f, why = tml.match(n1, n2, m["start"], idx, tourney=tour)
        if f is None:
            skipped[why] = skipped.get(why, 0) + 1; continue
        if f["w"]["n"] < 5 or f["l"]["n"] < 5:
            skipped["för få tourmatcher"] = skipped.get("för få tourmatcher", 0) + 1; continue
        first_w = orient(f, n1)
        if first_w is None:
            skipped["kunde inte orientera"] = skipped.get("kunde inte orientera", 0) + 1; continue
        # rimlighetskoll: TML och Polymarket ska vara överens om vem som vann
        if (r == 1.0) != first_w:
            skipped["TML och Polymarket oense om vinnaren"] = skipped.get("TML och Polymarket oense om vinnaren", 0) + 1; continue
        out.append({"slug": m["slug"], "start": m["start"], "pris": p, "x": x_for(f, first_w), "y": int(r),
                    "vol": m.get("volume") or 0})
    return out, skipped


def train(feats, before):
    R = [r for r in rows(feats, True) if r[0] < before]
    X = np.array([r[1] for r in R]); y = np.array([r[2] for r in R])
    return LogisticRegression(C=0.1, max_iter=3000).fit(np.vstack([X, -X]), np.concatenate([y, 1 - y])), len(R)


def evaluate(data, model_probs):
    ys = [d["y"] for d in data]
    pm = [d["pris"] for d in data]
    res = {"n": len(data), "modell": score(model_probs, ys), "polymarket": score(pm, ys), "blandning": []}
    for w in (0.0, 0.1, 0.2, 0.3, 0.5):
        res["blandning"].append((w, score([(1 - w) * p + w * q for p, q in zip(pm, model_probs)], ys)[0]))
    bets = []
    for d, q in zip(data, model_probs):
        for p, qq, y in ((d["pris"], q, d["y"]), (1 - d["pris"], 1 - q, 1 - d["y"])):
            if qq - p >= 0.10:
                cost = p + HALF_SPREAD; cost += FEE_RATE * cost * (1 - cost)
                bets.append((y - cost, cost))
    res["edgebet"] = (len(bets), sum(b[0] for b in bets) / sum(b[1] for b in bets) if bets else None,
                      (sum(b[0] for b in bets) / len(bets)) / (np.std([b[0] for b in bets], ddof=1) / math.sqrt(len(bets)))
                      if len(bets) > 2 else None)
    return res


def verdict(res):
    lm, lp = res["modell"][0], res["polymarket"][0]
    best_w = min(res["blandning"], key=lambda t: t[1])[0]
    n, roi, t = res["edgebet"]
    lines = []
    if lm < lp:
        lines.append("Modellen har LÄGRE log loss än Polymarket-priset: den träffar bättre än marknaden. Ovanligt; dubbelkolla.")
    else:
        lines.append(f"Modellen är SÄMRE än Polymarket-priset (log loss {lm:.4f} mot {lp:.4f}). "
                     "Den ska inte ensam avgöra bet.")
    if best_w > 0:
        lines.append(f"Men att blanda in {int(100 * best_w)} % modell förbättrar priset: modellen har viss egen information. "
                     "Den duger som filter.")
    else:
        lines.append("Att blanda in modellen gör inte priset bättre: modellen tillför ingenting marknaden inte redan vet.")
    if n and roi is not None:
        sig = "kan mycket väl vara slump" if t is None or abs(t) < 2 else "statistiskt tydligt"
        lines.append(f"Edgetest (minst 10 procentenheter enligt modellen): {n} bet, ROI {100 * roi:+.1f} % efter kostnad, t={t:+.1f} ({sig}).")
    return lines


def main(minutes=60, path="data/historik_atp.jsonl"):
    if not os.path.exists(path):
        print(f"Saknar {path}. Kör först:  python3 hamta_historik.py atp"); return
    pm = [json.loads(l) for l in open(path)]
    first = min(m["start"] for m in pm)
    feats = tml.features(tml.load())
    model, ntrain = train(feats, first)
    data, skipped = collect(pm, feats, minutes)
    if len(data) < 50:
        print(f"För få kopplade matcher ({len(data)}). Skäl till bortfall: {skipped}"); return
    q = list(model.predict_proba(np.array([d["x"] for d in data]))[:, 1])
    res = evaluate(data, q)
    d0 = datetime.fromtimestamp(first, timezone.utc).date()
    print(f"Modellen tränad på {ntrain} TML-matcher före {d0}. Testad på {res['n']} Polymarket-matcher, pris {minutes} min före start.")
    print(f"Bortfall: {skipped}")
    print(f"\n{'':<14}{'log loss':>10}{'Brier':>9}   (lägre = bättre)")
    for k in ("polymarket", "modell"):
        print(f"{k:<14}{res[k][0]:>10.4f}{res[k][1]:>9.4f}")
    print("\nBlandning: (1-w) * Polymarket + w * modell")
    for w, l in res["blandning"]:
        print(f"  w={w:.1f}  log loss {l:.4f}")
    print("\nUTLÅTANDE")
    for line in verdict(res):
        print(" -", line)
    print(" - Nästa steg oavsett: jämför också mot Pinnacle när det finns nog med Pinnacle-bet i data/paper.")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
