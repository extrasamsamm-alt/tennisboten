"""Tennisboten: hittar edge i kommande ATP-matcher på Polymarket och paper-tradear.

Kommandon (kör i mappen polymarket-tennis):
  python3 bot.py kör              ett varv: hitta matcher, lägg låtsasbud, rätta gamla, skriv signaler.html
  python3 bot.py kör --loop 20    samma sak var 20:e minut tills du trycker Ctrl+C (låt gå över natten)
  python3 bot.py uppslag "Carlos Alcaraz" "Jannik Sinner"     utlåtande för en match
  python3 bot.py uppslag https://polymarket.com/event/<slug>  samma sak med Polymarket-länk
  python3 bot.py rapport          hur det gått hittills

Två strategier låtsasspelas sida vid sida så att de kan jämföras:
  * "pinnacle" (huvudstrategin): Pinnacles odds utan marginal = rättvis chans.
    Edge = rättvis chans - vårt budpris, minst 3 procentenheter. Statistikmodellen
    används bara som filter: den får inte tycka att spelaren är sämre än budpriset.
    Kräver ODDSPAPI_KEY (se odds.py).
  * "modell" (den gamla): statistikmodellens chans - budpris, minst 10 procentenheter.
    Behålls bara som jämförelse. Kör validera.py för att se om modellen alls slår marknaden.
  * ATP-touren inkl. Grand Slam, ej kval (TML saknar kval och Challenger).
  * Köpbud 1 cent under mittpriset, cirka 3 timmar före start. Ingen avgift för bud.
  * Låtsasinsats: fast 100 kr, och parallellt kvarts-Kelly (max 3 %) av 10 000 kr.
  * Bud som inte fylls rättas ändå, så att rapporten visar om fyllda bud är sämre
    än ofyllda (fylls bara när priset går emot oss = snedvridning).
Inga riktiga order, ingen nyckel, ingen wallet. Bara publik data.
"""
import csv, json, math, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
import numpy as np
from sklearn.linear_model import LogisticRegression
import hamta_historik as h
import odds
import tml
from modell_val import vec, rows

STRAT = {"edge": 0.10, "edge_pin": 0.03, "modell_filter": 0.0, "fore_h": 3.0, "fonster_h": 0.75, "bud_under": 0.01, "min_salt": 15,
         "kassa": 10000.0, "fast": 100.0, "kelly": 0.25, "kelly_max": 0.03}
PAPER = "data/paper/bets.jsonl"
DATA = "https://data-api.polymarket.com/v2/trades"
NOW = lambda: time.time()


# ---------- statistik och modell ----------
def refresh_tml(max_age_h=3):
    """Hämtar årets TML-fil och listan över pågående turneringar (veckans resultat)."""
    y = datetime.now(timezone.utc).year
    for name, path in ((f"{y}.csv", f"data/tml/{y}.csv"), ("ongoing_tourneys.csv", "data/tml/ongoing.csv")):
        fresh = os.path.exists(path) and NOW() - os.path.getmtime(path) < max_age_h * 3600
        if fresh and not os.environ.get("TML_ALLTID_HAMTA"):   # i molnet: hämta alltid färsk data
            continue
        try:
            req = urllib.request.Request(f"https://stats.tennismylife.org/data/{name}", headers={"User-Agent": "pm-tennis"})
            d = urllib.request.urlopen(req, timeout=60).read()
            if len(d) > 500 and d[:10].startswith(b"tourney_id"):
                open(path, "wb").write(d)
        except Exception as e:
            print(f"Kunde inte uppdatera TML ({name}):", e)


def tour_check(rows, name, start, latest):
    """Avgör om Polymarkets turnering `name` som startar `start` är en ATP-tourturnering.

    Godkänns om TML har matcher från den de senaste 14 dagarna, eller om förra
    årets upplaga spelades samma tid på året OCH den inte redan borde ha synts i
    årets data (fångar flyttade turneringar, t.ex. Metz 2026 som nu är Challenger).
    Returnerar (turneringsrad eller None, förklaring)."""
    w = tml.words(name)
    if not w:
        return None, "inget turneringsnamn"
    same = [r for r in rows if tml.words(r["tourney_name"]) & w]
    recent = [r for r in same if start - 14 * 86400 <= tml.ts_of(r["tourney_date"]) <= start + 86400]
    if recent:
        return recent[-1], "spelas nu enligt TML"
    prev = [r for r in same if abs(tml.ts_of(r["tourney_date"]) + 365 * 86400 - start) <= 12 * 86400]
    if not prev:
        return None, f"{name} är inte en ATP-tourturnering enligt TML (troligen Challenger)"
    expected = min(tml.ts_of(r["tourney_date"]) for r in prev) + 364 * 86400
    if expected < tml.ts_of(latest) - 2 * 86400:
        return None, f"{name} spelades på touren förra året men syns inte i årets TML-data (troligen Challenger nu)"
    return prev[-1], "antagen ATP-tour utifrån förra årets kalender"


class Model:
    def __init__(self):
        self.rows = tml.load()
        feats = tml.features(self.rows)
        R = rows(feats, True)
        X = np.array([r[1] for r in R]); y = np.array([r[2] for r in R])
        self.lr = LogisticRegression(C=0.1, max_iter=3000).fit(np.vstack([X, -X]), np.concatenate([y, 1 - y]))
        self.last = {}
        for r in self.rows:
            for side in ("winner", "loser"):
                self.last[r[f"{side}_name"]] = (r, side)
        self.byfull, self.byshort = {}, {}
        for n in self.last:
            self.byfull.setdefault(tml.norm(n), set()).add(n)
            self.byshort.setdefault(tml.short(n), set()).add(n)
        self.last_date = max(r["tourney_date"] for r in self.rows)

    def player(self, name):
        c = self.byfull.get(tml.norm(name)) or self.byshort.get(tml.short(name)) or set()
        return next(iter(c)) if len(c) == 1 else None

    def tourney(self, name, start):
        """Underlag, nivå och bäst av för en ATP-tourturnering, eller (None, orsak)."""
        r, why = tour_check(self.rows, name, start, self.last_date)
        if r is None:
            return None, why
        return {"surface": r["surface"], "level": r["tourney_level"], "best_of": r["best_of"] or "3",
                "tml_name": r["tourney_name"], "källa": why}, why

    def predict(self, A, B, tinfo):
        """Vinstchans för A mot B just nu. Returnerar (chans, kontext) eller (None, orsak)."""
        a, b = self.player(A), self.player(B)
        if not a or not b:
            return None, f"spelare saknas i TML: {A if not a else B}"
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        def lastinfo(p):
            r, side = self.last[p]
            age = tml.fnum(r[f"{side}_age"])
            if age is not None:
                age += (tml.ts_of(today) - tml.ts_of(r["tourney_date"])) / (365.25 * 86400)
            return {"rank": r[f"{side}_rank"], "pts": r[f"{side}_rank_points"], "age": age, "ht": r[f"{side}_ht"]}
        la, lb = lastinfo(a), lastinfo(b)
        syn = {"tourney_id": "x", "tourney_name": tinfo["tml_name"], "surface": tinfo["surface"], "draw_size": "",
               "tourney_level": tinfo["level"], "tourney_date": today, "match_num": "999999", "round": "F",
               "winner_name": a, "loser_name": b, "best_of": tinfo["best_of"], "score": "W/O", "minutes": "",
               "winner_rank": la["rank"], "winner_rank_points": la["pts"], "winner_age": la["age"], "winner_ht": la["ht"],
               "loser_rank": lb["rank"], "loser_rank_points": lb["pts"], "loser_age": lb["age"], "loser_ht": lb["ht"]}
        for k in ("w_1stWon", "w_2ndWon", "w_svpt", "l_1stWon", "l_2ndWon", "l_svpt"):
            syn[k] = ""
        f = tml.features(self.rows + [syn])[-1]
        if f["w"]["n"] < 5 or f["l"]["n"] < 5:
            return None, "för få tidigare tourmatcher i TML"
        x = vec(f["w"], f["l"], {"h2h_a": f["h2h_w"], "h2h_b": f["h2h_l"], "best_of": f["best_of"]}, True)
        q = float(self.lr.predict_proba([x])[0, 1])
        ctx = {}
        for nm, inf in ((A, f["w"]), (B, f["l"])):
            ctx[nm] = {"ranking": None if inf["rank"] is None else int(inf["rank"]), "elo": round(inf["elo"]), "elo_underlag": round(inf["selo"]),
                       "form10": None if inf["form10"] is None else round(inf["form10"], 2),
                       "serve_vunna": None if inf["serve"] is None else round(inf["serve"], 3),
                       "retur_vunna": None if inf["ret"] is None else round(inf["ret"], 3),
                       "matcher_14d": inf["m14"], "vila_dagar": round(inf["rest"], 1)}
        ctx["inbördes"] = f"{A} {f['h2h_w']} - {f['h2h_l']} {B} (sedan 2018)"
        ctx["h2h"] = (f["h2h_w"], f["h2h_l"])
        ctx["underlag"] = tinfo["surface"]
        return q, ctx


# ---------- Polymarket ----------
def book(tok):
    b = h.get(f"{h.CLOB}/book?token_id={tok}")
    bids = sorted(((float(x["price"]), float(x["size"])) for x in b["bids"]), reverse=True)
    asks = sorted((float(x["price"]), float(x["size"])) for x in b["asks"])
    return bids, asks, float(b.get("tick_size") or 0.01)


def upcoming(hours=36):
    cur, now = None, NOW()
    while True:
        q = {"tag_id": 864, "closed": "false", "active": "true", "limit": 100}
        if cur:
            q["after_cursor"] = cur
        r = h.get(f"{h.GAMMA}/events/keyset?" + urllib.parse.urlencode(q))
        for e in r.get("events", []):
            if e.get("seriesSlug") != "atp":
                continue
            for m in e.get("markets", []):
                if m.get("sportsMarketType") == "moneyline" and m.get("gameStartTime") and m.get("acceptingOrders"):
                    st = h.ts(m["gameStartTime"])
                    if now < st < now + hours * 3600:
                        yield e, m, st
        cur = r.get("next_cursor")
        if not cur:
            return


def analyse(model, e, m, st):
    """Allt boten vet om en match: pris, djup, modell, edge per spelare, slutsats."""
    title = e.get("title") or m["question"]
    tour, rest = title.split(": ", 1) if ": " in title else ("", title)
    out = {"slug": e["slug"], "title": title, "start": st, "conditionId": m["conditionId"],
           "outcomes": json.loads(m["outcomes"]), "tokens": json.loads(m["clobTokenIds"]),
           "volume": m.get("volumeNum"), "fee_rate": (m.get("feeSchedule") or {}).get("rate", 0) if m.get("feesEnabled") else 0,
           "regler": m.get("description", "")}
    if "qualif" in tour.lower():
        out["skäl"] = "kvalmatch: modellen saknar data"; return out
    if " vs " not in rest:
        out["skäl"] = "kunde inte läsa spelarnamn"; return out
    A, B = [x.strip() for x in rest.split(" vs ", 1)]
    tinfo, why = model.tourney(tour, st)
    if not tinfo:
        out["skäl"] = why; return out
    q, ctx = model.predict(A, B, tinfo)
    if q is None:
        out["skäl"] = ctx; return out
    out.update({"A": A, "B": B, "q": q, "ctx": ctx, "level": tinfo["level"]})
    names = out["outcomes"]
    # Polymarkets utfall kan stå i annan ordning eller med kortare namn än titeln.
    # Kräv att exakt ett utfall är A och det andra B, annars ingen bedömning.
    idxA = outcome_index(names, A, B)
    if idxA is None:
        out["skäl"] = f"kunde inte koppla utfallen {names} till {A} / {B}"; return out
    sides = []
    for i, tok in enumerate(out["tokens"]):
        bids, asks, tick = book(tok)
        qi = q if i == idxA else 1 - q
        s = {"spelare": names[i], "chans": qi, "bästa_bud": bids[0][0] if bids else None,
             "bästa_sälj": asks[0][0] if asks else None, "djup_sälj": asks[:3], "djup_köp": bids[:3]}
        s["är_A"] = i == idxA
        if bids and asks:
            mid = (bids[0][0] + asks[0][0]) / 2
            bid = math.floor((mid - STRAT["bud_under"]) / tick + 1e-9) * tick
            bid = round(min(bid, asks[0][0] - tick), 4)
            s.update({"mitt": mid, "spread": round(asks[0][0] - bids[0][0], 4), "budpris": bid, "edge": qi - bid,
                      "maxpris": round(qi - STRAT["edge"], 3),
                      "edge_om_köp": qi - (asks[0][0] + out["fee_rate"] * asks[0][0] * (1 - asks[0][0]))})
        sides.append(s)
    out["sides"] = sides
    if "50-50" in out["regler"] and "walkover" in out["regler"].lower():
        out["flagga"] = "Walkover ger 50-50 på Polymarket (många bookmakers makulerar i stället)."
    decide(out)
    return out


def outcome_index(names, A, B):
    """Vilket av Polymarkets två utfall är spelare A? None om det inte är entydigt."""
    if len(names) != 2:
        return None
    for i in (0, 1):
        if odds.same_player(names[i], A) and odds.same_player(names[1 - i], B) \
                and not (odds.same_player(names[i], B) and odds.same_player(names[1 - i], A)):
            return i
    return None


def add_pin(a, pin):
    """Hämtar Pinnacles rättvisa chans och lägger den på varje sida. Kostar ett anrop."""
    if "sides" not in a:
        return
    p, why = pin.fair(a["A"], a["B"], a["start"])
    if not p:
        a["pin_skäl"] = why; return
    a["pin"] = p
    for s in a["sides"]:
        s["pin"] = p["pA"] if s["är_A"] else p["pB"]
        if s.get("budpris") is not None:
            s["edge_pin"] = s["pin"] - s["budpris"]
            s["maxpris_pin"] = round(s["pin"] - STRAT["edge_pin"], 3)


def decide(a):
    """Sätter signal (Pinnacle-strategin) och signal_modell (gamla strategin)."""
    a.pop("signal", None); a.pop("signal_modell", None)
    ok = [s for s in a.get("sides", []) if s.get("budpris") is not None and s["budpris"] >= 0.02]
    pin = [s for s in ok if s.get("edge_pin") is not None and s["edge_pin"] >= STRAT["edge_pin"]
           and s["chans"] - s["budpris"] >= STRAT["modell_filter"]]
    mod = [s for s in ok if s["edge"] > STRAT["edge"]]
    if pin:
        s = max(pin, key=lambda s: s["edge_pin"])
        a["signal"] = s["spelare"]
        a["slutsats"] = (f"Lägg köpbud på {s['spelare']} på {s['budpris']:.2f} (högst {s['maxpris_pin']:.2f}). "
                         f"Pinnacle: {100 * s['pin']:.0f} % rättvis chans, edge {100 * s['edge_pin']:.1f} procentenheter; "
                         f"modellen {100 * s['chans']:.0f} %.")
    elif a.get("pin"):
        a["slutsats"] = (f"Inget spelvärde: Polymarket ligger inom {100 * STRAT['edge_pin']:.0f} procentenheter från Pinnacle"
                         " (eller så säger modellen emot).")
    else:
        a["slutsats"] = "Ingen Pinnacle-jämförelse " + (f"({a['pin_skäl']})" if a.get("pin_skäl") else
                                                           "(hämtas bara ca 3 timmar före start)") + "."
    if mod:
        s = max(mod, key=lambda s: s["edge"])
        a["signal_modell"] = s["spelare"]
        a["slutsats"] += f" Gamla modellstrategin: {s['spelare']} (edge {100 * s['edge']:.1f}), bara låtsas."


# ---------- paper trading ----------
def load_bets():
    if not os.path.exists(PAPER):
        return []
    return [json.loads(l) for l in open(PAPER)]


def save_bets(bs):
    os.makedirs(os.path.dirname(PAPER), exist_ok=True)
    tmp = PAPER + ".tmp"
    with open(tmp, "w") as f:
        for b in bs:
            f.write(json.dumps(b, ensure_ascii=False) + "\n")
    os.replace(tmp, PAPER)


def strat_of(b):
    return b.get("strategi", "modell")   # bet från före Pinnacle tillhör den gamla strategin


def kassa_nu(bs, key, strategi="pinnacle"):
    k = STRAT["kassa"]
    for b in bs:
        if b.get("status") == "avgjord" and strat_of(b) == strategi:
            k += b[f"resultat_{key}"]
    return k


def place(a, bs, strategi="pinnacle"):
    who = a["signal"] if strategi == "pinnacle" else a["signal_modell"]
    s = next(x for x in a["sides"] if x["spelare"] == who)
    p = s["pin"] if strategi == "pinnacle" else s["chans"]
    kelly = max(0.0, min(STRAT["kelly"] * (p - s["budpris"]) / (1 - s["budpris"]), STRAT["kelly_max"]))
    b = {"lagd": int(NOW()), "strategi": strategi, "slug": a["slug"], "title": a["title"], "start": a["start"], "conditionId": a["conditionId"],
         "spelare": s["spelare"], "token": a["tokens"][a["outcomes"].index(s["spelare"])],
         "utfall_index": a["outcomes"].index(s["spelare"]), "budpris": s["budpris"], "chans": round(s["chans"], 4),
         "edge": round(s["edge"], 4), "pin": None if s.get("pin") is None else round(s["pin"], 4),
         "edge_pin": None if s.get("edge_pin") is None else round(s["edge_pin"], 4),
         "pin_odds": a.get("pin") and [a["pin"]["oddsA"], a["pin"]["oddsB"]], "mitt": s["mitt"], "spread": s["spread"], "djup_sälj": s["djup_sälj"],
         "volym": a["volume"], "nivå": a["level"], "kontext": a["ctx"], "insats_fast": STRAT["fast"],
         "insats_kelly": round(kelly * kassa_nu(bs, "kelly", strategi), 2), "status": "väntar på start"}
    bs.append(b)
    return b


def settle(bs):
    changed = 0
    for b in bs:
        if b["status"] == "väntar på start" and NOW() > b["start"] + 300:
            sold, cur = 0.0, None
            for _ in range(200):
                q = {"condition": b["conditionId"], "limit": 1000, "taker_only": "false"}
                if cur:
                    q["cursor"] = cur
                r = h.get(DATA + "?" + urllib.parse.urlencode(q))
                d = r["data"] or []
                for x in d:
                    if b["lagd"] <= x["timestamp"] < b["start"]:
                        p = x["price"] if x["outcome_index"] == b["utfall_index"] else 1 - x["price"]
                        if p < b["budpris"] - 1e-9:
                            sold += x["size"]
                cur = r["pagination"].get("next_cursor")
                if not cur or not d or d[-1]["timestamp"] < b["lagd"]:
                    break
            b["sålt_under_bud"] = round(sold / 2, 1)   # varje avslut syns två gånger i flödet
            b["fylld"] = sold / 2 >= STRAT["min_salt"]
            try:
                hist = h.get(f"{h.CLOB}/prices-history?market={b['token']}&startTs={int(b['start']) - 1800}&endTs={int(b['start'])}&fidelity=1")
                pts = hist.get("history", [])
                b["pris_vid_start"] = pts[-1]["p"] if pts else None
            except Exception:
                b["pris_vid_start"] = None
            b["status"] = "väntar på resultat" if b["fylld"] else "ej fylld"
            changed += 1
        # Rätta både fyllda och ofyllda bud. Ofyllda får "resultat_om_fylld" så att
        # rapporten kan visa om de bud som fylls är sämre än de som inte fylls.
        unfilled_open = b["status"] == "ej fylld" and "utfall" not in b and NOW() < b["start"] + 14 * 86400
        if b["status"] == "väntar på resultat" or unfilled_open:
            try:
                e = h.get(f"{h.GAMMA}/events/slug/{b['slug']}")
            except Exception as err:
                print("Kunde inte rätta", b["slug"], err); continue
            m = next((x for x in e.get("markets", []) if x["conditionId"] == b["conditionId"]), None)
            if m and m.get("closed"):
                r = float(json.loads(m["outcomePrices"])[b["utfall_index"]])
                b["utfall"] = r
                for key in ("fast", "kelly"):
                    st = b[f"insats_{key}"]
                    res = round(st / b["budpris"] * r - st, 2)
                    b[f"resultat_{key}" if b["status"] != "ej fylld" else f"resultat_om_fylld_{key}"] = res
                if b["status"] != "ej fylld":
                    b["status"] = "avgjord"
                changed += 1
    return changed


# ---------- utskrift ----------
def show(a):
    print(f"\n=== {a['title']}   start {datetime.fromtimestamp(a['start'], timezone.utc):%Y-%m-%d %H:%M} UTC")
    if "skäl" in a:
        print("  Ingen bedömning:", a["skäl"]); return
    for s in a["sides"]:
        if s.get("budpris") is None:
            print(f"  {s['spelare']}: ingen fullständig orderbok"); continue
        djup = ", ".join(f"{z:.0f} st @ {p:.2f}" for p, z in s["djup_sälj"])
        print(f"  {s['spelare']:<28} modell {100 * s['chans']:5.1f} %  bud/sälj {s['bästa_bud']:.2f}/{s['bästa_sälj']:.2f}  "
              f"vårt bud {s['budpris']:.2f}  edge {100 * s['edge']:+5.1f}  (om du klickar köp: {100 * s['edge_om_köp']:+5.1f})")
        print(f"  {'':<28} säljdjup: {djup}")
    for nm in (a["A"], a["B"]):
        c = a["ctx"][nm]
        print(f"  {nm:<28} rank {c['ranking']}, Elo {c['elo']} ({a['ctx']['underlag']}: {c['elo_underlag']}), form10 {c['form10']}, "
              f"serve {c['serve_vunna']}, retur {c['retur_vunna']}, matcher 14d {c['matcher_14d']}, vila {c['vila_dagar']} d")
    if a.get("pin"):
        p = a["pin"]
        print(f"  PINNACLE: {a['A']} {p['oddsA']:.2f} ({100 * p['pA']:.1f} %), {a['B']} {p['oddsB']:.2f} ({100 * p['pB']:.1f} %), "
              f"marginal {100 * p['marginal']:.1f} %, {p['ålder_min']} min gammalt")
        for s in a["sides"]:
            if s.get("edge_pin") is not None:
                print(f"  {s['spelare']:<28} edge mot Pinnacle med vårt bud: {100 * s['edge_pin']:+5.1f}")
    elif a.get("pin_skäl"):
        print("  Pinnacle:", a["pin_skäl"])
    print(f"  inbördes: {a['ctx']['inbördes']} | volym {a['volume']:,.0f} USD")
    if a.get("flagga"):
        print("  OBS:", a["flagga"])
    print("  SLUTSATS:", a["slutsats"])


def html(analyses, bs):
    import sida
    open("signaler.html", "w", encoding="utf-8").write(sida.build(analyses, bs, STRAT, kassa_nu))


def report(bs):
    for strategi in ("pinnacle", "modell"):
        g = [b for b in bs if strat_of(b) == strategi]
        print(f"\n===== Strategi: {strategi} =====")
        report_one(g, strategi)
        selection(g)


def selection(bs):
    """Snedvridning: är budet som fylls sämre än budet som inte fylls?

    Ett köpbud under mittpriset fylls oftast när någon säljer till oss, alltså när
    priset rör sig mot oss. Jämför faktiska vinster med väntade i båda grupperna."""
    f = [b for b in bs if b["status"] == "avgjord" and b.get("utfall") in (0, 1)]
    u = [b for b in bs if b["status"] == "ej fylld" and b.get("utfall") in (0, 1)]
    if not f and not u:
        return
    print("  Fyllda mot ofyllda bud (väntat = budets chans enligt strategins sannolikhet):")
    for label, g in (("fyllda", f), ("ofyllda", u)):
        if not g:
            print(f"    {label:<8} inga rättade än"); continue
        p = lambda b: b["pin"] if strat_of(b) == "pinnacle" and b.get("pin") is not None else b["chans"]
        won, exp = sum(b["utfall"] for b in g), sum(p(b) for b in g)
        key = "resultat_fast" if label == "fyllda" else "resultat_om_fylld_fast"
        roi = sum(b.get(key, 0) for b in g) / sum(b["insats_fast"] for b in g)
        clv = [b["pris_vid_start"] - b["budpris"] for b in g if b.get("pris_vid_start") is not None]
        clvt = f", pris vid start {100 * sum(clv) / len(clv):+.1f} öre mot budet" if clv else ""
        print(f"    {label:<8} {len(g):>3} st: vann {won:.0f}, väntat {exp:.1f}, ROI {100 * roi:+.1f} %{clvt}")
    if f and u:
        print("    Är ofyllda klart bättre än fyllda gör budstrategin att du systematiskt får de sämre betten.")


def report_one(bs, strategi):
    done = [b for b in bs if b["status"] == "avgjord"]
    print(f"Låtsasbet: {len(bs)} lagda, {sum(b['status'] == 'ej fylld' for b in bs)} ej fyllda, "
          f"{sum(b['status'].startswith('väntar') for b in bs)} väntar, {len(done)} avgjorda")
    filled = [b for b in bs if b.get("fylld") is not None]
    if filled:
        print(f"Andel bud som fylldes: {100 * sum(b['fylld'] for b in filled) / len(filled):.0f} %")
    if not done:
        print("Inga avgjorda bet än."); return
    for key in ("fast", "kelly"):
        st = sum(b[f"insats_{key}"] for b in done); pnl = sum(b[f"resultat_{key}"] for b in done)
        print(f"  {key:<5}: insats {st:,.0f} kr, resultat {pnl:+,.0f} kr, ROI {100 * pnl / st if st else 0:+.1f} %, kassa {kassa_nu(bs, key, strategi):,.0f} kr")
    pv = lambda b: b["pin"] if strategi == "pinnacle" and b.get("pin") is not None else b["chans"]
    print(f"  vann {sum(b['utfall'] == 1 for b in done)} av {len(done)}, strategins sannolikhet väntade sig "
          f"{sum(pv(b) for b in done):.1f} vinster, snittbud {sum(b['budpris'] for b in done) / len(done):.2f}")
    clv = [b["pris_vid_start"] - b["mitt"] for b in done if b.get("pris_vid_start") is not None]
    if clv:
        print(f"  priset rörde sig i snitt {100 * sum(clv) / len(clv):+.1f} öre mot oss fram till start (plus = marknaden höll med modellen)")
    ek = "edge_pin" if strategi == "pinnacle" else "edge"
    steps = ((0.03, 0.05), (0.05, 0.08), (0.08, 1)) if strategi == "pinnacle" else ((0.10, 0.15), (0.15, 0.25), (0.25, 1))
    for lo, hi in steps:
        g = [b for b in done if b.get(ek) is not None and lo <= b[ek] < hi]
        if g:
            pnl = sum(b["resultat_fast"] for b in g); st = sum(b["insats_fast"] for b in g)
            print(f"  edge {int(lo * 100)}-{int(hi * 100)}: {len(g)} bet, ROI {100 * pnl / st:+.1f} %")
    print("Kom ihåg: före ca 150 avgjorda bet säger siffrorna mycket lite.")


def run_once():
    refresh_tml()
    model = Model()
    bs = load_bets()
    n_settled = settle(bs)
    done = {(b["slug"], strat_of(b)) for b in bs}
    pin = odds.Pinnacle()
    analyses, new = [], 0
    for e, m, st in upcoming():
        try:
            analyses.append(analyse(model, e, m, st))
        except Exception as err:
            print("FEL", e.get("slug"), err)
    in_window = lambda a: STRAT["fore_h"] - STRAT["fonster_h"] <= (a["start"] - NOW()) / 3600 <= STRAT["fore_h"] + STRAT["fonster_h"]
    # Pinnacle-anropen är få (gratisnivån): bara matcher i spelfönstret som inte redan
    # har ett Pinnacle-bet, lägst Polymarket-volym först (där priserna oftast är skeva).
    todo = sorted((a for a in analyses if "sides" in a and in_window(a) and (a["slug"], "pinnacle") not in done),
                  key=lambda a: a.get("volume") or 0)
    for a in todo:
        add_pin(a, pin); decide(a)
    for a in analyses:
        if not in_window(a):
            continue
        for strategi, key in (("pinnacle", "signal"), ("modell", "signal_modell")):
            if a.get(key) and (a["slug"], strategi) not in done:
                b = place(a, bs, strategi); new += 1; done.add((a["slug"], strategi))
                e_ = b["edge_pin"] if strategi == "pinnacle" else b["edge"]
                print(f"NYTT LÅTSASBET ({strategi}): {b['title']} -> {b['spelare']} bud {b['budpris']:.2f}, edge {100 * e_:.1f}")
    if pin.active():
        print(f"Pinnacle-anrop kvar idag/månad: {pin.left()}")
    else:
        print("Pinnacle av: sätt ODDSPAPI_KEY för huvudstrategin (se odds.py).")
    save_bets(bs)
    html(analyses, bs)
    sig = [a for a in analyses if a.get("signal")]
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC: {len(analyses)} kommande ATP-matcher, {len(sig)} med signal, "
          f"{new} nya låtsasbet, {n_settled} rättade. Öppna signaler.html för översikten.")
    for a in sig:
        print(f"  SIGNAL {datetime.fromtimestamp(a['start'], timezone.utc):%d/%m %H:%M}: {a['slutsats']}  ({a['title']})")


def lookup(args):
    refresh_tml(); model = Model()
    if len(args) == 1 and "polymarket.com" in args[0]:
        slug = args[0].rstrip("/").split("/")[-1].split("?")[0]
        e = h.get(f"{h.GAMMA}/events/slug/{slug}")
        m = next((x for x in e.get("markets", []) if x.get("sportsMarketType") == "moneyline"), None)
        if not m:
            print("Ingen matchvinnarmarknad i den länken."); return
        a = analyse(model, e, m, h.ts(m["gameStartTime"])); add_pin(a, odds.Pinnacle()); decide(a); show(a); return
    if len(args) != 2:
        print('Ange två spelare: python3 bot.py uppslag "Spelare A" "Spelare B"'); return
    want = {tml.short(args[0]), tml.short(args[1])}
    for e, m, st in upcoming(hours=24 * 14):
        names = (e.get("title") or "").split(": ", 1)[-1].split(" vs ")
        if len(names) == 2 and {tml.short(n) for n in names} == want:
            a = analyse(model, e, m, st); add_pin(a, odds.Pinnacle()); decide(a); show(a); return
    print("Matchen finns inte bland Polymarkets kommande ATP-matcher (två veckor framåt). Ingen bedömning görs.")


def main():
    a = sys.argv[1:]
    if not a or a[0] == "kör":
        if len(a) >= 3 and a[1] == "--loop":
            while True:
                try:
                    run_once()
                except Exception as err:
                    print("FEL i varvet (försöker igen nästa gång):", err)
                time.sleep(float(a[2]) * 60)
        else:
            run_once()
    elif a[0] == "uppslag":
        lookup(a[1:])
    elif a[0] == "rapport":
        report(load_bets())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
