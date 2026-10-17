import json
from unittest.mock import MagicMock, patch

import pytest

from config import Config
from main import run_sync


def _cfg(trade_log_path: str, cash_buffer_pct: float = 1.0) -> Config:
    return Config(
        alpaca_api_key="key",
        alpaca_secret_key="secret",
        alpaca_base_url="https://paper-api.alpaca.markets",
        trade_log_path=trade_log_path,
        cash_buffer_pct=cash_buffer_pct,
    )


def _portfolio_file(tmp_path, weights: dict) -> str:
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(weights))
    return str(path)


@patch("main.Broker")
@patch("main.load_config")
def test_sync_with_yes_flag_submits_without_prompting(mock_load_config, mock_broker_cls, tmp_path, capsys):
    trade_log_path = str(tmp_path / "trades.jsonl")
    mock_load_config.return_value = _cfg(trade_log_path)
    broker = mock_broker_cls.return_value
    broker.get_cash.return_value = 1000.0
    broker.get_positions.return_value = {}
    broker.submit_notional_order.return_value = "order-1"
    broker.wait_for_orders.return_value = {"order-1": "filled"}

    file_path = _portfolio_file(tmp_path, {"AAPL": 1.0})
    run_sync(file_path, auto_yes=True)

    broker.submit_notional_order.assert_called_once_with("AAPL", "buy", pytest.approx(1000.0))
    broker.wait_for_orders.assert_called_once_with(["order-1"])
    captured = capsys.readouterr()
    assert "Submitted buy AAPL" in captured.out
    assert "SUCCESS" in captured.out

    with open(trade_log_path) as f:
        entry = json.loads(f.readline())
    assert entry["ticker"] == "AAPL"
    assert entry["alpaca_order_id"] == "order-1"


@patch("main.Broker")
@patch("main.load_config")
@patch("builtins.input", return_value="y")
def test_sync_prompts_and_submits_on_yes(mock_input, mock_load_config, mock_broker_cls, tmp_path, capsys):
    mock_load_config.return_value = _cfg(str(tmp_path / "trades.jsonl"))
    broker = mock_broker_cls.return_value
    broker.get_cash.return_value = 1000.0
    broker.get_positions.return_value = {}
    broker.submit_notional_order.return_value = "order-1"
    broker.wait_for_orders.return_value = {"order-1": "filled"}

    file_path = _portfolio_file(tmp_path, {"AAPL": 1.0})
    run_sync(file_path, auto_yes=False)

    mock_input.assert_called_once()
    broker.submit_notional_order.assert_called_once()


@patch("main.Broker")
@patch("main.load_config")
@patch("builtins.input", return_value="n")
def test_sync_prompts_and_aborts_on_no(mock_input, mock_load_config, mock_broker_cls, tmp_path, capsys):
    mock_load_config.return_value = _cfg(str(tmp_path / "trades.jsonl"))
    broker = mock_broker_cls.return_value
    broker.get_cash.return_value = 1000.0
    broker.get_positions.return_value = {}

    file_path = _portfolio_file(tmp_path, {"AAPL": 1.0})
    run_sync(file_path, auto_yes=False)

    broker.submit_notional_order.assert_not_called()
    captured = capsys.readouterr()
    assert "Aborted" in captured.out


@patch("main.Broker")
@patch("main.load_config")
def test_sync_no_trades_needed_skips_prompt_entirely(mock_load_config, mock_broker_cls, tmp_path, capsys):
    mock_load_config.return_value = _cfg(str(tmp_path / "trades.jsonl"))
    broker = mock_broker_cls.return_value
    broker.get_cash.return_value = 0.0
    broker.get_positions.return_value = {"AAPL": 1000.0}

    file_path = _portfolio_file(tmp_path, {"AAPL": 1.0})
    with patch("builtins.input") as mock_input:
        run_sync(file_path, auto_yes=False)
        mock_input.assert_not_called()

    broker.submit_notional_order.assert_not_called()
    captured = capsys.readouterr()
    assert "No trades needed" in captured.out


@patch("main.Broker")
@patch("main.load_config")
def test_sync_order_failure_is_reported_and_not_logged(mock_load_config, mock_broker_cls, tmp_path, capsys):
    trade_log_path = str(tmp_path / "trades.jsonl")
    mock_load_config.return_value = _cfg(trade_log_path)
    broker = mock_broker_cls.return_value
    broker.get_cash.return_value = 1000.0
    broker.get_positions.return_value = {}
    broker.submit_notional_order.side_effect = RuntimeError("insufficient buying power")

    file_path = _portfolio_file(tmp_path, {"AAPL": 1.0})
    run_sync(file_path, auto_yes=True)

    captured = capsys.readouterr()
    assert "FAILED" in captured.err
    import os

    assert not os.path.exists(trade_log_path)


@patch("main.Broker")
@patch("main.load_config")
def test_sync_accepted_but_unfilled_order_is_reported_and_not_logged(mock_load_config, mock_broker_cls, tmp_path, capsys):
    # Submission can succeed (Alpaca hands back an order id) while the order itself
    # never fills (e.g. rejected after acceptance) -- that must surface as a failure,
    # not get silently logged as a completed trade.
    trade_log_path = str(tmp_path / "trades.jsonl")
    mock_load_config.return_value = _cfg(trade_log_path)
    broker = mock_broker_cls.return_value
    broker.get_cash.return_value = 1000.0
    broker.get_positions.return_value = {}
    broker.submit_notional_order.return_value = "order-1"
    broker.wait_for_orders.return_value = {"order-1": "rejected"}

    file_path = _portfolio_file(tmp_path, {"AAPL": 1.0})
    run_sync(file_path, auto_yes=True)

    captured = capsys.readouterr()
    assert "FAILED" in captured.err
    assert "rejected" in captured.err
    import os

    assert not os.path.exists(trade_log_path)


@patch("main.Broker")
@patch("main.load_config")
def test_sync_full_close_uses_close_position(mock_load_config, mock_broker_cls, tmp_path):
    mock_load_config.return_value = _cfg(str(tmp_path / "trades.jsonl"))
    broker = mock_broker_cls.return_value
    broker.get_cash.return_value = 0.0
    broker.get_positions.return_value = {"TSLA": 500.0}
    broker.close_position.return_value = "close-order-1"
    broker.submit_notional_order.return_value = "order-1"

    # Target is AAPL only -> TSLA (not in target at all) must be fully liquidated via close_position.
    file_path = _portfolio_file(tmp_path, {"AAPL": 1.0})
    run_sync(file_path, auto_yes=True)

    broker.close_position.assert_called_once_with("TSLA")
    broker.submit_notional_order.assert_called_once_with("AAPL", "buy", pytest.approx(500.0))


@patch("main.Broker")
@patch("main.load_config")
def test_sync_skips_buy_orders_under_alpaca_minimum_notional(mock_load_config, mock_broker_cls, tmp_path, capsys):
    mock_load_config.return_value = _cfg(str(tmp_path / "trades.jsonl"))
    broker = mock_broker_cls.return_value
    broker.get_cash.return_value = 1.0
    # total equity = 1.0 -> AAPL target = $0.60 (under Alpaca's $1 buy minimum), GOOG = $0.40 (same).
    broker.get_positions.return_value = {}

    file_path = _portfolio_file(tmp_path, {"AAPL": 0.6, "GOOG": 0.4})
    run_sync(file_path, auto_yes=True)

    broker.submit_notional_order.assert_not_called()
    captured = capsys.readouterr()
    assert "Skipping 2 buy order(s)" in captured.out
    assert "No trades needed" in captured.out


@patch("main.Broker")
@patch("main.load_config")
def test_sync_submits_all_sells_before_any_buys(mock_load_config, mock_broker_cls, tmp_path):
    mock_load_config.return_value = _cfg(str(tmp_path / "trades.jsonl"))
    broker = mock_broker_cls.return_value
    broker.get_cash.return_value = 0.0
    # Both AAPL (held, needs trimming down) and MSFT (held, not in target at all -> full close)
    # must be sold before GOOG (not held, needs a full buy) is submitted.
    broker.get_positions.return_value = {"AAPL": 800.0, "MSFT": 200.0}
    broker.close_position.return_value = "close-order-1"
    broker.submit_notional_order.return_value = "order-1"
    broker.wait_for_orders.return_value = {}

    call_order: list[str] = []
    broker.close_position.side_effect = lambda ticker: (call_order.append(f"sell {ticker}"), "close-order-1")[1]
    broker.submit_notional_order.side_effect = lambda ticker, side, notional: (
        call_order.append(f"{side} {ticker}"),
        "order-1",
    )[1]

    # total equity = 1000 -> AAPL target = 400 (sell 400), MSFT target = 0 (full close), GOOG target = 600 (buy).
    file_path = _portfolio_file(tmp_path, {"AAPL": 0.4, "GOOG": 0.6})
    run_sync(file_path, auto_yes=True)

    assert call_order == ["sell AAPL", "sell MSFT", "buy GOOG"]


@patch("main.Broker")
@patch("main.load_config")
def test_sync_cash_buffer_scales_buys_but_not_full_closes(mock_load_config, mock_broker_cls, tmp_path, capsys):
    mock_load_config.return_value = _cfg(str(tmp_path / "trades.jsonl"), cash_buffer_pct=0.95)
    broker = mock_broker_cls.return_value
    broker.get_cash.return_value = 1000.0
    broker.get_positions.return_value = {"TSLA": 500.0}
    broker.close_position.return_value = "close-order-1"
    broker.submit_notional_order.return_value = "order-1"

    # total equity = 1500 -> target AAPL buy = $1500, TSLA (not in target) gets fully closed for $500.
    # Available cash for the buffer = cash (1000) + TSLA's sell proceeds (500) = 1500, buffered at
    # 95% = 1425 -- the AAPL buy must scale down to exactly that; the TSLA sell stays untouched.
    file_path = _portfolio_file(tmp_path, {"AAPL": 1.0})
    run_sync(file_path, auto_yes=True)

    broker.close_position.assert_called_once_with("TSLA")  # sell side: unscaled
    broker.submit_notional_order.assert_called_once_with("AAPL", "buy", pytest.approx(1425.0))

    captured = capsys.readouterr()
    assert "cash buffer" in captured.out
