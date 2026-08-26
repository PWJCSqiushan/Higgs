# Memory V2 / reminders implementation status

## Implemented

- QQ online state is separate from transport state. get_login_info and lifecycle hints drive qq_online; replies and reminders pause while QQ is offline.
- All accepted inbound messages enter memory_observations; a background reconciler runs every 15 minutes in batches of 50.
- High-frequency historical sources are excluded before candidate backfill. Backfill never auto-activates memories.
- Low-risk repeated owner preferences can auto-activate at confidence 0.90 and two independent message IDs. Credentials, permissions, owner claims, prompt injection and sensitive facts remain manual/quarantined.
- Memory governance and reminder commands use short IDs and owner-only authorization.
- Reminder creation requires the owner in a whitelisted private chat or group, plus explicit confirmation; delivery remains private by default. Sends are idempotent and retry at due, +5, +15 and +30 minutes; offline delivery is paused.
- Lexical retrieval uses SQLite FTS5 trigram when available. FTS and vector ranks are fused with reciprocal-rank fusion inside the exact principal scope.
- The default embedding backend is a local deterministic trigram hash vectorizer. It keeps QQ text on the server. A remote OpenAI-compatible backend is opt-in with R_AGENT_EMBEDDING_BACKEND=remote.
- GitHub Actions runs uv, Ruff and the complete pytest suite on every push and pull request.
- Model-assisted extraction is implemented behind `R_AGENT_MEMORY_MODEL_CANDIDATES=shadow`.
  It accepts only exact `memory-candidate-v1` JSON tied to the current evidence message;
  credentials, owner/permission claims and prompt injection are rejected or quarantined locally.
- Model proposals enter the separate `model_memory_candidate_shadow` review table. That component
  deliberately has no activation, replacement or deletion operation, and any model failure leaves
  deterministic reconciliation unchanged.
- The Chinese evaluation suite contains 30 cases and compares deterministic versus model-assisted
  recall, false extraction and admitted-pollution rates. Passing the offline suite authorizes only
  shadow evaluation, not production activation.

## Deliberately external/manual gates

- PushPlus incident notifications require the owner to place the token in /srv/secrets/higgs/higgs.env; the token is never committed or printed.
- A real non-empty memory recall requires two owner messages that match a safe preference pattern, then a recall-triggering message. The historical chat set did not contain enough safe atomic facts, so it was correctly excluded.
- Reminder delivery and offline replay still require one real owner-only QQ acceptance test after login recovery.
- Model candidate shadow remains off by default. It may be enabled only after reviewing the local
  30-case report; production candidates still require owner review and cannot auto-activate.

## Acceptance commands

/higgs memory stats
/higgs memory observations
/higgs memory list candidate 1
/higgs memory list active 1
/higgs memory backfill preview
/higgs remind list

For a real memory test, send the same low-risk preference twice in private chat, wait for the 15-minute reconciliation (or restart only Higgs agent), then ask a related question and inspect /higgs memory stats.
