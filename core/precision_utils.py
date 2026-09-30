import logging
from typing import Dict

logger = logging.getLogger(__name__)

# Instrument precision mapping
# Gold (XAU_USD) typically uses 3 decimal places on OANDA
PRECISION_MAP = {
    "XAU_USD": 3,
    "DEFAULT": 5
}

def round_price(price: float, instrument: str = "XAU_USD") -> float:
    """
    Rounds a price to the correct decimal precision based on the instrument.
    """
    if price is None:
        return None

    precision = PRECISION_MAP.get(instrument, PRECISION_MAP["DEFAULT"])
    return round(float(price), precision)
