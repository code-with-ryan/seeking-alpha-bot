import argparse
import sys

from broker import Broker
from config import load_config
from portfolio_file import load_portfolio_file
from rebalancer import MIN_BUY_NOTIONAL, Order, apply_cash_buffer, compute_rebalance_orders, drop_subminimum_buys
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


def run_sync(file_path: str, auto_yes: bool) -> None:
    cfg = load_config()
    broker = Broker(cfg)

    targets = load_portfolio_file(file_path)
    cash = broker.get_cash()
    current_values = broker.get_positions()
    total_equity = cash + sum(current_values.values())
    orders = compute_rebalance_orders(targets, current_values, cash)

    buffered_orders = apply_cash_buffer(orders, cash, cfg.cash_buffer_pct)
    if buffered_orders != orders:
        held_back = sum(o.notional for o in orders if o.side == "buy") - sum(
            o.notional for o in buffered_orders if o.side == "buy"
        )
        print(f"Scaling down buy orders to keep ${held_back:,.2f} in reserve ({cfg.cash_buffer_pct:.0%} cash buffer).")
    orders = buffered_orders

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

    # Sells first, buys second -- so buys aren't racing uncleared sell proceeds for
    # buying power. Both groups keep their original (ticker-sorted) relative order.
    sells = [o for o in orders if o.side == "sell"]
    buys = [o for o in orders if o.side == "buy"]

    submitted: dict[str, Order] = {}
    for order in sells + buys:
        try:
            if order.full_close:
                order_id = broker.close_position(order.ticker)
            else:
                order_id = broker.submit_notional_order(order.ticker, order.side, order.notional)
        except Exception as exc:
            print(f"FAILED {order.side} {order.ticker}: {exc}", file=sys.stderr)
            continue
        submitted[order_id] = order

    if not submitted:
        return

    # One batched check covering every order just submitted, instead of polling each
    # one individually -- confirming fills on 30 tickers takes the same ~10s as one.
    statuses = broker.wait_for_orders(list(submitted.keys()))

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
