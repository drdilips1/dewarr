# Review saved automation during recovery

This extends the [command recovery review](RECOVERY-COMMANDS.md) within S09-02 / FR-36 / AT-25. An operator can selectively pause automatic imports, list synchronization and Hardcover write-back while the persistent restore checkpoint stays active. It does not resolve external effects, withdraw wanted books or resume the installation.

## Operator workflow

1. Run fresh read-only checks and filter to Recovery status. Enabled saved settings appear as **Automation ready** findings, independently of request/controller findings.
2. Select **Review automation** for a finding. The preview explains exactly which setting will pause and which records remain unchanged.
3. Select **Pause selected automation**. A mixed API batch of settings and historical commands uses the same review engine, revision, expiration and acceptance checks.
4. Review other policies and unresolved external findings separately. Pausing list synchronization does not implicitly pause its acquisition policy or reconcile a pending write.

The browser presents one finding per review; the existing command-review API supports 1–100 selections per batch. All selected changes and audits commit together or roll back together. The designated active administrator, checkpoint, latest observation, complete current local context and exact review revision must still agree when the worker applies the changes. Repeat acceptance returns its receipt without advancing generations twice.

## Exact effects

| Setting | Change | Preserved evidence |
| --- | --- | --- |
| Automatic import policy | Disable and advance its generation, invalidating prior automatic-import authority | Destination configuration, original approver, existing import records, reservations and media |
| List subscription | Disable, advance generation and clear its old worker token/lease, due time and operation association | Configuration, membership, exclusions, baseline, last successful observation, old operation and independent wanted reasons |
| Hardcover write-back policy | Disable, advance generation and clear its last confirmation timestamp | Account/list binding, sequence, queued or uncertain outbound commands and existing remote-write lease evidence |

Changing a policy is not proof that a remote mutation did or did not happen. Outbound attempt markers and leases remain evidence for [outbound reconciliation](RECOVERY-OUTBOUND.md). Subscription scheduling stops because the subscription is disabled; the saved generation/token cannot publish a new baseline. Existing import policy checks reject the old generation. Offline restore still requires stopping ordinary processes; this review is not an in-flight cancellation primitive.

The recovery context now includes automatic-import policy records, including configuration, approval and generation. Changing these between preview and execution invalidates the review. Already-disabled settings are not offered again. Selected and unselected settings remain distinct, and namespace-qualified IDs prevent cross-family batch identity collisions.

## Destination verification after restore

An old destination probe remains stored as evidence but no longer makes a route available for publication or automatic-import approval. The destination view checks its probe operation against the durable approval boundary. A probe without an associated operation also cannot qualify a route when restore history exists. Incomplete legacy boundaries remain held.

A fresh route test must verify current mounted paths, hardlink/no-replace behavior and the Audiobookshelf mapping. Only its fresh, successful operation can qualify a new automatic-import approval. The test uses a saved plan as read-only file input; it does not publish from that historical plan or reactivate historical imports. Those plans and work IDs retain their independent protection.

## Deployment and verification

Deploy matching API, worker and UI builds on unchanged schema `0044_recovery_approvals`. No new task, endpoint, migration or runtime dependency is introduced; the restricted registry still contains seven recovery tasks. Existing command-review endpoints gain the three setting categories. Older observation/review digests require a fresh scan after the expanded context.

Verification includes each policy independently, untouched siblings, immutable memberships/exclusions/outbound evidence, replay receipts, generation and credential/configuration changes, revoked operator access, atomic multi-setting rollback, route re-verification with real synthetic files, and the browser's explicit list-synchronization pause. See [implementation status](IMPLEMENTATION-STATUS.md) for measured results and deployment evidence.

Current permission/configuration confirmation, unresolved or untracked effects, reservations, wanted-book activation and controlled resume remain required. Full populated restore/resume, real provider and supported-platform qualification, reference load and RPO/RTO remain open. This increment does not close S09 or any other incomplete PRD stage.
