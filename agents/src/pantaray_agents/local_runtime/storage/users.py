from __future__ import annotations

import sqlite3


def ensure_user_row(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    timestamp: str | None = None,
) -> None:
    if timestamp is None:
        connection.execute(
            """
            INSERT OR IGNORE INTO users(
                user_id,
                ui_language,
                created_at,
                updated_at
            ) VALUES (
                ?,
                'ja',
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            )
            """,
            (user_id,),
        )
        return

    connection.execute(
        """
        INSERT OR IGNORE INTO users(
            user_id,
            ui_language,
            created_at,
            updated_at
        ) VALUES (?, 'ja', ?, ?)
        """,
        (user_id, timestamp, timestamp),
    )
