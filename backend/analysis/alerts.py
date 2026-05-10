from __future__ import annotations

import time
import uuid
from typing import Any

from backend.storage import repository as repo


def create_alert(
    alert_type: str,
    title: str,
    message: str | None = None,
    severity: str = "info",
    symbol: str | None = None,
    data: dict | None = None,
) -> dict:
    alert = {
        "id": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
        "type": alert_type,
        "severity": severity,
        "symbol": symbol,
        "title": title,
        "message": message,
        "data": data,
    }
    repo.save_alert(alert)
    return alert


def check_signal_alert(signal: dict) -> dict | None:
    if signal.get("confidence", 0) >= 0.75:
        return create_alert(
            alert_type="high_confidence_signal",
            severity="high",
            title=f"{signal['side'].upper()} signal {signal['confidence']:.0%} confidence",
            message=f"Entry {signal['entry']:.2f}, SL {signal['stop_loss']:.2f}, TP {signal['exit_price']:.2f}",
            data=signal,
        )
    return None


def check_liquidity_alert(event: dict) -> dict | None:
    if event.get("engineered_score", 0) >= 0.7:
        return create_alert(
            alert_type="engineered_liquidity",
            severity="medium",
            title=f"Liquidity sweep {event.get('engineered_score',0):.0%} engineered",
            message=event.get("reason", ""),
            data=event,
        )
    return None


def check_regime_alert(old_phase: str | None, new_phase: str) -> dict | None:
    if old_phase and old_phase != new_phase:
        return create_alert(
            alert_type="regime_change",
            severity="medium",
            title=f"Regime changed: {old_phase} -> {new_phase}",
            data={"from": old_phase, "to": new_phase},
        )
    return None
