import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";
import RequestNextAction, {
  requestTargetLabel,
} from "../components/RequestNextAction";
import { EffectiveScope } from "./ScopeFields";
import { EffectivePreferences } from "./PreferenceFields";
import DownloadConstraints from "./DownloadConstraints";

const labels: Record<string, string> = {
  ebook: "Ebook",
  audio: "Audiobook",
  either: "Either medium",
  wanted: "Wanted",
  satisfied: "Available",
  paused: "Paused",
  cancelled: "Withdrawn",
  "awaiting-inventory": "Check inventory",
};

export default function ActivityRequests({
  canManage,
}: {
  canManage: boolean;
}) {
  const [offset, setOffset] = useState(0);
  const [includeWithdrawn, setIncludeWithdrawn] = useState(false);
  const cache = useQueryClient();
  const requests = useQuery({
    queryKey: ["requests", "activity", includeWithdrawn, offset],
    queryFn: async () =>
      result(
        await api.GET("/api/requests", {
          params: {
            query: { offset, limit: 10, active_only: !includeWithdrawn },
          },
        }),
      ),
    refetchInterval: 15_000,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
  const withdraw = useMutation({
    mutationFn: async ({
      intent,
      reason,
    }: {
      intent: string;
      reason: string;
    }) =>
      result(
        await api.DELETE("/api/requests/{intent_id}/reasons/{reason_id}", {
          params: { path: { intent_id: intent, reason_id: reason } },
        }),
      ),
    onSuccess: async () => {
      await Promise.all(
        [
          "requests",
          "request-preview",
          "activity",
          "downloads",
          "list-monitor",
        ].map((key) => cache.invalidateQueries({ queryKey: [key] })),
      );
    },
  });
  return (
    <section className="panel library-access" aria-label="Your media requests">
      <div className="page-heading">
        <div>
          <h2>Your media requests</h2>
          <p className="muted">
            Requests from you and your lists, including books already available.
            Saving a request does not mean a download has started.
          </p>
        </div>
        <label className="check-label">
          <input
            type="checkbox"
            checked={includeWithdrawn}
            onChange={(event) => {
              setIncludeWithdrawn(event.target.checked);
              setOffset(0);
            }}
          />
          Include withdrawn requests
        </label>
      </div>
      <Notice error={requests.error || withdraw.error} />
      {requests.isPending && <Loading />}
      {requests.error && (
        <button
          disabled={requests.isFetching}
          onClick={() => requests.refetch()}
        >
          Retry requests
        </button>
      )}
      {!requests.error && requests.data && (
        <>
          <p className="muted" role="status">
            {requests.data.total} saved{" "}
            {requests.data.total === 1 ? "request" : "requests"}
          </p>
          {!requests.data.items.length && (
            <p>
              {offset
                ? "No requests remain on this page. Go back to an earlier page."
                : includeWithdrawn
                  ? "You have no saved requests yet."
                  : "No requests with active reasons. Include withdrawn requests to see earlier history."}
            </p>
          )}
          {requests.data.items.map((request) => (
            <article
              className="panel editor request-progress-card"
              key={request.id}
              aria-label={`${request.work_title} request`}
            >
              <h3>
                {request.can_open_book ? (
                  <Link to={`/books/${request.work_id}`}>
                    {request.work_title}
                  </Link>
                ) : (
                  request.work_title
                )}
              </h3>
              <p className="muted">{request.description}</p>
              {request.targets.map((target) => (
                <div className="request-target" key={target.slot}>
                  <strong>
                    {labels[target.slot] || target.slot} ·{" "}
                    {requestTargetLabel(target)}
                  </strong>
                  <p>{target.message}</p>
                  {canManage && (
                    <RequestNextAction
                      request={request}
                      target={target}
                      inActivity
                    />
                  )}
                </div>
              ))}
              <details>
                <summary>Saved requirements and download preferences</summary>
                <EffectiveScope
                  specification={request.specification}
                  origins={request.release_policy?.scope_origins}
                />
                {request.release_policy && (
                  <EffectivePreferences
                    preferences={request.release_policy.preferences}
                    origins={request.release_policy.origins || {}}
                  />
                )}
                <DownloadConstraints
                  value={request.specification.download_constraints}
                />
              </details>
              <div aria-label="Request reasons">
                {request.reasons.map((reason) => (
                  <div className="source-attribution" key={reason.id}>
                    <span>
                      {reason.label}
                      {reason.active ? "" : " · Withdrawn"}
                    </span>
                    {canManage && reason.active && (
                      <button
                        type="button"
                        disabled={withdraw.isPending}
                        onClick={() =>
                          withdraw.mutate({
                            intent: request.id,
                            reason: reason.id,
                          })
                        }
                      >
                        Withdraw {reason.label.toLowerCase()}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </article>
          ))}
          <p className="muted">
            Withdrawing one reason preserves other requests, downloads and
            library files.
          </p>
          {(offset > 0 || requests.data.total > 10) && (
            <div className="pagination" aria-label="Request history pages">
              <button
                disabled={offset === 0 || requests.isFetching}
                onClick={() => setOffset(Math.max(0, offset - 10))}
              >
                Previous requests
              </button>
              <span>Page {Math.floor(offset / 10) + 1}</span>
              <button
                disabled={
                  offset + 10 >= requests.data.total || requests.isFetching
                }
                onClick={() => setOffset(offset + 10)}
              >
                Next requests
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
