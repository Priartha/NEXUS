from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from backend.config import settings


def evaluate_profitability(metrics: dict[str, Any]) -> dict[str, Any]:
    trade_count = int(metrics.get("trade_count", metrics.get("total_trades", 0)) or 0)
    win_rate = float(metrics.get("win_rate", 0) or 0)
    profit_factor = float(metrics.get("profit_factor", 0) or 0)
    max_drawdown_pct = float(metrics.get("max_drawdown_pct", 0) or 0)

    failures: list[str] = []
    if trade_count < settings.profitability_min_trades:
        failures.append(f"trades {trade_count} < {settings.profitability_min_trades}")
    if win_rate < settings.profitability_min_win_rate:
        failures.append(f"win_rate {win_rate:.4f} < {settings.profitability_min_win_rate:.4f}")
    if profit_factor < settings.profitability_min_profit_factor:
        failures.append(f"profit_factor {profit_factor:.4f} < {settings.profitability_min_profit_factor:.4f}")
    if max_drawdown_pct >= settings.profitability_max_drawdown_pct:
        failures.append(f"max_drawdown_pct {max_drawdown_pct:.4f} >= {settings.profitability_max_drawdown_pct:.4f}")

    return {
        "production_ready": not failures,
        "failures": failures,
        "thresholds": {
            "min_trades": settings.profitability_min_trades,
            "min_win_rate": settings.profitability_min_win_rate,
            "min_profit_factor": settings.profitability_min_profit_factor,
            "max_drawdown_pct": settings.profitability_max_drawdown_pct,
        },
    }


def write_validation(metrics: dict[str, Any]) -> dict[str, Any]:
    payload = {
        **metrics,
        **evaluate_profitability(metrics),
        "validated_at_ms": int(time.time() * 1000),
    }
    path = Path(settings.profitability_validation_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def read_validation() -> dict[str, Any] | None:
    path = Path(settings.profitability_validation_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def can_trade_live() -> tuple[bool, list[str]]:
    if not settings.require_profitability_validation:
        return True, []
    validation = read_validation()
    if not validation:
        return False, ["No profitability validation artifact found"]
    if validation.get("production_ready") is True:
        return True, []
    failures = validation.get("failures") or ["Latest profitability validation failed"]
    return False, list(failures)
