import time

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import ClosePositionRequest, GetOrdersRequest, MarketOrderRequest
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce

from config import Config

TERMINAL_ORDER_STATUSES = {"filled", "canceled", "expired", "rejected", "stopped", "suspended", "done_for_day"}


def _order_status(order) -> str:
    return order.status.value if hasattr(order.status, "value") else str(order.status)


class Broker:
    def __init__(self, cfg: Config):
        self._client = TradingClient(
            cfg.alpaca_api_key,
            cfg.alpaca_secret_key,
            paper="paper" in cfg.alpaca_base_url,
        )

    def get_cash(self) -> float:
        account = self._client.get_account()
        return float(account.cash)

    def get_equity(self) -> float:
        account = self._client.get_account()
        return float(account.equity)

    def get_positions(self) -> dict[str, float]:
        positions = self._client.get_all_positions()
        return {p.symbol: float(p.market_value) for p in positions}

    def submit_notional_order(self, ticker: str, side: str, notional: float) -> str:
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        request = MarketOrderRequest(
            symbol=ticker,
            notional=round(notional, 2),
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )
        order = self._client.submit_order(request)
        return str(order.id)

    def close_position(self, ticker: str) -> str:
        """Fully liquidate a position. Use this instead of a notional sell when a
        ticker is being removed from the target allocation entirely — it guarantees
        the position goes to exactly zero instead of leaving rounding dust."""
        order = self._client.close_position(ticker, close_options=ClosePositionRequest(percentage="100"))
        return str(order.id)

    def get_order_statuses(self, order_ids: set[str]) -> dict[str, str]:
        """One list-orders call covering every order we care about, instead of one
        get-order call per id -- the cost of checking a batch doesn't scale with how
        many tickers just traded."""
        orders = self._client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.ALL, limit=500))
        return {str(o.id): _order_status(o) for o in orders if str(o.id) in order_ids}

    def wait_for_orders(self, order_ids: list[str], timeout: float = 10.0, poll_interval: float = 1.0) -> dict[str, str]:
        """Poll the whole submitted batch at once until every order reaches a terminal
        state (filled/rejected/canceled/etc.) or the timeout elapses. Submitting an
        order only means Alpaca *accepted* it -- this confirms what actually happened,
        in a fixed ~timeout seconds total rather than ~timeout seconds per order."""
        wanted = set(order_ids)
        latest: dict[str, str] = {}
        deadline = time.monotonic() + timeout
        while True:
            latest.update(self.get_order_statuses(wanted))
            unresolved = {oid for oid in wanted if latest.get(oid) not in TERMINAL_ORDER_STATUSES}
            if not unresolved or time.monotonic() >= deadline:
                return latest
            time.sleep(poll_interval)
