import time
import unittest

from backend.analysis.institutional import _trend_score
from backend.ingestion.delta_ws import parse_quote_message, parse_trade_message


class MarketGuardsTest(unittest.TestCase):
    def test_trade_parser_rejects_non_positive_price(self) -> None:
        message = {"type": "trades", "sy": "BTCUSD", "p": "0", "s": "1", "t": int(time.time() * 1000)}
        self.assertIsNone(parse_trade_message(message, "BTCUSD"))

    def test_trade_parser_rejects_far_future_timestamp(self) -> None:
        message = {"type": "trades", "sy": "BTCUSD", "p": "100", "s": "1", "t": int(time.time() * 1000) + 90_000_000}
        self.assertIsNone(parse_trade_message(message, "BTCUSD"))

    def test_trend_score_avoids_vwap_saturation_at_one_percent(self) -> None:
        score = _trend_score(
            close=100.0,
            atr=2.0,
            ema20=101.0,
            ema50=100.0,
            rsi14=55.0,
            vwap_distance_pct=0.01,
            premium_discount=0.1,
        )
        self.assertLess(score, 0.8)

    def test_quote_parser_accepts_ticker_messages(self) -> None:
        message = {
            "type": "ticker",
            "sy": "BTCUSD",
            "ts": int(time.time() * 1000),
            "sp": "79673",
            "m": "79624.14897571",
            "close": "79625.0",
        }
        quote = parse_quote_message(message, "BTCUSD")
        self.assertIsNotNone(quote)
        self.assertEqual(quote.source, "ticker")
        self.assertEqual(quote.symbol, "BTCUSD")
        self.assertEqual(quote.last_trade, 79625.0)

    def test_quote_parser_accepts_orderbook_messages(self) -> None:
        message = {
            "type": "ob_l1",
            "sy": "BTCUSD",
            "ts": int(time.time() * 1000),
            "bp": "79674.5",
            "ap": "79675.5",
        }
        quote = parse_quote_message(message, "BTCUSD")
        self.assertIsNotNone(quote)
        self.assertEqual(quote.source, "ob_l1")
        self.assertEqual(quote.mid, 79675.0)


if __name__ == "__main__":
    unittest.main()
