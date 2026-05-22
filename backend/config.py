from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    symbol: str = os.getenv("ICT_SYMBOL", "BTCUSD")
    timeframe: str = os.getenv("ICT_TIMEFRAME", "5m")
    timeframes: tuple[str, ...] = tuple(
        timeframe.strip()
        for timeframe in os.getenv("ICT_TIMEFRAMES", "1m,5m,15m,1h").split(",")
        if timeframe.strip()
    )
    max_candles: int = int(os.getenv("ICT_MAX_CANDLES", "700"))
    history_seed_candles: int = int(os.getenv("ICT_HISTORY_SEED_CANDLES", "700"))
    market_data_provider: str = os.getenv("ICT_MARKET_DATA_PROVIDER", "delta")
    rest_base_url: str = os.getenv("DELTA_REST_BASE_URL", "https://api.india.delta.exchange")
    ws_url: str = os.getenv("DELTA_WS_URL", "wss://public-socket.india.delta.exchange")
    market_data_rest_base_url: str = os.getenv("ICT_MARKET_DATA_REST_BASE_URL", "https://api.binance.com")
    market_data_ws_url: str = os.getenv("ICT_MARKET_DATA_WS_URL", "wss://stream.binance.com:9443")
    market_data_rest_poll_seconds: float = float(os.getenv("ICT_MARKET_DATA_REST_POLL_SECONDS", "1"))
    ws_reconnect_initial_seconds: float = float(os.getenv("ICT_WS_RECONNECT_INITIAL_SECONDS", "2"))
    ws_reconnect_max_seconds: float = float(os.getenv("ICT_WS_RECONNECT_MAX_SECONDS", "30"))

    # Delta Exchange futures product config
    futures_product_id: int = int(os.getenv("DELTA_FUTURES_PRODUCT_ID", "372"))  # BTCUSD perpetual
    futures_leverage: int = int(os.getenv("DELTA_FUTURES_LEVERAGE", "20"))  # Increased for better futures profitability
    futures_margin_mode: str = os.getenv("DELTA_FUTURES_MARGIN_MODE", "cross")
    futures_funding_refresh_seconds: float = float(os.getenv("DELTA_FUTURES_FUNDING_REFRESH_SECONDS", "30"))
    futures_oi_refresh_seconds: float = float(os.getenv("DELTA_FUTURES_OI_REFRESH_SECONDS", "30"))
    futures_liq_refresh_seconds: float = float(os.getenv("DELTA_FUTURES_LIQ_REFRESH_SECONDS", "60"))
    # Default funding rate for backtesting (negative = we get paid to hold)
    # BTC perpetual typically has funding between -0.0003 and +0.0003
    futures_default_funding: float = float(os.getenv("DELTA_FUTURES_DEFAULT_FUNDING", "-0.0001"))

    ai_ict_refresh_seconds: float = float(os.getenv("ICT_AI_ICT_REFRESH_SECONDS", "180"))
    ai_ict_provider: str = os.getenv("ICT_AI_ICT_PROVIDER", "auto")
    sentiment_refresh_seconds: float = float(os.getenv("ICT_SENTIMENT_REFRESH_SECONDS", "300"))
    sentiment_provider: str = os.getenv("ICT_SENTIMENT_PROVIDER", "auto")
    sentiment_model: str = os.getenv("ICT_SENTIMENT_MODEL", "gpt-4o-mini")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_base_url: str = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv(
            "ICT_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    )
    api_key: str = os.getenv("ICT_API_KEY", "")
    log_level: str = os.getenv("ICT_LOG_LEVEL", "INFO")

    # Scalping engine configuration (Futures-only)
    scalp_enabled: bool = os.getenv("NEXUS_SCALP_ENABLED", "true").lower() == "true"
    scalp_max_risk_pct: float = float(os.getenv("NEXUS_SCALP_MAX_RISK_PCT", "0.02"))  # 2% risk per trade
    scalp_max_leverage: int = int(os.getenv("NEXUS_SCALP_MAX_LEVERAGE", "25"))  # 25x for futures profitability
    scalp_max_positions: int = int(os.getenv("NEXUS_SCALP_MAX_POSITIONS", "1"))
    scalp_daily_loss_limit_pct: float = float(os.getenv("NEXUS_SCALP_DAILY_LOSS_PCT", "0.05"))
    scalp_min_rrr: float = float(os.getenv("NEXUS_SCALP_MIN_RRR", "2.0"))
    scalp_max_hold_minutes: int = int(os.getenv("NEXUS_SCALP_MAX_HOLD_MINUTES", "25"))
    scalp_funding_rate_extreme: float = float(os.getenv("NEXUS_SCALP_FUNDING_EXTREME", "0.0015"))
    scalp_min_spot_volume_ratio: float = float(os.getenv("NEXUS_SCALP_MIN_VOL_RATIO", "0.60"))
    scalp_vwap_band_sd: float = float(os.getenv("NEXUS_SCALP_VWAP_SD", "1.0"))
    scalp_rsi_exhaustion: float = float(os.getenv("NEXUS_SCALP_RSI_EXHAUSTION", "3"))
    scalp_partial_exit_pct: float = float(os.getenv("NEXUS_SCALP_PARTIAL_EXIT", "0.50"))
    scalp_breakeven_premium_pct: float = float(os.getenv("NEXUS_SCALP_BE_PREMIUM_PCT", "0.50"))
    # Relaxed thresholds for more trading opportunities while maintaining quality
    scalp_min_confluence_score: float = float(os.getenv("NEXUS_SCALP_MIN_CONFLUENCE", "0.60"))
    scalp_min_directional_edge: float = float(os.getenv("NEXUS_SCALP_MIN_DIRECTIONAL_EDGE", "0.04"))
    scalp_min_trend_strength: float = float(os.getenv("NEXUS_SCALP_MIN_TREND_STRENGTH", "0.0005"))
    scalp_min_volume_impulse: float = float(os.getenv("NEXUS_SCALP_MIN_VOLUME_IMPULSE", "0.55"))
    scalp_require_mtf_alignment: bool = os.getenv("NEXUS_SCALP_REQUIRE_MTF_ALIGNMENT", "false").lower() == "true"
    scalp_require_candle_confirmation: bool = os.getenv("NEXUS_SCALP_REQUIRE_CANDLE_CONFIRMATION", "false").lower() == "true"
    scalp_max_entry_distance_pct: float = float(os.getenv("NEXUS_SCALP_MAX_ENTRY_DISTANCE_PCT", "0.003"))

    # Wick rejection analysis
    scalp_wick_lookback: int = int(os.getenv("NEXUS_SCALP_WICK_LOOKBACK", "5"))
    scalp_wick_min_ratio: float = float(os.getenv("NEXUS_SCALP_WICK_MIN_RATIO", "2.0"))
    scalp_wick_max_lookback: int = int(os.getenv("NEXUS_SCALP_WICK_MAX_LOOKBACK", "8"))

    # Production readiness gate
    require_profitability_validation: bool = os.getenv("NEXUS_REQUIRE_PROFITABILITY_VALIDATION", "true").lower() == "true"
    profitability_validation_path: str = os.getenv("NEXUS_PROFITABILITY_VALIDATION_PATH", "data/profitability_validation.json")
    profitability_min_trades: int = int(os.getenv("NEXUS_PROFITABILITY_MIN_TRADES", "100"))
    profitability_min_win_rate: float = float(os.getenv("NEXUS_PROFITABILITY_MIN_WIN_RATE", "0.50"))
    profitability_min_profit_factor: float = float(os.getenv("NEXUS_PROFITABILITY_MIN_PF", "1.50"))
    profitability_max_drawdown_pct: float = float(os.getenv("NEXUS_PROFITABILITY_MAX_DD_PCT", "15.0"))


settings = Settings()
