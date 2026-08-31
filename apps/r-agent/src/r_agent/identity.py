"""External QQ identity to internal principal mapping."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from r_agent.events import InboundEvent


@dataclass(frozen=True, slots=True)
class Principal:
    principal_id: str
    role: str


@dataclass(frozen=True, slots=True)
class PrincipalKey:
    channel: str
    account_id: str
    external_identity: str

    @classmethod
    def from_event(cls, event: InboundEvent) -> PrincipalKey:
        channel = event.channel.strip().casefold()
        account_id = event.account_id.strip()
        external_identity = event.sender_id.strip()
        if not channel or not account_id or not external_identity:
            raise ValueError("principal key fields are required")
        return cls(channel, account_id, external_identity)


class IdentityBindingError(RuntimeError):
    """An explicit cross-channel identity binding conflicts with stored state."""


class IdentityStore:
    def __init__(
        self,
        path: Path,
        *,
        owner_qq: str | None,
        owner_identities: Iterable[tuple[str, str]] = (),
        account_scoped_official_enabled: bool = False,
    ) -> None:
        self.path = path
        self.owner_qq = owner_qq
        self.owner_identities = tuple(
            (channel.strip().casefold(), external_id.strip())
            for channel, external_id in owner_identities
            if channel.strip() and external_id.strip()
        )
        self.account_scoped_official_enabled = account_scoped_official_enabled

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
            if self.account_scoped_official_enabled:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS account_external_identities (
                        channel TEXT NOT NULL,
                        account_id TEXT NOT NULL,
                        external_id TEXT NOT NULL,
                        principal_id TEXT NOT NULL REFERENCES principals(principal_id),
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY(channel, account_id, external_id)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS configured_identity_accounts (
                        channel TEXT NOT NULL,
                        external_id TEXT NOT NULL,
                        account_id TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY(channel, external_id)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS identity_schema_meta (
                        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                        version INTEGER NOT NULL CHECK(version >= 1)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO identity_schema_meta(singleton, version)
                    VALUES (1, 2)
                    ON CONFLICT(singleton) DO UPDATE SET version = excluded.version
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
        for channel, external_id in self.owner_identities:
            self.bind_owner_identity(channel, external_id)

    def bind_owner_identity(self, channel: str, external_id: str) -> Principal:
        """Bind one configured external identity to the existing owner principal.

        This method is only for deployment configuration.  It never guesses a
        relationship and refuses to overwrite a pre-existing user mapping.
        """
        normalized_channel = channel.strip().casefold()
        normalized_id = external_id.strip()
        if not normalized_channel or not normalized_id:
            raise ValueError("owner identity channel and external id are required")
        if self.owner_qq is None:
            raise IdentityBindingError("owner QQ must be configured before cross-channel binding")

        owner = self.resolve("qq", self.owner_qq)
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT principal_id
                FROM external_identities
                WHERE channel = ? AND external_id = ?
                """,
                (normalized_channel, normalized_id),
            ).fetchone()
            if row is not None and str(row[0]) != owner.principal_id:
                raise IdentityBindingError(
                    "configured owner identity is already bound to another principal"
                )
            if row is None:
                conn.execute(
                    """
                    INSERT INTO external_identities(channel, external_id, principal_id)
                    VALUES (?, ?, ?)
                    """,
                    (normalized_channel, normalized_id, owner.principal_id),
                )
            conn.execute(
                "UPDATE principals SET role = 'owner' WHERE principal_id = ?",
                (owner.principal_id,),
            )
        return Principal(owner.principal_id, "owner")

    def _configured_owner_identity(self, channel: str, external_id: str) -> bool:
        return (channel, external_id) in self.owner_identities

    def resolve_account(self, channel: str, account_id: str, external_id: str) -> Principal:
        """Resolve one external identity inside an authenticated account namespace.

        Official OpenIDs are Bot-scoped.  Legacy rows deliberately remain in
        ``external_identities`` for rollback, but ordinary legacy users are not
        guessed into a Bot namespace.  Only an explicitly configured owner may
        reuse its existing principal, and its first authenticated Bot binding
        becomes immutable until an operator performs a separate rotation.
        """

        normalized_channel = channel.strip().casefold()
        normalized_account = account_id.strip()
        normalized_id = external_id.strip()
        if not normalized_channel or not normalized_account or not normalized_id:
            raise ValueError("channel, account id, and external id are required")
        if not self.account_scoped_official_enabled:
            raise IdentityBindingError("account-scoped official identity schema is disabled")
        if normalized_channel != "qq_official":
            return self.resolve(normalized_channel, normalized_id)

        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT p.principal_id, p.role
                FROM account_external_identities e
                JOIN principals p ON p.principal_id = e.principal_id
                WHERE e.channel = ? AND e.account_id = ? AND e.external_id = ?
                """,
                (normalized_channel, normalized_account, normalized_id),
            ).fetchone()
            if row is not None:
                return Principal(str(row["principal_id"]), str(row["role"]))

            if self._configured_owner_identity(normalized_channel, normalized_id):
                bound = conn.execute(
                    """
                    SELECT account_id
                    FROM configured_identity_accounts
                    WHERE channel = ? AND external_id = ?
                    """,
                    (normalized_channel, normalized_id),
                ).fetchone()
                if bound is not None and str(bound[0]) != normalized_account:
                    raise IdentityBindingError(
                        "configured owner identity is bound to another Bot account"
                    )
                owner_row = conn.execute(
                    """
                    SELECT p.principal_id, p.role
                    FROM external_identities e
                    JOIN principals p ON p.principal_id = e.principal_id
                    WHERE e.channel = 'qq' AND e.external_id = ?
                    """,
                    (self.owner_qq or "",),
                ).fetchone()
                if owner_row is None or str(owner_row["role"]) != "owner":
                    raise IdentityBindingError("configured owner principal is unavailable")
                owner = Principal(str(owner_row["principal_id"]), "owner")
                conn.execute(
                    """
                    INSERT OR IGNORE INTO configured_identity_accounts(
                        channel, external_id, account_id
                    ) VALUES (?, ?, ?)
                    """,
                    (normalized_channel, normalized_id, normalized_account),
                )
                principal = owner
            else:
                principal = Principal(str(uuid.uuid4()), "user")
                conn.execute(
                    "INSERT INTO principals(principal_id, role) VALUES (?, 'user')",
                    (principal.principal_id,),
                )

            try:
                conn.execute(
                    """
                    INSERT INTO account_external_identities(
                        channel, account_id, external_id, principal_id
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        normalized_channel,
                        normalized_account,
                        normalized_id,
                        principal.principal_id,
                    ),
                )
            except sqlite3.IntegrityError:
                row = conn.execute(
                    """
                    SELECT p.principal_id, p.role
                    FROM account_external_identities e
                    JOIN principals p ON p.principal_id = e.principal_id
                    WHERE e.channel = ? AND e.account_id = ? AND e.external_id = ?
                    """,
                    (normalized_channel, normalized_account, normalized_id),
                ).fetchone()
                if row is None:
                    raise
                return Principal(str(row["principal_id"]), str(row["role"]))
            return principal

    def resolve_event(self, event: InboundEvent) -> Principal:
        if (
            event.channel.strip().casefold() == "qq_official"
            and self.account_scoped_official_enabled
        ):
            key = PrincipalKey.from_event(event)
            return self.resolve_account(key.channel, key.account_id, key.external_identity)
        return self.resolve(event.channel, event.sender_id)

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

    def principal_id_for(
        self,
        channel: str,
        external_id: str,
        *,
        account_id: str | None = None,
    ) -> str | None:
        if account_id is not None and not self.account_scoped_official_enabled:
            raise IdentityBindingError("account-scoped official identity schema is disabled")
        with sqlite3.connect(self.path) as conn:
            if account_id is not None:
                row = conn.execute(
                    """
                    SELECT principal_id
                    FROM account_external_identities
                    WHERE channel = ? AND account_id = ? AND external_id = ?
                    """,
                    (channel.strip().casefold(), account_id.strip(), external_id.strip()),
                ).fetchone()
                return str(row[0]) if row is not None else None
            row = conn.execute(
                """
                SELECT principal_id
                FROM external_identities
                WHERE channel = ? AND external_id = ?
                """,
                (channel, external_id),
            ).fetchone()
            return str(row[0]) if row is not None else None

    def delete_external_identity(
        self,
        channel: str,
        external_id: str,
        *,
        account_id: str | None = None,
    ) -> bool:
        if account_id is not None and not self.account_scoped_official_enabled:
            raise IdentityBindingError("account-scoped official identity schema is disabled")
        with sqlite3.connect(self.path) as conn:
            if account_id is not None:
                row = conn.execute(
                    """
                    SELECT principal_id
                    FROM account_external_identities
                    WHERE channel = ? AND account_id = ? AND external_id = ?
                    """,
                    (channel.strip().casefold(), account_id.strip(), external_id.strip()),
                ).fetchone()
                if row is None:
                    return False
                principal_id = str(row[0])
                conn.execute(
                    """
                    DELETE FROM account_external_identities
                    WHERE channel = ? AND account_id = ? AND external_id = ?
                    """,
                    (channel.strip().casefold(), account_id.strip(), external_id.strip()),
                )
                remaining = conn.execute(
                    """
                    SELECT 1 FROM external_identities WHERE principal_id = ?
                    UNION ALL
                    SELECT 1 FROM account_external_identities WHERE principal_id = ?
                    LIMIT 1
                    """,
                    (principal_id, principal_id),
                ).fetchone()
                if remaining is None:
                    conn.execute("DELETE FROM principals WHERE principal_id = ?", (principal_id,))
                return True
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
            if self.account_scoped_official_enabled:
                remaining = conn.execute(
                    """
                    SELECT 1 FROM external_identities WHERE principal_id = ?
                    UNION ALL
                    SELECT 1 FROM account_external_identities WHERE principal_id = ?
                    LIMIT 1
                    """,
                    (principal_id, principal_id),
                ).fetchone()
            else:
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
