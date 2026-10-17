"""Append-only audit log of executed trades, as JSON Lines -- one line per fill,
so it's trivial to inspect (`cat trades.jsonl`) or tail without any tooling.
"""

import json
import time


def log_trade(path: str, ticker: str, side: str, notional: float, alpaca_order_id: str, reason: str) -> None:
    entry = {
        "ticker": ticker,
        "side": side,
        "notional": notional,
        "alpaca_order_id": alpaca_order_id,
        "reason": reason,
        "filled_at": time.time(),
    }
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")
