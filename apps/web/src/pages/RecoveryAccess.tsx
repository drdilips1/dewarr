import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";
import type { components } from "../api/schema";
import { randomUUID } from "../randomUUID";

export type AccessReview = components["schemas"]["AccessReconciliationView"];
type Choice = components["schemas"]["AccessChoice"];
type State = components["schemas"]["AccessStateView"];
type Evidence = {
  access_schema: number;
  username: string;
  operator: boolean;
  before: State;
  libraries: { id: string; name: string; accessible: boolean }[];
};

export function PrepareAccessReview({
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
    queryKey: ["recovery-access", scanId, findingId],
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
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        {open
          ? `Close permissions for ${title}`
          : `Review permissions for ${title}`}
      </button>
      {open && (
        <>
          {observation.isPending && <Loading />}
          <Notice error={observation.error} />
          {evidence?.access_schema === 1 && !observation.isError && (
            <AccessEditor
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

function AccessEditor({
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
  const [choice, setChoice] = useState<Choice>({
    finding_id: findingId,
    active: evidence.before.active,
    role: evidence.before.role as Choice["role"],
    can_automate:
      evidence.before.role === "viewer" ? false : evidence.before.can_automate,
    library_ids: evidence.before.library_ids,
  });
  const [key, setKey] = useState(() => randomUUID());
  function edit(patch: Partial<Choice>) {
    setChoice((previous) => ({ ...previous, ...patch }));
    setKey(randomUUID());
  }
  const prepare = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/recovery/access-reconciliations", {
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
        <legend>Permissions for {evidence.username}</legend>
        {evidence.operator && (
          <p>
            The designated recovery operator must remain an active
            administrator.
          </p>
        )}
        <label className="difference-choice">
          <input
            type="checkbox"
            checked={choice.active}
            disabled={evidence.operator}
            onChange={(e) => edit({ active: e.target.checked })}
          />
          Account enabled
        </label>
        <label>
          Account role
          <select
            value={choice.role}
            disabled={evidence.operator}
            onChange={(e) => {
              const role = e.target.value as Choice["role"];
              edit({
                role,
                ...(role === "viewer" ? { can_automate: false } : {}),
              });
            }}
          >
            <option value="admin">Administrator</option>
            <option value="member">Member</option>
            <option value="viewer">Viewer</option>
          </select>
        </label>
        <label className="difference-choice">
          <input
            type="checkbox"
            checked={choice.can_automate}
            disabled={choice.role === "viewer"}
            onChange={(e) => edit({ can_automate: e.target.checked })}
          />
          Allow acquisition automation
        </label>
        {choice.role === "admin" && (
          <p>
            Administrators can access every connected library and manage
            automation. Saved library grants and the member automation setting
            do not limit administrator access.
          </p>
        )}
        {choice.role === "viewer" && (
          <p>Viewers have read-only access and cannot request downloads.</p>
        )}
        <fieldset>
          <legend>Saved library grants</legend>
          <p>
            Keep or remove existing grants. Adding a grant requires current
            backend inventory reconciliation. A grant does not prove a library
            is reachable.
          </p>
          {evidence.libraries.length === 0 && <p>No saved libraries.</p>}
          {evidence.libraries.map((library) => (
            <label className="difference-choice" key={library.id}>
              <input
                type="checkbox"
                checked={choice.library_ids.includes(library.id)}
                onChange={(e) =>
                  edit({
                    library_ids: e.target.checked
                      ? [...choice.library_ids, library.id]
                      : choice.library_ids.filter((id) => id !== library.id),
                  })
                }
              />
              {library.name}
              {!library.accessible && " (currently unavailable)"}
            </label>
          ))}
        </fieldset>
        <button type="submit">
          {prepare.isPending
            ? "Preparing permissions preview…"
            : "Preview permissions"}
        </button>
      </fieldset>
      <Notice error={prepare.error} />
    </form>
  );
}

function PermissionSummary({
  value,
  libraries,
}: {
  value: State;
  libraries: { id: string; name: string }[];
}) {
  return (
    <>
      <p>
        {value.active ? "Enabled" : "Disabled"} · {value.role} · Member
        automation {value.can_automate ? "allowed" : "not allowed"}
      </p>
      <p>
        Saved grants:{" "}
        {value.library_ids.length
          ? value.library_ids
              .map(
                (id) =>
                  libraries.find((l) => l.id === id)?.name ??
                  "Unavailable library",
              )
              .join(", ")
          : "none"}
        .
      </p>
      {value.role === "admin" && (
        <p>
          Administrator access includes all connected libraries and automation
          controls.
        </p>
      )}
    </>
  );
}

export function AccessRecoveryReview({
  review,
  currentScan,
  otherBusy,
}: {
  review: AccessReview;
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
        await api.POST(
          "/api/recovery/access-reconciliations/{identifier}/accept",
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
      aria-labelledby="access-review-title"
    >
      <h3 id="access-review-title" ref={heading} tabIndex={-1}>
        Review account permissions
      </h3>
      <p>
        Confirm the current household access or apply the changes below. Changed
        accounts other than the operator lose existing sessions. Books, list
        ownership, existing requests and external files remain unchanged.
      </p>
      <p>
        This reviews local permissions. Backend credentials, current library
        access and reactivation of wanted books still require their own checks.
        Sign-in by other accounts and automation remain paused.
      </p>
      <ul>
        {review.items.map((item) => (
          <li key={item.user_id}>
            <strong>
              {item.username}
              {item.operator && " · Recovery operator"}
            </strong>
            <h4>Saved permissions</h4>
            <PermissionSummary value={item.before} libraries={item.libraries} />
            <h4>Reviewed permissions</h4>
            <PermissionSummary value={item.after} libraries={item.libraries} />
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
              ? "Applying permissions…"
              : "Confirm reviewed permissions"}
          </button>
        </>
      )}
      <Notice error={accept.error} />
    </section>
  );
}
