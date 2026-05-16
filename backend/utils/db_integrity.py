"""
Database Integrity Manager for NEXUS.

Provides SQLite database integrity checks, automatic backups,
WAL mode configuration, and recovery procedures.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend")

DB_PATH = Path("data/nexus.db")
BACKUP_DIR = Path("data/backups")
MAX_BACKUPS = 7


class DatabaseIntegrityManager:
    """Manages SQLite database integrity, backups, and recovery."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.backup_dir = BACKUP_DIR
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def enable_wal_mode(self) -> None:
        """Enable Write-Ahead Logging for better concurrency and crash recovery."""
        conn = self._get_conn()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")
            conn.execute("PRAGMA temp_store=MEMORY")
            logger.info("Database WAL mode enabled")
        finally:
            conn.close()

    def check_integrity(self) -> dict[str, Any]:
        """Run full database integrity check."""
        result = {"status": "ok", "issues": [], "timestamp": int(time.time() * 1000)}
        conn = self._get_conn()
        try:
            quick_check = conn.execute("PRAGMA quick_check").fetchone()
            if quick_check and quick_check[0] != "ok":
                result["status"] = "corrupted"
                result["issues"].append(f"Integrity check failed: {quick_check[0]}")

            foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_keys:
                result["status"] = "warning"
                result["issues"].append(f"Foreign key violations: {len(foreign_keys)}")

            for table in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                name = table[0]
                count = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
                result.setdefault("tables", {})[name] = count

            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
            result["db_size_bytes"] = db_size
            result["db_size_mb"] = round(db_size / (1024 * 1024), 2)

        except Exception as e:
            result["status"] = "error"
            result["issues"].append(str(e))
        finally:
            conn.close()
        return result

    def create_backup(self) -> Path | None:
        """Create a timestamped backup of the database."""
        if not self.db_path.exists():
            logger.warning("Database file not found, skipping backup")
            return None

        ts = time.strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"nexus_{ts}.db"
        try:
            conn = self._get_conn()
            backup_conn = sqlite3.connect(str(backup_path))
            conn.backup(backup_conn)
            backup_conn.close()
            conn.close()
            self._cleanup_old_backups()
            logger.info(f"Database backup created: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"Database backup failed: {e}")
            return None

    def restore_backup(self, backup_path: Path | None = None) -> bool:
        """Restore database from the most recent (or specified) backup."""
        if backup_path is None:
            backups = sorted(self.backup_dir.glob("nexus_*.db"))
            if not backups:
                logger.error("No backups available for restore")
                return False
            backup_path = backups[-1]

        if not backup_path.exists():
            logger.error(f"Backup file not found: {backup_path}")
            return False

        try:
            integrity = self._check_file_integrity(backup_path)
            if not integrity:
                logger.error(f"Backup file corrupted: {backup_path}")
                return False

            if self.db_path.exists():
                self.db_path.rename(self.db_path.with_suffix(".db.corrupted"))
            shutil.copy2(backup_path, self.db_path)
            logger.info(f"Database restored from: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"Database restore failed: {e}")
            return False

    def vacuum(self) -> None:
        """Reclaim unused space and defragment the database."""
        conn = self._get_conn()
        try:
            conn.execute("VACUUM")
            logger.info("Database vacuum completed")
        finally:
            conn.close()

    def analyze(self) -> None:
        """Update query planner statistics."""
        conn = self._get_conn()
        try:
            conn.execute("ANALYZE")
            logger.info("Database analyze completed")
        finally:
            conn.close()

    def _check_file_integrity(self, path: Path) -> bool:
        """Check if a database file is valid."""
        try:
            conn = sqlite3.connect(str(path))
            result = conn.execute("PRAGMA quick_check").fetchone()
            conn.close()
            return result is not None and result[0] == "ok"
        except Exception:
            return False

    def _cleanup_old_backups(self) -> None:
        """Remove old backups beyond the maximum count."""
        backups = sorted(self.backup_dir.glob("nexus_*.db"))
        while len(backups) > MAX_BACKUPS:
            oldest = backups.pop(0)
            oldest.unlink()
            logger.info(f"Removed old backup: {oldest}")

    def _get_conn(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(self.db_path))


db_integrity = DatabaseIntegrityManager()
