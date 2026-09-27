"""Session store retention related constants."""

from __future__ import annotations

# ACK が来なかった completed process metadata を回収するための保険保持時間。
SESSION_STORE_RETENTION_SECONDS = 60 * 60 * 3
