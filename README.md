# Tennisboten

Hittar ATP-matcher på Polymarket där priset avviker från Pinnacles rättvisa odds, och låtsasspelar dem.
Körs automatiskt varje timme av GitHub Actions. Inga riktiga order, ingen wallet.

## Så funkar det
* **Huvudstrategin (pinnacle):** Pinnacles odds utan marginal = rättvis chans. Signal när vårt köpbud ligger
  minst 3 procentenheter under, och statistikmodellen inte säger emot. Kräver en gratis nyckel från oddspapi.io.
* **Gamla strategin (modell):** modellens chans minst 10 procentenheter över budet. Låtsasspelas bara som jämförelse.
* Bud som inte fylls rättas ändå, så `python3 bot.py rapport` visar om de fyllda betten är sämre än de ofyllda.

## Kom igång med Pinnacle
1. Skaffa en gratis nyckel på oddspapi.io (250 anrop/månad räcker: boten hämtar bara odds ca 3 h före start).
2. GitHub: Settings → Secrets and variables → Actions → New repository secret. Namn `ODDSPAPI_KEY`.
3. Lokalt: `export ODDSPAPI_KEY=din_nyckel` innan du kör `python3 bot.py uppslag ...`.

## Slår modellen marknaden?
    python3 hamta_historik.py atp
    python3 validera.py
Jämför modellen med Polymarket-priset på matcher den aldrig tränats på och skriver ett rakt utlåtande.

* Sidan med signaler: se länken under Settings → Pages.
* Låtsasbeten: `data/paper/bets.jsonl`. Pinnacle-anrop och cache: `data/odds/cache.json`.
* Statistik: TML-databasen (stats.tennismylife.org), ej för kommersiellt bruk.
