# Importing a reviewed omnibus

A completed ebook omnibus or inseparable audiobook collection can now carry a reviewed list of complete books through the ordinary import workflow. Select the catalog edition of the whole collection, open **Books contained in this collection**, select two to one hundred contained works, and confirm that the inspected files contain each complete book. Saving a plan freezes those identities; it does not establish ownership.

The publisher uses the configured naming, destination and hardlink/copy rules for one physical edition. It preserves the source files, publishes one collection folder and waits for the corresponding Audiobookshelf item. Only successful backend confirmation establishes the contained books as available. Each child shows **In collection** and opens that same item. No artificial child files, playback items or catalog editions are created.

## Identity and request satisfaction

The imported collection retains its own confirmed catalog version, allowing repeat imports to recognize the physical edition already present. Child coverage is separate: the collection's ISBN, language, edition and narrator credits do not become claims about individual children. Generic requests can be satisfied by complete contained books; standalone, exact-edition or uncorroborated language/narrator requests remain wanted.

The import plan records each selected child's title, authors, canonical identity and revision. Changes before submission or publication require a fresh review. Changes while awaiting library detection hold the operation without replacing or removing published files. Accepted coverage is committed with backend confirmation and queues ordinary request reconciliation for both the physical work and the contained books.

An unchanged inventory refresh retains the physical edition and reviewed coverage. Changed backend/file evidence or a changed physical version invalidates coverage; later observations cannot silently restore that confirmation. Current library grants still determine what each user sees and which requests can be satisfied.

## Correction and deployment

[Reviewing an existing library collection](COLLECTION-CONTENTS.md) remains available and reversible. That action alone does not confirm a physical catalog edition, so it clears the previous edition binding. Import-time review can retain one because the importer has independently matched the inspected edition to the detected backend item. Both paths use the same coverage evidence and correction journal.

This addition uses schema `0038_asset_containment`; no new migration or queue is required. Back up the database and encryption key, then deploy API and worker together before saving plans with collection contents. The new plan and proof fields are additive JSON, but older workers do not understand their semantics. Deployment does not enable download dispatch.

## Verification and remaining stage work

The automated workflow uses real inspected files, PostgreSQL, API commands, the durable worker and hardlink publication with synthetic ABS observations. It checks ownership before/after immediate or delayed detection, one physical item, unchanged source bytes, repeat-import suppression, request constraints and stale identity holds. Browser evidence covers selecting contents, required confirmation, saved-plan reload and delayed library ownership.

This is the reviewed import route. Unattended discovery and verification of omnibus contents, per-child edition/recording evidence, broader source-to-collection acquisition, and native ABS collection certification remain required. A tracker title or series membership alone must not populate a confirmed contents proof. S04/S06 and FR-26 are not complete merely because this route passes.
