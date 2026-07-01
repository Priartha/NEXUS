"""
Feature Store — SQLite-backed feature registry with versioning.

Features are computed ad-hoc by the pipeline. This module provides:
  - Feature registration (name, type, description, version)
  - Feature value persistence with timestamps
  - Feature importance tracking (for ML models)
  - Retrieval by timeframe / symbol / feature set
  - Cleanup of old records
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from backend.storage.schema import get_conn

logger = logging.getLogger(__name__)


@dataclass
class FeatureDefinition:
    name: str
    feature_type: str  # "numerical", "categorical", "binary", "derived"
    category: str  # "orderflow", "ict", "momentum", "regime", "futures", "microstructure"
    description: str
    version: int = 1
    source: str = "analysis"
    is_active: bool = True


@dataclass
class FeatureImportance:
    name: str
    importance: float
    model_name: str
    timestamp: int
    rank: int = 0


class FeatureStore:
    """
    Feature registry and persistence layer.

    Features flow: pipeline computation → ingest_feature_values() → SQLite
    ML models read: get_feature_vector(timestamp, timeframe, feature_names)
    """

    def __init__(self) -> None:
        self._definitions: dict[str, FeatureDefinition] = {}
        self._importance: deque[FeatureImportance] = deque(maxlen=1000)
        self._init_tables()

    def _init_tables(self) -> None:
        conn = get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS feature_definitions (
                name TEXT PRIMARY KEY,
                feature_type TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT DEFAULT '',
                version INTEGER DEFAULT 1,
                source TEXT DEFAULT 'analysis',
                is_active INTEGER DEFAULT 1,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feature_values (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                feature_name TEXT NOT NULL,
                value REAL NOT NULL,
                version INTEGER DEFAULT 1,
                FOREIGN KEY (feature_name) REFERENCES feature_definitions(name)
            );
            CREATE INDEX IF NOT EXISTS idx_fv_lookup ON feature_values(timestamp, symbol, timeframe, feature_name);
            CREATE INDEX IF NOT EXISTS idx_fv_name ON feature_values(feature_name);
            CREATE TABLE IF NOT EXISTS feature_importance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                feature_name TEXT NOT NULL,
                importance REAL NOT NULL,
                model_name TEXT NOT NULL,
                rank INTEGER DEFAULT 0,
                FOREIGN KEY (feature_name) REFERENCES feature_definitions(name)
            );
            CREATE INDEX IF NOT EXISTS idx_fi_model ON feature_importance(model_name, timestamp);
        """)
        conn.commit()

    register_feature_queries_run = False

    def register_feature(self, name: str, feature_type: str, category: str, description: str = "", version: int = 1, source: str = "analysis") -> None:
        """Register a feature definition (idempotent)."""
        if name in self._definitions:
            return
        conn = get_conn()
        conn.execute("""
            INSERT OR IGNORE INTO feature_definitions
            (name, feature_type, category, description, version, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, feature_type, category, description, version, source, int(time.time())))
        conn.commit()
        self._definitions[name] = FeatureDefinition(name, feature_type, category, description, version, source)

    def register_default_features(self) -> None:
        """Register all known features used by the system."""
        if FeatureStore.register_feature_queries_run:
            return
        FeatureStore.register_feature_queries_run = True

        features = [
            # Order flow
            ("of_delta", "numerical", "orderflow", "Order flow delta"),
            ("of_cvd", "numerical", "orderflow", "Cumulative volume delta"),
            ("of_cvd_slope", "numerical", "orderflow", "CVD slope (momentum)"),
            ("of_absorption", "numerical", "orderflow", "Absorption ratio"),
            ("of_footprint", "numerical", "orderflow", "Footprint imbalance"),
            ("of_vol_delta_ratio", "numerical", "orderflow", "Volume delta ratio"),

            # VWAP
            ("vwap_deviation", "numerical", "orderflow", "VWAP price deviation %"),
            ("vwap_compressed", "binary", "orderflow", "VWAP compressed flag"),

            # Volume profile
            ("vp_value_area_width", "numerical", "orderflow", "Value area width %"),
            ("vp_poc_distance", "numerical", "orderflow", "Distance from POC %"),

            # Funding
            ("funding_rate", "numerical", "futures", "Funding rate"),
            ("funding_annualized", "numerical", "futures", "Annualized funding APR"),
            ("funding_extreme", "binary", "futures", "Funding extreme flag"),
            ("funding_contrarian_bias", "categorical", "futures", "Funding contrarian bias"),

            # Open interest
            ("oi_change_pct", "numerical", "futures", "OI change %"),
            ("oi_trend", "categorical", "futures", "OI trend direction"),
            ("oi_momentum", "binary", "futures", "OI momentum confirmation"),

            # Market metrics
            ("rsi14", "numerical", "momentum", "RSI 14-period"),
            ("atr14", "numerical", "momentum", "ATR 14-period"),
            ("trend_score", "numerical", "momentum", "Trend score (-1 to 1)"),
            ("volatility_score", "numerical", "momentum", "Volatility score"),
            ("volume_zscore", "numerical", "momentum", "Volume Z-score"),
            ("realized_volatility", "numerical", "momentum", "Realized volatility"),
            ("hurst_exponent", "numerical", "momentum", "Hurst exponent"),
            ("shannon_entropy", "numerical", "momentum", "Shannon entropy"),

            # ICT patterns
            ("bullish_fvg_count", "numerical", "ict", "Active bullish FVG count"),
            ("bearish_fvg_count", "numerical", "ict", "Active bearish FVG count"),
            ("bullish_ob_count", "numerical", "ict", "Active bullish OB count"),
            ("bearish_ob_count", "numerical", "ict", "Active bearish OB count"),
            ("liquidity_sweep_count", "numerical", "ict", "Recent liquidity sweep count"),
            ("bos_bullish", "binary", "ict", "Break of structure bullish"),
            ("bos_bearish", "binary", "ict", "Break of structure bearish"),
            ("mss_bullish", "binary", "ict", "Market structure shift bullish"),
            ("mss_bearish", "binary", "ict", "Market structure shift bearish"),

            # Regime
            ("regime_phase", "categorical", "regime", "Market regime phase"),
            ("regime_bias", "categorical", "regime", "Market regime bias"),
            ("regime_confidence", "numerical", "regime", "Regime confidence"),

            # RSI(3) scalping
            ("rsi3", "numerical", "momentum", "RSI 3-period"),
            ("rsi3_zone", "categorical", "momentum", "RSI3 zone classification"),

            # Killzone
            ("killzone_active", "binary", "momentum", "Killzone active"),
            ("killzone_session", "categorical", "momentum", "Killzone session"),

            # Macro
            ("weekend", "binary", "regime", "Is weekend"),
            ("asian_session_low_vol", "binary", "regime", "Asian session low volume"),

            # ML-generated
            ("xgboost_score", "numerical", "derived", "XGBoost model score"),
            ("xgboost_direction", "categorical", "derived", "XGBoost predicted direction"),
            ("label_forward_return", "numerical", "derived", "Triple-barrier forward return"),
            ("label_direction", "categorical", "derived", "Triple-barrier label"),

            # CVD divergence
            ("cvd_divergence_type", "categorical", "orderflow", "Active CVD divergence type"),
            ("cvd_divergence_strength", "numerical", "orderflow", "CVD divergence strength"),

            # Cross-exchange
            ("cross_exchange_spread_pct", "numerical", "futures", "Cross-exchange spread %"),
            ("cross_exchange_deviation", "numerical", "futures", "Price deviation from ME median"),

            # On-chain
            ("btc_mvrv_zscore", "numerical", "onchain", "MVRV Z-score"),
            ("btc_exchange_net_flow", "numerical", "onchain", "Exchange net flow"),
            ("btc_whale_tx_count", "numerical", "onchain", "Whale transaction count >$100k"),
            ("btc_sopr", "numerical", "onchain", "Spent output profit ratio"),

            # Sentiment
            ("sentiment_label", "categorical", "sentiment", "Sentiment label"),
            ("sentiment_score", "numerical", "sentiment", "Sentiment score"),

            # RL / Adaptive
            ("kelly_fraction", "numerical", "derived", "Optimal Kelly fraction"),
            ("position_size", "numerical", "derived", "Suggested position size"),
        ]
        for name, ftype, cat, desc in features:
            self.register_feature(name, ftype, cat, desc)

    def ingest_feature_values(self, timestamp: int, symbol: str, timeframe: str, feature_values: dict[str, float]) -> int:
        """Store a batch of feature values. Returns count stored."""
        if not feature_values:
            return 0
        conn = get_conn()
        rows = []
        for name, value in feature_values.items():
            if not isinstance(value, (int, float)):
                continue
            rows.append((timestamp, symbol, timeframe, name, float(value)))
        conn.executemany("""
            INSERT INTO feature_values (timestamp, symbol, timeframe, feature_name, value)
            VALUES (?, ?, ?, ?, ?)
        """, rows)
        conn.commit()
        return len(rows)

    def get_feature_vector(self, timestamp: int, symbol: str, timeframe: str, feature_names: list[str] | None = None) -> dict[str, float]:
        """Get the most recent feature values before or at the given timestamp."""
        conn = get_conn()
        if feature_names:
            placeholders = ",".join("?" for _ in feature_names)
            rows = conn.execute(f"""
                SELECT fv.feature_name, fv.value
                FROM feature_values fv
                INNER JOIN (
                    SELECT feature_name, MAX(timestamp) as max_ts
                    FROM feature_values
                    WHERE timestamp <= ? AND symbol = ? AND timeframe = ?
                        AND feature_name IN ({placeholders})
                    GROUP BY feature_name
                ) latest ON fv.feature_name = latest.feature_name AND fv.timestamp = latest.max_ts
            """, (timestamp, symbol, timeframe, *feature_names)).fetchall()
        else:
            rows = conn.execute(f"""
                SELECT fv.feature_name, fv.value
                FROM feature_values fv
                INNER JOIN (
                    SELECT feature_name, MAX(timestamp) as max_ts
                    FROM feature_values
                    WHERE timestamp <= ? AND symbol = ? AND timeframe = ?
                    GROUP BY feature_name
                ) latest ON fv.feature_name = latest.feature_name AND fv.timestamp = latest.max_ts
            """, (timestamp, symbol, timeframe)).fetchall()
        return {row["feature_name"]: row["value"] for row in rows}

    def get_feature_history(self, feature_name: str, symbol: str, timeframe: str, limit: int = 500) -> list[dict]:
        """Get time series of a single feature."""
        conn = get_conn()
        rows = conn.execute("""
            SELECT timestamp, value FROM feature_values
            WHERE feature_name = ? AND symbol = ? AND timeframe = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (feature_name, symbol, timeframe, limit)).fetchall()
        return [{"timestamp": r["timestamp"], "value": r["value"]} for r in rows]

    def record_importance(self, feature_name: str, importance: float, model_name: str) -> None:
        """Record feature importance from an ML model."""
        conn = get_conn()
        conn.execute("""
            INSERT INTO feature_importance (timestamp, feature_name, importance, model_name)
            VALUES (?, ?, ?, ?)
        """, (int(time.time()), feature_name, importance, model_name))
        conn.commit()
        self._importance.append(FeatureImportance(feature_name, importance, model_name, int(time.time())))

    def get_top_features(self, model_name: str, n: int = 20) -> list[dict]:
        """Get top N most important features for a model."""
        conn = get_conn()
        rows = conn.execute("""
            SELECT feature_name, AVG(importance) as avg_importance
            FROM feature_importance
            WHERE model_name = ?
            GROUP BY feature_name
            ORDER BY avg_importance DESC
            LIMIT ?
        """, (model_name, n)).fetchall()
        return [{"name": r["feature_name"], "importance": r["avg_importance"]} for r in rows]

    def cleanup_old_values(self, retention_days: int = 30) -> int:
        """Remove feature values older than retention_days."""
        conn = get_conn()
        cutoff = int(time.time()) - retention_days * 86400
        result = conn.execute("DELETE FROM feature_values WHERE timestamp < ?", (cutoff,))
        deleted = result.rowcount
        conn.commit()
        logger.info(f"Cleaned up {deleted} old feature value records")
        return deleted

    def get_state(self) -> dict:
        conn = get_conn()
        total_defs = conn.execute("SELECT COUNT(*) FROM feature_definitions").fetchone()[0]
        total_values = conn.execute("SELECT COUNT(*) FROM feature_values").fetchone()[0]
        total_importance = conn.execute("SELECT COUNT(*) FROM feature_importance").fetchone()[0]
        top_features = self.get_top_features("xgboost")
        return {
            "total_definitions": total_defs,
            "total_values": total_values,
            "total_importance_records": total_importance,
            "top_features": top_features[:5],
            "cached_importance": len(self._importance),
        }


# Singleton
feature_store = FeatureStore()
