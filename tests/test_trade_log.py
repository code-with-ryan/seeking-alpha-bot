import json

from trade_log import log_trade


def test_log_trade_appends_json_line(tmp_path):
    path = str(tmp_path / "trades.jsonl")
    log_trade(path, "AAPL", "buy", 500.0, "order-1", "sync")
    log_trade(path, "MSFT", "sell", 200.0, "order-2", "sync")

    with open(path) as f:
        lines = [json.loads(line) for line in f]

    assert len(lines) == 2
    assert lines[0]["ticker"] == "AAPL"
    assert lines[0]["side"] == "buy"
    assert lines[0]["notional"] == 500.0
    assert lines[0]["alpaca_order_id"] == "order-1"
    assert lines[1]["ticker"] == "MSFT"


def test_log_trade_creates_file_if_missing(tmp_path):
    path = str(tmp_path / "new_trades.jsonl")
    log_trade(path, "AAPL", "buy", 100.0, "order-1", "sync")
    with open(path) as f:
        assert len(f.readlines()) == 1
