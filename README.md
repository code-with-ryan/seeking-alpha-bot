# seeking-alpha-bot

A plain CLI that rebalances your Alpaca account to match a target portfolio —
built around Seeking Alpha's Alpha Picks model portfolio, but the target can
be anything. No daemon, no bot, no background process: you run it when you
have the list in hand.

```
.venv/bin/python main.py sync --file portfolio.json
.venv/bin/python main.py sync --file portfolio.csv
```

It prints the buy/sell orders needed to converge your actual Alpaca
positions to the target, asks `Submit these orders to Alpaca? [y/N]`, and
only trades on yes. Add `--yes` to skip the prompt (e.g. if you're having me
run it for you in a session where you've already reviewed the output).

Execution order: every sell (including full closes) is submitted before any
buy, so buys aren't racing uncleared sell proceeds for buying power.

Submitting an order only means Alpaca *accepted* it -- it doesn't mean the
order filled. Once the whole batch is submitted, `sync` makes one API call
per poll tick (not one per order) to check every order's real status at
once -- confirming fills on 30 tickers takes the same ~10s as confirming
one. It then prints `SUCCESS`, `PARTIAL FILL`, or `FAILED (<status>)` per
ticker; only actually-filled orders get written to `trades.jsonl` (a partial
fill is reported but not logged -- check Alpaca for the amount that
actually went through), so the log can't claim a trade happened when it
didn't.

## Target file formats

- **`.json`** — either flat `{"TICKER": weight}`, weight as a 0-1 fraction
  (e.g. `{"MU": 0.0374, "CLS": 0.0383}`), or `{"TICKER": {"weight": 0.0374,
  ...}}` -- any other keys (e.g. a leftover `"rating"` or `"picked"` field)
  are ignored.
- **`.csv` / `.tsv`** — same `Company, Symbol, Picked, Closed, Return,
  Sector, Rating, Holding %` columns as the Alpha Picks portfolio page (e.g.
  an exported spreadsheet). Only `Symbol` and `Holding %` are read; rows
  with no Symbol (paywalled positions on the free tier) are skipped rather
  than guessed at. `Holding %` cells can be `"3.74%"` or a bare `3.74` —
  both mean 3.74%. A ticker that appears twice (Alpha Picks re-picks names
  it still likes) has its `Holding %` summed across rows, since you only
  hold one position per ticker.

This deliberately mirrors the full Alpha Picks list as-given, weighted
exactly as Seeking Alpha weights it — no rating or pick-date filtering. The
whole point of paying for the picks is to follow their methodology, not
second-guess it with an unvalidated overlay.

## Setup

1. `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`
2. Copy `.env.example` to `.env`, fill in Alpaca paper-trading keys (from
   alpaca.markets — no funding needed to start).
3. Copy `portfolio.example.json` to `portfolio.json` and fill in your actual
   target weights -- it's gitignored since it holds your real holdings data,
   so this step is required on every fresh clone, not just the first setup.
4. `.venv/bin/python -m pytest tests/` — 55 tests should pass.

Every executed trade is appended to `trades.jsonl` (ticker, side, notional,
Alpaca order id, reason, timestamp) as a durable audit log — `cat
trades.jsonl` to read it, no tooling needed.

## Cash buffer

New buy orders (combined) are scaled down so they never spend more than
`CASH_BUFFER_PCT` (default 0.95) of actually-available cash — a cushion
against price drift between computing an order and it filling, e.g. a full
first-time sync trying to deploy ~100% of cash across several sequential
buys. Only buys are ever scaled, and only when their total would otherwise
exceed the limit — sells (including full closes) always execute exactly as
computed, and "available cash" counts this batch's sell proceeds too (a sell
funding a buy in the same sync isn't treated as if that cash doesn't exist).
In the common case — a small drift correction well under your cash on hand —
nothing is scaled at all, so you land exactly on the pasted target.

Separately, Alpaca rejects notional *buy* orders under $1 outright (sells
aren't restricted the same way) — `sync` drops any buy order under that
floor before submitting, since it's immaterial rebalance drift that'll get
picked up on some later sync once it grows past $1, rather than letting
Alpaca reject it and printing a `FAILED` line for something that was never
worth trading.

## Going live

Defaults to Alpaca paper trading. Switching to real money is a deliberate
one-line `.env` change: `ALPACA_BASE_URL=https://api.alpaca.markets`, plus
swapping in live (not paper) API keys.
