import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class StateStore:
    """SQLite-backed state for stats, seen assets, and feed cursors."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_assets (
                    asset_id TEXT PRIMARY KEY,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    shown_count INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feed_cursor (
                    feed_key TEXT PRIMARY KEY,
                    next_page INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get_state_json(self, key: str) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        return json.loads(row["value"])

    def set_state_json(self, key: str, value: Any) -> None:
        payload = json.dumps(value, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, payload),
            )

    def get_feed_cursor(self, feed_key: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT next_page FROM feed_cursor WHERE feed_key = ?",
                (feed_key,),
            ).fetchone()
        if not row:
            return 1
        return max(1, int(row["next_page"]))

    def set_feed_cursor(self, feed_key: str, next_page: int) -> None:
        safe_page = max(1, int(next_page))
        now = datetime.utcnow().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO feed_cursor(feed_key, next_page, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(feed_key)
                DO UPDATE SET next_page = excluded.next_page, updated_at = excluded.updated_at
                """,
                (feed_key, safe_page, now),
            )

    def mark_seen(self, asset_ids: list[str]) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        with self._connect() as conn:
            for asset_id in asset_ids:
                conn.execute(
                    """
                    INSERT INTO seen_assets(asset_id, first_seen_at, last_seen_at, shown_count)
                    VALUES(?, ?, ?, 1)
                    ON CONFLICT(asset_id)
                    DO UPDATE SET
                        last_seen_at = excluded.last_seen_at,
                        shown_count = seen_assets.shown_count + 1
                    """,
                    (asset_id, now, now),
                )

    def filter_unseen(self, asset_ids: list[str], cooldown_days: int) -> list[str]:
        ids = [asset_id for asset_id in asset_ids if asset_id]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT asset_id, last_seen_at FROM seen_assets WHERE asset_id IN ({placeholders})",
                tuple(ids),
            ).fetchall()
        seen_map = {row["asset_id"]: row["last_seen_at"] for row in rows}
        cutoff = datetime.utcnow() - timedelta(days=max(0, int(cooldown_days)))
        unseen = []
        for asset_id in ids:
            last_seen_raw = seen_map.get(asset_id)
            if not last_seen_raw:
                unseen.append(asset_id)
                continue
            last_seen_dt = datetime.fromisoformat(last_seen_raw)
            if last_seen_dt < cutoff:
                unseen.append(asset_id)
        return unseen

    def clear_seen(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM seen_assets")
