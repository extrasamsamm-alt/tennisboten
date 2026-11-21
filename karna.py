"""Kärnberäkningar: avgift, verkligt köppris ur orderboken, de-vig och edge."""


def fee_per_share(price, rate=0.05):
    """Polymarkets avgift per andel för den som köper ur boken: rate * p * (1 - p)."""
    return rate * price * (1 - price)


def buy_cost(asks, usd, rate=0.05):
    """Går igenom säljorder (asks) från billigast och köper för `usd` dollar.

    asks: lista av (pris, antal). Returnerar dict med antal andelar, snittpris
    inkl. avgift, spenderat belopp och om hela beloppet gick att köpa.
    """
    left, shares, spent = usd, 0.0, 0.0
    for price, size in sorted(asks):
        unit = price + fee_per_share(price, rate)
        take = min(size, left / unit)
        shares += take
        spent += take * unit
        left -= take * unit
        if left <= 1e-9:
            break
    return {"shares": shares, "spent": spent, "filled": left <= 1e-6,
            "avg_price": spent / shares if shares else None}


def devig(odds_a, odds_b):
    """Tar bort bookmakerns marginal ur två decimalodds (proportionell metod).

    Returnerar (sannolikhet A, sannolikhet B) som summerar till 1.
    """
    if odds_a <= 1 or odds_b <= 1:
        raise ValueError("decimalodds måste vara större än 1")
    ia, ib = 1 / odds_a, 1 / odds_b
    return ia / (ia + ib), ib / (ia + ib)


def edge(fair_prob, avg_price_incl_fee, p_void=0.0):
    """Förväntad vinst per andel.

    p_void = sannolikhet att marknaden avgörs 50-50 (walkover/inställd). Då
    betalas 0,50 per andel oavsett vem man köpt.
    """
    value = (1 - p_void) * fair_prob + p_void * 0.5
    return value - avg_price_incl_fee
