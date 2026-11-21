"""TML-statistik för ATP-touren, kopplad till Polymarkets matcher.

Laddar data/tml/ÅÅÅÅ.csv (från stats.tennismylife.org, ej för kommersiellt bruk)
och räknar för varje match statistik som var känd FÖRE matchen:
Elo totalt och per underlag, ranking, serve- och returpoäng senaste 52 veckor,
ålder, längd och inbördes möten sedan 2018.

Koppling till Polymarket: samma två spelare (namn normaliserade) och matchen
startar inom turneringens tidsfönster. Osäkra kopplingar flaggas och används inte.
"""
import csv, glob, math, re, unicodedata
from collections import defaultdict
from datetime import datetime, timezone

ROUND = {"R128": 1, "R64": 2, "R32": 3, "R16": 4, "QF": 5, "SF": 6, "F": 7, "RR": 3, "3rd/4th": 6, "": 3}


def norm(name):
    """'Félix Auger-Aliassime' -> 'felix auger aliassime'"""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]+", " ", s.replace("-", " ").replace("'", ""))
    return re.sub(r"\s+", " ", s).strip()


def short(name):
    """Efternamn + första initial: 'felix auger aliassime' -> 'aliassime f'.

    Används bara som reserv när fullständiga namn inte matchar."""
    p = norm(name).split()
    return f"{p[-1]} {p[0][0]}" if len(p) >= 2 else (p[0] if p else "")


def ts_of(d):
    return datetime.strptime(d, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()


def fnum(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def load(folder="data/tml"):
    rows, seen = [], set()
    for f in sorted(glob.glob(f"{folder}/*.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            if r.get("tourney_date") and r.get("winner_name") and r.get("loser_name"):
                key = (r.get("tourney_id"), r.get("match_num"), r["winner_name"], r["loser_name"])
                if key in seen:   # samma match kan finnas i både årsfilen och ongoing.csv
                    continue
                seen.add(key); rows.append(r)
    rows.sort(key=lambda r: (r["tourney_date"], ROUND.get(r["round"], 3), int(fnum(r["match_num"], 0))))
    return rows


def features(rows):
    """Går igenom matcherna i tidsordning och sparar statistik före varje match."""
    elo, selo = defaultdict(lambda: 1500.0), defaultdict(lambda: 1500.0)
    n, sn = defaultdict(int), defaultdict(int)
    serve = defaultdict(list)   # spelare -> [(tid, servepoäng vunna, servepoäng, returpoäng vunna, returpoäng)]
    h2h = defaultdict(int)
    hist = defaultdict(list)    # spelare -> [(tid, vann 1/0, minuter)]
    out = []
    for r in rows:
        w, l, surf = r["winner_name"], r["loser_name"], r["surface"] or "?"
        t = ts_of(r["tourney_date"])

        def sv(p):
            v = [x for x in serve[p] if t - 365 * 86400 <= x[0] < t]
            sp = sum(x[2] for x in v); rp = sum(x[4] for x in v)
            return (sum(x[1] for x in v) / sp if sp > 200 else None,
                    sum(x[3] for x in v) / rp if rp > 200 else None)

        def info(p, side):
            s, ret = sv(p)
            h = hist[p]
            last10 = [x[1] for x in h[-10:]]
            return {"elo": elo[p], "selo": selo[(p, surf)], "n": n[p], "sn": sn[(p, surf)],
                    "form10": sum(last10) / len(last10) if last10 else None,
                    "min14": sum(x[2] for x in h if t - 14 * 86400 <= x[0] < t),
                    "m14": sum(1 for x in h if t - 14 * 86400 <= x[0] < t),
                    "rest": min((t - h[-1][0]) / 86400, 60) if h else 60,
                    "rank": fnum(r[f"{side}_rank"]), "pts": fnum(r[f"{side}_rank_points"]),
                    "age": fnum(r[f"{side}_age"]), "ht": fnum(r[f"{side}_ht"]), "serve": s, "ret": ret}
        out.append({"t": t, "tourney": r["tourney_name"], "surface": surf, "level": r["tourney_level"],
                    "best_of": int(fnum(r["best_of"], 3)), "round": r["round"],
                    "winner": w, "loser": l, "w": info(w, "winner"), "l": info(l, "loser"),
                    "h2h_w": h2h[(w, l)], "h2h_l": h2h[(l, w)]})
        # uppdatera efter matchen
        if "W/O" not in (r.get("score") or ""):
            pw = 1 / (1 + 10 ** ((elo[l] - elo[w]) / 400))
            spw = 1 / (1 + 10 ** ((selo[(l, surf)] - selo[(w, surf)]) / 400))
            for p, res, e in ((w, 1, pw), (l, 0, 1 - pw)):
                elo[p] += 250 / (n[p] + 5) ** 0.4 * (res - e); n[p] += 1
            for p, res, e in ((w, 1, spw), (l, 0, 1 - spw)):
                selo[(p, surf)] += 250 / (sn[(p, surf)] + 5) ** 0.4 * (res - e); sn[(p, surf)] += 1
            h2h[(w, l)] += 1
            mins = fnum(r.get("minutes"), 0) or 0
            hist[w].append((t, 1, mins)); hist[l].append((t, 0, mins))
        wsv = (fnum(r["w_1stWon"]), fnum(r["w_2ndWon"]), fnum(r["w_svpt"]))
        lsv = (fnum(r["l_1stWon"]), fnum(r["l_2ndWon"]), fnum(r["l_svpt"]))
        if None not in wsv + lsv and wsv[2] > 0 and lsv[2] > 0:
            ww, lw = wsv[0] + wsv[1], lsv[0] + lsv[1]
            serve[w].append((t, ww, wsv[2], lsv[2] - lw, lsv[2]))
            serve[l].append((t, lw, lsv[2], wsv[2] - ww, wsv[2]))
    return out


def index(feats):
    full, sh = defaultdict(list), defaultdict(list)
    for f in feats:
        full[frozenset((norm(f["winner"]), norm(f["loser"])))].append(f)
        sh[frozenset((short(f["winner"]), short(f["loser"])))].append(f)
    return full, sh


STOP = {"open", "masters", "the", "de", "of", "atp", "championships", "international", "tennis", "cup", "and", "men", "s", "mens"}


def words(s):
    return {w for w in norm(s).split() if len(w) > 2 and w not in STOP}


def match(a, b, start, idx, window_days=21, tourney=""):
    """Hittar TML-matchen för Polymarkets spelare a och b med starttid `start`.

    `tourney` = turneringsnamnet i Polymarkets titel. Kvalmatcher finns inte i
    TML och kopplas aldrig. Finns flera möjliga matcher avgör turneringsnamnet;
    blir det ändå inte entydigt flaggas matchen som osäker.
    Returnerar (match, 'exakt'|'kortnamn') eller (None, orsak)."""
    if "qualif" in tourney.lower():
        return None, "kvalmatch (finns inte i TML)"
    full, sh = idx
    ok = lambda f: f["t"] - 2 * 86400 <= start <= f["t"] + window_days * 86400
    c = [f for f in full.get(frozenset((norm(a), norm(b))), []) if ok(f)]
    kind = "exakt"
    if not c:
        c = [f for f in sh.get(frozenset((short(a), short(b))), []) if ok(f)]
        kind = "kortnamn"
    if not c:
        return None, "saknas i TML"
    if len(c) > 1 and tourney:
        c2 = [f for f in c if words(f["tourney"]) & words(tourney)]
        if len(c2) == 1:
            c = c2
    if len(c) > 1:
        return None, "flera möjliga (osäker)"
    return c[0], kind
