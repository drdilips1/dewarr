# Review account permissions after restore

This implements the household-access part of S09-02 / FR-02 / FR-36 / AT-25 and AT-27. The designated recovery operator can confirm or change restored account status, role, member automation permission and library grants. The persistent restore pause, historical queue boundary and saved-approval protections remain in force.

## Operator workflow

1. Run fresh read-only checks and choose **Recovery status**. Each saved account appears as an access finding, including disabled accounts and the operator.
2. Choose **Review permissions**. Inspect the account's enabled state, role, automation privilege and library grants. The operator cannot disable or demote their own recovery account.
3. Choose **Preview permissions**. The review shows saved and proposed permissions side by side in document order, including the broader access of administrators.
4. Choose **Confirm reviewed permissions**. The restricted worker rechecks the exact checkpoint, operator, latest scan, revision, expiration and complete local context before applying the batch atomically.
5. Run fresh checks after a change. An unchanged reviewed identity and grant set appears as **Access reviewed**. An account's credential identity or permissions changing makes it require review again.

Confirming unchanged permissions records evidence without clearing that account's sessions. Changing another account's permissions clears its sessions. The current operator retains their session. Other accounts still cannot sign in while restore review is active, even if the operator re-enables them. Users, list ownership, library assets, acquisition reasons/reservations and external files are not deleted or reassigned by this workflow.

Administrators have access to connected libraries and automation controls independently of member grants or the member automation flag. Viewers cannot acquire books or be granted acquisition automation. The form and preview explain these semantics; a checkbox does not silently constrain administrator authority.

## Library grants and current inventory

Existing grants can be retained or removed even while their backend is unavailable. This reviews local intended access, not current remote access.

Adding a grant requires an enabled accessible library with a completed post-restore inventory reconciliation from this checkpoint. Its recorded connection signature must still match the current integration, and the latest scan must contain a complete matching inventory observation. Changing credentials or observed inventory requires another inventory reconciliation before adding grants. A recent timestamp alone is insufficient proof.

The shared context check catches permission, credential, library and configuration changes between preview, acceptance and worker application. Current backend configuration and wanted-work activation still need their own recovery workflow; this access review does not approve dispatch or resume.

## Durable contract

The API provides POST `/api/recovery/access-reconciliations`, GET `/api/recovery/access-reconciliations/{id}` and POST `/api/recovery/access-reconciliations/{id}/accept`. Preparation accepts one to 100 distinct account findings and their explicit desired permissions. Exact command replay returns the existing receipt; reusing a key for different choices is rejected. Acceptance requires the exact preview revision and CSRF/origin validation. Only the active designated administrator can read or mutate a review.

The shared recovery engine serializes accepted corrections. Any failed item rolls back the entire account/grant/session/audit batch. A fresh scan or a changed context holds stale work. Existing queue jobs, downloads and imports are not rescheduled. Review results contain a digest of the applied identity/permissions, not password hashes or connector secrets. Observations expose only the account and grant fields needed for review.

The restricted worker registry gains `recovery.access` and now contains eight explicit recovery tasks with no periodic or ordinary tasks. API and worker must be deployed together. Schema remains `0044_recovery_approvals`; no migration or new dependency is needed. Prepared reviews from earlier builds should be replaced by fresh observations.

## Evidence and remaining work

Verification covers permission removal, re-enablement, unchanged operator confirmation, new grants following actual fixture-backed inventory reconciliation, changed credentials, same-command replay, stale/context-changed reviews, exact revisions, CSRF, batch rollback and preservation of the restore pause. Browser coverage exercises the operator restrictions, member role/automation/grant edits, exact preview focus, persisted results and mobile reload while synthetic external state stays unchanged.

Measured results belong in [implementation status](IMPLEMENTATION-STATUS.md). Current connection/path configuration, uncertain external effects, reservations, fresh wanted-book activation and controlled resume remain required. Actual restored-state qualification, live service compatibility, supported deployment and full PRD acceptance remain separate gates.
