"""Väljer statistikmodellens inställningar på TML-data FÖRE Polymarket-perioden.

Kör:  python3 modell_val.py
Tränar på 2018-2023, utvärderar på jan 2024 - sep 2025. Polymarket-matcherna
(okt 2025 och framåt) används inte alls här, så valet kan inte "fuska".
"""
import math, random
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import log_loss
import tml
from datetime import datetime, timezone

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
T1 = datetime(2025, 10, 1, tzinfo=timezone.utc).timestamp()


def vec(a, b, f, extra):
    d = lambda k, dflt: (a[k] if a[k] is not None else dflt) - (b[k] if b[k] is not None else dflt)
    lr = lambda x: math.log(x["rank"]) if x["rank"] else math.log(500)
    lp = lambda x: math.log1p(x["pts"]) if x["pts"] else 0.0
    sv = a["serve"] is not None and b["serve"] is not None
    rt = a["ret"] is not None and b["ret"] is not None
    elo = (a["elo"] - b["elo"]) / 400
    v = [elo, (a["selo"] - b["selo"]) / 400, lr(b) - lr(a), lp(a) - lp(b),
         (a["serve"] - b["serve"]) * 10 if sv else 0.0, (a["ret"] - b["ret"]) * 10 if rt else 0.0,
         d("age", 25) / 5, d("ht", 185) / 10, f["h2h_a"] - f["h2h_b"],
         math.log1p(a["n"]) - math.log1p(b["n"]), elo * (f["best_of"] == 5)]
    if extra:
        v += [d("form10", 0.5), (a["min14"] - b["min14"]) / 300, a["m14"] - b["m14"],
              (min(a["rest"], 14) - min(b["rest"], 14)) / 7]
    return v


def rows(feats, extra):
    random.seed(7); out = []
    for f in feats:
        if f["w"]["n"] < 5 or f["l"]["n"] < 5:
            continue
        flip = random.random() < 0.5
        a, b = (f["l"], f["w"]) if flip else (f["w"], f["l"])
        g = {"h2h_a": f["h2h_l"] if flip else f["h2h_w"], "h2h_b": f["h2h_w"] if flip else f["h2h_l"], "best_of": f["best_of"]}
        out.append((f["t"], vec(a, b, g, extra), 0 if flip else 1))
    return out


def main():
    feats = tml.features(tml.load())
    for extra in (False, True):
        R = rows(feats, extra)
        t = np.array([r[0] for r in R]); X = np.array([r[1] for r in R]); y = np.array([r[2] for r in R])
        tr, va = t < T0, (t >= T0) & (t < T1)
        Xm = np.vstack([X[tr], -X[tr]]); ym = np.concatenate([y[tr], 1 - y[tr]])
        print(f"{'med' if extra else 'utan'} form/belastning/vila: träning {tr.sum()}, validering {va.sum()}")
        print(f"  bara Elo underlag      {log_loss(y[va], LogisticRegression().fit(Xm[:, 1:2], ym).predict_proba(X[va][:, 1:2])[:, 1]):.4f}")
        for C in (0.1, 1.0):
            m = LogisticRegression(C=C, max_iter=3000).fit(Xm, ym)
            print(f"  logistisk C={C:<4}      {log_loss(y[va], m.predict_proba(X[va])[:, 1]):.4f}")
        for d in (2, 3):
            g = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.03, max_depth=d, min_samples_leaf=200, l2_regularization=1.0).fit(Xm, ym)
            p = (g.predict_proba(X[va])[:, 1] + 1 - g.predict_proba(-X[va])[:, 1]) / 2
            print(f"  boosting djup {d}        {log_loss(y[va], p):.4f}")


if __name__ == "__main__":
    main()
