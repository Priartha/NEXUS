from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis.backtest import BacktestEngine
from scripts.optimize_backtest_settings import load_candles


def main() -> None:
    symbol = "BTCUSD"
    timeframe = "15m"
    candles = load_candles(symbol, timeframe, 500)
    configs = [
        {"name": "current_guard", "max_hold_bars": 6, "trailing_stop": True, "breakeven_threshold": 1.0, "signal_side_mode": "normal", "avoid_reason_tokens": [], "tp_atr_multiplier": 0.0, "sl_atr_multiplier": 0.0},
        {"name": "longer_no_trail", "max_hold_bars": 50, "trailing_stop": False, "breakeven_threshold": 1.0, "signal_side_mode": "normal", "avoid_reason_tokens": [], "tp_atr_multiplier": 4.0, "sl_atr_multiplier": 0.0},
        {"name": "avoid_cvd_rising", "max_hold_bars": 12, "trailing_stop": False, "breakeven_threshold": 1.0, "signal_side_mode": "normal", "avoid_reason_tokens": ["CVD rising"], "tp_atr_multiplier": 0.0, "sl_atr_multiplier": 0.0},
        {"name": "invert_hold12", "max_hold_bars": 12, "trailing_stop": False, "breakeven_threshold": 1.0, "signal_side_mode": "invert", "avoid_reason_tokens": [], "tp_atr_multiplier": 0.0, "sl_atr_multiplier": 0.0},
        {"name": "invert_hold50", "max_hold_bars": 50, "trailing_stop": False, "breakeven_threshold": 1.0, "signal_side_mode": "invert", "avoid_reason_tokens": [], "tp_atr_multiplier": 4.0, "sl_atr_multiplier": 0.0},
        {"name": "invert_avoid_cvd", "max_hold_bars": 12, "trailing_stop": False, "breakeven_threshold": 1.0, "signal_side_mode": "invert", "avoid_reason_tokens": ["CVD falling"], "tp_atr_multiplier": 0.0, "sl_atr_multiplier": 0.0},
        {"name": "regime_aligned", "max_hold_bars": 12, "trailing_stop": False, "breakeven_threshold": 1.0, "signal_side_mode": "normal", "avoid_reason_tokens": ["CVD rising"], "tp_atr_multiplier": 0.0, "sl_atr_multiplier": 0.0, "require_regime_alignment": True},
    ]
    results = []
    print(f"Loaded {len(candles)} {symbol} {timeframe} candles", flush=True)
    for cfg in configs:
        started = time.time()
        engine = BacktestEngine(
            initial_balance=10_000.0,
            position_size_pct=0.02,
            max_hold_bars=cfg["max_hold_bars"],
            trailing_stop=cfg["trailing_stop"],
            breakeven_threshold=cfg["breakeven_threshold"],
            signal_side_mode=cfg["signal_side_mode"],
            avoid_reason_tokens=cfg["avoid_reason_tokens"],
            tp_atr_multiplier=cfg["tp_atr_multiplier"],
            sl_atr_multiplier=cfg["sl_atr_multiplier"],
            require_regime_alignment=cfg.get("require_regime_alignment", False),
            slippage_pct=0.0001,
            commission_pct=0.0002,
            funding_rate_per_8h=0.0001,
        )
        result = engine.run(candles, symbol=symbol, timeframe=timeframe)
        row = {
            **cfg,
            "seconds": round(time.time() - started, 1),
            "trades": result["total_trades"],
            "win_rate": result["win_rate"],
            "profit_factor": result["profit_factor"],
            "total_pnl_pct": result["total_pnl_pct"],
            "max_drawdown_pct": result["max_drawdown_pct"],
            "sharpe_ratio": result["sharpe_ratio"],
        }
        results.append(row)
        print(
            f"{row['name']}: trades={row['trades']} WR={row['win_rate']*100:.1f}% "
            f"PF={row['profit_factor']:.2f} PnL={row['total_pnl_pct']:.2f}% "
            f"DD={row['max_drawdown_pct']:.2f}% sec={row['seconds']}",
            flush=True,
        )
    out = ROOT / "data" / "strategy_config_probe.json"
    out.write_text(json.dumps({"timestamp": int(time.time() * 1000), "results": results}, indent=2), encoding="utf-8")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
