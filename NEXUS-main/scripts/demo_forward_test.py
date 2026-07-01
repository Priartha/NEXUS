"""
Forward demo testing script for NEXUS optimized strategy.

This script:
1. Connects to Binance websocket for live BTCUSDT 5m candles
2. Generates signals using optimized logic
3. Tracks paper trades with improved exits
4. Logs all results to file for analysis

Run this script and let it run for 1-2 weeks to collect statistically significant data.
"""

import asyncio
import json
import sys
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets
import httpx

from backend.models.types import Candle
from backend.analysis.optimized_signals import detect_optimized_signals
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.swing_detector import detect_swings
from backend.analysis.improved_backtest import ImprovedBacktestEngine


# Configuration
SYMBOL = "BTCUSDT"
INTERVAL = "5m"
INITIAL_BALANCE = 10000.0
POSITION_SIZE_PCT = 0.02
MAX_CONCURRENT = 1
SLIPPAGE_PCT = 0.0002
COMMISSION_PCT = 0.0004
MAX_HOLD_BARS = 12  # Combo3: Quick exits
BREAKEVEN_THRESHOLD = 0.5  # Combo3: Move to BE at 0.5R
PARTIAL_TP1_R = 1.0
PARTIAL_TP2_R = 1.5  # Combo3: Lower TP2
STOP_LOSS_MULTIPLIER = 0.5  # Combo3: Tight stops
USE_ADX_FILTER = True
ADX_THRESHOLD = 20.0
USE_LIMIT_ORDERS = True
MIN_CONFIDENCE = 0.55
SIGNAL_COOLDOWN_CANDLES = 12  # 1 hour

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("demo_trading.log"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


class DemoTrader:
    """Forward demo trading engine."""

    def __init__(self):
        self.candles: list[Candle] = []
        self.open_trades: list[dict] = []
        self.closed_trades: list[dict] = []
        self.balance = INITIAL_BALANCE
        self.peak_balance = INITIAL_BALANCE
        self.last_signal_ts = 0
        self.signal_count = 0
        self.trade_count = 0
        
        # Stats
        self.total_pnl = 0.0
        self.winning_trades = 0
        self.losing_trades = 0
        
        # File paths
        self.data_dir = Path("demo_data")
        self.data_dir.mkdir(exist_ok=True)
        self.trades_file = self.data_dir / "trades.json"
        self.signals_file = self.data_dir / "signals.json"
        self.stats_file = self.data_dir / "stats.json"
        
        # Load existing data if any
        self._load_existing_data()
    
    def _load_existing_data(self):
        """Load existing trades and signals from previous runs."""
        if self.trades_file.exists():
            with open(self.trades_file) as f:
                data = json.load(f)
                self.closed_trades = data.get("closed_trades", [])
                self.open_trades = data.get("open_trades", [])
                self.balance = data.get("balance", INITIAL_BALANCE)
                self.peak_balance = data.get("peak_balance", INITIAL_BALANCE)
                self.last_signal_ts = data.get("last_signal_ts", 0)
                self.signal_count = data.get("signal_count", 0)
                self.trade_count = data.get("trade_count", 0)
                self.total_pnl = data.get("total_pnl", 0.0)
                self.winning_trades = data.get("winning_trades", 0)
                self.losing_trades = data.get("losing_trades", 0)
                logger.info(f"Loaded {len(self.closed_trades)} closed trades, {len(self.open_trades)} open trades")
    
    def save_data(self):
        """Save trades and stats to file."""
        trades_data = {
            "closed_trades": self.closed_trades,
            "open_trades": self.open_trades,
            "balance": self.balance,
            "peak_balance": self.peak_balance,
            "last_signal_ts": self.last_signal_ts,
            "signal_count": self.signal_count,
            "trade_count": self.trade_count,
            "total_pnl": self.total_pnl,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        with open(self.trades_file, "w") as f:
            json.dump(trades_data, f, indent=2, default=str)
        
        # Save stats
        stats = self.get_stats()
        with open(self.stats_file, "w") as f:
            json.dump(stats, f, indent=2)
    
    def get_stats(self) -> dict:
        """Get current trading statistics."""
        total_trades = len(self.closed_trades)
        win_rate = self.winning_trades / total_trades if total_trades > 0 else 0
        avg_win = (self.total_pnl / self.winning_trades) if self.winning_trades > 0 else 0
        avg_loss = (self.total_pnl / self.losing_trades) if self.losing_trades > 0 else 0
        
        return {
            "balance": self.balance,
            "initial_balance": INITIAL_BALANCE,
            "total_pnl": self.total_pnl,
            "total_pnl_pct": (self.total_pnl / INITIAL_BALANCE) * 100,
            "total_trades": total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "signal_count": self.signal_count,
            "peak_balance": self.peak_balance,
            "max_drawdown": self.peak_balance - self.balance,
            "max_drawdown_pct": ((self.peak_balance - self.balance) / self.peak_balance * 100) if self.peak_balance > 0 else 0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    
    def add_candle(self, candle: Candle):
        """Add new candle and process."""
        self.candles.append(candle)
        
        # Keep last 2000 candles
        if len(self.candles) > 2000:
            self.candles = self.candles[-2000:]
        
        # Need minimum candles
        if len(self.candles) < 100:
            return
        
        # Process open trades
        self._process_trades(candle)
        
        # Check for new signals every 12 candles (1 hour)
        if len(self.candles) % 12 == 0:
            self._check_signals()
        
        # Save data every 100 candles
        if len(self.candles) % 100 == 0:
            self.save_data()
            stats = self.get_stats()
            logger.info(f"Stats: Balance=${stats['balance']:.2f}, P&L=${stats['total_pnl']:.2f} ({stats['total_pnl_pct']:.2f}%), "
                       f"Trades: {stats['total_trades']}, Win%: {stats['win_rate']*100:.1f}%")
    
    def _check_signals(self):
        """Check for new trading signals."""
        if len(self.candles) < 100:
            return
        
        # Run analysis
        swings = detect_swings(self.candles)[-100:]
        fvgs = detect_fvgs(self.candles[-80:])
        order_blocks = detect_order_blocks(self.candles[-80:], swings)
        liquidity = detect_equal_levels(swings)
        
        for c in self.candles[-20:]:
            fvgs = update_fvg_fills(fvgs, c)
            order_blocks = update_order_block_breakers(order_blocks, c)
            liquidity = check_liquidity_sweeps(liquidity, c)
        
        metrics = compute_market_metrics(self.candles, swings)
        atr = metrics.atr14 if metrics else 0.0
        liquidity_events = detect_liquidity_events(self.candles[-80:], liquidity, atr)[-40:]
        
        # Detect signals
        signals = detect_optimized_signals(
            candles=self.candles,
            metrics=metrics,
            fvgs=fvgs,
            order_blocks=order_blocks,
            liquidity_events=liquidity_events,
            swings=swings,
            last_signal_ts=self.last_signal_ts,
            signal_cooldown_candles=SIGNAL_COOLDOWN_CANDLES,
            min_confidence=MIN_CONFIDENCE,
            stop_loss_multiplier=STOP_LOSS_MULTIPLIER,
            use_adx_filter=USE_ADX_FILTER,
            adx_threshold=ADX_THRESHOLD,
            use_limit_orders=USE_LIMIT_ORDERS,
        )
        
        for sig in signals:
            self.signal_count += 1
            
            # Check if we can take the trade
            if len([t for t in self.open_trades if t.get("status") == "open"]) >= MAX_CONCURRENT:
                logger.info(f"Signal #{self.signal_count} skipped - max concurrent trades reached")
                continue
            
            if sig.confidence < MIN_CONFIDENCE:
                continue
            
            # Calculate position size
            risk_per_trade = self.balance * POSITION_SIZE_PCT
            risk_per_unit = abs(sig.entry - sig.stop_loss)
            quantity = risk_per_trade / risk_per_unit if risk_per_unit > 0 else 0
            
            # Apply slippage
            slippage = sig.entry * SLIPPAGE_PCT
            entry_with_slippage = sig.entry + slippage if sig.side == "buy" else sig.entry - slippage
            
            # Apply commission
            notional = entry_with_slippage * quantity
            commission = notional * COMMISSION_PCT
            
            # Calculate TP levels
            risk = abs(entry_with_slippage - sig.stop_loss)
            tp1 = entry_with_slippage + (risk * PARTIAL_TP1_R) if sig.side == "buy" else entry_with_slippage - (risk * PARTIAL_TP1_R)
            tp2 = entry_with_slippage + (risk * PARTIAL_TP2_R) if sig.side == "buy" else entry_with_slippage - (risk * PARTIAL_TP2_R)
            
            trade = {
                "id": f"demo-{self.signal_count}",
                "signal_id": sig.id,
                "timestamp": sig.timestamp,
                "side": sig.side,
                "entry_price": round(entry_with_slippage, 2),
                "stop_loss": sig.stop_loss,
                "initial_sl": sig.stop_loss,
                "tp1": round(tp1, 2),
                "tp2": round(tp2, 2),
                "quantity": quantity,
                "remaining_qty": quantity,
                "status": "open",
                "confidence": sig.confidence,
                "reason": sig.reason,
                "slippage": round(slippage, 2),
                "commission": round(commission, 2),
                "bars_held": 0,
                "tp1_hit": False,
                "total_pnl": 0.0,
                "opened_at": datetime.now(timezone.utc).isoformat(),
            }
            
            self.open_trades.append(trade)
            self.last_signal_ts = sig.timestamp
            
            logger.info(f"NEW TRADE #{self.signal_count}: {sig.side.upper()} @ ${entry_with_slippage:.2f}, "
                       f"SL=${sig.stop_loss:.2f}, TP1=${tp1:.2f}, TP2=${tp2:.2f}, "
                       f"Conf={sig.confidence:.2f}, Reason: {sig.reason}")
            
            # Save signal
            signal_data = {
                "id": sig.id,
                "timestamp": sig.timestamp,
                "side": sig.side,
                "entry": sig.entry,
                "stop_loss": sig.stop_loss,
                "confidence": sig.confidence,
                "reason": sig.reason,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            
            signals_file = self.data_dir / "signals.json"
            signals = []
            if signals_file.exists():
                with open(signals_file) as f:
                    signals = json.load(f)
            signals.append(signal_data)
            with open(signals_file, "w") as f:
                json.dump(signals, f, indent=2, default=str)
    
    def _process_trades(self, candle: Candle):
        """Process open trades against new candle."""
        for trade in list(self.open_trades):
            if trade["status"] != "open":
                continue
            
            side = trade["side"]
            entry = trade["entry_price"]
            sl = trade["stop_loss"]
            tp1 = trade["tp1"]
            tp2 = trade["tp2"]
            qty = trade["remaining_qty"]
            bars_held = trade.get("bars_held", 0) + 1
            trade["bars_held"] = bars_held
            
            # Move to breakeven after 0.75R profit
            risk = abs(entry - trade.get("initial_sl", sl))
            if risk > 0 and not trade["tp1_hit"]:
                if side == "buy":
                    profit_r = (candle.high - entry) / risk
                    if profit_r >= BREAKEVEN_THRESHOLD:
                        trade["stop_loss"] = max(trade["stop_loss"], entry)
                        sl = trade["stop_loss"]
                else:
                    profit_r = (entry - candle.low) / risk
                    if profit_r >= BREAKEVEN_THRESHOLD:
                        trade["stop_loss"] = min(trade["stop_loss"], entry)
                        sl = trade["stop_loss"]
            
            # Check TP1 (50% position)
            if not trade["tp1_hit"]:
                if side == "buy" and candle.high >= tp1:
                    pnl1 = (tp1 - entry) * (qty * 0.5)
                    trade["tp1_hit"] = True
                    trade["remaining_qty"] = qty * 0.5
                    trade["total_pnl"] += pnl1
                    self.balance += pnl1
                    logger.info(f"TRADE {trade['id']}: TP1 hit at ${tp1:.2f}, PnL=${pnl1:.2f}")
                elif side == "sell" and candle.low <= tp1:
                    pnl1 = (entry - tp1) * (qty * 0.5)
                    trade["tp1_hit"] = True
                    trade["remaining_qty"] = qty * 0.5
                    trade["total_pnl"] += pnl1
                    self.balance += pnl1
                    logger.info(f"TRADE {trade['id']}: TP1 hit at ${tp1:.2f}, PnL=${pnl1:.2f}")
            
            # Time-based exit
            if bars_held >= MAX_HOLD_BARS:
                exit_price = candle.close
                remaining_pnl = (exit_price - entry) * trade["remaining_qty"] if side == "buy" else (entry - exit_price) * trade["remaining_qty"]
                remaining_pnl -= trade["commission"]
                
                trade["status"] = "closed"
                trade["exit_price"] = exit_price
                trade["exit_timestamp"] = candle.timestamp
                trade["total_pnl"] += remaining_pnl
                trade["pnl"] = round(trade["total_pnl"], 2)
                trade["close_reason"] = "time_exit"
                trade["closed_at"] = datetime.now(timezone.utc).isoformat()
                self.balance += remaining_pnl
                
                self._close_trade(trade)
                continue
            
            # Check stop loss
            if side == "buy":
                hit_stop = candle.low <= sl
                hit_tp2 = candle.high >= tp2
            else:
                hit_stop = candle.high >= sl
                hit_tp2 = candle.low <= tp2
            
            if hit_stop:
                exit_price = sl
                remaining_pnl = (exit_price - entry) * trade["remaining_qty"] if side == "buy" else (entry - exit_price) * trade["remaining_qty"]
                remaining_pnl -= trade["commission"]
                
                trade["status"] = "closed"
                trade["exit_price"] = exit_price
                trade["exit_timestamp"] = candle.timestamp
                trade["total_pnl"] += remaining_pnl
                trade["pnl"] = round(trade["total_pnl"], 2)
                trade["close_reason"] = "stop_loss"
                trade["closed_at"] = datetime.now(timezone.utc).isoformat()
                self.balance += remaining_pnl
                
                self._close_trade(trade)
            
            elif hit_tp2:
                exit_price = tp2
                remaining_pnl = (exit_price - entry) * trade["remaining_qty"] if side == "buy" else (entry - exit_price) * trade["remaining_qty"]
                remaining_pnl -= trade["commission"]
                
                trade["status"] = "closed"
                trade["exit_price"] = exit_price
                trade["exit_timestamp"] = candle.timestamp
                trade["total_pnl"] += remaining_pnl
                trade["pnl"] = round(trade["total_pnl"], 2)
                trade["close_reason"] = "tp2_hit"
                trade["closed_at"] = datetime.now(timezone.utc).isoformat()
                self.balance += remaining_pnl
                
                self._close_trade(trade)
    
    def _close_trade(self, trade: dict):
        """Close a trade and update stats."""
        self.trade_count += 1
        self.closed_trades.append(trade)
        self.open_trades.remove(trade)
        
        pnl = trade.get("pnl", 0)
        self.total_pnl += pnl
        
        if pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
        
        logger.info(f"CLOSED TRADE {trade['id']}: {trade['side'].upper()}, "
                   f"PnL=${pnl:.2f}, Reason: {trade['close_reason']}, "
                   f"Bars: {trade['bars_held']}")
        
        # Save immediately
        self.save_data()


async def fetch_initial_candles(symbol=SYMBOL, interval=INTERVAL, limit=500) -> list[Candle]:
    """Fetch initial historical candles."""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    
    candles = []
    for k in data:
        candles.append(Candle(
            timestamp=k[0],
            open=float(k[1]),
            high=float(k[2]),
            low=float(k[3]),
            close=float(k[4]),
            volume=float(k[5]),
        ))
    
    return candles


async def run_demo():
    """Run the forward demo trading system."""
    logger.info("=" * 60)
    logger.info("NEXUS FORWARD DEMO TRADING")
    logger.info("=" * 60)
    logger.info(f"Symbol: {SYMBOL}")
    logger.info(f"Timeframe: {INTERVAL}")
    logger.info(f"Initial Balance: ${INITIAL_BALANCE:.2f}")
    logger.info(f"Stop Loss: {STOP_LOSS_MULTIPLIER}x ATR")
    logger.info(f"ADX Filter: {'Yes' if USE_ADX_FILTER else 'No'} (threshold={ADX_THRESHOLD})")
    logger.info(f"Limit Orders: {'Yes' if USE_LIMIT_ORDERS else 'No'}")
    logger.info("=" * 60)
    
    # Initialize trader
    trader = DemoTrader()
    
    # Fetch initial candles
    logger.info("Fetching initial historical candles...")
    candles = await fetch_initial_candles()
    logger.info(f"Fetched {len(candles)} candles")
    
    # Add initial candles
    for candle in candles:
        trader.add_candle(candle)
    
    logger.info(f"Initial stats: Balance=${trader.balance:.2f}, Trades: {len(trader.closed_trades)}")
    
    # Connect to Binance websocket
    ws_url = f"wss://stream.binance.com:9443/ws/{SYMBOL.lower()}@kline_{INTERVAL}"
    logger.info(f"Connecting to Binance websocket: {ws_url}")
    
    while True:
        try:
            async with websockets.connect(ws_url) as ws:
                logger.info("Connected to Binance websocket")
                
                while True:
                    message = await ws.recv()
                    data = json.loads(message)
                    
                    if "k" in data:
                        kline = data["k"]
                        
                        candle = Candle(
                            timestamp=kline["t"],
                            open=float(kline["o"]),
                            high=float(kline["h"]),
                            low=float(kline["l"]),
                            close=float(kline["c"]),
                            volume=float(kline["v"]),
                            is_closed=kline["x"],
                        )
                        
                        # Only process closed candles
                        if candle.is_closed:
                            trader.add_candle(candle)
        
        except Exception as e:
            logger.error(f"Websocket error: {e}")
            logger.info("Reconnecting in 10 seconds...")
            await asyncio.sleep(10)


if __name__ == "__main__":
    try:
        asyncio.run(run_demo())
    except KeyboardInterrupt:
        logger.info("Demo trading stopped by user")
