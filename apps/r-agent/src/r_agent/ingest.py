"""One-event vertical slice: policy → identity → journal."""

from __future__ import annotations

from dataclasses import dataclass

from r_agent.access import IngressDecision, IngressPolicy
from r_agent.events import InboundEvent
from r_agent.identity import IdentityBindingError, IdentityStore
from r_agent.journal import Journal


@dataclass(frozen=True, slots=True)
class IngestResult:
    decision: IngressDecision
    stored: bool = False
    duplicate: bool = False


class IngestService:
    def __init__(
        self,
        *,
        policy: IngressPolicy,
        identities: IdentityStore,
        journal: Journal,
    ) -> None:
        self.policy = policy
        self.identities = identities
        self.journal = journal

    def initialize(self) -> None:
        self.identities.initialize()
        self.journal.initialize()

    def ingest(self, event: InboundEvent) -> IngestResult:
        decision = self.policy.decide(event)
        if decision is not IngressDecision.ACCEPT:
            return IngestResult(decision=decision)
        if event.channel.strip().casefold() == "qq_official" and not event.account_id.strip():
            return IngestResult(decision=IngressDecision.ACCOUNT_NOT_ALLOWED)
        try:
            principal = self.identities.resolve_event(event)
        except (ValueError, IdentityBindingError):
            return IngestResult(decision=IngressDecision.ACCOUNT_NOT_ALLOWED)
        stored = self.journal.append(event, principal)
        return IngestResult(
            decision=decision,
            stored=stored,
            duplicate=not stored,
        )
