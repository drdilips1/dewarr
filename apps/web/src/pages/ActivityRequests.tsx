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
  pendingOnly = false,
}: {
  canManage: boolean;
  pendingOnly?: boolean;
}) {
  const [includeWithdrawn, setIncludeWithdrawn] = useState(false);
  const cache = useQueryClient();
  const requests = usePagedQuery({
    queryKey: [
      "requests",
      pendingOnly ? "pending" : "activity",
      includeWithdrawn,
    ],
    queryFn: async (offset, signal) =>
      result(
        await api.GET("/api/requests", {
          signal,
          params: {
            query: pendingOnly
              ? { offset, limit: 10, pending_only: true }
              : { offset, limit: 10, active_only: !includeWithdrawn },
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
  const ready = usePagedQuery({
    queryKey: ["requests", "download-ready"],
    enabled: pendingOnly,
    queryFn: async (offset, signal) =>
      result(
        await api.GET("/api/requests", {
          signal,
          params: {
            query: { offset, limit: 10, download_ready: true },
          },
        }),
      ),
    refetchInterval: pendingOnly ? 15_000 : false,
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
  const decide = useMutation({
    mutationFn: async ({
      id,
      status,
      download,
      expected,
    }: {
      id: string;
      status: "approved" | "declined";
      download: boolean;
      expected: "pending" | "approved" | "declined";
    }) =>
      result(
        await api.POST("/api/requests/{intent_id}/decision", {
          params: {
            path: { intent_id: id },
            header: { "idempotency-key": crypto.randomUUID() },
          },
          body: { status, download, expected_status: expected },
        }),
      ),
    onSuccess: async () => {
      await cache.invalidateQueries({ queryKey: ["requests"] });
    },
  });
  return (
    <>
      <section
        className="panel library-access requests-panel"
        aria-label={pendingOnly ? "Requests to review" : "Your media requests"}
      >
        <div className="page-heading">
          <div>
            <h2>
              {pendingOnly ? "Requests to review" : "Your media requests"}
            </h2>
            <p className="muted">
              {pendingOnly
                ? "Approve a request to allow it, or decline it. Approve and download starts the download. If that download does not start, the request stays here so you can try again."
                : "Track requests from you and your lists. Expand a book to review its preferences."}
            </p>
          </div>
          {!pendingOnly && (
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
          )}
        </div>
        <Notice error={requests.error || withdraw.error || decide.error} />
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
              {requests.data.total} {pendingOnly ? "waiting" : "saved"}{" "}
              {requests.data.total === 1 ? "request" : "requests"}
            </p>
            {!requests.data.items.length && (
              <p>
                {pendingOnly
                  ? "No requests are waiting for approval."
                  : includeWithdrawn
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
                                  preferences={
                                    request.release_policy.preferences
                                  }
                                  origins={request.release_policy.origins || {}}
                                />
                              )}
                              <DownloadConstraints
                                value={
                                  request.specification.download_constraints
                                }
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
                                  className={
                                    reason.active ? undefined : "muted"
                                  }
                                >
                                  {reason.label}
                                  {reason.active ? "" : " · Withdrawn"}
                                  {reason.approval_status === "pending" &&
                                    " · Waiting for approval"}
                                  {reason.approval_status === "declined" &&
                                    " · Declined"}
                                </span>
                                {reason.decision_note && (
                                  <p className="muted">
                                    {reason.decision_note}
                                  </p>
                                )}
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
                            {request.can_decide && (
                              <div className="request-decision">
                                {request.can_start_download && (
                                  <button
                                    type="button"
                                    className="primary"
                                    disabled={decide.isPending}
                                    onClick={() =>
                                      decide.mutate({
                                        id: request.id,
                                        status: "approved",
                                        download: true,
                                        expected: "pending",
                                      })
                                    }
                                  >
                                    Approve and download
                                  </button>
                                )}
                                <button
                                  type="button"
                                  disabled={decide.isPending}
                                  onClick={() =>
                                    decide.mutate({
                                      id: request.id,
                                      status: "approved",
                                      download: false,
                                      expected: "pending",
                                    })
                                  }
                                >
                                  Approve
                                </button>
                                <button
                                  type="button"
                                  disabled={decide.isPending}
                                  onClick={() =>
                                    decide.mutate({
                                      id: request.id,
                                      status: "declined",
                                      download: false,
                                      expected: "pending",
                                    })
                                  }
                                >
                                  Decline
                                </button>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {decide.data?.download_message && (
              <p className="notice" role="status">
                {decide.data.download_message}
              </p>
            )}
            {!pendingOnly && (
              <p className="muted">
                Withdrawing one reason preserves other requests, downloads and
                library files.
              </p>
            )}
            <InfiniteScroll query={requests} />
          </>
        )}
      </section>
      {pendingOnly && (
        <section
          className="panel library-access requests-panel"
          aria-label="Approved requests waiting for a download"
        >
          <div className="page-heading">
            <div>
              <h2>Approved and waiting for a download</h2>
              <p className="muted">
                These requests are allowed. Start the download when a route is
                ready. It stays here if the download does not start.
              </p>
            </div>
          </div>
          <Notice error={ready.error} />
          {ready.isPending && <Loading />}
          {ready.data && (
            <>
              <p className="requests-count muted" role="status">
                {ready.data.total} approved{" "}
                {ready.data.total === 1 ? "request" : "requests"}
              </p>
              {!ready.data.items.length && (
                <p>No approved requests are waiting for a download.</p>
              )}
              {!!ready.data.items.length && (
                <div className="requests-table-scroll">
                  <table
                    className="requests-table"
                    aria-label="Approved requests"
                  >
                    <thead>
                      <tr>
                        <th scope="col">Book</th>
                        <th scope="col">Media / status</th>
                        <th scope="col">Download</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ready.data.items.map((request) => (
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
                              {request.owner_name}
                            </p>
                          </td>
                          <td>
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
                              </div>
                            ))}
                          </td>
                          <td>
                            {request.can_start_download && (
                              <button
                                type="button"
                                className="primary"
                                disabled={decide.isPending}
                                onClick={() =>
                                  decide.mutate({
                                    id: request.id,
                                    status: "approved",
                                    download: true,
                                    expected: "approved",
                                  })
                                }
                              >
                                Download
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <InfiniteScroll query={ready} />
            </>
          )}
        </section>
      )}
    </>
  );
}
