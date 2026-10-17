from dataclasses import dataclass

MIN_BUY_NOTIONAL = 1.00  # Alpaca rejects notional buy orders under this outright; sells aren't restricted


@dataclass(frozen=True)
class Order:
    ticker: str
    side: str  # "buy" or "sell"
    notional: float
    reason: str
    full_close: bool = False  # sell the entire position via Alpaca's close_position, not a notional sell


def equal_weights(tickers: list[str]) -> dict[str, float]:
    if not tickers:
        return {}
    w = 1.0 / len(tickers)
    return {ticker: w for ticker in tickers}


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("weights must sum to a positive number")
    return {ticker: w / total for ticker, w in weights.items()}


def bootstrap_orders(targets: dict[str, float], cash: float, reason: str = "bootstrap") -> list[Order]:
    """Split available cash across targets according to weight. Assumes no existing positions."""
    return [
        Order(ticker=ticker, side="buy", notional=weight * cash, reason=reason)
        for ticker, weight in targets.items()
        if weight * cash > 0
    ]


def compute_rebalance_orders(
    targets: dict[str, float],
    current_values: dict[str, float],
    cash: float,
    reason: str = "rebalance",
) -> list[Order]:
    """Diff current holdings against target weights and return every order needed to
    converge exactly — no "is this trade worth it" filtering. You approve every order
    individually anyway, so that judgment call is yours, not a threshold baked in here.
    """
    total_equity = cash + sum(current_values.values())
    if total_equity <= 0:
        return []

    orders: list[Order] = []

    all_tickers = set(targets.keys()) | set(current_values.keys())
    for ticker in sorted(all_tickers):
        target_value = targets.get(ticker, 0.0) * total_equity
        current_value = current_values.get(ticker, 0.0)
        delta = target_value - current_value

        if abs(delta) < 0.01:  # a cent or less is float noise, not a real trade
            continue

        side = "buy" if delta > 0 else "sell"
        # A target weight of 0 (or no target at all) means the position should be fully
        # liquidated. Use Alpaca's close_position for that instead of a notional sell —
        # a notional sell can leave rounding dust behind instead of zeroing the position.
        full_close = side == "sell" and targets.get(ticker, 0.0) == 0.0
        orders.append(Order(ticker=ticker, side=side, notional=abs(delta), reason=reason, full_close=full_close))

    return orders


def apply_cash_buffer(orders: list[Order], cash: float, buffer_pct: float) -> list[Order]:
    """Scale down buy orders (proportionally; sells are untouched) so their total never
    exceeds buffer_pct of available cash. This is a cushion against price drift/slippage
    between computing an order and it actually filling -- not a change to the target
    weights, which is why it only touches buys (sells free up cash, they don't spend it)
    and leaves compute_rebalance_orders itself buffer-free so targets still match exactly.

    "Available cash" includes this batch's sell proceeds, not just pre-existing cash --
    a sell and a buy in the same sync commonly fund each other (e.g. closing a dropped
    pick to help pay for a new one), so ignoring sell proceeds would wrongly starve a
    buy that's actually fully funded.
    """
    sell_total = sum(o.notional for o in orders if o.side == "sell")
    buy_total = sum(o.notional for o in orders if o.side == "buy")
    max_deployable = (cash + sell_total) * buffer_pct

    if buy_total <= max_deployable or buy_total == 0:
        return orders

    scale = max_deployable / buy_total
    return [
        Order(ticker=o.ticker, side=o.side, notional=o.notional * scale, reason=o.reason, full_close=o.full_close)
        if o.side == "buy"
        else o
        for o in orders
    ]


def drop_subminimum_buys(orders: list[Order], minimum: float = MIN_BUY_NOTIONAL) -> list[Order]:
    """Drop buy orders Alpaca would reject outright for being under its notional minimum,
    instead of submitting them and letting that failure print. These are immaterial
    rebalance-drift amounts -- skipping one just means it gets picked up on some later
    sync once the drift for that ticker grows past the minimum. Sells pass through
    untouched since Alpaca doesn't apply the same floor to them.
    """
    return [o for o in orders if o.side != "buy" or o.notional >= minimum]
