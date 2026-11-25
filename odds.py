"""Pinnacles odds via OddsPapi: marknadens bästa uppskattning av vinstchansen.

Pinnacle är den skarpaste bookmakern. Tar man bort deras marginal (de-vig) får man
en "rättvis" sannolikhet som är svår att slå. Boten letar efter matcher där
Polymarket-priset avviker från den, i stället för att lita på sin egen modell.

Nyckel: sätt miljövariabeln ODDSPAPI_KEY (gratis på oddspapi.io). I GitHub:
Settings -> Secrets and variables -> Actions -> New repository secret.
Utan nyckel körs boten som förut, bara utan Pinnacle.

Gratisnivån är 250 anrop i månaden, så varje anrop räknas och sparas i
data/odds/cache.json (som checkas in, annars nollställs räknaren varje körning).
  * Matchlistan hämtas högst en gång per dygn.
  * Odds hämtas bara för matcher i spelfönstret, högst en gång per match och 2 timmar.
  * Tak: ODDS_MAX_PER_MONTH (230) och ODDS_MAX_PER_DAY (8).

API (docs: oddspapi.io): GET /v4/fixtures?sportId=12&from&to,
GET /v4/odds?fixtureId&bookmakers=pinnacle. Tennis matchvinnare = marknad 121,
utfall 121 = spelare 1, 122 = spelare 2, pris i players["0"]["price"].
"""
import json, os, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
import karna
import tml

BASE = "https://api.oddspapi.io/v4"
CACHE = "data/odds/cache.json"
TENNIS, MARKET, OUT1, OUT2 = 12, "121", "121", "122"


def parse_time(x):
    """startTime kan komma som sekunder, millisekunder eller ISO-text."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return x / 1000 if x > 1e11 else float(x)
    s = str(x).strip().replace(" ", "T").replace("Z", "+00:00")
    if s.isdigit():
        return parse_time(int(s))
    d = datetime.fromisoformat(s)
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()


def fix_name(name):
    """'Zverev, Alexander' -> 'Alexander Zverev'."""
    if name and "," in name:
        last, first = [p.strip() for p in name.split(",", 1)]
        return f"{first} {last}"
    return name or ""


def same_player(a, b):
    """Samma spelare? Fullt namn, efternamn+initial, eller efternamn + initial var som helst."""
    a, b = fix_name(a), fix_name(b)
    if tml.norm(a) == tml.norm(b) or tml.short(a) == tml.short(b):
        return True
    ta, tb = tml.norm(a).split(), tml.norm(b).split()
    if not ta or not tb:
        return False
    # efternamnet (sista ordet) finns hos den andra, och förnamnets initial stämmer
    for x, y in ((ta, tb), (tb, ta)):
        if x[-1] in y and len(x[-1]) > 2:
            rest = [w for w in y if w != x[-1]]
            if not rest or not x[:-1] or any(w[0] == x[0][0] for w in rest):
                return True
    return False


class Pinnacle:
    def __init__(self, key=None, path=CACHE, now=time.time, fetch=None,
                 per_month=None, per_day=None):
        self.key = os.environ.get("ODDSPAPI_KEY", "") if key is None else key
        self.path, self.now = path, now
        self.fetch = fetch or self._http
        self.per_month = per_month or int(os.environ.get("ODDS_MAX_PER_MONTH", "230"))
        self.per_day = per_day or int(os.environ.get("ODDS_MAX_PER_DAY", "8"))
        self.c = {"anrop": {}, "fixtures": {"hämtad": 0, "lista": []}, "odds": {}}
        if os.path.exists(path):
            try:
                self.c.update(json.load(open(path)))
            except Exception:
                pass

    # ---------- budget ----------
    def _keys(self):
        d = datetime.fromtimestamp(self.now(), timezone.utc)
        return d.strftime("%Y-%m"), d.strftime("%Y-%m-%d")

    def left(self):
        m, d = self._keys()
        return min(self.per_month - self.c["anrop"].get(m, 0), self.per_day - self.c["anrop"].get(d, 0))

    def active(self):
        return bool(self.key)

    def save(self):
        m, d = self._keys()
        # behåll bara räknare för denna och förra månaden, och odds yngre än 3 dygn
        keep = {k: v for k, v in self.c["anrop"].items() if k[:7] >= (datetime.fromtimestamp(self.now() - 40 * 86400, timezone.utc).strftime("%Y-%m"))}
        self.c["anrop"] = keep
        self.c["odds"] = {k: v for k, v in self.c["odds"].items() if self.now() - v.get("t", 0) < 3 * 86400}
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        json.dump(self.c, open(tmp, "w"), ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def _http(self, path, params):
        q = urllib.parse.urlencode(dict(params, apiKey=self.key))
        req = urllib.request.Request(f"{BASE}/{path}?{q}", headers={"User-Agent": "tennisboten"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:          # OddsPapi svarar 404 när listan är tom
                return []
            raise

    def _call(self, path, params):
        if not self.active():
            raise RuntimeError("ingen ODDSPAPI_KEY")
        if self.left() <= 0:
            raise RuntimeError("anropsbudgeten för dagen/månaden är slut")
        m, d = self._keys()
        for k in (m, d):
            self.c["anrop"][k] = self.c["anrop"].get(k, 0) + 1
        self.save()    # räkna anropet även om det sedan misslyckas
        return self.fetch(path, params)

    # ---------- data ----------
    def fixtures(self):
        f = self.c["fixtures"]
        if self.now() - f.get("hämtad", 0) < 20 * 3600 and f.get("lista"):
            return f["lista"]
        d0 = datetime.fromtimestamp(self.now(), timezone.utc)
        raw = self._call("fixtures", {"sportId": TENNIS, "from": d0.strftime("%Y-%m-%d"),
                                      "to": (d0 + timedelta(days=2)).strftime("%Y-%m-%d")}) or []
        lista = []
        for x in raw:
            st = parse_time(x.get("startTime"))
            if st and x.get("fixtureId"):
                lista.append({"id": x["fixtureId"], "p1": fix_name(x.get("participant1Name")),
                              "p2": fix_name(x.get("participant2Name")), "start": st,
                              "turnering": x.get("tournamentName") or ""})
        self.c["fixtures"] = {"hämtad": self.now(), "lista": lista}
        self.save()
        return lista

    def find(self, A, B, start, lista):
        """Hittar OddsPapi-matchen för A mot B som startar inom 12 timmar från `start`."""
        hits = []
        for f in lista:
            if abs(f["start"] - start) > 12 * 3600:
                continue
            if same_player(A, f["p1"]) and same_player(B, f["p2"]):
                hits.append((f, False))
            elif same_player(A, f["p2"]) and same_player(B, f["p1"]):
                hits.append((f, True))
        return hits[0] if len(hits) == 1 else (None, None)

    def fair(self, A, B, start, max_age=2 * 3600):
        """Pinnacles rättvisa chans för A och B. Returnerar (dict, None) eller (None, orsak)."""
        if not self.active():
            return None, "ingen ODDSPAPI_KEY (Pinnacle av)"
        try:
            f, swapped = self.find(A, B, start, self.fixtures())
            if not f:
                return None, "matchen hittades inte hos OddsPapi"
            hit = self.c["odds"].get(f["id"])
            if not hit or self.now() - hit["t"] > max_age:
                o = self._call("odds", {"fixtureId": f["id"], "bookmakers": "pinnacle"}) or {}
                m = ((o.get("bookmakerOdds") or {}).get("pinnacle") or {}).get("markets", {}).get(MARKET)
                if not m:
                    return None, "Pinnacle har inget matchvinnarpris"
                pr = lambda oid: float(((m["outcomes"].get(oid) or {}).get("players", {}).get("0") or {}).get("price") or 0)
                hit = {"t": self.now(), "o1": pr(OUT1), "o2": pr(OUT2)}
                self.c["odds"][f["id"]] = hit
                self.save()
            if hit["o1"] <= 1 or hit["o2"] <= 1:
                return None, "Pinnacle har inget giltigt pris"
            p1, p2 = karna.devig(hit["o1"], hit["o2"])
            oa, ob, pa, pb = (hit["o2"], hit["o1"], p2, p1) if swapped else (hit["o1"], hit["o2"], p1, p2)
            return {"pA": pa, "pB": pb, "oddsA": oa, "oddsB": ob, "marginal": 1 / oa + 1 / ob - 1,
                    "ålder_min": round((self.now() - hit["t"]) / 60), "fixture": f["id"]}, None
        except Exception as e:
            return None, f"Pinnacle: {e}"
