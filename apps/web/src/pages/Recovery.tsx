import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, result, setCsrf } from "../api/client";
import { Loading, Notice } from "../components";

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
              These counts describe the backup. They do not confirm the current
              state of your downloader or library.
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
            <RecoveryChecks
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
}: {
  scanId?: string;
  state?: string;
}) {
  const client = useQueryClient();
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [domain, setDomain] = useState("");
  const [offset, setOffset] = useState(0);
  const start = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/recovery/scans", {
          params: { header: { "idempotency-key": key } },
        }),
      ),
    onSuccess: () => {
      setKey(crypto.randomUUID());
      setOffset(0);
      client.invalidateQueries({ queryKey: ["recovery"] });
    },
  });
  const report = useQuery({
    queryKey: ["recovery-findings", scanId, state, domain, offset],
    enabled: Boolean(scanId),
    queryFn: async () =>
      result(
        await api.GET("/api/recovery/scans/{scan_id}", {
          params: {
            path: { scan_id: scanId! },
            query: { offset, ...(domain ? { domain } : {}) },
          },
        }),
      ),
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
        disabled={start.isPending || state === "queued" || state === "running"}
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
          option. It processes only these observations and has no ordinary
          automation tasks.
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
                setOffset(0);
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
                {finding.has_evidence && (
                  <FindingEvidence scanId={scanId!} findingId={finding.id} />
                )}
              </li>
            ))}
          </ul>
          <div className="recovery-pagination">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              Previous observations
            </button>
            <button
              disabled={report.data.next_offset == null}
              onClick={() => setOffset(report.data!.next_offset!)}
            >
              Next observations
            </button>
          </div>
        </>
      )}
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
