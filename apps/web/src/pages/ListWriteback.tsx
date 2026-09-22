import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import { Notice } from "../components";
import ListDifferences from "./ListDifferences";
import { randomUUID } from "../randomUUID";

export default function ListWriteback({
  listId,
  onMembershipChange,
}: {
  listId: string;
  onMembershipChange?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [offset, setOffset] = useState(0);
  const [comparisonId, setComparisonId] = useState<string | null>(null);
  const [comparisonReady, setComparisonReady] = useState(false);
  const [comparisonMessage, setComparisonMessage] = useState("");
  const cache = useQueryClient();
  const path = { list_id: listId };
  const keys = useRef(new Map<string, string>());
  const key = (name: string) => {
    if (!keys.current.has(name)) keys.current.set(name, randomUUID());
    return keys.current.get(name)!;
  };
  const policy = useQuery({
    queryKey: ["list-writeback", listId],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}/writeback", { params: { path } }),
      ),
    enabled: expanded,
    staleTime: 0,
    gcTime: 0,
    refetchInterval: expanded ? 5000 : false,
  });
  const changes = useQuery({
    queryKey: ["list-writeback-changes", listId, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/lists/{list_id}/writeback/changes", {
          params: { path, query: { offset, limit: 10 } },
        }),
      ),
    enabled: expanded && policy.isSuccess,
    staleTime: 0,
    gcTime: 0,
    refetchInterval: expanded ? 3000 : false,
  });
  const refresh = () => {
    for (const queryKey of [
      ["list-writeback", listId],
      ["list-writeback-changes", listId],
      ["list", listId],
      ["lists"],
      ["list-observations", listId],
    ])
      cache.invalidateQueries({ queryKey });
  };
  const preview = useMutation({
    mutationFn: async () =>
      result(
        await api.POST("/api/lists/{list_id}/writeback/preview", {
          params: {
            path,
            header: {
              "idempotency-key": key(`enable:${policy.data?.generation}`),
            },
          },
          body: { expected_generation: policy.data?.generation ?? 0 },
        }),
      ),
    onSuccess: (data) => {
      keys.current.delete(`enable:${policy.data?.generation}`);
      setComparisonId(data.comparison_id ?? null);
      setComparisonReady(false);
      setComparisonMessage("");
    },
  });
  const configure = useMutation({
    mutationFn: async (enabled: boolean) =>
      result(
        await api.PUT("/api/lists/{list_id}/writeback", {
          params: {
            path,
            header: {
              "idempotency-key": key(
                `configure:${enabled}:${policy.data?.generation}:${preview.data?.id}`,
              ),
            },
          },
          body: {
            enabled,
            expected_generation: policy.data?.generation ?? 0,
            preview_id: enabled ? preview.data?.id : null,
          },
        }),
      ),
    onSuccess: () => {
      preview.reset();
      refresh();
    },
  });
  const reconcile = useMutation({
    mutationFn: async (operationId: string) =>
      result(
        await api.POST(
          "/api/lists/{list_id}/writeback/changes/{operation_id}/reconcile",
          { params: { path: { ...path, operation_id: operationId } } },
        ),
      ),
    onSuccess: refresh,
  });
  const review = useMutation({
    mutationFn: async (workId: string) =>
      result(
        await api.POST("/api/lists/{list_id}/writeback/changes/preview", {
          params: { path, header: { "idempotency-key": randomUUID() } },
          body: { work_id: workId },
        }),
      ),
  });
  const resolve = useMutation({
    mutationFn: async (action: "apply_local" | "keep_remote") =>
      result(
        await api.POST("/api/lists/{list_id}/writeback/changes/resolve", {
          params: {
            path,
            header: {
              "idempotency-key": key(`resolve:${review.data!.id}:${action}`),
            },
          },
          body: { preview_id: review.data!.id, action },
        }),
      ),
    onSuccess: () => {
      review.reset();
      onMembershipChange?.();
      refresh();
    },
  });
  const generation = policy.data?.generation;
  const resetPreview = preview.reset;
  const resetReview = review.reset;
  useEffect(() => {
    resetPreview();
    resetReview();
    keys.current.clear();
    // A new policy revision invalidates captured enablement and difference previews.
  }, [generation, resetPreview, resetReview]);
  const busy =
    preview.isPending ||
    configure.isPending ||
    reconcile.isPending ||
    review.isPending ||
    resolve.isPending;
  const unavailable = policy.isError || changes.isError;
  return (
    <details
      className="writeback-controls"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary>Sync local changes back to Hardcover</summary>
      {expanded && (
        <div className="editor">
          <p>
            Optional: send future additions and removals from this list to a
            Hardcover list you own. Reading status and library files stay
            independent.
          </p>
          <Notice
            error={
              policy.error ||
              changes.error ||
              preview.error ||
              configure.error ||
              reconcile.error ||
              review.error ||
              resolve.error
            }
          />
          {policy.isPending && <p role="status">Checking list connection…</p>}
          {!unavailable && policy.data && (
            <>
              <p>
                <strong>
                  {policy.data.enabled
                    ? "Write-back enabled"
                    : "Write-back off"}
                </strong>{" "}
                · {policy.data.message}
              </p>
              <div className="button-row">
                {policy.data.enabled && (
                  <button
                    disabled={busy}
                    onClick={() => configure.mutate(false)}
                  >
                    Pause write-back
                  </button>
                )}
                {
                  <button
                    disabled={
                      busy || (!policy.data.available && !policy.data.enabled)
                    }
                    onClick={() => preview.mutate()}
                  >
                    {policy.data.enabled
                      ? "Compare existing books"
                      : "Review enablement"}
                  </button>
                }
              </div>
              {preview.data &&
                (!policy.data.enabled || !policy.data.available) && (
                  <div className="notice" role="status">
                    <p>
                      Send future local membership changes to{" "}
                      <strong>{preview.data.list_name}</strong> on Hardcover.
                      Existing differences are shown below and require a
                      separate selection.
                    </p>
                    <p>
                      Your token needs list read/write and profile-read access.
                      Ownership is verified; write permission is confirmed by
                      the first successful membership change.
                    </p>
                    <div className="button-row">
                      <button
                        className="primary"
                        disabled={busy || !comparisonReady}
                        onClick={() => configure.mutate(true)}
                      >
                        Enable future changes
                      </button>
                      <button disabled={busy} onClick={() => preview.reset()}>
                        Cancel enablement
                      </button>
                    </div>
                  </div>
                )}
              {comparisonMessage && <p role="status">{comparisonMessage}</p>}
              {comparisonId && (
                <ListDifferences
                  key={comparisonId}
                  listId={listId}
                  comparisonId={comparisonId}
                  generation={policy.data.generation}
                  enabled={policy.data.enabled && policy.data.available}
                  onReady={setComparisonReady}
                  onApplied={(message) => {
                    setComparisonMessage(message);
                    setComparisonId(null);
                    setComparisonReady(false);
                    preview.reset();
                    onMembershipChange?.();
                    refresh();
                  }}
                />
              )}
              {policy.data.confirmed_at && (
                <p className="muted">
                  Last confirmed membership:{" "}
                  {new Date(policy.data.confirmed_at).toLocaleString()}
                </p>
              )}
              {resolve.data && <p role="status">{resolve.data.message}</p>}
              {review.data && (
                <section
                  className="notice"
                  aria-label="Review Hardcover membership"
                >
                  <h3>{review.data.title}</h3>
                  <p>
                    Local list:{" "}
                    {review.data.local_present ? "present" : "absent"}.
                    Hardcover:{" "}
                    {review.data.remote_present
                      ? `present (${review.data.remote_memberships} membership${review.data.remote_memberships === 1 ? "" : "s"})`
                      : "absent"}
                    .
                  </p>
                  <p>
                    Applying local state creates a new checked change. Keeping
                    Hardcover state updates this local list without sending a
                    write.
                  </p>
                  <div className="button-row">
                    <button
                      disabled={
                        busy || !policy.data.enabled || !policy.data.available
                      }
                      onClick={() => resolve.mutate("apply_local")}
                    >
                      Apply local state
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => resolve.mutate("keep_remote")}
                    >
                      Keep Hardcover state
                    </button>
                    <button disabled={busy} onClick={() => review.reset()}>
                      Close review
                    </button>
                  </div>
                </section>
              )}
              <h3>Membership changes</h3>
              {changes.data?.total === 0 && (
                <p className="muted">
                  No outbound changes yet. Enabling write-back does not send
                  your existing list.
                </p>
              )}
              {changes.data?.items.map((change) => (
                <article className="writeback-change" key={change.id}>
                  <p>
                    <strong>
                      {change.work_id ? (
                        <Link to={`/books/${change.work_id}`}>
                          {change.title}
                        </Link>
                      ) : (
                        change.title
                      )}
                    </strong>{" "}
                    · {change.desired_present ? "Add" : "Remove"} ·{" "}
                    {change.status}
                  </p>
                  <p className="muted">{change.message}</p>
                  {change.status === "attention" && (
                    <div className="button-row">
                      {change.may_have_applied && (
                        <button
                          disabled={busy}
                          onClick={() => reconcile.mutate(change.id)}
                        >
                          Check remote state
                        </button>
                      )}
                      {change.work_id && (
                        <button
                          disabled={busy}
                          onClick={() => review.mutate(change.work_id!)}
                        >
                          Review difference
                        </button>
                      )}
                    </div>
                  )}
                </article>
              ))}
              {(changes.data?.total ?? 0) > 10 && (
                <div className="button-row">
                  <button
                    disabled={offset === 0 || changes.isFetching}
                    onClick={() => setOffset(Math.max(0, offset - 10))}
                  >
                    Newer changes
                  </button>
                  <span>
                    {offset + 1}–{Math.min(offset + 10, changes.data!.total)} of{" "}
                    {changes.data!.total}
                  </span>
                  <button
                    disabled={
                      offset + 10 >= changes.data!.total || changes.isFetching
                    }
                    onClick={() => setOffset(offset + 10)}
                  >
                    Older changes
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </details>
  );
}
