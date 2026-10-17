import pytest

from rebalancer import (
    Order,
    apply_cash_buffer,
    bootstrap_orders,
    compute_rebalance_orders,
    drop_subminimum_buys,
    equal_weights,
    normalize_weights,
)


def test_equal_weights_splits_evenly():
    weights = equal_weights(["AAPL", "MSFT", "GOOG"])
    assert weights == pytest.approx({"AAPL": 1 / 3, "MSFT": 1 / 3, "GOOG": 1 / 3})


def test_equal_weights_empty():
    assert equal_weights([]) == {}


def test_normalize_weights():
    weights = normalize_weights({"AAPL": 2, "MSFT": 1, "GOOG": 1})
    assert weights == pytest.approx({"AAPL": 0.5, "MSFT": 0.25, "GOOG": 0.25})


def test_normalize_weights_rejects_zero_total():
    with pytest.raises(ValueError):
        normalize_weights({"AAPL": 0, "MSFT": 0})


def test_bootstrap_orders_splits_cash_by_weight():
    targets = equal_weights(["AAPL", "MSFT"])
    orders = bootstrap_orders(targets, cash=1000.0)
    assert len(orders) == 2
    assert {o.ticker for o in orders} == {"AAPL", "MSFT"}
    for order in orders:
        assert order.side == "buy"
        assert order.notional == pytest.approx(500.0)


def test_compute_rebalance_orders_buys_underweight_position():
    targets = {"AAPL": 0.5, "MSFT": 0.5}
    current_values = {"AAPL": 400.0, "MSFT": 600.0}
    orders = compute_rebalance_orders(targets, current_values, cash=0.0)
    # total equity = 1000, target each = 500 -> AAPL needs +100, MSFT needs -100
    by_ticker = {o.ticker: o for o in orders}
    assert by_ticker["AAPL"].side == "buy"
    assert by_ticker["AAPL"].notional == pytest.approx(100.0)
    assert by_ticker["MSFT"].side == "sell"
    assert by_ticker["MSFT"].notional == pytest.approx(100.0)


def test_compute_rebalance_orders_proposes_every_real_drift_no_matter_how_small():
    # No "is this worth it" filtering — every real order is proposed; you approve or reject it.
    targets = {"AAPL": 0.5, "MSFT": 0.5}
    current_values = {"AAPL": 498.0, "MSFT": 502.0}
    orders = compute_rebalance_orders(targets, current_values, cash=0.0)
    by_ticker = {o.ticker: o for o in orders}
    assert by_ticker["AAPL"].side == "buy"
    assert by_ticker["AAPL"].notional == pytest.approx(2.0)
    assert by_ticker["MSFT"].side == "sell"
    assert by_ticker["MSFT"].notional == pytest.approx(2.0)


def test_compute_rebalance_orders_skips_only_sub_cent_float_noise():
    targets = {"AAPL": 1 / 3, "MSFT": 1 / 3, "GOOG": 1 / 3}
    current_values = {"AAPL": 333.33, "MSFT": 333.34, "GOOG": 333.33}  # rounds to exactly 1000 either way
    orders = compute_rebalance_orders(targets, current_values, cash=0.0)
    assert orders == []


def test_compute_rebalance_orders_sells_position_removed_from_targets():
    targets = {"AAPL": 1.0}
    current_values = {"AAPL": 500.0, "TSLA": 500.0}
    orders = compute_rebalance_orders(targets, current_values, cash=0.0)
    by_ticker = {o.ticker: o for o in orders}
    assert by_ticker["TSLA"].side == "sell"
    assert by_ticker["TSLA"].notional == pytest.approx(500.0)
    # Full removal should be flagged for close_position, not a notional sell that can leave dust.
    assert by_ticker["TSLA"].full_close is True
    # AAPL is merely underweight-trimmed elsewhere in these tests, never fully removed,
    # so full_close must default to False for ordinary trims and buys.
    assert by_ticker["AAPL"].full_close is False


def test_compute_rebalance_orders_partial_sell_is_not_full_close():
    targets = {"AAPL": 0.2, "MSFT": 0.8}
    current_values = {"AAPL": 600.0, "MSFT": 400.0}
    orders = compute_rebalance_orders(targets, current_values, cash=0.0)
    by_ticker = {o.ticker: o for o in orders}
    assert by_ticker["AAPL"].side == "sell"
    assert by_ticker["AAPL"].full_close is False


def test_compute_rebalance_orders_empty_portfolio():
    assert compute_rebalance_orders({}, {}, cash=0.0) == []


def test_apply_cash_buffer_no_scaling_when_under_limit():
    orders = [Order("AAPL", "buy", 500.0, "sync")]
    result = apply_cash_buffer(orders, cash=1000.0, buffer_pct=0.95)
    assert result == orders


def test_apply_cash_buffer_scales_buys_proportionally_when_over_limit():
    # Full bootstrap: buys total $1000 against $1000 cash -- at a 0.95 buffer,
    # only $950 should actually get deployed, split proportionally across both buys.
    orders = [Order("AAPL", "buy", 600.0, "sync"), Order("MSFT", "buy", 400.0, "sync")]
    result = apply_cash_buffer(orders, cash=1000.0, buffer_pct=0.95)
    by_ticker = {o.ticker: o for o in result}
    assert sum(o.notional for o in result) == pytest.approx(950.0)
    assert by_ticker["AAPL"].notional == pytest.approx(570.0)  # 600 * 0.95
    assert by_ticker["MSFT"].notional == pytest.approx(380.0)  # 400 * 0.95


def test_apply_cash_buffer_leaves_sells_untouched():
    # Available cash for buys = pre-existing cash + this batch's sell proceeds = 500 + 500 = 1000.
    orders = [Order("AAPL", "buy", 1000.0, "sync"), Order("TSLA", "sell", 500.0, "sync", full_close=True)]
    result = apply_cash_buffer(orders, cash=500.0, buffer_pct=0.9)
    by_ticker = {o.ticker: o for o in result}
    assert by_ticker["TSLA"].notional == pytest.approx(500.0)  # sell untouched, even though it funds the buy
    assert by_ticker["TSLA"].full_close is True
    assert by_ticker["AAPL"].notional == pytest.approx(900.0)  # (500 cash + 500 sell proceeds) * 0.9


def test_apply_cash_buffer_noop_with_no_buy_orders():
    orders = [Order("TSLA", "sell", 500.0, "sync", full_close=True)]
    assert apply_cash_buffer(orders, cash=0.0, buffer_pct=0.95) == orders


def test_apply_cash_buffer_buy_fully_funded_by_same_batch_sell_is_not_starved():
    # Zero pre-existing cash, but a sell in the same batch covers the buy exactly --
    # must not be scaled down to zero just because `cash` alone looks insufficient.
    orders = [Order("AAPL", "buy", 500.0, "sync"), Order("TSLA", "sell", 500.0, "sync", full_close=True)]
    result = apply_cash_buffer(orders, cash=0.0, buffer_pct=1.0)
    assert result == orders


def test_drop_subminimum_buys_removes_buys_under_the_floor():
    orders = [Order("AAPL", "buy", 0.99, "sync"), Order("MSFT", "buy", 1.00, "sync")]
    assert drop_subminimum_buys(orders) == [Order("MSFT", "buy", 1.00, "sync")]


def test_drop_subminimum_buys_leaves_small_sells_alone():
    # Alpaca's $1 minimum is a notional-buy restriction -- sells of any size go through.
    orders = [Order("AAPL", "sell", 0.05, "sync"), Order("TSLA", "sell", 500.0, "sync", full_close=True)]
    assert drop_subminimum_buys(orders) == orders


def test_drop_subminimum_buys_respects_custom_minimum():
    orders = [Order("AAPL", "buy", 2.50, "sync")]
    assert drop_subminimum_buys(orders, minimum=5.0) == []
