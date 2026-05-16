from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from backend.storage.history_repository import (
    get_pattern_stats,
    get_regime_distribution,
    get_ai_accuracy,
    get_daily_performance,
    save_daily_performance,
    get_storage_stats,
)
from backend.storage.schema import get_conn

logger = logging.getLogger(__name__)


class DailyReportGenerator:
    """Generates and saves daily performance reports."""

    def __init__(self, report_hour: int = 0, report_minute: int = 0):
        self.report_hour = report_hour
        self.report_minute = report_minute
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the daily report generator."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("DailyReportGenerator started")

    async def stop(self) -> None:
        """Stop the daily report generator."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DailyReportGenerator stopped")

    async def _run_loop(self) -> None:
        """Main loop - checks every minute if it's time to generate report."""
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                if now.hour == self.report_hour and now.minute == self.report_minute:
                    await self._generate_report()
                    await asyncio.sleep(60)
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"DailyReportGenerator error: {e}", exc_info=True)
                await asyncio.sleep(300)

    async def _generate_report(self) -> None:
        """Generate and save the daily report."""
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            logger.info(f"Generating daily report for {today}")

            pattern_stats = get_pattern_stats(days=1)
            regime_dist = get_regime_distribution(days=1)
            ai_accuracy = get_ai_accuracy(days=1)
            storage_stats = get_storage_stats()

            perf_data = get_daily_performance(start_date=today, end_date=today)
            existing = next((p for p in perf_data if p["date"] == today), None)

            pnl = existing.get("paper_pnl", 0) if existing else 0
            win_rate = existing.get("paper_win_rate") if existing else None
            avg_regime = existing.get("avg_regime") if existing else None
            dominant_pattern = existing.get("dominant_pattern") if existing else None
            avg_atr = existing.get("avg_atr") if existing else None
            avg_rsi = existing.get("avg_rsi") if existing else None
            max_dd = existing.get("max_drawdown_pct") if existing else None

            report = {
                "date": today,
                "generated_at": int(time.time() * 1000),
                "pattern_summary": pattern_stats,
                "regime_distribution": regime_dist,
                "ai_accuracy": ai_accuracy,
                "performance": {
                    "paper_pnl": pnl,
                    "paper_win_rate": win_rate,
                    "avg_regime": avg_regime,
                    "dominant_pattern": dominant_pattern,
                    "avg_atr": avg_atr,
                    "avg_rsi": avg_rsi,
                    "max_drawdown_pct": max_dd,
                },
                "storage_stats": storage_stats,
            }

            save_daily_report(report)
            logger.info(f"Daily report saved for {today}")

        except Exception as e:
            logger.error(f"Failed to generate daily report: {e}", exc_info=True)

    def generate_now(self) -> dict:
        """Generate report immediately (synchronous)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        pattern_stats = get_pattern_stats(days=1)
        regime_dist = get_regime_distribution(days=1)
        ai_accuracy = get_ai_accuracy(days=1)
        storage_stats = get_storage_stats()

        return {
            "date": today,
            "generated_at": int(time.time() * 1000),
            "pattern_summary": pattern_stats,
            "regime_distribution": regime_dist,
            "ai_accuracy": ai_accuracy,
            "storage_stats": storage_stats,
        }


def save_daily_report(report: dict) -> None:
    """Save a daily report to the database."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO daily_reports (date, generated_at, report_data)
            VALUES (?, ?, ?)
        """, (
            report["date"],
            report["generated_at"],
            json.dumps(report),
        ))
        conn.commit()
    finally:
        conn.close()


def get_daily_reports(limit: int = 30) -> list[dict]:
    """Get recent daily reports."""
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT date, generated_at, report_data
            FROM daily_reports ORDER BY date DESC LIMIT ?
        """, (limit,)).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("report_data"):
                try:
                    d["report_data"] = json.loads(d["report_data"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results
    finally:
        conn.close()


daily_reporter = DailyReportGenerator()
