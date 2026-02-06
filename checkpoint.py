import sqlite3
from pathlib import Path
from typing import Optional

from models import Follower, LookupStatus


class CheckpointDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS followers (
                username TEXT PRIMARY KEY,
                followed_at INTEGER,
                follower_count INTEGER,
                following_count INTEGER,
                full_name TEXT,
                is_verified INTEGER,
                is_private INTEGER,
                lookup_status TEXT NOT NULL DEFAULT 'pending',
                lookup_source TEXT,
                error_message TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.commit()

    def import_from_export(self, followers: list[Follower]) -> tuple[int, int]:
        """Import followers from parsed export. Returns (imported, skipped) counts."""
        imported = 0
        skipped = 0
        for f in followers:
            try:
                self._conn.execute(
                    """INSERT INTO followers (username, followed_at, lookup_status)
                       VALUES (?, ?, ?)""",
                    (f.username, f.followed_at, LookupStatus.PENDING.value),
                )
                imported += 1
            except sqlite3.IntegrityError:
                skipped += 1
        self._conn.commit()
        return imported, skipped

    def get_pending(
        self, batch_size: int = 100, max_retries: int = 3
    ) -> list[Follower]:
        """Get a batch of pending followers for lookup."""
        cursor = self._conn.execute(
            """SELECT username, followed_at, follower_count, following_count,
                      full_name, is_verified, is_private, lookup_status,
                      lookup_source, error_message, retry_count
               FROM followers
               WHERE lookup_status IN (?, ?)
                 AND retry_count < ?
               ORDER BY retry_count ASC, username ASC
               LIMIT ?""",
            (LookupStatus.PENDING.value, LookupStatus.RATE_LIMITED.value, max_retries, batch_size),
        )
        return [self._row_to_follower(row) for row in cursor.fetchall()]

    def update_result(self, follower: Follower):
        """Update a follower's lookup result. Atomic single-row write."""
        self._conn.execute(
            """UPDATE followers SET
                follower_count = ?,
                following_count = ?,
                full_name = ?,
                is_verified = ?,
                is_private = ?,
                lookup_status = ?,
                lookup_source = ?,
                error_message = ?,
                retry_count = ?,
                updated_at = CURRENT_TIMESTAMP
               WHERE username = ?""",
            (
                follower.follower_count,
                follower.following_count,
                follower.full_name,
                1 if follower.is_verified else (0 if follower.is_verified is not None else None),
                1 if follower.is_private else (0 if follower.is_private is not None else None),
                follower.lookup_status.value,
                follower.lookup_source,
                follower.error_message,
                follower.retry_count,
                follower.username,
            ),
        )
        self._conn.commit()

    def get_stats(self) -> dict:
        """Get progress statistics."""
        cursor = self._conn.execute(
            """SELECT lookup_status, COUNT(*) FROM followers GROUP BY lookup_status"""
        )
        status_counts = dict(cursor.fetchall())

        cursor = self._conn.execute("SELECT COUNT(*) FROM followers")
        total = cursor.fetchone()[0]

        cursor = self._conn.execute(
            """SELECT lookup_source, COUNT(*) FROM followers
               WHERE lookup_status = ?
               GROUP BY lookup_source""",
            (LookupStatus.SUCCESS.value,),
        )
        source_counts = dict(cursor.fetchall())

        return {
            "total": total,
            "pending": status_counts.get(LookupStatus.PENDING.value, 0),
            "success": status_counts.get(LookupStatus.SUCCESS.value, 0),
            "failed": status_counts.get(LookupStatus.FAILED.value, 0),
            "rate_limited": status_counts.get(LookupStatus.RATE_LIMITED.value, 0),
            "by_source": source_counts,
        }

    def get_all_completed(self) -> list[Follower]:
        """Get all followers with successful lookups, sorted by follower count desc."""
        cursor = self._conn.execute(
            """SELECT username, followed_at, follower_count, following_count,
                      full_name, is_verified, is_private, lookup_status,
                      lookup_source, error_message, retry_count
               FROM followers
               WHERE lookup_status = ?
               ORDER BY follower_count DESC NULLS LAST""",
            (LookupStatus.SUCCESS.value,),
        )
        return [self._row_to_follower(row) for row in cursor.fetchall()]

    def get_all(self) -> list[Follower]:
        """Get all followers sorted by follower count desc (completed first, then pending)."""
        cursor = self._conn.execute(
            """SELECT username, followed_at, follower_count, following_count,
                      full_name, is_verified, is_private, lookup_status,
                      lookup_source, error_message, retry_count
               FROM followers
               ORDER BY
                 CASE WHEN lookup_status = 'success' THEN 0 ELSE 1 END,
                 follower_count DESC NULLS LAST,
                 username ASC"""
        )
        return [self._row_to_follower(row) for row in cursor.fetchall()]

    def _row_to_follower(self, row) -> Follower:
        return Follower(
            username=row[0],
            followed_at=row[1],
            follower_count=row[2],
            following_count=row[3],
            full_name=row[4],
            is_verified=bool(row[5]) if row[5] is not None else None,
            is_private=bool(row[6]) if row[6] is not None else None,
            lookup_status=LookupStatus(row[7]),
            lookup_source=row[8],
            error_message=row[9],
            retry_count=row[10],
        )

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
