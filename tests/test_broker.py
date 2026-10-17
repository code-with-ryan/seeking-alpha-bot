from unittest.mock import MagicMock, patch

import pytest

from alpaca.trading.enums import OrderSide
from broker import Broker
from config import Config


def _cfg(base_url="https://paper-api.alpaca.markets") -> Config:
    return Config(
        alpaca_api_key="key",
        alpaca_secret_key="secret",
        alpaca_base_url=base_url,
        trade_log_path=":memory:",
        cash_buffer_pct=1.0,
    )


@patch("broker.TradingClient")
def test_paper_flag_derived_from_base_url(mock_client_cls):
    Broker(_cfg(base_url="https://paper-api.alpaca.markets"))
    _, kwargs = mock_client_cls.call_args
    assert kwargs["paper"] is True

    Broker(_cfg(base_url="https://api.alpaca.markets"))
    _, kwargs = mock_client_cls.call_args
    assert kwargs["paper"] is False


@patch("broker.TradingClient")
def test_get_cash_returns_float(mock_client_cls):
    mock_client = mock_client_cls.return_value
    mock_client.get_account.return_value = MagicMock(cash="1234.56")

    broker = Broker(_cfg())
    assert broker.get_cash() == pytest.approx(1234.56)
    assert isinstance(broker.get_cash(), float)


@patch("broker.TradingClient")
def test_get_equity_returns_float(mock_client_cls):
    mock_client = mock_client_cls.return_value
    mock_client.get_account.return_value = MagicMock(equity="9876.54")

    broker = Broker(_cfg())
    assert broker.get_equity() == pytest.approx(9876.54)


@patch("broker.TradingClient")
def test_get_positions_maps_symbol_to_market_value(mock_client_cls):
    mock_client = mock_client_cls.return_value
    mock_client.get_all_positions.return_value = [
        MagicMock(symbol="AAPL", market_value="500.00"),
        MagicMock(symbol="MSFT", market_value="300.00"),
    ]

    broker = Broker(_cfg())
    assert broker.get_positions() == {"AAPL": 500.0, "MSFT": 300.0}


@patch("broker.TradingClient")
def test_submit_notional_order_builds_correct_request(mock_client_cls):
    mock_client = mock_client_cls.return_value
    mock_client.submit_order.return_value = MagicMock(id="order-abc-123")

    broker = Broker(_cfg())
    order_id = broker.submit_notional_order("AAPL", "buy", 123.456)

    assert order_id == "order-abc-123"
    mock_client.submit_order.assert_called_once()
    (request,), _ = mock_client.submit_order.call_args
    assert request.symbol == "AAPL"
    assert request.side == OrderSide.BUY
    assert request.notional == 123.46  # rounded to cents


@patch("broker.TradingClient")
def test_submit_notional_order_sell_side(mock_client_cls):
    mock_client = mock_client_cls.return_value
    mock_client.submit_order.return_value = MagicMock(id="order-xyz")

    broker = Broker(_cfg())
    broker.submit_notional_order("TSLA", "sell", 50.0)

    (request,), _ = mock_client.submit_order.call_args
    assert request.side == OrderSide.SELL


@patch("broker.TradingClient")
def test_get_order_statuses_filters_to_requested_ids(mock_client_cls):
    mock_client = mock_client_cls.return_value
    mock_client.get_orders.return_value = [
        MagicMock(id="order-1", status=MagicMock(value="filled")),
        MagicMock(id="order-2", status=MagicMock(value="rejected")),
        MagicMock(id="order-unrelated", status=MagicMock(value="filled")),  # not in our batch
    ]

    broker = Broker(_cfg())
    statuses = broker.get_order_statuses({"order-1", "order-2"})

    assert statuses == {"order-1": "filled", "order-2": "rejected"}
    mock_client.get_orders.assert_called_once()  # one list call, not one per id


@patch("broker.TradingClient")
def test_wait_for_orders_returns_immediately_once_all_terminal(mock_client_cls):
    mock_client = mock_client_cls.return_value
    mock_client.get_orders.return_value = [
        MagicMock(id="order-1", status=MagicMock(value="filled")),
        MagicMock(id="order-2", status=MagicMock(value="rejected")),
    ]

    broker = Broker(_cfg())
    statuses = broker.wait_for_orders(["order-1", "order-2"], timeout=5.0, poll_interval=0.01)

    assert statuses == {"order-1": "filled", "order-2": "rejected"}
    mock_client.get_orders.assert_called_once()  # resolved on the first tick -- no polling needed


@patch("broker.TradingClient")
def test_wait_for_orders_polls_whole_batch_until_all_terminal(mock_client_cls):
    mock_client = mock_client_cls.return_value
    mock_client.get_orders.side_effect = [
        [MagicMock(id="order-1", status=MagicMock(value="filled")), MagicMock(id="order-2", status=MagicMock(value="pending_new"))],
        [MagicMock(id="order-1", status=MagicMock(value="filled")), MagicMock(id="order-2", status=MagicMock(value="pending_new"))],
        [MagicMock(id="order-1", status=MagicMock(value="filled")), MagicMock(id="order-2", status=MagicMock(value="filled"))],
    ]

    broker = Broker(_cfg())
    statuses = broker.wait_for_orders(["order-1", "order-2"], timeout=5.0, poll_interval=0.01)

    assert statuses == {"order-1": "filled", "order-2": "filled"}
    assert mock_client.get_orders.call_count == 3


@patch("broker.TradingClient")
def test_wait_for_orders_gives_up_at_timeout_and_returns_last_known_statuses(mock_client_cls):
    mock_client = mock_client_cls.return_value
    mock_client.get_orders.return_value = [MagicMock(id="order-1", status=MagicMock(value="partially_filled"))]

    broker = Broker(_cfg())
    statuses = broker.wait_for_orders(["order-1"], timeout=0.0, poll_interval=0.01)

    assert statuses == {"order-1": "partially_filled"}


@patch("broker.TradingClient")
def test_close_position_uses_100_percent_and_returns_order_id(mock_client_cls):
    mock_client = mock_client_cls.return_value
    mock_client.close_position.return_value = MagicMock(id="close-order-1")

    broker = Broker(_cfg())
    order_id = broker.close_position("TSLA")

    assert order_id == "close-order-1"
    mock_client.close_position.assert_called_once()
    args, kwargs = mock_client.close_position.call_args
    assert args[0] == "TSLA"
    assert kwargs["close_options"].percentage == "100"
