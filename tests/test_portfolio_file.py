from pathlib import Path

import pytest

from portfolio_file import load_portfolio_file

FIXTURES = Path(__file__).parent / "fixtures"


def test_loads_json_portfolio():
    weights = load_portfolio_file(str(FIXTURES / "portfolio.json"))
    assert weights == {"AAPL": 0.5, "MSFT": 0.3, "GOOG": 0.2}


def test_json_rejects_non_numeric_weight(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text('{"AAPL": "half"}')
    with pytest.raises(SystemExit):
        load_portfolio_file(str(bad_file))


def test_json_rejects_empty_object(tmp_path):
    empty_file = tmp_path / "empty.json"
    empty_file.write_text("{}")
    with pytest.raises(SystemExit):
        load_portfolio_file(str(empty_file))


def test_loads_real_alpha_picks_csv_with_percent_signs():
    weights = load_portfolio_file(str(FIXTURES / "alpha_picks_portfolio.csv"))
    assert weights == {
        "MU": pytest.approx(0.0374),
        "CLS": pytest.approx(0.0383),
        "POWL": pytest.approx(0.0231),
        "STRL": pytest.approx(0.0166),
        "CRDO": pytest.approx(0.0061),
    }


def test_csv_skips_rows_with_no_symbol():
    weights = load_portfolio_file(str(FIXTURES / "alpha_picks_portfolio.csv"))
    # The fixture has 2 extra rows with blank Symbol (paywalled) -- must not appear.
    assert len(weights) == 5


def test_csv_accepts_bare_numbers_without_percent_sign():
    weights = load_portfolio_file(str(FIXTURES / "bare_numbers_portfolio.csv"))
    assert weights == {"AAPL": pytest.approx(0.05), "MSFT": pytest.approx(0.03)}


def test_csv_missing_required_columns_raises(tmp_path):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("Ticker,Weight\nAAPL,0.5\n")
    with pytest.raises(SystemExit):
        load_portfolio_file(str(bad_csv))


def test_tsv_extension_also_parsed_as_csv(tmp_path):
    tsv_file = tmp_path / "portfolio.tsv"
    tsv_file.write_text("Company\tSymbol\tPicked\tClosed\tReturn\tSector\tRating\tHolding %\n" "Apple\tAAPL\t1/1/2026\t-\t1%\tTech\tStrong Buy\t10%\n")
    weights = load_portfolio_file(str(tsv_file))
    assert weights == {"AAPL": pytest.approx(0.10)}


def test_unsupported_extension_raises(tmp_path):
    txt_file = tmp_path / "portfolio.txt"
    txt_file.write_text("whatever")
    with pytest.raises(SystemExit):
        load_portfolio_file(str(txt_file))


def test_missing_file_raises_a_friendly_error_instead_of_a_traceback(tmp_path):
    missing = tmp_path / "portfolio.json"
    with pytest.raises(SystemExit, match="portfolio.example.json"):
        load_portfolio_file(str(missing))


def test_csv_sums_duplicate_tickers_picked_twice(tmp_path):
    csv_file = tmp_path / "dupes.csv"
    csv_file.write_text(
        "Company,Symbol,Picked,Closed,Return,Sector,Rating,Holding %\n"
        "Credo,CRDO,5/1/2026,-,10%,Information Technology,Strong Buy,0.62%\n"
        "Credo,CRDO,2/3/2025,-,187%,Information Technology,Strong Buy,3.40%\n"
    )
    weights = load_portfolio_file(str(csv_file))
    # CRDO appears as two separate picks -- must be summed, not overwritten.
    assert weights == {"CRDO": pytest.approx(0.0402)}


def test_json_ignores_extra_fields_like_rating_or_picked():
    # portfolio.json may carry leftover "rating"/"picked" metadata from an earlier
    # export -- only "weight" is read, nothing else is required or validated.
    weights = load_portfolio_file(str(FIXTURES / "rated_portfolio.json"))
    assert weights == {"AAPL": 0.5, "MSFT": 0.2, "GOOG": 0.3}


def test_warns_when_weights_sum_well_over_one(tmp_path, capsys):
    percent_file = tmp_path / "percents.json"
    percent_file.write_text('{"AAPL": 50, "MSFT": 50}')  # forgot to divide by 100
    load_portfolio_file(str(percent_file))
    captured = capsys.readouterr()
    assert "did you mean fractions" in captured.err
