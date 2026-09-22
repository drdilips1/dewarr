import { usePagedQuery } from "../hooks/usePagedQuery";
import InfiniteScroll from "../components/InfiniteScroll";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, result, setCsrf } from "../api/client";
import { Loading, Notice } from "../components";
import type { components } from "../api/schema";
import {
  InventoryRecoveryReview,
  PrepareInventoryReview,
  type InventoryReview,
} from "./RecoveryInventory";
import {
  PublicationRecoveryReview,
  PreparePublicationReview,
  type PublicationReview,
} from "./RecoveryPublication";
import {
  ListBaselineRecoveryReview,
  PrepareListBaselineReview,
  type ListBaselineReview,
} from "./RecoveryLists";
import {
  OutboundRecoveryReview,
  PrepareOutboundReview,
  type OutboundReview,
} from "./RecoveryOutbound";
import {
  CommandRecoveryReview,
  PrepareCommandReview,
  type CommandReview,
} from "./RecoveryCommands";
import {
  AccessRecoveryReview,
  PrepareAccessReview,
  type AccessReview,
} from "./RecoveryAccess";
import {
  ConnectionRecoveryReview,
  PrepareConnectionReview,
  type ConnectionReview,
} from "./RecoveryConnections";
import {
  SourceRecoveryReview,
  PrepareSourceReview,
  type SourceReview,
} from "./RecoverySources";
import { randomUUID } from "../randomUUID";

type RecoveryReview = components["schemas"]["ReconciliationView"];

export default function Recovery() {
  const client = useQueryClient();
  const review = useQuery({
    queryKey: ["recovery"],
    queryFn: async () => result(await api.GET("/api/recovery")),
    refetchInterval: 2000,
  });
  const logout = useMutation({
    mutationFn: async () => result(await api.POST("/api/auth/logout")),
    onSuccess: () => {
      setCsrf("");
      client.clear();
      window.location.assign("/");
    },
  });
  return (
    <main id="main" className="recovery-page">
      <section
        className="panel recovery-panel"
        aria-labelledby="recovery-title"
      >
        <p className="eyebrow">BOOK SEARCH · OPERATOR REVIEW</p>
        <h1 id="recovery-title">Your restored library is paused</h1>
        <p>
          Downloads, imports and list changes cannot run while recovery review
          is active. Saved library availability must be checked against your
          current media server before automation resumes.
        </p>
        {review.isPending && <Loading />}
        {review.isError && (
          <>
            <Notice error={review.error} />
            <button onClick={() => review.refetch()}>Try again</button>
          </>
        )}
        {review.data && !review.isError && (
          <>
            <h2>Saved workflow evidence</h2>
            <p>
              These are saved workflow states, including corrections made during
              recovery. They do not confirm the current state of your library.
            </p>
            <div className="recovery-counts">
              {[
                { label: "Downloads", counts: review.data.downloads },
                { label: "Imports", counts: review.data.imports },
              ].map(({ label, counts }) => (
                <div key={label}>
                  <h3>{label}</h3>
                  {Object.entries(counts).length ? (
                    <dl>
                      {Object.entries(counts).map(([state, count]) => (
                        <div key={state}>
                          <dt>{state}</dt>
                          <dd>{count}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    <p>No saved records.</p>
                  )}
                </div>
              ))}
            </div>
            <section aria-labelledby="queue-boundary-title">
              <h2 id="queue-boundary-title">Historical queue protection</h2>
              {review.data.queue_fence ? (
                <p>
                  {review.data.queue_fence.historical_jobs} saved jobs are
                  fenced. Restored commands, download attempts, import records
                  and books also retain their recovery boundary. Retrying an old
                  job or giving it a new queue ID does not authorize it to run.
                </p>
              ) : (
                <p>
                  No sealed queue boundary is recorded. Keep automation paused;
                  the restored database needs the supported offline upgrade
                  before a future resume can be reviewed.
                </p>
              )}
              <p>
                Protection remains after recovery. Resuming current work
                requires a separate review; this screen does not enable
                automation.
              </p>
              <p>
                {review.data.queue_fence?.approvals_protected
                  ? "Saved approvals are protected. Old download selections, import plans, CSV previews and list or series approvals cannot authorize new work. Completed receipts remain available."
                  : "Saved approval protection needs the supported offline upgrade before recovery can proceed."}
              </p>
            </section>
            <RecoveryChecks
              key={review.data.latest_scan?.id ?? "none"}
              review={review.data.latest_reconciliation ?? undefined}
              inventoryReview={
                review.data.latest_inventory_reconciliation ?? undefined
              }
              publicationReview={
                review.data.latest_publication_reconciliation ?? undefined
              }
              commandReview={
                review.data.latest_command_reconciliation ?? undefined
              }
              outboundReview={
                review.data.latest_outbound_reconciliation ?? undefined
              }
              listReview={review.data.latest_list_reconciliation ?? undefined}
              accessReview={
                review.data.latest_access_reconciliation ?? undefined
              }
              connectionReview={
                review.data.latest_connection_reconciliation ?? undefined
              }
              sourceReview={
                review.data.latest_source_reconciliation ?? undefined
              }
              scanId={review.data.latest_scan?.id}
              state={review.data.latest_scan?.state}
            />
            <h2>Before resuming</h2>
            <p>
              Keep the backup, encryption key and publication journals together.
              Preserve the current download, staging and library folders. An
              operator must reconcile remote downloads, published files and
              external list changes with this saved state.
            </p>
            <p className="recovery-limit">
              Observations do not authorize automatic reconciliation or resume.
              Follow the repository’s recovery runbook; changing the recovery
              environment flag does not clear a restored database.
            </p>
          </>
        )}
        <Notice error={logout.error} />
        <button onClick={() => logout.mutate()} disabled={logout.isPending}>
          Sign out
        </button>
      </section>
    </main>
  );
}

function RecoveryChecks({
  scanId,
  state,
  review,
  inventoryReview,
  publicationReview,
  listReview,
  outboundReview,
  commandReview,
  accessReview,
  connectionReview,
  sourceReview,
}: {
  scanId?: string;
  state?: string;
  review?: RecoveryReview;
  inventoryReview?: InventoryReview;
  publicationReview?: PublicationReview;
  listReview?: ListBaselineReview;
  outboundReview?: OutboundReview;
  commandReview?: CommandReview;
  accessReview?: AccessReview;
  connectionReview?: ConnectionReview;
  sourceReview?: SourceReview;
}) {
  const client = useQueryClient();
  const [key, setKey] = useState(() => randomUUID());
  const [domain, setDomain] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [prepareKey, setPrepareKey] = useState(() => randomUUID());
  const reviews = [
    review,
    inventoryReview,
    publicationReview,
    listReview,
    outboundReview,
    commandReview,
    accessReview,
    connectionReview,
    sourceReview,
  ];
  const busy =
    reviews.some(
      (item) => item?.status === "queued" || item?.status === "running",
    ) ||
    ["queued", "running"].includes(sourceReview?.verification?.status ?? "");
  const applied = reviews.some(
    (item) => item?.scan_id === scanId && item?.status === "completed",
  );
  const preview = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/recovery/reconciliations", {
          params: { header: { "idempotency-key": prepareKey } },
          body: { scan_id: scanId!, finding_ids: selected },
        }),
      ),
    onSuccess: async () => {
      setSelected([]);
      setPrepareKey(randomUUID());
      await client.invalidateQueries({ queryKey: ["recovery"] });
    },
  });
  function choose(id: string, checked: boolean) {
    setSelected((previous) =>
      checked ? [...previous, id] : previous.filter((item) => item !== id),
    );
    setPrepareKey(randomUUID());
  }

  const start = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/recovery/scans", {
          params: { header: { "idempotency-key": key } },
        }),
      ),
    onSuccess: () => {
      setKey(randomUUID());
      client.invalidateQueries({ queryKey: ["recovery"] });
    },
  });
  const report = usePagedQuery({
    queryKey: ["recovery-findings", scanId, state, domain],
    enabled: Boolean(scanId),
    queryFn: async (offset, signal) =>
      result(
        await api.GET("/api/recovery/scans/{scan_id}", {
          signal,
          params: {
            path: { scan_id: scanId! },
            query: { offset, ...(domain ? { domain } : {}) },
          },
        }),
      ),
    initial: 0,
    next: (last) => last.next_offset ?? undefined,
    refetchInterval: state === "queued" || state === "running" ? 2000 : false,
  });
  return (
    <section className="recovery-checks" aria-labelledby="checks-title">
      <h2 id="checks-title">Check current external state</h2>
      <p>
        Read the downloader, media libraries, external lists and publication
        journals. These checks leave transfers, files and list memberships
        unchanged.
      </p>
      <button
        disabled={
          start.isPending || busy || state === "queued" || state === "running"
        }
        onClick={() => start.mutate()}
      >
        {state === "running"
          ? "Checking current state…"
          : state === "queued"
            ? "Waiting for recovery worker…"
            : "Run read-only checks"}
      </button>
      <Notice error={start.error} />
      <details>
        <summary>Running the recovery worker</summary>
        <p>
          Start the worker with your restored configuration and the recovery
          option. It processes observations and explicitly reviewed local
          corrections. Ordinary download, import and list automation stays
          paused.
        </p>
        <pre>python -m app.jobs.worker --recovery</pre>
      </details>
      {report.isError && <Notice error={report.error} />}
      {report.data && !report.isError && (
        <>
          <p role="status">{report.data.scan.message}</p>
          {report.data.scan.finished_at && (
            <p className="muted">
              Observed {new Date(report.data.scan.finished_at).toLocaleString()}
              . This is a saved report.
            </p>
          )}
          <label>
            Filter observations
            <select
              value={domain}
              onChange={(event) => {
                setDomain(event.target.value);
              }}
            >
              <option value="">All areas</option>
              <option value="downloads">Downloads</option>
              <option value="library">Media libraries</option>
              <option value="files">Files and journals</option>
              <option value="lists">External lists</option>
              <option value="review">Recovery status</option>
            </select>
          </label>
          <p>
            {report.data.total} observations
            {state === "running" ? " collected so far" : ""}
          </p>
          <ul className="recovery-findings">
            {report.data.items.map((finding) => (
              <li key={finding.id}>
                <div className="recovery-finding-heading">
                  <h3>{finding.title}</h3>
                  <span>{finding.state.replaceAll("-", " ")}</span>
                </div>
                <p>{finding.message}</p>
                {state === "completed" &&
                  finding.domain === "downloads" &&
                  finding.state === "matched" &&
                  !applied && (
                    <label className="difference-choice">
                      <input
                        type="checkbox"
                        checked={selected.includes(finding.id)}
                        disabled={
                          busy ||
                          preview.isPending ||
                          (!selected.includes(finding.id) &&
                            selected.length >= 100)
                        }
                        onChange={(event) =>
                          choose(finding.id, event.target.checked)
                        }
                      />
                      Select {finding.title} for recovery review
                    </label>
                  )}
                {state === "completed" &&
                  finding.state === "inventory-ready" &&
                  finding.domain === "library" &&
                  !applied && (
                    <PrepareInventoryReview
                      scanId={scanId!}
                      findingId={finding.id}
                      title={finding.title}
                      disabled={busy}
                    />
                  )}
                {state === "completed" &&
                  ["published", "relocated"].includes(finding.state) &&
                  finding.domain === "files" &&
                  !applied && (
                    <PreparePublicationReview
                      scanId={scanId!}
                      findingId={finding.id}
                      title={finding.title}
                      disabled={busy}
                    />
                  )}
                {state === "completed" &&
                  finding.state === "list-ready" &&
                  finding.domain === "lists" &&
                  !applied && (
                    <PrepareListBaselineReview
                      scanId={scanId!}
                      findingId={finding.id}
                      title={finding.title}
                      disabled={busy}
                    />
                  )}
                {state === "completed" &&
                  finding.state === "outbound-ready" &&
                  finding.domain === "lists" &&
                  !applied && (
                    <PrepareOutboundReview
                      scanId={scanId!}
                      findingId={finding.id}
                      title={finding.title}
                      disabled={busy}
                    />
                  )}
                {state === "completed" &&
                  ["command-ready", "automation-ready"].includes(
                    finding.state,
                  ) &&
                  finding.domain === "review" &&
                  !applied && (
                    <PrepareCommandReview
                      automation={finding.state === "automation-ready"}
                      scanId={scanId!}
                      findingId={finding.id}
                      title={finding.title}
                      disabled={busy}
                    />
                  )}
                {state === "completed" &&
                  ["access-ready", "access-reviewed"].includes(finding.state) &&
                  finding.domain === "review" &&
                  !applied && (
                    <PrepareAccessReview
                      scanId={scanId!}
                      findingId={finding.id}
                      title={finding.title}
                      disabled={busy}
                    />
                  )}
                {state === "completed" &&
                  ["connection-ready", "connection-reviewed"].includes(
                    finding.state,
                  ) &&
                  finding.domain === "review" &&
                  !applied && (
                    <PrepareConnectionReview
                      scanId={scanId!}
                      findingId={finding.id}
                      title={finding.title}
                      disabled={busy}
                    />
                  )}
                {state === "completed" &&
                  ["source-ready", "source-verified"].includes(finding.state) &&
                  finding.domain === "review" &&
                  !applied && (
                    <PrepareSourceReview
                      scanId={scanId!}
                      findingId={finding.id}
                      title={finding.title}
                      disabled={busy}
                    />
                  )}
                {finding.has_evidence && (
                  <FindingEvidence scanId={scanId!} findingId={finding.id} />
                )}
              </li>
            ))}
          </ul>
          {state === "completed" &&
            !applied &&
            (domain === "" ||
              domain === "downloads" ||
              selected.length > 0) && (
              <div className="recovery-selection">
                <p>
                  {selected.length} matching transfers selected (maximum 100).
                </p>
                <button
                  disabled={!selected.length || busy || preview.isPending}
                  onClick={() => preview.mutate()}
                >
                  {preview.isPending
                    ? "Preparing review…"
                    : "Review selected transfers"}
                </button>
                <Notice error={preview.error} />
              </div>
            )}
          <InfiniteScroll query={report} />
        </>
      )}
      {review && (
        <ReconciliationReview
          key={review.id}
          review={review}
          currentScan={scanId}
          otherBusy={busy || applied}
        />
      )}
      {inventoryReview && (
        <InventoryRecoveryReview
          key={inventoryReview.id}
          review={inventoryReview}
          currentScan={scanId}
          otherBusy={busy || applied}
        />
      )}
      {publicationReview && (
        <PublicationRecoveryReview
          key={publicationReview.id}
          review={publicationReview}
          currentScan={scanId}
          otherBusy={busy || applied}
        />
      )}
      {sourceReview && (
        <SourceRecoveryReview
          key={sourceReview.id}
          review={sourceReview}
          currentScan={scanId}
          otherBusy={busy || applied}
        />
      )}
      {connectionReview && (
        <ConnectionRecoveryReview
          key={connectionReview.id}
          review={connectionReview}
          currentScan={scanId}
          otherBusy={busy || applied}
        />
      )}
      {accessReview && (
        <AccessRecoveryReview
          key={accessReview.id}
          review={accessReview}
          currentScan={scanId}
          otherBusy={busy || applied}
        />
      )}
      {commandReview && (
        <CommandRecoveryReview
          key={commandReview.id}
          review={commandReview}
          currentScan={scanId}
          otherBusy={busy || applied}
        />
      )}
      {outboundReview && (
        <OutboundRecoveryReview
          key={outboundReview.id}
          review={outboundReview}
          currentScan={scanId}
          otherBusy={busy || applied}
        />
      )}
      {listReview && (
        <ListBaselineRecoveryReview
          key={listReview.id}
          review={listReview}
          currentScan={scanId}
          otherBusy={busy || applied}
        />
      )}
    </section>
  );
}

function ReconciliationReview({
  review,
  currentScan,
  otherBusy,
}: {
  review: RecoveryReview;
  currentScan?: string;
  otherBusy: boolean;
}) {
  const client = useQueryClient();
  const [key] = useState(() => randomUUID());
  const heading = useRef<HTMLHeadingElement>(null);
  const prepared = review.status === "prepared";
  useEffect(() => {
    if (prepared) heading.current?.focus();
  }, [review.id, prepared]);
  const accept = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/recovery/reconciliations/{identifier}/accept", {
          params: {
            path: { identifier: review.id },
            header: { "idempotency-key": key },
          },
          body: { revision: review.revision },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["recovery"] }),
  });
  return (
    <section
      className="recovery-decision"
      aria-labelledby="reconciliation-title"
    >
      <h3 id="reconciliation-title" ref={heading} tabIndex={-1}>
        Review existing transfers
      </h3>
      <p>
        Record these transfers as already submitted so they cannot be added
        again. The worker rechecks identity, location and files before updating
        the saved records. Progress may have advanced since the observation.
      </p>
      <p>
        This does not approve imports or resume automation. Unmatched transfers,
        library changes and external lists still need reconciliation.
      </p>
      <ul>
        {review.items.map((item) => (
          <li key={item.attempt_id}>
            <strong>{item.title}</strong>: saved {item.saved_state}, observed{" "}
            {item.observed_state}.
            {!item.saved_external_may_exist &&
              " The restored record has no submission marker."}
          </li>
        ))}
      </ul>
      <p role="status">{review.message}</p>
      {review.status === "prepared" && (
        <>
          <p className="muted">
            Review expires {new Date(review.expires_at).toLocaleString()}.
          </p>
          {review.scan_id !== currentScan && (
            <p>A newer observation exists. Prepare a new review from it.</p>
          )}
          <button
            disabled={
              accept.isPending || otherBusy || review.scan_id !== currentScan
            }
            onClick={() => accept.mutate()}
          >
            {accept.isPending
              ? "Accepting review…"
              : "Record verified transfers"}
          </button>
        </>
      )}
      <Notice error={accept.error} />
    </section>
  );
}

function FindingEvidence({
  scanId,
  findingId,
}: {
  scanId: string;
  findingId: string;
}) {
  const [open, setOpen] = useState(false);
  const detail = useQuery({
    queryKey: ["recovery-evidence", scanId, findingId],
    enabled: open,
    queryFn: async () =>
      result(
        await api.GET("/api/recovery/scans/{scan_id}/findings/{finding_id}", {
          params: { path: { scan_id: scanId, finding_id: findingId } },
        }),
      ),
  });
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Observed evidence</summary>
      {open && (
        <>
          {detail.isPending && <Loading />}
          {detail.isError && <Notice error={detail.error} />}
          {detail.data && !detail.isError && (
            <pre>{JSON.stringify(detail.data.evidence, null, 2)}</pre>
          )}
        </>
      )}
    </details>
  );
}
