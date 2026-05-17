"""
Local NEXUS BTC scalping optimizer.

Uses the workspace SQLite candle archive instead of live exchange calls so the
result is reproducible when network access is unavailable. The tested strategy
is intentionally strict: trend alignment, VWAP, ATR expansion, volume impulse,
and RSI confirmation must agree before a trade is opened.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "nexus.db"
OUT_PATH = ROOT / "data" / "local_scalp_optimization.json"


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    direction_mode: str
    min_score: float
    min_trend_strength: float
    min_volume_z: float
    max_vwap_dev_pct: float
    atr_stop_mult: float
    reward_mult: float
    max_hold_bars: int
    require_killzone: bool
    pullback_bars: int


def load_candles(db_path: Path, symbol: str, timeframe: str) -> list[Candle]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT timestamp, open, high, low, close, volume
            FROM candle_archive
            WHERE symbol = ? AND timeframe = ?
            ORDER BY timestamp
            """,
            (symbol, timeframe),
        ).fetchall()
    return [
        Candle(
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
        for row in rows
    ]


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append((value - out[-1]) * k + out[-1])
    return out


def rolling_atr(candles: list[Candle], period: int = 14) -> list[float]:
    tr = [0.0]
    for prev, cur in zip(candles, candles[1:]):
        tr.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    out: list[float] = []
    for idx in range(len(tr)):
        start = max(0, idx - period + 1)
        window = tr[start : idx + 1]
        out.append(sum(window) / len(window))
    return out


def rolling_rsi(closes: list[float], period: int = 14) -> list[float]:
    out = [50.0] * len(closes)
    gains = [0.0]
    losses = [0.0]
    for prev, cur in zip(closes, closes[1:]):
        delta = cur - prev
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    for idx in range(period, len(closes)):
        gain = sum(gains[idx - period + 1 : idx + 1]) / period
        loss = sum(losses[idx - period + 1 : idx + 1]) / period
        rs = gain / loss if loss > 0 else 100.0
        out[idx] = 100.0 - (100.0 / (1.0 + rs))
    return out


def rolling_vwap(candles: list[Candle], period: int = 96) -> list[float]:
    out: list[float] = []
    for idx in range(len(candles)):
        window = candles[max(0, idx - period + 1) : idx + 1]
        pv = sum(((c.high + c.low + c.close) / 3.0) * c.volume for c in window)
        vol = sum(c.volume for c in window)
        out.append(pv / vol if vol > 0 else candles[idx].close)
    return out


def volume_zscores(candles: list[Candle], period: int = 48) -> list[float]:
    volumes = [c.volume for c in candles]
    out = [0.0] * len(candles)
    for idx in range(period, len(candles)):
        window = volumes[idx - period : idx]
        avg = sum(window) / len(window)
        variance = sum((value - avg) ** 2 for value in window) / len(window)
        std = math.sqrt(variance)
        out[idx] = (volumes[idx] - avg) / std if std > 0 else 0.0
    return out


def is_killzone(ts_ms: int) -> bool:
    hour = (ts_ms // 3_600_000) % 24
    minute = (ts_ms // 60_000) % 60
    t = hour + minute / 60.0
    return (2.0 <= t < 5.0) or (8.5 <= t < 11.0) or (13.5 <= t < 16.0)


def indicators(candles: list[Candle]) -> dict[str, list[float]]:
    closes = [c.close for c in candles]
    return {
        "ema9": ema(closes, 9),
        "ema21": ema(closes, 21),
        "ema50": ema(closes, 50),
        "ema100": ema(closes, 100),
        "atr": rolling_atr(candles),
        "rsi": rolling_rsi(closes),
        "vwap": rolling_vwap(candles),
        "vol_z": volume_zscores(candles),
    }


def signal_at(candles: list[Candle], ind: dict[str, list[float]], idx: int, cfg: StrategyConfig) -> tuple[str, float] | None:
    if idx < 120:
        return None
    if cfg.require_killzone and not is_killzone(candles[idx].timestamp):
        return None

    close = candles[idx].close
    atr = ind["atr"][idx]
    if atr <= 0:
        return None

    ema9 = ind["ema9"][idx]
    ema21 = ind["ema21"][idx]
    ema50 = ind["ema50"][idx]
    ema100 = ind["ema100"][idx]
    rsi = ind["rsi"][idx]
    vwap = ind["vwap"][idx]
    vol_z = ind["vol_z"][idx]
    vwap_dev = abs(close - vwap) / vwap if vwap > 0 else 0.0
    trend_strength = abs(ema21 - ema100) / close
    recent = candles[max(0, idx - cfg.pullback_bars) : idx + 1]

    score = 0.0
    if ema9 > ema21 > ema50 > ema100:
        score += 0.25
    if close > vwap and close > ema21:
        score += 0.18
    if trend_strength >= cfg.min_trend_strength:
        score += 0.16
    if vol_z >= cfg.min_volume_z:
        score += 0.16
    if 48 <= rsi <= 68:
        score += 0.12
    if min(c.low for c in recent) <= ema21 * 1.002:
        score += 0.08
    if vwap_dev <= cfg.max_vwap_dev_pct:
        score += 0.05
    if cfg.direction_mode in {"long", "both"} and score >= cfg.min_score:
        return "long", score

    score = 0.0
    if ema9 < ema21 < ema50 < ema100:
        score += 0.25
    if close < vwap and close < ema21:
        score += 0.18
    if trend_strength >= cfg.min_trend_strength:
        score += 0.16
    if vol_z >= cfg.min_volume_z:
        score += 0.16
    if 32 <= rsi <= 52:
        score += 0.12
    if max(c.high for c in recent) >= ema21 * 0.998:
        score += 0.08
    if vwap_dev <= cfg.max_vwap_dev_pct:
        score += 0.05
    if cfg.direction_mode in {"short", "both"} and score >= cfg.min_score:
        return "short", score
    return None


def run_backtest(candles: list[Candle], ind: dict[str, list[float]], cfg: StrategyConfig, start: int, end: int) -> dict[str, float | int]:
    balance = 10_000.0
    risk_pct = 0.01
    fee_pct = 0.0006
    trades: list[float] = []
    peak = balance
    max_dd = 0.0
    idx = max(start, 120)
    while idx < end - 2:
        sig = signal_at(candles, ind, idx, cfg)
        if not sig:
            idx += 1
            continue
        side, _score = sig
        entry_bar = candles[idx + 1]
        entry = entry_bar.open
        atr = ind["atr"][idx]
        stop_distance = atr * cfg.atr_stop_mult
        if stop_distance <= 0:
            idx += 1
            continue
        stop = entry - stop_distance if side == "long" else entry + stop_distance
        target = entry + stop_distance * cfg.reward_mult if side == "long" else entry - stop_distance * cfg.reward_mult
        risk_cash = balance * risk_pct
        qty = risk_cash / stop_distance
        pnl = None
        exit_idx = min(end - 1, idx + cfg.max_hold_bars)
        for j in range(idx + 1, exit_idx + 1):
            bar = candles[j]
            if side == "long":
                if bar.low <= stop:
                    pnl = -risk_cash
                    exit_idx = j
                    break
                if bar.high >= target:
                    pnl = risk_cash * cfg.reward_mult
                    exit_idx = j
                    break
            else:
                if bar.high >= stop:
                    pnl = -risk_cash
                    exit_idx = j
                    break
                if bar.low <= target:
                    pnl = risk_cash * cfg.reward_mult
                    exit_idx = j
                    break
        if pnl is None:
            exit_price = candles[exit_idx].close
            raw = (exit_price - entry) * qty if side == "long" else (entry - exit_price) * qty
            pnl = max(-risk_cash, min(risk_cash * cfg.reward_mult, raw))
        pnl -= entry * qty * fee_pct
        balance += pnl
        trades.append(pnl)
        peak = max(peak, balance)
        max_dd = max(max_dd, (peak - balance) / peak if peak > 0 else 0.0)
        idx = exit_idx + 1

    wins = [p for p in trades if p > 0]
    losses = [p for p in trades if p <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win > 0 else 0.0)
    pnl_pct = (balance - 10_000.0) / 10_000.0 * 100.0
    win_rate = len(wins) / len(trades) * 100.0 if trades else 0.0
    return {
        "trades": len(trades),
        "pnl_pct": round(pnl_pct, 4),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(pf, 4),
        "max_drawdown_pct": round(max_dd * 100.0, 4),
    }


def score_result(train: dict[str, float | int], validation: dict[str, float | int]) -> float:
    trades = int(validation["trades"])
    if trades < 3:
        return -999.0 + trades
    return (
        float(validation["pnl_pct"])
        + float(validation["profit_factor"]) * 4.0
        - float(validation["max_drawdown_pct"]) * 1.2
        + min(trades, 30) * 0.08
        + min(float(train["profit_factor"]), 3.0)
    )


def config_grid() -> list[StrategyConfig]:
    configs: list[StrategyConfig] = []
    for values in itertools.product(
        ["long", "both"],
        [0.70, 0.78],
        [0.0015, 0.0025],
        [0.4, 0.8],
        [0.007, 0.010],
        [0.9, 1.1],
        [1.2, 1.5],
        [6, 10],
        [False, True],
        [5],
    ):
        cfg = StrategyConfig(
            name="",
            direction_mode=values[0],
            min_score=values[1],
            min_trend_strength=values[2],
            min_volume_z=values[3],
            max_vwap_dev_pct=values[4],
            atr_stop_mult=values[5],
            reward_mult=values[6],
            max_hold_bars=values[7],
            require_killzone=values[8],
            pullback_bars=values[9],
        )
        configs.append(cfg.__class__(**{**asdict(cfg), "name": config_name(cfg)}))
    return configs


def config_name(cfg: StrategyConfig) -> str:
    kz = "kz" if cfg.require_killzone else "all"
    return (
        f"{cfg.direction_mode}_s{cfg.min_score:.2f}_tr{cfg.min_trend_strength:.4f}_"
        f"vz{cfg.min_volume_z:.1f}_vw{cfg.max_vwap_dev_pct:.3f}_"
        f"sl{cfg.atr_stop_mult:.1f}_rr{cfg.reward_mult:.1f}_h{cfg.max_hold_bars}_{kz}_pb{cfg.pullback_bars}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    candles = load_candles(args.db, args.symbol, args.timeframe)
    if len(candles) < 300:
        raise SystemExit(f"Not enough candles in {args.db}: found {len(candles)}")

    ind = indicators(candles)
    split = int(len(candles) * 0.7)
    results = []
    for cfg in config_grid():
        train = run_backtest(candles, ind, cfg, 0, split)
        validation = run_backtest(candles, ind, cfg, split, len(candles))
        results.append({
            "score": round(score_result(train, validation), 4),
            "config": asdict(cfg),
            "train": train,
            "validation": validation,
        })

    results.sort(key=lambda item: item["score"], reverse=True)
    payload = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "candles": len(candles),
        "train_candles": split,
        "validation_candles": len(candles) - split,
        "top": results[:25],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"candles={len(candles)} train={split} validation={len(candles) - split}")
    for rank, item in enumerate(results[:10], 1):
        cfg = item["config"]
        val = item["validation"]
        print(
            f"{rank:02d} score={item['score']:.2f} {cfg['name']} "
            f"val_pnl={val['pnl_pct']}% wr={val['win_rate']}% "
            f"pf={val['profit_factor']} dd={val['max_drawdown_pct']}% trades={val['trades']}"
        )
    print(f"saved={args.out}")


if __name__ == "__main__":
    main()
