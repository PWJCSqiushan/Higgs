"""External QQ identity to internal principal mapping."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Principal:
    principal_id: str
    role: str


class IdentityStore:
    def __init__(self, path: Path, *, owner_qq: str | None) -> None:
        self.path = path
        self.owner_qq = owner_qq

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS principals (
                    principal_id TEXT PRIMARY KEY,
                    role TEXT NOT NULL CHECK(role IN ('owner', 'user', 'blocked')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS external_identities (
                    channel TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(channel, external_id)
                )
                """
            )
            # Deployment configuration is the sole authority for owner role.
            # Rotation/removal must demote a previously configured owner.
            conn.execute(
                """
                UPDATE principals
                SET role = 'user'
                WHERE role = 'owner'
                  AND principal_id NOT IN (
                    SELECT principal_id
                    FROM external_identities
                    WHERE channel = 'qq' AND external_id = ?
                  )
                """,
                (self.owner_qq or "",),
            )
            if self.owner_qq is not None:
                conn.execute(
                    """
                    UPDATE principals
                    SET role = 'owner'
                    WHERE principal_id IN (
                        SELECT principal_id
                        FROM external_identities
                        WHERE channel = 'qq' AND external_id = ?
                    )
                    """,
                    (self.owner_qq,),
                )

    def resolve(self, channel: str, external_id: str) -> Principal:
        desired_role = "owner" if channel == "qq" and external_id == self.owner_qq else "user"
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT p.principal_id, p.role
                FROM external_identities e
                JOIN principals p ON p.principal_id = e.principal_id
                WHERE e.channel = ? AND e.external_id = ?
                """,
                (channel, external_id),
            ).fetchone()
            if row is not None:
                # Configuration can promote the exact owner identity, but chat data
                # can never perform this transition.
                if desired_role == "owner" and row["role"] != "owner":
                    conn.execute(
                        "UPDATE principals SET role = 'owner' WHERE principal_id = ?",
                        (row["principal_id"],),
                    )
                    return Principal(str(row["principal_id"]), "owner")
                return Principal(str(row["principal_id"]), str(row["role"]))

            principal_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO principals(principal_id, role) VALUES (?, ?)",
                (principal_id, desired_role),
            )
            conn.execute(
                """
                INSERT INTO external_identities(channel, external_id, principal_id)
                VALUES (?, ?, ?)
                """,
                (channel, external_id, principal_id),
            )
            return Principal(principal_id, desired_role)

    def principal_id_for(self, channel: str, external_id: str) -> str | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT principal_id
                FROM external_identities
                WHERE channel = ? AND external_id = ?
                """,
                (channel, external_id),
            ).fetchone()
            return str(row[0]) if row is not None else None

    def delete_external_identity(self, channel: str, external_id: str) -> bool:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT principal_id
                FROM external_identities
                WHERE channel = ? AND external_id = ?
                """,
                (channel, external_id),
            ).fetchone()
            if row is None:
                return False
            principal_id = str(row[0])
            conn.execute(
                "DELETE FROM external_identities WHERE channel = ? AND external_id = ?",
                (channel, external_id),
            )
            remaining = conn.execute(
                "SELECT 1 FROM external_identities WHERE principal_id = ? LIMIT 1",
                (principal_id,),
            ).fetchone()
            if remaining is None:
                conn.execute(
                    "DELETE FROM principals WHERE principal_id = ?",
                    (principal_id,),
                )
            return True
