from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.config import settings


@dataclass(frozen=True)
class ProfitabilityGateResult:
    allowed: bool
    production_ready: bool
    blockers: list[str]
    artifact: dict[str, Any] | None = None


def _artifact_path() -> Path:
    return Path(settings.profitability_validation_path)


def read_validation_artifact(path: Path | None = None) -> dict[str, Any] | None:
    target = path or _artifact_path()
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def evaluate_profitability_artifact(artifact: dict[str, Any] | None = None) -> ProfitabilityGateResult:
    if not settings.require_profitability_validation:
        return ProfitabilityGateResult(True, True, [], artifact)

    data = artifact if artifact is not None else read_validation_artifact()
    if data is None:
        return ProfitabilityGateResult(
            allowed=False,
            production_ready=False,
            blockers=[f"Profitability validation artifact missing: {settings.profitability_validation_path}"],
            artifact=None,
        )

    blockers: list[str] = []
    trade_count = int(data.get("trade_count", data.get("total_trades", 0)) or 0)
    win_rate = float(data.get("win_rate", 0.0) or 0.0)
    profit_factor = float(data.get("profit_factor", 0.0) or 0.0)
    max_drawdown_pct = float(data.get("max_drawdown_pct", 100.0) or 100.0)

    if trade_count < settings.profitability_min_trades:
        blockers.append(f"trade_count {trade_count} < {settings.profitability_min_trades}")
    if win_rate < settings.profitability_min_win_rate:
        blockers.append(f"win_rate {win_rate:.4f} < {settings.profitability_min_win_rate:.4f}")
    if profit_factor < settings.profitability_min_profit_factor:
        blockers.append(f"profit_factor {profit_factor:.4f} < {settings.profitability_min_profit_factor:.4f}")
    if max_drawdown_pct >= settings.profitability_max_drawdown_pct:
        blockers.append(f"max_drawdown_pct {max_drawdown_pct:.4f} >= {settings.profitability_max_drawdown_pct:.4f}")

    if data.get("production_ready") is False and not blockers:
        blockers.append("production_ready is false")

    return ProfitabilityGateResult(
        allowed=not blockers,
        production_ready=not blockers,
        blockers=blockers,
        artifact=data,
    )


def summarize_gate() -> dict[str, Any]:
    result = evaluate_profitability_artifact()
    return {
        "enabled": settings.require_profitability_validation,
        "allowed": result.allowed,
        "production_ready": result.production_ready,
        "blockers": result.blockers,
        "artifact_path": settings.profitability_validation_path,
        "checked_at_ms": int(time.time() * 1000),
        "artifact": result.artifact,
    }
