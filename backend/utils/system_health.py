"""System health aggregator for the AI Lab.

Exposes a lightweight snapshot of self-heal status and panel freshness
to be included in the WebSocket stats payload.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_system_health() -> dict:
    """Return a dict combining self-heal and panel-freshness status."""
    out: dict = {}
    try:
        from backend.utils.self_heal import self_heal
        out["self_heal"] = self_heal.get_status()
    except Exception as e:
        logger.debug("self_heal unavailable: %s", e)
        out["self_heal"] = {}
    try:
        from backend.utils.panel_freshness import panel_freshness
        out["panel_freshness"] = panel_freshness.get_status()
    except Exception as e:
        logger.debug("panel_freshness unavailable: %s", e)
        out["panel_freshness"] = {}
    return out
