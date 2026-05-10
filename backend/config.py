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
    market_data_rest_base_url: str = os.getenv("ICT_MARKET_DATA_REST_BASE_URL", os.getenv("ICT_REST_BASE_URL", os.getenv("DELTA_REST_BASE_URL", "https://api.binance.com")))
    market_data_ws_url: str = os.getenv("ICT_MARKET_DATA_WS_URL", os.getenv("ICT_WS_URL", os.getenv("DELTA_WS_URL", "wss://stream.binance.com:9443")))
    options_rest_base_url: str = os.getenv("ICT_OPTIONS_REST_BASE_URL", os.getenv("DELTA_REST_BASE_URL", "https://api.india.delta.exchange"))
    ws_reconnect_initial_seconds: float = float(os.getenv("ICT_WS_RECONNECT_INITIAL_SECONDS", "2"))
    ws_reconnect_max_seconds: float = float(os.getenv("ICT_WS_RECONNECT_MAX_SECONDS", "30"))
    options_underlying: str = os.getenv("ICT_OPTIONS_UNDERLYING", "BTC")
    options_refresh_seconds: float = float(os.getenv("ICT_OPTIONS_REFRESH_SECONDS", "10"))
    min_options_momentum_score: float = float(os.getenv("ICT_MIN_OPTIONS_MOMENTUM_SCORE", "0.40"))
    options_max_spread_pct: float = float(os.getenv("ICT_OPTIONS_MAX_SPREAD_PCT", "0.18"))
    options_min_delta_abs: float = float(os.getenv("ICT_OPTIONS_MIN_DELTA_ABS", "0.35"))
    options_max_delta_abs: float = float(os.getenv("ICT_OPTIONS_MAX_DELTA_ABS", "0.75"))
    options_max_moneyness_pct: float = float(os.getenv("ICT_OPTIONS_MAX_MONEYNESS_PCT", "0.08"))
    ai_ict_refresh_seconds: float = float(os.getenv("ICT_AI_ICT_REFRESH_SECONDS", "30"))
    ai_ict_provider: str = os.getenv("ICT_AI_ICT_PROVIDER", "auto")
    sentiment_refresh_seconds: float = float(os.getenv("ICT_SENTIMENT_REFRESH_SECONDS", "60"))
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


settings = Settings()
