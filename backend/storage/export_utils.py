from __future__ import annotations

import csv
import io
import json
from typing import Any

from backend.storage.schema import get_conn


def export_to_csv(table: str, filters: dict[str, Any] | None = None) -> str:
    """Export table data to CSV string."""
    conn = get_conn()
    try:
        query = f"SELECT * FROM {table} WHERE 1=1"
        params: list[Any] = []

        if filters:
            for key, value in filters.items():
                if value is not None:
                    query += f" AND {key}=?"
                    params.append(value)

        query += " ORDER BY timestamp DESC LIMIT 10000"
        rows = conn.execute(query, params).fetchall()

        if not rows:
            return ""

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        for row in rows:
            cleaned = {}
            for k, v in row.items():
                if isinstance(v, (dict, list)):
                    cleaned[k] = json.dumps(v)
                else:
                    cleaned[k] = v
            writer.writerow(cleaned)

        return output.getvalue()
    finally:
        conn.close()


def export_to_json(table: str, filters: dict[str, Any] | None = None) -> str:
    """Export table data to JSON string."""
    conn = get_conn()
    try:
        query = f"SELECT * FROM {table} WHERE 1=1"
        params: list[Any] = []

        if filters:
            for key, value in filters.items():
                if value is not None:
                    query += f" AND {key}=?"
                    params.append(value)

        query += " ORDER BY timestamp DESC LIMIT 10000"
        rows = conn.execute(query, params).fetchall()

        results = []
        for row in rows:
            d = dict(row)
            for k, v in d.items():
                if isinstance(v, str):
                    try:
                        d[k] = json.loads(v)
                    except (json.JSONDecodeError, TypeError):
                        pass
            results.append(d)

        return json.dumps(results, indent=2)
    finally:
        conn.close()


VALID_EXPORT_TABLES = {
    "market_snapshots",
    "pattern_history",
    "regime_history",
    "metrics_history",
    "candle_archive",
    "ai_decisions_history",
    "liquidity_history",
    "orderbook_history",
    "performance_daily",
}
