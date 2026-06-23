"""
Configuration Validator for NEXUS.

Validates all environment variables and settings at startup,
providing clear error messages for misconfigurations.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from backend.config import settings

logger = logging.getLogger("backend")


@dataclass
class ValidationIssue:
    field: str
    severity: str  # "error", "warning", "info"
    message: str


class ConfigValidator:
    """Validates NEXUS configuration at startup."""

    VALID_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"}
    VALID_PROVIDERS = {"binance", "delta", "auto", "local"}
    VALID_AI_PROVIDERS = {"auto", "groq", "openai", "local"}
    VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

    def validate_all(self) -> list[ValidationIssue]:
        """Run all validation checks."""
        issues: list[ValidationIssue] = []
        issues.extend(self._validate_symbol())
        issues.extend(self._validate_timeframes())
        issues.extend(self._validate_market_provider())
        issues.extend(self._validate_ai_config())
        issues.extend(self._validate_sentiment_config())
        issues.extend(self._validate_urls())
        issues.extend(self._validate_limits())
        issues.extend(self._validate_log_level())
        return issues

    def _validate_symbol(self) -> list[ValidationIssue]:
        issues = []
        sym = settings.symbol
        if not sym or len(sym) < 3:
            issues.append(ValidationIssue("ICT_SYMBOL", "error", "Symbol must be at least 3 characters"))
        elif not re.match(r"^[A-Z0-9]{2,10}$", sym.replace("USDT", "").replace("USD", "")):
            issues.append(ValidationIssue("ICT_SYMBOL", "warning", f"Unusual symbol format: {sym}"))
        return issues

    def _validate_timeframes(self) -> list[ValidationIssue]:
        issues = []
        if settings.timeframe not in self.VALID_TIMEFRAMES:
            issues.append(ValidationIssue("ICT_TIMEFRAME", "error", f"Invalid timeframe: {settings.timeframe}. Must be one of {self.VALID_TIMEFRAMES}"))
        for tf in settings.timeframes:
            if tf not in self.VALID_TIMEFRAMES:
                issues.append(ValidationIssue("ICT_TIMEFRAMES", "error", f"Invalid timeframe in list: {tf}"))
        if settings.timeframe not in settings.timeframes:
            issues.append(ValidationIssue("ICT_TIMEFRAMES", "warning", f"Primary timeframe {settings.timeframe} not in timeframes list"))
        return issues

    def _validate_market_provider(self) -> list[ValidationIssue]:
        issues = []
        provider = (settings.market_data_provider or "").lower()
        if provider not in self.VALID_PROVIDERS:
            issues.append(ValidationIssue("ICT_MARKET_DATA_PROVIDER", "error", f"Invalid provider: {provider}. Must be binance or delta"))
        return issues

    def _validate_ai_config(self) -> list[ValidationIssue]:
        issues = []
        provider = (settings.ai_ict_provider or "").lower()
        if provider not in self.VALID_AI_PROVIDERS:
            issues.append(ValidationIssue("ICT_AI_ICT_PROVIDER", "error", f"Invalid AI provider: {provider}"))
        if provider == "groq" and not settings.groq_api_key:
            issues.append(ValidationIssue("GROQ_API_KEY", "warning", "Groq provider selected but API key is empty. Falling back to local."))
        if provider == "openai" and not settings.openai_api_key:
            issues.append(ValidationIssue("OPENAI_API_KEY", "warning", "OpenAI provider selected but API key is empty. Falling back to local."))
        if not settings.groq_api_key and not settings.openai_api_key:
            issues.append(ValidationIssue("AI_API_KEYS", "info", "No AI API keys configured. Using deterministic local analysis only."))
        return issues

    def _validate_sentiment_config(self) -> list[ValidationIssue]:
        issues = []
        provider = (settings.sentiment_provider or "").lower()
        if provider not in {"auto", "groq", "openai", "local"}:
            issues.append(ValidationIssue("ICT_SENTIMENT_PROVIDER", "error", f"Invalid sentiment provider: {provider}"))
        if provider == "groq" and not settings.groq_api_key:
            issues.append(ValidationIssue("GROQ_API_KEY", "warning", "Groq sentiment selected but API key is empty."))
        return issues

    def _validate_urls(self) -> list[ValidationIssue]:
        issues = []
        url_fields = [
            ("ICT_MARKET_DATA_REST_BASE_URL", settings.market_data_rest_base_url),
            ("ICT_REST_BASE_URL", settings.rest_base_url),
            ("ICT_WS_URL", settings.ws_url),
            ("GROQ_BASE_URL", settings.groq_base_url),
            ("OPENAI_BASE_URL", settings.openai_base_url),
        ]
        for field_name, url in url_fields:
            if url and not url.startswith(("http://", "https://", "wss://", "ws://")):
                issues.append(ValidationIssue(field_name, "error", f"Invalid URL format: {url}"))
        return issues

    def _validate_limits(self) -> list[ValidationIssue]:
        issues = []
        if settings.max_candles < 50:
            issues.append(ValidationIssue("ICT_MAX_CANDLES", "warning", f"Very low candle count: {settings.max_candles}. Minimum recommended: 50"))
        if settings.max_candles > 5000:
            issues.append(ValidationIssue("ICT_MAX_CANDLES", "warning", f"Very high candle count: {settings.max_candles}. May impact memory."))
        if settings.ai_ict_refresh_seconds < 30:
            issues.append(ValidationIssue("ICT_AI_ICT_REFRESH_SECONDS", "warning", "AI refresh interval too low. May hit API rate limits."))
        if settings.sentiment_refresh_seconds < 60:
            issues.append(ValidationIssue("ICT_SENTIMENT_REFRESH_SECONDS", "warning", "Sentiment refresh interval too low."))
        return issues

    def _validate_log_level(self) -> list[ValidationIssue]:
        issues = []
        if settings.log_level not in self.VALID_LOG_LEVELS:
            issues.append(ValidationIssue("ICT_LOG_LEVEL", "error", f"Invalid log level: {settings.log_level}"))
        return issues

    def print_report(self, issues: list[ValidationIssue]) -> None:
        """Print validation report."""
        if not issues:
            logger.info("Configuration validation: ALL CHECKS PASSED")
            return

        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        infos = [i for i in issues if i.severity == "info"]

        if errors:
            logger.error(f"Configuration validation: {len(errors)} ERROR(S) found")
            for e in errors:
                logger.error(f"  [ERROR] {e.field}: {e.message}")
        if warnings:
            logger.warning(f"Configuration validation: {len(warnings)} WARNING(S)")
            for w in warnings:
                logger.warning(f"  [WARN] {w.field}: {w.message}")
        if infos:
            logger.info(f"Configuration validation: {len(infos)} INFO(S)")
            for i in infos:
                logger.info(f"  [INFO] {i.field}: {i.message}")

    def has_errors(self, issues: list[ValidationIssue]) -> bool:
        return any(i.severity == "error" for i in issues)


validator = ConfigValidator()
