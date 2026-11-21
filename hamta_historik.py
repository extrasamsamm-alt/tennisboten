"""Laddar ner avslutade tennismatcher från Polymarket + priset före matchstart.

Kör:  python3 hamta_historik.py atp          (serier: atp, wta, itf)
Sparar till data/historik_<serie>.jsonl, en rad per match. Kan köras om; redan
hämtade matcher hoppas över. Bara publik data, ingen nyckel, inga order.
"""
import gzip, json, os, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
SERIES = {"atp": 10365, "wta": 10366, "itf": 11634}  # från GET /sports


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "pm-tennis"})
            with urllib.request.urlopen(req, timeout=40) as r:
                d = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    d = gzip.decompress(d)
            return json.loads(d)
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def ts(s):
    s = s.replace(" ", "T").replace("Z", "+00:00")
    if s.endswith("+00"):
        s += ":00"
    return datetime.fromisoformat(s).timestamp()


def closed_events(series_id):
    cur = None
    while True:
        q = {"series_id": series_id, "closed": "true", "limit": 100}
        if cur:
            q["after_cursor"] = cur
        r = get(f"{GAMMA}/events/keyset?" + urllib.parse.urlencode(q))
        ev = r.get("events") or r.get("data") or []
        yield from ev
        cur = r.get("next_cursor")
        if not cur or not ev:
            return


def build(e):
    ml = [m for m in e.get("markets", []) if m.get("sportsMarketType") == "moneyline"]
    if not ml or not ml[0].get("gameStartTime") or not ml[0].get("clobTokenIds"):
        return None
    m = ml[0]
    start = int(ts(m["gameStartTime"]))
    tok = json.loads(m["clobTokenIds"])
    # Prishistorik för spelare 1 (spelare 2 = 1 - pris), upp till 48 h före start.
    h = get(f"{CLOB}/prices-history?market={tok[0]}&startTs={start - 172800}&endTs={start}&fidelity=5")
    return {
        "slug": e["slug"], "title": e.get("title"), "start": start,
        "created": m.get("createdAt"), "closedTime": m.get("closedTime"),
        "outcomes": json.loads(m["outcomes"]), "result": json.loads(m["outcomePrices"]),
        "volume": m.get("volumeNum"), "feeSchedule": m.get("feeSchedule"),
        "feesEnabled": m.get("feesEnabled"), "description": m.get("description"),
        "pre": [[x["t"], x["p"]] for x in h.get("history", [])],
    }


def main(name):
    path = f"data/historik_{name}.jsonl"
    done = set()
    if os.path.exists(path):
        done = {json.loads(l)["slug"] for l in open(path)}
    todo = [e for e in closed_events(SERIES[name]) if e["slug"] not in done]
    print(f"{name}: {len(done)} redan sparade, {len(todo)} att hämta", flush=True)
    n = fel = 0
    with open(path, "a") as f, ThreadPoolExecutor(8) as ex:
        def safe(e):
            try:
                return build(e)
            except Exception as err:
                return {"_fel": f"{e['slug']}: {err}"}
        for row in ex.map(safe, todo):
            if row and "_fel" in row:
                fel += 1; print("FEL", row["_fel"], flush=True); continue
            if row:
                f.write(json.dumps(row) + "\n"); n += 1
                if n % 500 == 0:
                    f.flush(); print(f"  {n} sparade", flush=True)
    print(f"Klart: {n} nya matcher, {fel} fel.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "atp")
