from backend.ingestion.binance import _binance_symbol, _symbols_equal, parse_quote_message, parse_trade_message


def test_binance_symbol_mapping() -> None:
    assert _binance_symbol("BTCUSD") == "BTCUSDT"
    assert _binance_symbol("ethusd") == "ETHUSDT"
    assert _binance_symbol("BTCUSDT") == "BTCUSDT"
    assert _symbols_equal("BTCUSDT", "BTCUSD")
    assert _symbols_equal("BTCUSDT", "BTCUSDT")
    assert not _symbols_equal("ETHUSDT", "BTCUSD")


def test_parse_trade_message() -> None:
    payload = {
        "e": "trade",
        "s": "BTCUSDT",
        "p": "30000.0",
        "q": "0.25",
        "T": 1700000000000,
    }
    tick = parse_trade_message(payload, "BTCUSD")
    assert tick is not None
    assert tick.price == 30000.0
    assert tick.qty == 0.25
    assert tick.timestamp_ms == 1700000000000


def test_parse_quote_message() -> None:
    payload = {
        "e": "bookTicker",
        "s": "BTCUSDT",
        "b": "29990.0",
        "a": "30010.0",
        "E": 1700000000000,
    }
    quote = parse_quote_message(payload, "BTCUSD")
    assert quote is not None
    assert quote.bid == 29990.0
    assert quote.ask == 30010.0
    assert quote.mid == 30000.0
    assert quote.source == "bookTicker"
    assert quote.symbol == "BTCUSD"
