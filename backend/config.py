from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    symbol: str = os.getenv("ICT_SYMBOL", "BTCUSDT")
    timeframe: str = os.getenv("ICT_TIMEFRAME", "5m")
    timeframes: tuple[str, ...] = tuple(
        timeframe.strip()
        for timeframe in os.getenv("ICT_TIMEFRAMES", "1m,5m,15m,1h").split(",")
        if timeframe.strip()
    )
    max_candles: int = int(os.getenv("ICT_MAX_CANDLES", "500"))
    history_seed_candles: int = int(os.getenv("ICT_HISTORY_SEED_CANDLES", "500"))
    market_data_provider: str = os.getenv("ICT_MARKET_DATA_PROVIDER", "binance")
    rest_base_url: str = os.getenv("ICT_REST_BASE_URL", os.getenv("DELTA_REST_BASE_URL", "https://api.india.delta.exchange"))
    ws_url: str = os.getenv("ICT_WS_URL", os.getenv("DELTA_WS_URL", "wss://public-socket.india.delta.exchange"))
    market_data_rest_base_url: str = os.getenv("ICT_MARKET_DATA_REST_BASE_URL", "https://api.binance.com")
    market_data_ws_url: str = os.getenv("ICT_MARKET_DATA_WS_URL", "wss://stream.binance.com:9443")
    market_data_rest_poll_seconds: float = float(os.getenv("ICT_MARKET_DATA_REST_POLL_SECONDS", "1"))
    options_rest_base_url: str = os.getenv("ICT_OPTIONS_REST_BASE_URL", os.getenv("DELTA_REST_BASE_URL", "https://api.india.delta.exchange"))
    ws_reconnect_initial_seconds: float = float(os.getenv("ICT_WS_RECONNECT_INITIAL_SECONDS", "2"))
    ws_reconnect_max_seconds: float = float(os.getenv("ICT_WS_RECONNECT_MAX_SECONDS", "30"))
    options_underlying: str = os.getenv("ICT_OPTIONS_UNDERLYING", "BTC")
    options_refresh_seconds: float = float(os.getenv("ICT_OPTIONS_REFRESH_SECONDS", "60"))
    min_options_momentum_score: float = float(os.getenv("ICT_MIN_OPTIONS_MOMENTUM_SCORE", "0.40"))
    options_max_spread_pct: float = float(os.getenv("ICT_OPTIONS_MAX_SPREAD_PCT", "0.18"))
    options_min_delta_abs: float = float(os.getenv("ICT_OPTIONS_MIN_DELTA_ABS", "0.35"))
    options_max_delta_abs: float = float(os.getenv("ICT_OPTIONS_MAX_DELTA_ABS", "0.75"))
    options_max_moneyness_pct: float = float(os.getenv("ICT_OPTIONS_MAX_MONEYNESS_PCT", "0.08"))
    ai_ict_refresh_seconds: float = float(os.getenv("ICT_AI_ICT_REFRESH_SECONDS", "180"))
    ai_ict_provider: str = os.getenv("ICT_AI_ICT_PROVIDER", "auto")
    sentiment_refresh_seconds: float = float(os.getenv("ICT_SENTIMENT_REFRESH_SECONDS", "300"))
    sentiment_provider: str = os.getenv("ICT_SENTIMENT_PROVIDER", "auto")
    sentiment_model: str = os.getenv("ICT_SENTIMENT_MODEL", "gpt-5.4-mini")
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

    # Scalping engine configuration
    scalp_enabled: bool = os.getenv("NEXUS_SCALP_ENABLED", "true").lower() == "true"
    scalp_max_risk_pct: float = float(os.getenv("NEXUS_SCALP_MAX_RISK_PCT", "0.01"))
    scalp_max_leverage: int = int(os.getenv("NEXUS_SCALP_MAX_LEVERAGE", "10"))
    scalp_max_positions: int = int(os.getenv("NEXUS_SCALP_MAX_POSITIONS", "2"))
    scalp_daily_loss_limit_pct: float = float(os.getenv("NEXUS_SCALP_DAILY_LOSS_PCT", "0.03"))
    scalp_min_rrr: float = float(os.getenv("NEXUS_SCALP_MIN_RRR", "1.5"))
    scalp_max_hold_minutes: int = int(os.getenv("NEXUS_SCALP_MAX_HOLD_MINUTES", "15"))
    scalp_funding_rate_extreme: float = float(os.getenv("NEXUS_SCALP_FUNDING_EXTREME", "0.001"))
    scalp_ivr_low_threshold: float = float(os.getenv("NEXUS_SCALP_IVR_LOW", "30"))
    scalp_ivr_high_threshold: float = float(os.getenv("NEXUS_SCALP_IVR_HIGH", "70"))
    scalp_ivr_no_trade_low: float = float(os.getenv("NEXUS_SCALP_IVR_NO_TRADE_LOW", "30"))
    scalp_ivr_no_trade_high: float = float(os.getenv("NEXUS_SCALP_IVR_NO_TRADE_HIGH", "50"))
    scalp_options_min_delta: float = float(os.getenv("NEXUS_SCALP_OPT_MIN_DELTA", "0.30"))
    scalp_options_max_delta: float = float(os.getenv("NEXUS_SCALP_OPT_MAX_DELTA", "0.50"))
    scalp_options_max_dte: int = int(os.getenv("NEXUS_SCALP_OPT_MAX_DTE", "3"))
    scalp_options_premium_exit_pct: float = float(os.getenv("NEXUS_SCALP_OPT_EXIT_PCT", "0.60"))
    scalp_options_spread_max_pct: float = float(os.getenv("NEXUS_SCALP_OPT_SPREAD_MAX", "0.005"))
    scalp_min_spot_volume_ratio: float = float(os.getenv("NEXUS_SCALP_MIN_VOL_RATIO", "0.70"))
    scalp_vwap_band_sd: float = float(os.getenv("NEXUS_SCALP_VWAP_SD", "1.0"))
    scalp_rsi_exhaustion: float = float(os.getenv("NEXUS_SCALP_RSI_EXHAUSTION", "3"))
    scalp_partial_exit_pct: float = float(os.getenv("NEXUS_SCALP_PARTIAL_EXIT", "0.70"))
    scalp_breakeven_premium_pct: float = float(os.getenv("NEXUS_SCALP_BE_PREMIUM_PCT", "0.20"))
    scalp_min_confluence_score: float = float(os.getenv("NEXUS_SCALP_MIN_CONFLUENCE", "0.45"))
    scalp_min_directional_edge: float = float(os.getenv("NEXUS_SCALP_MIN_DIRECTIONAL_EDGE", "0.08"))
    scalp_min_trend_strength: float = float(os.getenv("NEXUS_SCALP_MIN_TREND_STRENGTH", "0.001"))
    scalp_min_volume_impulse: float = float(os.getenv("NEXUS_SCALP_MIN_VOLUME_IMPULSE", "0.80"))
    scalp_require_options_alignment: bool = os.getenv("NEXUS_SCALP_REQUIRE_OPTIONS_ALIGNMENT", "true").lower() == "true"
    scalp_require_mtf_alignment: bool = os.getenv("NEXUS_SCALP_REQUIRE_MTF_ALIGNMENT", "true").lower() == "true"
    scalp_require_candle_confirmation: bool = os.getenv("NEXUS_SCALP_REQUIRE_CANDLE_CONFIRMATION", "true").lower() == "true"
    scalp_max_entry_distance_pct: float = float(os.getenv("NEXUS_SCALP_MAX_ENTRY_DISTANCE_PCT", "0.0015"))


settings = Settings()
