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

Execution happens in two phases, sells then buys -- not just submitted in
that order, but sells are fully confirmed filled before any buy is sized or
submitted, so buy sizing reacts to real post-sell cash instead of an
upfront estimate of what the sells would produce.

Buys are then submitted one at a time, checking real available cash fresh
before each one (`broker.get_cash()`, not a number computed once at the
start of the sync) -- a buy goes through at its full target size if the
cash is there, gets sized down to whatever's actually available if it
isn't (reported as `"buying as much as fits"`), and only gets skipped
outright if even that reduced amount would fall under Alpaca's notional
minimum. There's no cash-buffer heuristic estimating this in advance --
this isn't a latency-sensitive system, so it just checks reality before
every single order instead of guessing once upfront.

Submitting an order only means Alpaca *accepted* it -- it doesn't mean the
order filled. After each phase, `sync` makes one API call per poll tick
(not one per order) to check every order in that phase's real status at
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

## Over-allocated targets and the $1 minimum

A target file whose weights sum to over 100% (a typo, or a deliberate test)
doesn't error out -- the live per-buy cash check (described above) just
means you'd end up buying less of each position than the numbers literally
say, since there's only ever as much real cash as there actually is.
`load_portfolio_file` warns on stderr whenever weights sum to over 100%,
specifically so that doesn't happen silently.

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
