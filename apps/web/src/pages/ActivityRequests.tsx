import { usePagedQuery } from "../hooks/usePagedQuery";
import InfiniteScroll from "../components/InfiniteScroll";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
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
  const [includeWithdrawn, setIncludeWithdrawn] = useState(false);
  const cache = useQueryClient();
  const requests = usePagedQuery({
    queryKey: ["requests", "activity", includeWithdrawn],
    queryFn: async (offset, signal) =>
      result(
        await api.GET("/api/requests", {
          signal,
          params: {
            query: { offset, limit: 10, active_only: !includeWithdrawn },
          },
        }),
      ),
    refetchInterval: 15_000,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    initial: 0,
    next: (last, pages) => {
      const count = pages.reduce((n, p) => n + p.items.length, 0);
      return last.items.length && count < last.total ? count : undefined;
    },
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
    <section
      className="panel library-access requests-panel"
      aria-label="Your media requests"
    >
      <div className="page-heading">
        <div>
          <h2>Your media requests</h2>
          <p className="muted">
            Track requests from you and your lists. Expand a book to review its
            preferences.
          </p>
        </div>
        <label className="check-label">
          <input
            type="checkbox"
            checked={includeWithdrawn}
            onChange={(event) => {
              setIncludeWithdrawn(event.target.checked);
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
      {requests.data && (
        <>
          <p className="requests-count muted" role="status">
            {requests.data.total} saved{" "}
            {requests.data.total === 1 ? "request" : "requests"}
          </p>
          {!requests.data.items.length && (
            <p>
              {includeWithdrawn
                ? "You have no saved requests yet."
                : "No requests with active reasons. Include withdrawn requests to see earlier history."}
            </p>
          )}
          {!!requests.data.items.length && (
            <div className="requests-table-scroll">
              <table
                className="requests-table"
                aria-label="Saved media requests"
              >
                <thead>
                  <tr>
                    <th scope="col">Book / preferences</th>
                    <th scope="col">Media / status</th>
                    <th scope="col">Requested by</th>
                  </tr>
                </thead>
                <tbody>
                  {requests.data.items.map((request) => (
                    <tr
                      key={request.id}
                      aria-label={`${request.work_title} request`}
                    >
                      <td>
                        <div className="request-book-title">
                          {request.can_open_book ? (
                            <Link to={`/books/${request.work_id}`}>
                              {request.work_title}
                            </Link>
                          ) : (
                            request.work_title
                          )}
                        </div>
                        <p className="muted request-description">
                          {request.description}
                        </p>
                        <details className="request-preferences">
                          <summary>
                            Saved requirements and download preferences
                          </summary>
                          <div className="request-preferences-body">
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
                          </div>
                        </details>
                      </td>
                      <td>
                        <div className="request-targets">
                          {request.targets.map((target) => (
                            <div
                              className="request-table-target"
                              key={target.slot}
                            >
                              <span
                                className="request-state"
                                data-state={target.state}
                              >
                                {labels[target.slot] || target.slot} ·{" "}
                                {requestTargetLabel(target)}
                              </span>
                              <p className="muted">{target.message}</p>
                              {canManage && (
                                <RequestNextAction
                                  request={request}
                                  target={target}
                                  inActivity
                                />
                              )}
                            </div>
                          ))}
                        </div>
                      </td>
                      <td>
                        <div
                          className="request-reasons"
                          aria-label="Request reasons"
                        >
                          {request.reasons.map((reason) => (
                            <div className="request-reason" key={reason.id}>
                              <span
                                className={reason.active ? undefined : "muted"}
                              >
                                {reason.label}
                                {reason.active ? "" : " · Withdrawn"}
                              </span>
                              {canManage && reason.active && (
                                <button
                                  type="button"
                                  className="request-withdraw"
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
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted">
            Withdrawing one reason preserves other requests, downloads and
            library files.
          </p>
          <InfiniteScroll query={requests} />
        </>
      )}
    </section>
  );
}
