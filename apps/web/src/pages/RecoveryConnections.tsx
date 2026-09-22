import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";
import type { components } from "../api/schema";

export type ConnectionReview =
  components["schemas"]["ConnectionReconciliationView"];
type Choice = components["schemas"]["ConnectionChoice"];
type Settings = components["schemas"]["ConnectionRepairItemView"]["before"];
type Evidence = {
  connection_schema: number;
  before: Settings;
  source_roots: { key: string; path: string }[];
};

export function PrepareConnectionReview({
  scanId,
  findingId,
  title,
  disabled,
}: {
  scanId: string;
  findingId: string;
  title: string;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const observation = useQuery({
    queryKey: ["recovery-connection", scanId, findingId],
    enabled: open,
    queryFn: async () =>
      result(
        await api.GET("/api/recovery/scans/{scan_id}/findings/{finding_id}", {
          params: { path: { scan_id: scanId, finding_id: findingId } },
        }),
      ),
  });
  const evidence = observation.data?.evidence as Evidence | undefined;
  return (
    <>
      <button
        disabled={disabled}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? `Close settings for ${title}` : `Review settings for ${title}`}
      </button>
      {open && (
        <>
          {observation.isPending && <Loading />}
          <Notice error={observation.error} />
          {evidence?.connection_schema === 1 && !observation.isError && (
            <ConnectionEditor
              key={findingId}
              evidence={evidence}
              scanId={scanId}
              findingId={findingId}
              disabled={disabled}
              onPrepared={() => setOpen(false)}
            />
          )}
        </>
      )}
    </>
  );
}

function initialChoice(evidence: Evidence, findingId: string): Choice {
  const before = evidence.before;
  const common = {
    finding_id: findingId,
    kind: before.kind,
    name: before.name,
    base_url: before.base_url,
    enabled: before.enabled,
  };
  return before.kind === "audiobookshelf"
    ? { ...common, public_url: before.public_url }
    : {
        ...common,
        save_path: before.save_path,
        category: before.category,
        mappings: before.mappings.map(({ download_root, source_key }) => ({
          download_root,
          source_key,
        })),
      };
}

function ConnectionEditor({
  evidence,
  scanId,
  findingId,
  disabled,
  onPrepared,
}: {
  evidence: Evidence;
  scanId: string;
  findingId: string;
  disabled: boolean;
  onPrepared: () => void;
}) {
  const client = useQueryClient();
  const [choice, setChoice] = useState<Choice>(() =>
    initialChoice(evidence, findingId),
  );
  const [key, setKey] = useState(() => crypto.randomUUID());
  function edit(patch: Partial<Choice>) {
    setChoice((previous) => ({ ...previous, ...patch }));
    setKey(crypto.randomUUID());
  }
  function mapping(
    index: number,
    patch: Partial<NonNullable<Choice["mappings"]>[number]>,
  ) {
    edit({
      mappings: (choice.mappings ?? []).map((value, i) =>
        i === index ? { ...value, ...patch } : value,
      ),
    });
  }
  const prepare = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/recovery/connection-reconciliations", {
          params: { header: { "idempotency-key": key } },
          body: { scan_id: scanId, changes: [choice] },
        }),
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["recovery"] });
      onPrepared();
    },
  });
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        prepare.mutate();
      }}
    >
      <fieldset disabled={disabled || prepare.isPending}>
        <legend>Settings for {evidence.before.name}</legend>
        <p>
          Review the current connection. Enabled connections are tested only
          after you confirm the preview.
        </p>
        <label>
          Connection name
          <input
            required
            maxLength={120}
            value={choice.name}
            onChange={(e) => edit({ name: e.target.value })}
          />
        </label>
        <label>
          Server URL
          <input
            required
            type="url"
            maxLength={2000}
            value={choice.base_url}
            onChange={(e) => edit({ base_url: e.target.value })}
          />
        </label>
        <label className="difference-choice">
          <input
            type="checkbox"
            checked={choice.enabled}
            onChange={(e) => edit({ enabled: e.target.checked })}
          />
          Enable connection
        </label>
        <p>
          Leave credentials blank to keep the saved credentials. Changing the
          server URL requires fresh credentials.
        </p>
        {choice.kind === "audiobookshelf" ? (
          <>
            <label>
              Public library URL
              <input
                type="url"
                maxLength={2000}
                value={choice.public_url ?? ""}
                onChange={(e) => edit({ public_url: e.target.value || null })}
              />
            </label>
            <label>
              New API token
              <input
                type="password"
                autoComplete="new-password"
                maxLength={8192}
                value={choice.token ?? ""}
                onChange={(e) => edit({ token: e.target.value || null })}
              />
            </label>
          </>
        ) : (
          <>
            <label>
              New downloader username
              <input
                autoComplete="off"
                maxLength={300}
                value={choice.username ?? ""}
                onChange={(e) => edit({ username: e.target.value || null })}
              />
            </label>
            <label>
              New downloader password
              <input
                type="password"
                autoComplete="new-password"
                maxLength={1000}
                value={choice.password ?? ""}
                onChange={(e) => edit({ password: e.target.value || null })}
              />
            </label>
            <label>
              Download save path
              <input
                required
                maxLength={2000}
                value={choice.save_path ?? ""}
                onChange={(e) => edit({ save_path: e.target.value })}
              />
            </label>
            <label>
              Download category
              <input
                required
                maxLength={100}
                pattern="[A-Za-z0-9_-]+"
                value={choice.category ?? ""}
                onChange={(e) => edit({ category: e.target.value })}
              />
            </label>
            <fieldset>
              <legend>Download path mappings</legend>
              <p>
                Map qBittorrent paths to the download roots configured on this
                worker. Saving these settings does not verify hardlinks or
                import destinations.
              </p>
              {(choice.mappings ?? []).map((value, index) => (
                <fieldset key={index}>
                  <legend>Mapping {index + 1}</legend>
                  <label>
                    qBittorrent download root
                    <input
                      required
                      maxLength={2000}
                      value={value.download_root}
                      onChange={(e) =>
                        mapping(index, { download_root: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    Worker download root
                    <select
                      value={value.source_key ?? ""}
                      onChange={(e) =>
                        mapping(index, { source_key: e.target.value })
                      }
                    >
                      {!evidence.source_roots.some(
                        (root) => root.key === value.source_key,
                      ) && (
                        <option value={value.source_key ?? ""}>
                          Unavailable ·{" "}
                          {value.source_key || "Choose a configured root"}
                        </option>
                      )}
                      {evidence.source_roots.map((root) => (
                        <option key={root.key} value={root.key}>
                          {root.key} · {root.path}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    disabled={(choice.mappings?.length ?? 0) <= 1}
                    onClick={() =>
                      edit({
                        mappings: choice.mappings?.filter(
                          (_, i) => i !== index,
                        ),
                      })
                    }
                  >
                    Remove mapping {index + 1}
                  </button>
                </fieldset>
              ))}
              <button
                type="button"
                disabled={
                  !evidence.source_roots.length ||
                  (choice.mappings?.length ?? 0) >= 20
                }
                onClick={() =>
                  edit({
                    mappings: [
                      ...(choice.mappings ?? []),
                      {
                        download_root: "",
                        source_key: evidence.source_roots[0]?.key ?? "",
                      },
                    ],
                  })
                }
              >
                Add path mapping
              </button>
              {!evidence.source_roots.length && (
                <p>
                  No worker download roots are configured. You can keep this
                  connection disabled while repairing the deployment mounts.
                </p>
              )}
            </fieldset>
          </>
        )}
        <button type="submit">
          {prepare.isPending
            ? "Preparing connection preview…"
            : "Preview connection settings"}
        </button>
      </fieldset>
      <Notice error={prepare.error} />
    </form>
  );
}

function SettingsSummary({ value }: { value: Settings }) {
  return (
    <>
      <p>
        {value.name} · {value.enabled ? "Enabled" : "Disabled"}
      </p>
      <p>Server: {value.base_url}</p>
      {value.kind === "audiobookshelf" ? (
        <p>Public library: {value.public_url}</p>
      ) : (
        <>
          <p>
            Save path: {value.save_path} · Category: {value.category}
          </p>
          <ul>
            {value.mappings.map((item, i) => (
              <li key={i}>
                {item.download_root} → {item.source_key} · {item.worker_path}
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

export function ConnectionRecoveryReview({
  review,
  currentScan,
  otherBusy,
}: {
  review: ConnectionReview;
  currentScan?: string;
  otherBusy: boolean;
}) {
  const client = useQueryClient();
  const [key] = useState(() => crypto.randomUUID());
  const heading = useRef<HTMLHeadingElement>(null);
  const prepared = review.status === "prepared";
  useEffect(() => {
    if (prepared) heading.current?.focus();
  }, [review.id, prepared]);
  const accept = useMutation({
    mutationFn: async () =>
      result(
        await api.POST(
          "/api/recovery/connection-reconciliations/{identifier}/accept",
          {
            params: {
              path: { identifier: review.id },
              header: { "idempotency-key": key },
            },
            body: { revision: review.revision },
          },
        ),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["recovery"] }),
  });
  return (
    <section
      className="recovery-decision"
      aria-labelledby="connection-review-title"
    >
      <h3 id="connection-review-title" ref={heading} tabIndex={-1}>
        Review connection settings
      </h3>
      <p>
        Enabled connections must pass a fresh read-only connection test before
        these settings are saved. Disabled connections are saved without
        contacting the server.
      </p>
      <p>
        Changed media connections require another inventory reconciliation.
        Downloader mappings require file-route verification. Existing transfers,
        library files and saved approvals remain unchanged; automation stays
        paused.
      </p>
      <ul>
        {review.items.map((item) => (
          <li key={item.integration_id}>
            <h4>Saved settings</h4>
            <SettingsSummary value={item.before} />
            <h4>Reviewed settings</h4>
            <SettingsSummary value={item.after} />
            <p>
              Credentials:{" "}
              {item.replace_credentials
                ? "replace with the newly entered credentials"
                : "keep saved credentials"}
              .
            </p>
          </li>
        ))}
      </ul>
      <p role="status">{review.message}</p>
      {prepared && (
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
              ? "Verifying settings…"
              : "Confirm reviewed connection settings"}
          </button>
        </>
      )}
      <Notice error={accept.error} />
    </section>
  );
}
