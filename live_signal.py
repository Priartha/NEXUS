from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, ".")

from backend.analysis.ai_ict import AiIctService
from backend.analysis.options import build_options_context
from backend.analysis.pipeline import AnalysisPipeline
from backend.engine.candle_store import CandleStore
from backend.ingestion.binance import fetch_historical_candles
from backend.ingestion.delta_rest import fetch_option_tickers
from backend.models.types import SentimentSnapshot, to_wire


async def main():
    print("=" * 65)
    print("  ICT TERMINAL — LIVE BTC ANALYSIS WITH PATTERN RECOGNITION")
    print("=" * 65)

    print("\n[1/5] Fetching BTCUSDT 5m candles from Binance...")
    candles = await fetch_historical_candles(
        base_url="https://api.binance.com",
        symbol="BTCUSDT",
        timeframe="5m",
        limit=200,
    )
    print(f"  Loaded {len(candles)} candles")

    store = CandleStore("BTCUSDT", "5m", max_candles=500)
    store.seed(candles, now_ms=int(time.time() * 1000))

    pipeline = AnalysisPipeline()
    snapshot = pipeline.snapshot(store)
    payload = dict(snapshot)
    candle = payload.get("candle") or {}
    metrics = payload.get("metrics") or {}
    regime = payload.get("regime") or {}
    projection = payload.get("projection") or {}
    signals = payload.get("signals") or []
    btc_patterns = payload.get("btc_patterns") or {}

    price = candle.get("close", 0)
    print(f"\n  Current BTC Price: ${price:,.2f}")

    print(f"\n{'='*65}")
    print(f"  SECTION 1: MARKET METRICS")
    print(f"{'='*65}")
    for k in ("atr14","ema20","ema50","rsi14","vwap","vwap_distance_pct","volume_zscore","displacement_ratio","premium_discount","institutional_bias","bias_score","expected_move","expected_move_pct","volatility_score","trend_score"):
        print(f"  {k}: {metrics.get(k, 'N/A')}")

    print(f"\n{'='*65}")
    print(f"  SECTION 2: MARKET REGIME")
    print(f"{'='*65}")
    for k in ("phase","confidence","bias","range_high","range_low","range_mid","width_pct","volume_state","reason"):
        print(f"  {k}: {regime.get(k, 'N/A')}")

    print(f"\n{'='*65}")
    print(f"  SECTION 3: PRICE PROJECTION")
    print(f"{'='*65}")
    for k in ("direction","probability","expected_high","expected_low","expected_move","invalidation","score","reason"):
        print(f"  {k}: {projection.get(k, 'N/A')}")

    print(f"\n{'='*65}")
    print(f"  SECTION 4: BTC MOVEMENT BEHAVIOR PATTERNS")
    print(f"{'='*65}")
    if btc_patterns:
        print(f"  Session:          {btc_patterns.get('session','?')}")
        print(f"  Killzone:         {btc_patterns.get('killzone','none')}")
        print(f"  Halving Phase:    {btc_patterns.get('halving_phase','?')}")
        print(f"  Volatility:       {btc_patterns.get('volatility_regime','?')}")
        print(f"  Is Weekend:       {btc_patterns.get('is_weekend','?')}")
        print(f"  Pattern Signal:   {btc_patterns.get('pattern_signal','neutral')}")
        print(f"  Bullish Score:    {btc_patterns.get('bullish_pattern_score',0):.3f}")
        print(f"  Bearish Score:    {btc_patterns.get('bearish_pattern_score',0):.3f}")
        print(f"  Fractal Clusters: {btc_patterns.get('fractal_clusters',[])}")

        patterns = btc_patterns.get("patterns", [])
        if patterns:
            print(f"\n  --- Active BTC Movement Patterns ({len(patterns)}) ---")
            for p in sorted(patterns, key=lambda x: x.get("score",0), reverse=True):
                print(f"  [{p.get('direction','?').upper():7s}] {p.get('name','?')}")
                print(f"         Score: {p.get('score',0):.3f} | Conf: {p.get('confidence',0):.0%}")
                print(f"         {p.get('description','')[:130]}")
        else:
            print(f"\n  No active BTC movement patterns")

        behaviors = btc_patterns.get("investor_behaviors", [])
        if behaviors:
            print(f"\n  --- Investor Behavior Patterns ({len(behaviors)}) ---")
            for b in sorted(behaviors, key=lambda x: x.get("confidence",0), reverse=True):
                print(f"  [{b.get('side','?').upper():7s}] {b.get('behavior_type','?')}")
                print(f"         Intensity: {b.get('intensity',0):.3f} | Conf: {b.get('confidence',0):.0%}")
                print(f"         {b.get('description','')[:130]}")
        else:
            print(f"\n  No active investor behavior patterns")
    else:
        print("  No BTC pattern data available")

    print(f"\n{'='*65}")
    print(f"  SECTION 5: OPTIONS DATA (Delta Exchange)")
    print(f"{'='*65}")
    try:
        option_tickers = await fetch_option_tickers("https://api.india.delta.exchange", "BTC")
        print(f"  Retrieved {len(option_tickers)} BTC option tickers")
        options_context = build_options_context(
            payload=payload,
            option_tickers=option_tickers,
            underlying="BTC",
            min_momentum_score=0.40,
            max_spread_pct=0.18,
            min_delta_abs=0.35,
            max_delta_abs=0.75,
            max_moneyness_pct=0.08,
        )
        payload["options_context"] = to_wire(options_context)
        opt = to_wire(options_context)
        print(f"  Momentum: {opt['momentum_score']:.3f} (bull {opt['bullish_momentum_score']:.3f} / bear {opt['bearish_momentum_score']:.3f})")
        print(f"  Threshold: {opt['minimum_momentum_score']:.3f} | State: {opt['momentum_state']}")
        cc = opt.get("call_candidate")
        pc = opt.get("put_candidate")
        if cc:
            print(f"  CALL: {cc.get('symbol','')} | delta:{cc.get('delta',0):.2f} | gamma:{cc.get('gamma',0):.6f} | mid:${cc.get('mid_price',0):.2f} | Score:{cc.get('score',0):.3f}")
        if pc:
            print(f"  PUT:  {pc.get('symbol','')} | delta:{pc.get('delta',0):.2f} | gamma:{pc.get('gamma',0):.6f} | mid:${pc.get('mid_price',0):.2f} | Score:{pc.get('score',0):.3f}")
        blockers = opt.get("blockers", [])
        if blockers:
            print(f"  Blockers: {blockers}")
    except Exception as e:
        print(f"  Options unavailable: {e}")
        payload["options_context"] = {}

    print(f"\n{'='*65}")
    print(f"  SECTION 6: AI ICT DECISION (DETERMINISTIC)")
    print(f"{'='*65}")
    sentiment = SentimentSnapshot(
        label="neutral", score=0.0, confidence=0.0,
        source_count=0, updated_at=int(time.time() * 1000),
    )
    service = AiIctService(provider="local")
    decision = service.local_review(payload, sentiment)
    d = to_wire(decision)

    print(f"  Direction:     {d['direction']}")
    print(f"  Grade:         {d['grade']}")
    print(f"  Readiness:     {d['readiness']}")
    print(f"  Confidence:    {d['confidence']:.3f}")
    print(f"  Setup Score:   {d['setup_score']:.3f}")
    print(f"  Entry:         ${d['entry']:,.2f}" if d.get("entry") else "  Entry:         N/A")
    print(f"  Stop Loss:     ${d['stop_loss']:,.2f}" if d.get("stop_loss") else "  Stop Loss:     N/A")
    print(f"  Take Profit:   ${d['take_profit']:,.2f}" if d.get("take_profit") else "  Take Profit:   N/A")
    print(f"  Risk/Reward:   {d['risk_reward']}" if d.get("risk_reward") else "  Risk/Reward:   N/A")
    print(f"  Invalid:       ${d['invalidation']:,.2f}" if d.get("invalidation") else "  Invalid:       N/A")
    print(f"  Momentum:      {d['momentum_score']:.3f}" if d.get("momentum_score") is not None else "  Momentum:      N/A")

    print(f"\n  Confirmations:")
    for c in d.get("confirmations", []):
        print(f"    [+] {c}")
    print(f"\n  Blockers:")
    for b in d.get("blockers", []):
        print(f"    [-] {b}")

    print(f"\n  Calculations:")
    for c in d.get("calculations", []):
        print(f"    - {c}")
    print(f"\n  Summary: {d['summary']}")

    oc = d.get("option_contract")
    if oc:
        print(f"\n  Selected Option: {oc.get('symbol','')}")
        print(f"    delta:{oc.get('delta',0):.2f} | gamma:{oc.get('gamma',0):.6f} | theta:{oc.get('theta',0):.4f} | vega:{oc.get('vega',0):.4f}")
        print(f"    Mid: ${oc.get('mid_price',0):.2f} | Spread: {oc.get('spread_pct',0)*100:.2f}% | Score: {oc.get('score',0):.3f}")

    print(f"\n{'='*65}")
    print(f"  FINAL OPTION BUYING SIGNAL")
    print(f"{'='*65}")
    if d["direction"] in ("bullish", "bearish") and d.get("entry"):
        side_label = "CALL" if d["direction"] == "bullish" else "PUT"
        print(f"  > ACTION: BUY {side_label} OPTION")
        print(f"  > Spot Entry: ${d['entry']:,.2f}")
        if oc:
            print(f"  > Contract: {oc.get('symbol','')} @ ${oc.get('mid_price',0):.2f}")
        print(f"  > Stop Loss: ${d['stop_loss']:,.2f}")
        print(f"  > Take Profit: ${d['take_profit']:,.2f}")
        print(f"  > Risk/Reward: {d['risk_reward']} | Confidence: {d['confidence']:.0%}")
        print(f"  > Grade: {d['grade']} ({d['readiness']})")
        conf = d.get("confidence", 0)
        print(f"  > Suggested Risk: {conf * 0.02:.2%} of portfolio")
    else:
        print(f"  > ACTION: NO TRADE")
        print(f"  > Reason: {d['summary']}")
        if btc_patterns:
            pat_signal = btc_patterns.get("pattern_signal", "neutral")
            print(f"  > BTC Pattern Signal: {pat_signal.upper()}")
            print(f"  > Pattern Scores: Bullish {btc_patterns.get('bullish_pattern_score',0):.3f} / Bearish {btc_patterns.get('bearish_pattern_score',0):.3f}")
            behaviors = btc_patterns.get("investor_behaviors", [])
            if behaviors:
                print(f"  > Investor Behaviors Active: {len(behaviors)}")
                for b in behaviors:
                    print(f"      {b.get('behavior_type','')} ({b.get('side','')}, {b.get('confidence',0):.0%} conf)")

    print(f"\n{'='*65}")
    print(f"  DISCLAIMER: {d['guarantee']}")
    print(f"{'='*65}")


if __name__ == "__main__":
    asyncio.run(main())
