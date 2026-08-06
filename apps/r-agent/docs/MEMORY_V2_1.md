# Memory V2.1 safety contract

Memory V2.1 keeps raw observations, reviewable memory and recall decisions as
separate stages. An observation failure is stored as a content-free error type
and hash, so one malformed row cannot stop later rows. Failed rows can be listed
and explicitly retried by short observation ID.

Only the reconciler receives the verified principal role. The legacy passive
learner is candidate-only. A non-owner can never auto-activate memory; only a
verified owner's repeated low-risk preference (at least two messages and 0.90
confidence) is eligible. Sensitive data, privilege claims and owner-relationship
claims remain manual or quarantined.

Schema migration is idempotent and adds importance, source trust, validity
intervals and `supersedes_item_id`. Activating a reviewed revision closes and
invalidates the previous active version instead of overwriting history.

Recall has no arbitrary fallback. FTS is updated incrementally by SQLite
triggers, vector-only matches require a similarity threshold, and fused results
are capped at eight records and roughly 1,200 characters. HNSW is deliberately
not enabled at the current data size.

Backups include all eight runtime SQLite stores: identity, journal,
conversation, memory, reply audit, reminders, conversation guard and the
content-free risk ledger. Restore
verification always targets a new empty directory; it never overwrites live
runtime databases.

Deferred gray feature: a model-assisted structured candidate extractor remains
disabled until its strict JSON schema, content bounds and adversarial tests are
reviewed. A model will only be allowed to propose candidates, never activate
memory.
