import argparse
import sys

from broker import Broker
from config import Config, load_config
from portfolio_file import load_portfolio_file
from rebalancer import MIN_BUY_NOTIONAL, Order, compute_rebalance_orders, drop_subminimum_buys
from trade_log import log_trade


def print_orders(orders: list[Order], targets: dict[str, float]) -> None:
    if not orders:
        print("No trades needed -- already at target.")
        return

    print(f"{'SIDE':6}{'TICKER':8}{'NOTIONAL':>12}  TARGET WEIGHT")
    for order in orders:
        target_pct = targets.get(order.ticker, 0.0)
        tag = " (full close)" if order.full_close else ""
        print(f"{order.side.upper():6}{order.ticker:8}{order.notional:>12,.2f}  {target_pct:.2%}{tag}")


def _report_results(cfg: Config, submitted: dict[str, Order], statuses: dict[str, str]) -> None:
    for order_id, order in submitted.items():
        tag = " (full close)" if order.full_close else ""
        status = statuses.get(order_id, "unknown")
        if status == "filled":
            log_trade(cfg.trade_log_path, order.ticker, order.side, order.notional, order_id, order.reason)
            print(f"Submitted {order.side} {order.ticker} ${order.notional:,.2f}{tag} -- SUCCESS (order {order_id})")
        elif status == "partially_filled":
            print(
                f"Submitted {order.side} {order.ticker} ${order.notional:,.2f}{tag} -- "
                f"PARTIAL FILL, not logged -- check Alpaca for the actual filled amount (order {order_id})",
                file=sys.stderr,
            )
        else:
            print(
                f"Submitted {order.side} {order.ticker} ${order.notional:,.2f}{tag} -- "
                f"FAILED ({status}, order {order_id})",
                file=sys.stderr,
            )


def run_sync(file_path: str, auto_yes: bool) -> None:
    cfg = load_config()
    broker = Broker(cfg)

    targets = load_portfolio_file(file_path)
    cash = broker.get_cash()
    current_values = broker.get_positions()
    total_equity = cash + sum(current_values.values())
    orders = compute_rebalance_orders(targets, current_values, cash)

    tradable_orders = drop_subminimum_buys(orders)
    skipped = [o for o in orders if o not in tradable_orders]
    if skipped:
        details = ", ".join(f"{o.ticker} (${o.notional:.2f})" for o in skipped)
        print(f"Skipping {len(skipped)} buy order(s) under Alpaca's ${MIN_BUY_NOTIONAL:.2f} minimum notional: {details}")
    orders = tradable_orders

    print(f"Account equity: ${total_equity:,.2f}  (cash ${cash:,.2f})")
    print_orders(orders, targets)

    if not orders:
        return

    if not auto_yes:
        answer = input("\nSubmit these orders to Alpaca? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted -- no orders submitted.")
            return

    sells = [o for o in orders if o.side == "sell"]
    buys = [o for o in orders if o.side == "buy"]

    # Phase 1: sells. Submitted and confirmed filled before any buy is sized, so buy
    # sizing (phase 2) reacts to real post-sell cash instead of an upfront estimate.
    sell_submitted: dict[str, Order] = {}
    for order in sells:
        try:
            order_id = broker.close_position(order.ticker) if order.full_close else broker.submit_notional_order(
                order.ticker, order.side, order.notional
            )
        except Exception as exc:
            print(f"FAILED {order.side} {order.ticker}: {exc}", file=sys.stderr)
            continue
        sell_submitted[order_id] = order

    if sell_submitted:
        sell_statuses = broker.wait_for_orders(list(sell_submitted.keys()))
        _report_results(cfg, sell_submitted, sell_statuses)

    # Phase 2: buys. Not latency-sensitive, so cash is re-checked live before each one
    # instead of estimating upfront and hoping -- buy as much of the target as actually
    # fits right now; whatever doesn't fit this cycle gets picked up on the next sync.
    buy_submitted: dict[str, Order] = {}
    for order in buys:
        available_cash = broker.get_cash()
        notional = min(order.notional, available_cash)
        if notional < MIN_BUY_NOTIONAL:
            print(
                f"Skipping buy {order.ticker} -- only ${available_cash:,.2f} cash available "
                f"(below Alpaca's ${MIN_BUY_NOTIONAL:.2f} minimum)",
                file=sys.stderr,
            )
            continue
        if notional < order.notional:
            print(f"Only ${available_cash:,.2f} cash available for {order.ticker} (wanted ${order.notional:,.2f}) -- buying as much as fits")
            order = Order(ticker=order.ticker, side=order.side, notional=notional, reason=order.reason, full_close=order.full_close)

        try:
            order_id = broker.submit_notional_order(order.ticker, order.side, order.notional)
        except Exception as exc:
            print(f"FAILED {order.side} {order.ticker}: {exc}", file=sys.stderr)
            continue
        buy_submitted[order_id] = order

    if buy_submitted:
        buy_statuses = broker.wait_for_orders(list(buy_submitted.keys()))
        _report_results(cfg, buy_submitted, buy_statuses)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebalance your Alpaca account toward a target portfolio.json")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_cmd = sub.add_parser("sync", help="Compute and (with confirmation) submit the orders needed to converge")
    sync_cmd.add_argument(
        "--file",
        required=True,
        help='Portfolio file: .json ({"TICKER": weight}) or .csv/.tsv (Symbol + Holding %% columns)',
    )
    sync_cmd.add_argument("--yes", action="store_true", help="Skip the confirmation prompt and submit immediately")

    args = parser.parse_args()
    if args.command == "sync":
        run_sync(args.file, args.yes)


if __name__ == "__main__":
    main()
