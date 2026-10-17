"""Loads target portfolio weights from either a .json or .csv/.tsv file.

.json: either a flat {"TICKER": weight} object (weight as a 0-1 fraction), or
{"TICKER": {"weight": weight, ...}} -- any other keys (e.g. a leftover
"rating" or "picked" field from an earlier export) are ignored.

.csv/.tsv: the same Company/Symbol/Picked/Closed/Return/Sector/Rating/Holding %
columns as the Alpha Picks portfolio page (e.g. an exported spreadsheet) --
only Symbol and Holding % are read. Rows with no Symbol (paywalled positions
on the free tier) are skipped rather than guessed at. Holding % cells may be
"3.74%" or a bare "3.74" -- either way they're read as a percentage and
converted to the 0.0374 fraction.

A ticker that appears twice (Alpha Picks re-picks names it still likes) gets
its Holding % summed across rows -- you only hold one position per ticker,
so the weights must add up to match.
"""

import csv
import json
import os
import sys


def _parse_percent(value: str) -> float:
    cleaned = value.strip().rstrip("%").replace(",", "")
    return float(cleaned) / 100.0


def _load_json(path: str) -> dict[str, float]:
    with open(path) as f:
        raw = json.load(f)

    if not isinstance(raw, dict) or not raw:
        raise SystemExit(f'{path} must contain a non-empty JSON object of {{"TICKER": weight}}')

    weights: dict[str, float] = {}
    for ticker, value in raw.items():
        weight = value.get("weight") if isinstance(value, dict) else value
        if not isinstance(weight, (int, float)):
            raise SystemExit(f"Weight for {ticker!r} must be a number, got {weight!r}")
        weights[ticker.upper()] = float(weight)

    return weights


def _load_csv(path: str) -> dict[str, float]:
    with open(path, newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        except csv.Error:
            dialect = csv.excel  # plain comma-separated fallback

        reader = csv.DictReader(f, dialect=dialect)
        if not reader.fieldnames:
            raise SystemExit(f"{path} has no header row")

        header_lookup = {name.strip(): name for name in reader.fieldnames}
        symbol_col = header_lookup.get("Symbol")
        holding_col = header_lookup.get("Holding %") or header_lookup.get("Holding%")
        if symbol_col is None or holding_col is None:
            raise SystemExit(f"{path} must have 'Symbol' and 'Holding %' columns (found: {list(header_lookup)})")

        weights: dict[str, float] = {}
        for row in reader:
            ticker = (row.get(symbol_col) or "").strip().upper()
            holding_raw = (row.get(holding_col) or "").strip()
            if not ticker or not holding_raw:
                continue  # paywalled/incomplete row
            weights[ticker] = weights.get(ticker, 0.0) + _parse_percent(holding_raw)

    return weights


def load_portfolio_file(path: str) -> dict[str, float]:
    if not os.path.exists(path):
        raise SystemExit(
            f"{path} not found -- copy portfolio.example.json to {path} "
            "(or point --file at your own .json/.csv) and fill in your weights"
        )

    lower = path.lower()
    if lower.endswith(".json"):
        weights = _load_json(path)
    elif lower.endswith((".csv", ".tsv")):
        weights = _load_csv(path)
    else:
        raise SystemExit(f"Unsupported file type for {path} -- use .json or .csv")

    total = sum(weights.values())
    if total > 1.5:
        print(
            f"Warning: weights sum to {total:.2f}, well over 1.0 -- did you mean fractions "
            f"(0.0374) instead of raw percentages (3.74)?",
            file=sys.stderr,
        )
    elif total > 1.001:  # small tolerance for float-sum noise on an intentional 1.0
        print(
            f"Warning: weights sum to {total:.1%}, over 100% -- the cash buffer will "
            f"silently scale every buy down to fit rather than spend more than you have, "
            f"so you won't land on the weights as typed.",
            file=sys.stderr,
        )

    return weights
