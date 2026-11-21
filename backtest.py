"""Backtest på Polymarkets egen historik: var priset före matchstart rätt?

Kör:  python3 backtest.py atp
Frågan: om man köpt en spelare till Polymarket-priset X minuter före start,
hade man gått plus efter avgift? Uppdelat på prisnivå, volym och tid på dygnet.

VIKTIGA BEGRÄNSNINGAR (läs dem):
- Historiken innehåller ett pris per tidpunkt, inte orderboken. Vi vet alltså
  inte exakt vad det kostade att köpa. Vi lägger på ANTAGEN halv spread.
- Avgiften räknas med dagens regel för sport (0,05 * p * (1-p)).
- "Volym" är matchens totala volym, inklusive handel under matchen.
- Starttid är den planerade. Började matchen tidigare kan priset vara "smittat".
"""
import json, math, sys
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HALF_SPREAD = 0.01   # antagande: vi betalar 1 cent över historikpriset
FEE_RATE = 0.05      # sportavgift enligt docs.polymarket.com/trading/fees
MIN_BEFORE = 60      # pris tas denna många minuter före planerad start
MAX_STALE = 6 * 3600 # prispunkten får vara högst så här gammal


def price_at(pre, t):
    best = None
    for ts, p in pre:
        if ts <= t:
            best = (ts, p)
    if best and t - best[0] <= MAX_STALE:
        return best[1]
    return None


def load(name, minutes=MIN_BEFORE):
    bets = []
    for line in open(f"data/historik_{name}.jsonl"):
        m = json.loads(line)
        p1 = price_at(m["pre"], m["start"] - minutes * 60)
        if p1 is None or not (0.02 <= p1 <= 0.98):
            continue
        r1 = float(m["result"][0])
        hour = datetime.fromtimestamp(m["start"], timezone.utc).astimezone(ZoneInfo("Europe/Stockholm")).hour
        for p, r, who in ((p1, r1, 0), (1 - p1, 1 - r1, 1)):
            cost = p + HALF_SPREAD
            cost += FEE_RATE * cost * (1 - cost)
            bets.append({"slug": m["slug"], "start": m["start"], "p": p, "r": r, "cost": cost,
                         "pnl": r - cost, "roi": (r - cost) / cost, "vol": m.get("volume") or 0,
                         "hour": hour, "fav": p >= 0.5, "player": m["outcomes"][who],
                         "void": r == 0.5})
    return bets


def row(label, bs):
    n = len(bs)
    if n < 2:
        return f"  {label:<26} n={n}"
    avg_p = sum(b["p"] for b in bs) / n
    win = sum(b["r"] for b in bs) / n
    pnl = [b["pnl"] for b in bs]
    mean = sum(pnl) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in pnl) / (n - 1))
    se = sd / math.sqrt(n)
    roi = sum(pnl) / sum(b["cost"] for b in bs)
    return (f"  {label:<26} n={n:<6} snittpris {avg_p:.3f}  utfall {win:.3f}  "
            f"skillnad {win - avg_p:+.3f}  ROI efter kostnad {roi * 100:+6.1f}%  (t={mean / se:+.1f})")


def table(title, bs, key, order=None):
    print(f"\n{title}")
    g = defaultdict(list)
    for b in bs:
        g[key(b)].append(b)
    for k in (order or sorted(g)):
        if k in g:
            print(row(str(k), g[k]))


def pbucket(b):
    lo = min(int(b["p"] * 10), 9) / 10
    return f"pris {lo:.1f}-{lo + 0.1:.1f}"


def volbucket(b):
    v = b["vol"]
    return "1: under 1 000 USD" if v < 1000 else "2: 1 000-10 000" if v < 10000 else \
           "3: 10 000-100 000" if v < 100000 else "4: över 100 000"


def daypart(b):
    return "natt (23-07 svensk tid)" if (b["hour"] >= 23 or b["hour"] < 7) else "dag/kväll (07-23)"


def main(name):
    bs = load(name)
    matches = len({b["slug"] for b in bs})
    d0 = datetime.fromtimestamp(min(b["start"] for b in bs)).date()
    d1 = datetime.fromtimestamp(max(b["start"] for b in bs)).date()
    print(f"Serie {name}: {matches} matcher med användbart pris {MIN_BEFORE} min före start, {d0} till {d1}")
    print(f"Antaganden: halv spread {HALF_SPREAD}, avgift {FEE_RATE}*p*(1-p). Varje match ger två 'bet' (en per spelare).")
    print(f"Avgjorda 50-50 (walkover/inställd): {sum(b['void'] for b in bs) // 2} matcher")
    print("t-värde: under ca 2 i absolutvärde = kan mycket väl vara slump.")
    table("PRISNIVÅ (kalibrering): stämmer priset med hur ofta spelaren vann?", bs, pbucket)
    table("VOLYM: är lågvolymsmatcher sämre prissatta? (bara favoriter)", [b for b in bs if b["fav"]], volbucket)
    table("VOLYM (bara underdogs)", [b for b in bs if not b["fav"]], volbucket)
    table("TID PÅ DYGNET (favoriter)", [b for b in bs if b["fav"]], daypart)
    table("TID PÅ DYGNET (underdogs)", [b for b in bs if not b["fav"]], daypart)
    cut = sorted(b["start"] for b in bs)[int(len(bs) * 0.7)]
    table("STABILITET: favoriter, första 70 % av tiden mot sista 30 %", [b for b in bs if b["fav"]],
          lambda b: "A: tidig period" if b["start"] < cut else "B: sen period")
    table("STABILITET: underdogs", [b for b in bs if not b["fav"]],
          lambda b: "A: tidig period" if b["start"] < cut else "B: sen period")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "atp")
