"""Bygger signaler.html: botens översikt i webbläsaren (uppdateras själv var 5:e minut)."""
import html as H
from datetime import datetime

RIKTIG_INSATS_USD = 10   # förslag på riktig insats per bet medan strategin testas (1 % av 1 000 $)


def tid(ts):
    return datetime.fromtimestamp(ts).strftime("%a %d/%m %H:%M").replace("Mon", "mån").replace("Tue", "tis") \
        .replace("Wed", "ons").replace("Thu", "tor").replace("Fri", "fre").replace("Sat", "lör").replace("Sun", "sön")


def pct(x, d=0):
    return f"{100 * x:.{d}f} %".replace(".", ",")


def varfor(a, spelare):
    """Plockar ut de statistikskillnader som talar för spelaren, på vanlig svenska."""
    other = a["B"] if spelare == a["A"] else a["A"]
    x, y = a["ctx"].get(spelare), a["ctx"].get(other)
    if not x or not y:
        return []
    out = []
    hw, hl = a["ctx"].get("h2h", (0, 0))
    lead, lag = (hw, hl) if spelare == a["A"] else (hl, hw)
    if lead - lag >= 2:
        out.append(f"Leder inbördes mötena {lead}–{lag} sedan 2018")
    if x["retur_vunna"] and y["retur_vunna"] and x["retur_vunna"] - y["retur_vunna"] >= 0.015:
        out.append(f"Vinner fler returpoäng ({pct(x['retur_vunna'], 1)} mot {pct(y['retur_vunna'], 1)})")
    if x["serve_vunna"] and y["serve_vunna"] and x["serve_vunna"] - y["serve_vunna"] >= 0.015:
        out.append(f"Vinner fler servepoäng ({pct(x['serve_vunna'], 1)} mot {pct(y['serve_vunna'], 1)})")
    if x["elo_underlag"] - y["elo_underlag"] >= 30:
        out.append(f"Starkare på {a['ctx']['underlag'].lower()} enligt styrkebetyget ({x['elo_underlag']} mot {y['elo_underlag']})")
    if x["form10"] is not None and y["form10"] is not None and x["form10"] - y["form10"] >= 0.2:
        out.append(f"Bättre form: vann {round(10 * x['form10'])} av senaste 10 mot {round(10 * y['form10'])}")
    if y["matcher_14d"] - x["matcher_14d"] >= 2:
        out.append(f"Mindre matchtrött: {x['matcher_14d']} matcher senaste två veckorna mot {y['matcher_14d']}")
    if x["vila_dagar"] - y["vila_dagar"] >= 2 and y["vila_dagar"] < 3:
        out.append(f"Mer vilad: {x['vila_dagar']:.0f} dagar sedan senaste match mot {y['vila_dagar']:.0f}")
    if not out:
        out.append("Ingen enskild siffra sticker ut; sammantaget ser statistiken matchen som jämnare än priset gör")
    return out[:4]


CSS = """
:root{--bg:#f6f5f1;--card:#fff;--fg:#1d1d1b;--mut:#6b6b66;--line:#e4e2db;--acc:#1f6f4a;--accbg:#e3f1e9;
--warn:#8a5a00;--warnbg:#fbf0d9;--bad:#a23b2c;--badbg:#f7e3df;--bar:#d9d6cc;--pm:#7c7a73}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--fg:#ecebe6;--mut:#9b9a94;--line:#2f2e2b;
--acc:#5cc58f;--accbg:#173326;--warn:#e0b45a;--warnbg:#3a2e14;--bad:#e8806f;--badbg:#3b1f1a;--bar:#3a3935;--pm:#8d8b84}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:24px 16px 64px}
header{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:20px}
h1{font-size:28px;margin:0;letter-spacing:-.01em}h2{font-size:18px;margin:32px 0 12px}
.mut{color:var(--mut)}.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:13px;font-weight:600}
.pill.paper{background:var(--warnbg);color:var(--warn)}.pill.win{background:var(--accbg);color:var(--acc)}
.pill.loss{background:var(--badbg);color:var(--bad)}.pill.wait{background:var(--line);color:var(--mut)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.tile .v{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums}.tile .l{font-size:13px;color:var(--mut)}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:16px}
.card .top{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;font-size:14px;color:var(--mut)}
.pick{font-size:24px;font-weight:700;margin:6px 0 2px}.edge{background:var(--accbg);color:var(--acc);font-weight:700;padding:4px 10px;border-radius:8px;font-size:14px}
.bars{margin:14px 0}.bar{display:grid;grid-template-columns:120px 1fr 56px;align-items:center;gap:10px;margin:6px 0;font-size:14px}
.track{height:10px;background:var(--bar);border-radius:99px;overflow:hidden}.fill{height:100%;border-radius:99px}
.fill.bot{background:var(--acc)}.fill.pm{background:var(--pm)}.num{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:20px}@media (max-width:640px){.cols{grid-template-columns:1fr}.bar{grid-template-columns:96px 1fr 48px}}
ul{margin:6px 0 0;padding-left:20px}li{margin:3px 0}
.how{background:var(--bg);border-radius:12px;padding:12px 14px;font-size:14px}.how b{font-variant-numeric:tabular-nums}
.flag{margin-top:12px;font-size:13px;color:var(--warn)}
.empty{text-align:center;padding:36px 20px}.empty .big{font-size:20px;font-weight:700;margin-bottom:4px}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:9px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:13px}td.r,th.r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.scroll{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:4px 8px}
details{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:12px 16px}summary{cursor:pointer;font-weight:600}
svg.chart{display:block;width:100%;height:200px}.hide-sm{}
.sub{display:block;font-size:12px;color:var(--mut)}
@media (max-width:640px){.hide-sm{display:none}svg.chart{height:150px}td,th{padding:8px 5px}}footer{margin-top:40px;font-size:13px;color:var(--mut)}
"""


def bar(label, val, cls):
    return (f'<div class="bar"><span>{label}</span><div class="track"><div class="fill {cls}" '
            f'style="width:{max(2, min(100, 100 * val)):.0f}%"></div></div><span class="num">{pct(val)}</span></div>')


def signal_card(a):
    s = next(x for x in a["sides"] if x["spelare"] == a["signal"])
    other = next(x for x in a["sides"] if x["spelare"] != a["signal"])
    bud = s["budpris"]
    andelar = max(5, round(RIKTIG_INSATS_USD / bud))
    from tml import short
    vem = a["A"] if short(s["spelare"]) == short(a["A"]) or s["spelare"] == a["A"] else a["B"]
    reasons = "".join(f"<li>{H.escape(r)}</li>" for r in varfor(a, vem))
    flag = f'<div class="flag">⚠ {H.escape(a["flagga"])}</div>' if a.get("flagga") else ""
    return f"""<div class="card">
<div class="top"><span>{H.escape(a['title'])}</span><span>Start {tid(a['start'])}</span></div>
<div class="pick">Köp {H.escape(s['spelare'])}</div>
<span class="edge">Edge {100 * s['edge']:.0f} procentenheter</span>
<div class="bars">{bar('Botens chans', s['chans'], 'bot')}{bar('Polymarket', s['mitt'], 'pm')}</div>
<div class="cols"><div><b>Varför boten tror det</b><ul>{reasons}</ul></div>
<div class="how"><b>Så lägger du budet</b><br>Polymarket → {H.escape(s['spelare'])} → <b>Buy</b> → <b>Limit</b><br>
Limit price: <b>{100 * bud:.0f}¢</b> &nbsp;(högst {100 * s['maxpris']:.0f}¢, klicka aldrig vanligt köp)<br>
Shares: <b>{andelar}</b> → kostar ca <b>{andelar * bud:.2f} $</b>, ger <b>{andelar} $</b> tillbaka om {H.escape(s['spelare'].split()[-1])} vinner<br>
<span class="mut">Fylls budet inte före start försvinner det. Det är okej.</span></div></div>{flag}
<div class="mut" style="margin-top:10px;font-size:13px">Motståndaren {H.escape(other['spelare'])}: botens chans {pct(other['chans'])}, Polymarket {pct(other.get('mitt') or 0)}.</div>
</div>"""


def kurva(bs, start):
    pts, k = [start], start
    for b in sorted((b for b in bs if b.get("status") == "avgjord"), key=lambda b: b["start"]):
        k += b["resultat_fast"]; pts.append(k)
    if len(pts) < 3:
        return '<p class="mut">Kurvan visas när minst två bet är avgjorda.</p>'
    w, h, p = 900, 220, 34
    lo, hi = min(pts + [start]) * 0.98, max(pts + [start]) * 1.02
    X = lambda i: p + (w - 2 * p) * i / (len(pts) - 1)
    Y = lambda v: h - p - (h - 2 * p) * (v - lo) / (hi - lo)
    line = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(pts))
    col = "var(--acc)" if pts[-1] >= start else "var(--bad)"
    kr = lambda v: f"{v:,.0f}".replace(",", " ") + " kr"
    return (f'<div class="mut" style="font-size:14px">Start {kr(start)} → nu <b style="color:{col}">{kr(pts[-1])}</b> '
            f'efter {len(pts) - 1} avgjorda bet (streckad linje = start)</div>'
            f'<svg class="chart" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" aria-label="Låtsaskassan över tid">'
            f'<line x1="{p}" x2="{w - p}" y1="{Y(start):.1f}" y2="{Y(start):.1f}" stroke="var(--mut)" stroke-opacity=".5" '
            f'stroke-dasharray="6 6" vector-effect="non-scaling-stroke"/>'
            f'<polyline points="{line}" fill="none" stroke="{col}" stroke-width="2.5" stroke-linejoin="round" '
            f'vector-effect="non-scaling-stroke"/></svg>')


def status_pill(b):
    if b["status"] == "avgjord":
        return '<span class="pill win">Vann</span>' if b["resultat_fast"] > 0 else (
            '<span class="pill wait">50-50</span>' if b.get("utfall") == 0.5 else '<span class="pill loss">Förlust</span>')
    if b["status"] == "ej fylld":
        return '<span class="pill wait">Ej fylld</span>'
    return f'<span class="pill wait">{H.escape(b["status"].capitalize())}</span>'


def build(analyses, bs, strat, kassa_fn):
    done = [b for b in bs if b.get("status") == "avgjord"]
    insats = sum(b["insats_fast"] for b in done); res = sum(b["resultat_fast"] for b in done)
    vann = sum(1 for b in done if b.get("utfall") == 1)
    tiles = [(f"{kassa_fn(bs, 'fast'):,.0f} kr".replace(",", " "), "Låtsaskassa"),
             (str(len(done)), "Avgjorda bet"),
             (f"{vann} av {len(done)}" if done else "–", "Vunna"),
             ((f"{100 * res / insats:+.1f} %".replace(".", ",") if insats else "–"), "Avkastning")]
    tiles_html = "".join(f'<div class="tile"><div class="v">{v}</div><div class="l">{l}</div></div>' for v, l in tiles)
    sig = sorted((a for a in analyses if a.get("signal")), key=lambda a: a["start"])
    cards = "".join(signal_card(a) for a in sig) or (
        '<div class="card empty"><div class="big">Inget spelvärde just nu</div>'
        '<div class="mut">Boten hittar ingen ATP-match där edgen är minst 10 procentenheter. Det är vanligt; vänta in nästa.</div></div>')
    def logrow(b):
        res_txt = f"{b['resultat_fast']:+.0f} kr" if b.get("status") == "avgjord" else ""
        return (f"<tr><td>{tid(b['start'])}</td><td><b>{H.escape(b['spelare'])}</b>"
                f"<span class='sub'>{H.escape(b['title'].split(': ', 1)[-1])}</span></td>"
                f"<td class='r'>{100 * b['budpris']:.0f}¢</td><td class='r hide-sm'>{pct(b['chans'])}</td><td>{status_pill(b)}</td>"
                f"<td class='r'>{res_txt}</td></tr>")
    log = "".join(logrow(b) for b in sorted(bs, key=lambda b: -b["lagd"]))
    log_html = ('<div class="scroll"><table><tr><th>Start</th><th>Spelare</th><th class="r">Bud</th><th class="r hide-sm">Boten</th>'
                '<th>Status</th><th class="r">Resultat</th></tr>' + log + "</table></div>") if bs else '<p class="mut">Inga låtsasbet än. Boten lägger dem ca 3 timmar före start.</p>'
    ovr = "".join(f"<tr><td>{tid(a['start'])}</td><td>{H.escape(a['title'])}"
                  f"<span class='sub'>{H.escape(a.get('skäl') or a.get('slutsats', ''))}</span></td></tr>"
                  for a in sorted(analyses, key=lambda a: a["start"]) if not a.get("signal"))
    now = datetime.now().strftime("%d/%m %H:%M")
    return f"""<!doctype html><html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300"><title>Tennisboten</title><style>{CSS}</style></head><body><div class="wrap">
<header><div><h1>Tennisboten</h1><div class="mut">Uppdaterad {now} · laddar om var 5:e minut</div></div>
<span class="pill paper">Testläge: låtsasbet</span></header>
<div class="tiles">{tiles_html}</div>
<h2>Dagens bud</h2>{cards}
<h2>Låtsaskassan</h2><div class="card">{kurva(bs, strat['kassa'])}</div>
<h2>Låtsasbet</h2>{log_html}
<h2>Övriga ATP-matcher</h2><details><summary>{len(analyses) - len(sig)} matcher utan spelvärde (visa varför)</summary>
<div class="scroll" style="border:0;padding:0;margin-top:8px"><table>{ovr}</table></div></details>
<footer>Strategin: köpbud när botens chans är minst 10 procentenheter högre än budpriset, ca 3 timmar före start, bara ATP-touren.
Låtsasinsats 100 kr per bet. Förslaget på riktig insats ({RIKTIG_INSATS_USD} $) är 1 % av 1 000 $ medan strategin testas.
Inget här är en garanti; räkna med långa förlustsviter.</footer></div></body></html>"""
